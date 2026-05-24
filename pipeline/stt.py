"""
ScamGuardian v2 — STT 모듈
YouTube URL / 로컬 파일 / 텍스트 입력을 처리하여 텍스트를 반환한다.

OpenAI Whisper API를 사용한다. OPENAI_API_KEY 환경변수 필수.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_YOUTUBE_PATTERN = re.compile(
    r"https?://(www\.)?(youtube\.com|youtu\.be)/"
)


@dataclass
class TranscriptResult:
    text: str
    language: str = ""
    segments: list[dict] = field(default_factory=list)
    source_type: str = ""  # "youtube" | "file" | "text"


def _is_youtube_url(source: str) -> bool:
    return bool(_YOUTUBE_PATTERN.match(source.strip()))


def _is_file(source: str) -> bool:
    try:
        p = Path(source)
        return p.exists() and p.is_file()
    except OSError:
        return False


def _download_youtube_audio(
    url: str,
    output_dir: str,
    debug: bool = False,
    logger: Callable[[str], None] | None = None,
) -> str:
    """yt-dlp로 YouTube 오디오를 추출하여 mp3 파일 경로를 반환한다."""
    import yt_dlp

    output_path = str(Path(output_dir) / "audio.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_path,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "64",
            }
        ],
        "postprocessor_args": {"ExtractAudio": ["-t", "180"]},
        "quiet": not debug,
        "no_warnings": not debug,
    }

    if logger:
        logger(f"[STT] YouTube 오디오 다운로드 시작: {url}")
    t0 = time.time()
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    if logger:
        logger(f"[STT] YouTube 오디오 다운로드 완료 ({time.time() - t0:.1f}s)")

    mp3_path = str(Path(output_dir) / "audio.mp3")
    if not Path(mp3_path).exists():
        raise FileNotFoundError(f"YouTube 오디오 다운로드 실패: {url}")
    return mp3_path


def _probe_audio_seconds(path: str) -> float:
    """ffprobe 로 오디오 길이(초). 측정 실패면 0.0."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10,
        )
        return float(result.stdout.strip() or "0")
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return 0.0


def _ensure_audio_nonempty(path: str) -> None:
    """ffprobe로 오디오 길이를 확인한다. 0이면 에러."""
    duration = _probe_audio_seconds(path)
    if duration > 0 and duration < 0.1:
        raise ValueError(
            "오디오를 읽지 못했습니다. 오디오 트랙이 없는 영상이거나 파일이 손상됐을 수 있습니다."
        )


# 병렬 chunk STT 파라미터 — 영상 분석 latency 단축
STT_CHUNK_SEC = int(os.getenv("STT_CHUNK_SEC", "45"))
STT_MAX_WORKERS = int(os.getenv("STT_MAX_WORKERS", "4"))
STT_CHUNK_THRESHOLD_SEC = int(os.getenv("STT_CHUNK_THRESHOLD_SEC", "45"))


def _whisper_one(audio_path: str) -> str:
    """단일 오디오 파일 Whisper API 호출 + 비용 ledger. chunk 병렬 워커가 호출."""
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 가 설정되지 않았습니다.")
    client = OpenAI(api_key=api_key)
    with open(audio_path, "rb") as f:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language="ko",
        )

    duration = _probe_audio_seconds(audio_path)
    if duration > 0:
        try:
            from platform_layer.cost import record_openai_whisper
            record_openai_whisper(duration)
        except Exception:
            pass

    return (response.text or "").strip()


def _split_audio_chunks(audio_path: str, chunk_sec: int, out_dir: str) -> list[str]:
    """ffmpeg segment 로 오디오를 chunk_sec 단위로 자른다. chunk 경로 리스트 반환 (index 순)."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg 가 설치되어 있지 않습니다.")
    pattern = str(Path(out_dir) / "chunk_%04d.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path,
         "-f", "segment", "-segment_time", str(chunk_sec),
         "-c", "copy", pattern],
        check=True, capture_output=True,
    )
    chunks = sorted(Path(out_dir).glob("chunk_*.mp3"))
    if not chunks:
        raise RuntimeError("오디오 chunk 분할 결과가 비었습니다.")
    return [str(p) for p in chunks]


def _transcribe_chunks_parallel(
    audio_path: str,
    logger: Callable[[str], None] | None = None,
) -> str:
    """오디오를 chunk 로 분할 후 ThreadPoolExecutor 로 Whisper API 병렬 호출. index 순서대로 concat."""
    with tempfile.TemporaryDirectory(prefix="sg_stt_") as tmp_dir:
        chunks = _split_audio_chunks(audio_path, STT_CHUNK_SEC, tmp_dir)
        if logger:
            logger(
                f"[STT] 병렬 chunking — chunk={STT_CHUNK_SEC}s, "
                f"개수={len(chunks)}, workers={STT_MAX_WORKERS}"
            )
        results: dict[int, str] = {}
        with ThreadPoolExecutor(max_workers=STT_MAX_WORKERS) as pool:
            futures = {pool.submit(_whisper_one, p): i for i, p in enumerate(chunks)}
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    results[idx] = fut.result()
                except Exception as exc:
                    if logger:
                        logger(f"[STT] chunk {idx} 실패: {exc} — 빈 텍스트로 대체")
                    results[idx] = ""
        return " ".join(results[i] for i in sorted(results) if results[i]).strip()


def _transcribe_with_openai_api(
    audio_path: str,
    logger: Callable[[str], None] | None = None,
) -> dict:
    """OpenAI Whisper API로 음성 파일을 텍스트로 변환한다. 길면 자동 병렬 chunking."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY가 설정되지 않았습니다. "
            ".env 파일에 OPENAI_API_KEY를 추가해주세요."
        )

    file_size_mb = Path(audio_path).stat().st_size / (1024 * 1024)
    duration = _probe_audio_seconds(audio_path)

    if logger:
        logger(
            f"[STT] OpenAI Whisper API 호출 시작\n"
            f"       → 전송 파일: {Path(audio_path).name} ({file_size_mb:.1f}MB, {duration:.1f}s)\n"
            f"       → 모델: whisper-1, 언어: ko"
        )
    t0 = time.time()

    if duration > STT_CHUNK_THRESHOLD_SEC:
        text = _transcribe_chunks_parallel(audio_path, logger=logger)
    else:
        text = _whisper_one(audio_path)

    elapsed = time.time() - t0
    preview = text[:150] + "…" if len(text) > 150 else text

    if logger:
        logger(
            f"[STT] OpenAI Whisper API 완료 ({elapsed:.1f}s)\n"
            f"       ← 전사 길이: {len(text)}자\n"
            f"       ← 미리보기: {preview}"
        )
    return {"text": text, "language": "ko", "segments": []}


def _transcribe_with_claude(
    audio_path: str,
    logger: Callable[[str], None] | None = None,
) -> dict:
    """Claude API에 오디오를 직접 전송하여 전사한다."""
    import base64

    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY가 설정되지 않았습니다. "
            ".env 파일에 ANTHROPIC_API_KEY를 추가해주세요."
        )

    audio_bytes = Path(audio_path).read_bytes()
    file_size_mb = len(audio_bytes) / (1024 * 1024)

    # 확장자로 media_type 결정
    ext = Path(audio_path).suffix.lower().lstrip(".")
    media_type_map = {
        "mp3": "audio/mp3",
        "wav": "audio/wav",
        "flac": "audio/flac",
        "ogg": "audio/ogg",
        "m4a": "audio/mp4",
        "mp4": "audio/mp4",
        "webm": "audio/webm",
    }
    media_type = media_type_map.get(ext, "audio/mp3")
    audio_b64 = base64.standard_b64encode(audio_bytes).decode("utf-8")

    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    if logger:
        logger(
            f"[STT] Claude Audio API 호출 시작\n"
            f"       → 파일: {Path(audio_path).name} ({file_size_mb:.1f}MB)\n"
            f"       → 모델: {model}, 타입: {media_type}"
        )

    t0 = time.time()
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "audio",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": audio_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "위 오디오를 한국어로 전사(transcription)해주세요. "
                            "말한 내용을 그대로 텍스트로 옮기세요. "
                            "전사 결과만 출력하고, 다른 설명은 하지 마세요."
                        ),
                    },
                ],
            }
        ],
    )
    elapsed = time.time() - t0
    text = message.content[0].text.strip()
    preview = text[:150] + "…" if len(text) > 150 else text

    if logger:
        logger(
            f"[STT] Claude Audio API 완료 ({elapsed:.1f}s)\n"
            f"       ← 전사 길이: {len(text)}자\n"
            f"       ← 미리보기: {preview}"
        )
    return {"text": text, "language": "ko", "segments": []}


# STT 백엔드 설정 (현재 whisper만 지원)
STT_BACKEND = os.getenv("STT_BACKEND", "whisper")


def transcribe(
    source: str,
    model_size: str = "medium",
    debug: bool = False,
    logger: Callable[[str], None] | None = None,
    stt_backend: str | None = None,
) -> TranscriptResult:
    """
    입력 소스를 텍스트로 변환한다.

    Args:
        source: YouTube URL, 로컬 파일 경로, 또는 텍스트
        model_size: (미사용, 호환성 유지)
        stt_backend: "whisper" 또는 "claude" (None이면 STT_BACKEND 환경변수 사용)

    Returns:
        TranscriptResult 객체
    """
    backend = stt_backend or STT_BACKEND

    if not _is_youtube_url(source) and not _is_file(source):
        return TranscriptResult(
            text=source.strip(),
            source_type="text",
        )

    # v3 Phase 1: 이미지·PDF 는 vision OCR 로 라우팅
    if _is_file(source):
        from pipeline import vision as _vision
        if _vision.supported(source):
            if logger:
                logger(f"[Phase 1] vision OCR 라우팅: {Path(source).suffix}")
            result = _vision.transcribe(source)
            return TranscriptResult(
                text=result.text,
                language="ko",
                segments=[],
                source_type=result.source_type,
            )

    # STT 함수 선택
    _do_stt = _transcribe_with_claude if backend == "claude" else _transcribe_with_openai_api

    # YouTube URL
    if _is_youtube_url(source):
        with tempfile.TemporaryDirectory() as tmp_dir:
            audio_path = _download_youtube_audio(
                source, tmp_dir, debug=debug, logger=logger,
            )
            if logger:
                logger(f"[STT] 오디오 파일 준비 완료: {audio_path}")
            _ensure_audio_nonempty(audio_path)
            result = _do_stt(audio_path, logger=logger)
        return TranscriptResult(
            text=result["text"],
            language=result.get("language", "ko"),
            segments=result.get("segments", []),
            source_type="youtube",
        )

    # 로컬 파일
    _ensure_audio_nonempty(source)
    result = _do_stt(source, logger=logger)
    return TranscriptResult(
        text=result["text"],
        language=result.get("language", "ko"),
        segments=result.get("segments", []),
        source_type="file",
    )
