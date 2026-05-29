"""
ScamGuardian v2 — STT 모듈
YouTube URL / 로컬 파일 / 텍스트 입력을 처리하여 텍스트를 반환한다.

OpenAI Whisper API를 사용한다. OPENAI_API_KEY 환경변수 필수.
"""

from __future__ import annotations

import logging
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
    # CLOVA 등 audio-based diarization 백엔드가 직접 화자 분리한 결과.
    # None 이면 LLM 후처리 diarize 필요. 있으면 그대로 사용 (LLM skip).
    # 형식: [{"speaker": "상대방|본인", "text": "..."}, ...]
    turns: list[dict] | None = None


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

# Whisper API prompt — *짧은 컨텍스트 문장만* 사용.
# ⚠️ 도메인 어휘 list 를 prompt 에 박으면 Whisper 가 침묵·노이즈 구간에서 그 어휘를
# 그대로 transcript 로 출력하는 hallucination 발생 (관찰됨: 12개 어휘로도 무한 반복).
# 해결책: 어휘 list 빼고 짧은 문장 컨텍스트만 → 한국어 모드 + 통화 도메인 hint 만.
# 도메인 어휘 교정 ("뇌통장→대포통장") 은 별도 LLM 후처리 단계로 분리 가능.
# 환경변수 STT_DOMAIN_PROMPT 로 override (빈 문자열 = prompt 안 보냄).
_DEFAULT_DOMAIN_PROMPT = "한국어 전화 통화 녹음입니다."
STT_DOMAIN_PROMPT = os.getenv("STT_DOMAIN_PROMPT", _DEFAULT_DOMAIN_PROMPT)


# Whisper 가 학습 데이터의 빈도 높은 한국어 YouTube/방송 phrase 를 침묵·노이즈
# 구간에서 자동 생성하는 known hallucination. 정확히 일치하면 제거.
_WHISPER_HALLUCINATION_PHRASES = [
    "시청해주셔서 감사합니다.",
    "시청해주셔서 감사합니다",
    "시청해 주셔서 감사합니다.",
    "시청해 주셔서 감사합니다",
    "끝까지 시청해주셔서 감사합니다.",
    "구독과 좋아요 부탁드립니다.",
    "구독과 좋아요 부탁드려요.",
    "구독 좋아요 부탁드립니다.",
    "구독 좋아요 알림설정 부탁드립니다.",
    "[음악]",
    "♪",
    "Music",
    "MBC 뉴스",
    "KBS 뉴스",
]


def _strip_hallucination_phrases(text: str) -> str:
    """Whisper 의 알려진 hallucination phrase 제거. 정상 본문 안에 박힌 것도 strip."""
    if not text:
        return text
    cleaned = text
    for phrase in _WHISPER_HALLUCINATION_PHRASES:
        cleaned = cleaned.replace(phrase, " ")
    # 공백 정규화
    cleaned = " ".join(cleaned.split())
    # 결과가 너무 짧으면 (3자 미만) hallucination 만 있었던 것 — 빈 문자열로
    return cleaned if len(cleaned) >= 3 else ""


def _squash_repetition(text: str, min_repeat: int = 3) -> str:
    """Whisper hallucination 의 loop 패턴 제거. 같은 phrase 가 min_repeat+ 회 연속
    반복되면 1회로 줄임. n-gram 사이즈 큰 것부터 처리 — 큰 단위 반복 (예: "중앙지검
    합동수사본부 중앙지검 합동수사본부 ...") 을 먼저 squash."""
    if not text:
        return text
    tokens = text.split()
    if len(tokens) < min_repeat * 2:
        return text
    # 8-gram 부터 1-gram 까지 큰 것 → 작은 것 순서
    max_ngram = min(8, len(tokens) // min_repeat)
    for ngram_size in range(max_ngram, 0, -1):
        new_tokens: list[str] = []
        i = 0
        while i < len(tokens):
            ngram = tokens[i:i + ngram_size]
            if len(ngram) < ngram_size:
                new_tokens.extend(tokens[i:])
                break
            # 직후에 같은 ngram 이 몇 번 반복되는지
            count = 1
            j = i + ngram_size
            while j + ngram_size <= len(tokens) and tokens[j:j + ngram_size] == ngram:
                count += 1
                j += ngram_size
            if count >= min_repeat:
                # N+ 회 반복 발견 → 1회만 유지
                new_tokens.extend(ngram)
                i = j
            else:
                new_tokens.append(tokens[i])
                i += 1
        tokens = new_tokens
    return " ".join(tokens)


def _whisper_one(audio_path: str) -> str:
    """단일 오디오 파일 Whisper API 호출 + 비용 ledger. chunk 병렬 워커가 호출."""
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 가 설정되지 않았습니다.")
    client = OpenAI(api_key=api_key)
    # prompt 가 빈 문자열이면 아예 안 보냄 (Whisper hallucination 원천 차단)
    kwargs: dict = {
        "model": "whisper-1",
        "file": None,  # 아래에서 채움
        "language": "ko",
        "temperature": 0.0,  # deterministic — hallucination 줄임
    }
    if STT_DOMAIN_PROMPT:
        kwargs["prompt"] = STT_DOMAIN_PROMPT
    with open(audio_path, "rb") as f:
        kwargs["file"] = f
        response = client.audio.transcriptions.create(**kwargs)

    duration = _probe_audio_seconds(audio_path)
    if duration > 0:
        try:
            from platform_layer.cost import record_openai_whisper
            record_openai_whisper(duration)
        except Exception:
            pass

    text = (response.text or "").strip()
    text = _strip_hallucination_phrases(text)
    return _squash_repetition(text)


def _split_audio_chunks(audio_path: str, chunk_sec: int, out_dir: str) -> list[str]:
    """ffmpeg segment 로 오디오를 chunk_sec 단위로 자른다. chunk 경로 리스트 반환 (index 순).

    원래 yt-dlp mp3 입력만 가정해 `-c copy` 사용했으나 — wav/m4a 등
    다른 코덱 입력에서는 mp3 컨테이너로 mux 실패(exit 234). 어떤 입력
    이든 동작하도록 libmp3lame 재인코딩 (mono 16k 64kbps — Whisper API
    충분 + 업로드 크기 작음).
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg 가 설치되어 있지 않습니다.")
    pattern = str(Path(out_dir) / "chunk_%04d.mp3")
    subprocess.run(
        ["ffmpeg", "-y", "-i", audio_path,
         "-f", "segment", "-segment_time", str(chunk_sec),
         "-ac", "1", "-ar", "16000",
         "-c:a", "libmp3lame", "-b:a", "64k",
         pattern],
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


def _clova_to_turns(segments: list[dict]) -> list[dict]:
    """CLOVA Speech segments (speaker_label 포함) → 상대방/본인 turn 리스트.

    휴리스틱: 발화 시간 총합 더 긴 화자 = 상대방 (사기범의 긴 모놀로그), 짧은 = 본인 (피해자).
    각 turn 에 start_sec / end_sec 도 함께 — frontend 에서 원본 오디오 segment 재생용.
    """
    if not segments:
        return []
    speaker_durations: dict[str, float] = {}
    for seg in segments:
        label = str(seg.get("speaker_label", "")).strip()
        if not label:
            continue
        duration = float(seg.get("end", 0.0) - seg.get("start", 0.0))
        speaker_durations[label] = speaker_durations.get(label, 0.0) + duration
    if not speaker_durations:
        joined = " ".join((s.get("text", "") or "").strip() for s in segments).strip()
        if not joined:
            return []
        first_start = float(segments[0].get("start", 0.0)) if segments else 0.0
        last_end = float(segments[-1].get("end", 0.0)) if segments else 0.0
        return [{"speaker": "상대방", "text": joined, "start_sec": first_start, "end_sec": last_end}]
    longest_label = max(speaker_durations, key=lambda k: speaker_durations[k])
    turns: list[dict] = []
    current_speaker: str | None = None
    current_parts: list[str] = []
    current_start: float = 0.0
    current_end: float = 0.0
    for seg in segments:
        label = str(seg.get("speaker_label", "")).strip()
        text = (seg.get("text", "") or "").strip()
        if not text:
            continue
        speaker = "상대방" if label == longest_label else "본인"
        seg_start = float(seg.get("start", 0.0))
        seg_end = float(seg.get("end", 0.0))
        if speaker == current_speaker:
            current_parts.append(text)
            current_end = seg_end
        else:
            if current_speaker is not None and current_parts:
                turns.append({
                    "speaker": current_speaker,
                    "text": " ".join(current_parts),
                    "start_sec": current_start,
                    "end_sec": current_end,
                })
            current_speaker = speaker
            current_parts = [text]
            current_start = seg_start
            current_end = seg_end
    if current_speaker is not None and current_parts:
        turns.append({
            "speaker": current_speaker,
            "text": " ".join(current_parts),
            "start_sec": current_start,
            "end_sec": current_end,
        })
    return turns


_DEFAULT_CLOVA_BOOSTING = (
    "소환장,소환,출석조사,출두,통보,발부,검찰청,경찰청,금융감독원,금감원,"
    "국정원,중앙지검,서울중앙지검,합동수사본부,수사관,검사,사건번호,"
    "대포통장,안전계좌,명의도용,개인정보,증거물,압수,범죄,피의자,참고인,"
    "송금,이체,입금,출금,계좌번호,주민등록번호,비밀번호,OTP,보안카드,인증번호,"
    "피해자,가해자,보이스피싱,사기"
)


_CLOVA_LOGGER: logging.Logger | None = None


def _get_clova_logger() -> logging.Logger:
    """CLOVA 전용 로그 파일 (.scamguardian/logs/clova-kyy.log) 설정."""
    global _CLOVA_LOGGER
    if _CLOVA_LOGGER is not None and _CLOVA_LOGGER.handlers:
        return _CLOVA_LOGGER
    logger = logging.getLogger("pipeline.stt.clova")
    log_path = Path(__file__).resolve().parent.parent / ".scamguardian" / "logs" / "clova-kyy.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(str(log_path), encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [CLOVA] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False  # backend-kyy.log 에 중복 X
    _CLOVA_LOGGER = logger
    return logger


def _transcribe_with_clova(
    audio_path: str,
    logger: Callable[[str], None] | None = None,
) -> dict:
    """Naver CLOVA Speech API 로 한국어 STT + audio-based 화자 분리.

    한 번의 호출로 전사문 + segments + speaker_label 모두 받음 (LLM diarize 불필요).
    응답에 `segments` (각 segment 가 speaker_label 포함) + `turns` (상대방/본인 매핑됨) 포함.

    도메인 어휘 bias 는 `boostings` 파라미터로 적용 (Whisper prompt 와 달리
    hallucination 부작용 없음 — 단어 출력만 가중치, 새 텍스트 생성 X).
    환경변수 CLOVA_BOOSTING_WORDS 로 override.

    모든 호출이 .scamguardian/logs/clova-kyy.log 에 상세 기록 (진단용).
    """
    import json
    import traceback
    import requests

    clova_log = _get_clova_logger()

    invoke_url = os.environ.get("CLOVA_INVOKE_URL", "").strip().rstrip("/")
    secret_key = os.environ.get("CLOVA_SECRET_KEY", "").strip()
    if not invoke_url or not secret_key:
        clova_log.error("env 미설정 — CLOVA_INVOKE_URL/CLOVA_SECRET_KEY 둘 다 필요")
        raise RuntimeError(
            "CLOVA_INVOKE_URL / CLOVA_SECRET_KEY env 미설정 — NCP 콘솔에서 CLOVA Speech 도메인 생성 필요."
        )

    boosting_words = os.environ.get("CLOVA_BOOSTING_WORDS", _DEFAULT_CLOVA_BOOSTING).strip()

    # 요청 시작 로그
    try:
        audio_size = Path(audio_path).stat().st_size
    except Exception:
        audio_size = 0
    audio_duration = _probe_audio_seconds(audio_path)
    clova_log.info("=== 새 요청 ===")
    clova_log.info(
        "  audio: %s (%s bytes, %.1fs)",
        Path(audio_path).name, f"{audio_size:,}", audio_duration,
    )
    clova_log.info("  invoke_url: %s", invoke_url[:60] + "..." if len(invoke_url) > 60 else invoke_url)
    clova_log.info("  boosting: %d 단어", len(boosting_words.split(",")) if boosting_words else 0)

    params: dict = {
        "language": "ko-KR",
        "completion": "sync",
        "wordAlignment": False,
        "fullText": True,
        # 보이스피싱 통화 = 항상 2명 (사기범 + 피해자) 가정
        "diarization": {
            "enable": True,
            "speakerCountMin": 2,
            "speakerCountMax": 2,
        },
    }
    if boosting_words:
        # CLOVA boostings: 도메인 어휘 인식 우선순위 ↑.
        # "소환자" 대신 "소환장" 출력하도록 bias.
        params["boostings"] = [{"words": boosting_words}]

    t0 = time.time()
    try:
        with open(audio_path, "rb") as f:
            files = {
                "media": f,
                "params": (None, json.dumps(params).encode("utf-8"), "application/json"),
            }
            headers = {"X-CLOVASPEECH-API-KEY": secret_key}
            response = requests.post(
                f"{invoke_url}/recognizer/upload",
                files=files,
                headers=headers,
                timeout=300,
            )
        elapsed = time.time() - t0
        clova_log.info("  HTTP %d, elapsed=%.2fs", response.status_code, elapsed)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        elapsed = time.time() - t0
        clova_log.error("  ❌ 실패 (%.2fs): %s: %s", elapsed, type(exc).__name__, exc)
        clova_log.error("  traceback:\n%s", traceback.format_exc())
        raise

    if data.get("result") != "COMPLETED":
        clova_log.error(
            "  ❌ result != COMPLETED: result=%r message=%r",
            data.get("result"), data.get("message"),
        )
        raise RuntimeError(
            f"CLOVA Speech 실패: result={data.get('result')!r} message={data.get('message')!r}"
        )

    # 비용 ledger
    duration = _probe_audio_seconds(audio_path)
    if duration > 0:
        try:
            from platform_layer.cost import record_clova_speech
            record_clova_speech(duration)
        except Exception:
            pass

    full_text = (data.get("text") or "").strip()
    segments_raw = data.get("segments") or []
    segments: list[dict] = []
    for seg in segments_raw:
        speaker_label = ""
        speaker_obj = seg.get("speaker")
        if isinstance(speaker_obj, dict):
            speaker_label = str(speaker_obj.get("label", "")).strip()
        segments.append({
            "start": float(seg.get("start", 0)) / 1000.0,  # CLOVA 는 ms → 초
            "end": float(seg.get("end", 0)) / 1000.0,
            "text": (seg.get("text") or "").strip(),
            "speaker_label": speaker_label,
        })

    turns = _clova_to_turns(segments)

    # 결과 상세 기록
    preview = full_text[:200] + "…" if len(full_text) > 200 else full_text
    clova_log.info(
        "  ✅ 완료: text=%d자, segments=%d개, turns=%d개",
        len(full_text), len(segments), len(turns),
    )
    clova_log.info("  preview: %s", preview)
    # 첫 5 segments (speaker label 확인용)
    for i, seg in enumerate(segments[:5]):
        clova_log.info(
            "  seg[%d]: %.2f-%.2fs label=%s text=%r",
            i, seg["start"], seg["end"], seg.get("speaker_label", "?"),
            seg["text"][:60],
        )
    if len(segments) > 5:
        clova_log.info("  ... (%d more segments)", len(segments) - 5)
    # 전체 turns
    for i, t in enumerate(turns):
        clova_log.info(
            "  turn[%d] %s @ %.2f-%.2fs: %s",
            i, t["speaker"], t.get("start_sec", 0.0), t.get("end_sec", 0.0),
            t["text"][:80],
        )
    clova_log.info("")  # 빈 줄 — 다음 요청과 구분

    if logger:
        logger(
            f"[STT] CLOVA Speech 완료 ({elapsed:.1f}s)\n"
            f"       ← 전사 길이: {len(full_text)}자, segments: {len(segments)}개, turns: {len(turns)}개\n"
            f"       ← 미리보기: {preview}"
        )

    return {
        "text": full_text,
        "language": "ko",
        "segments": segments,
        "turns": turns,
    }


# STT 백엔드 설정 — whisper(openai) | claude | clova
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
    backend_lower = (backend or "").lower()
    if backend_lower == "clova":
        _do_stt = _transcribe_with_clova
    elif backend_lower == "claude":
        _do_stt = _transcribe_with_claude
    else:
        _do_stt = _transcribe_with_openai_api

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
            turns=result.get("turns"),  # CLOVA 만 채워짐, 나머지는 None
            source_type="youtube",
        )

    # 로컬 파일
    _ensure_audio_nonempty(source)
    result = _do_stt(source, logger=logger)
    return TranscriptResult(
        text=result["text"],
        language=result.get("language", "ko"),
        segments=result.get("segments", []),
        turns=result.get("turns"),
        source_type="file",
    )
