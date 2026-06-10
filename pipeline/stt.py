"""
ScamGuardian v2 — STT 모듈 (진입점 + Whisper 백엔드)
YouTube URL / 로컬 파일 / 텍스트 입력을 처리하여 텍스트를 반환한다.

구현 분리:
- pipeline.stt_common — TranscriptResult·소스 판별·YouTube 다운로드·오디오 프로브
- pipeline.stt_claude — Claude Audio API 백엔드
- pipeline.stt_clova  — CLOVA Speech 백엔드 (+ 화자 역할 배정)
- 이 파일 — Whisper(OpenAI) 백엔드 + 병렬 chunking + `transcribe()` 라우팅

Whisper 체인(_whisper_one 등)과 STT_CHUNK_* 노브는 테스트가 이 모듈 attribute 를
monkeypatch 하므로 여기 잔류해야 한다 (tests/test_stt_chunked.py).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from pipeline.stt_common import (  # noqa: F401
    TranscriptResult,
    _YOUTUBE_PATTERN,
    _is_youtube_url,
    _is_file,
    _download_youtube_audio,
    _probe_audio_seconds,
    _ensure_audio_nonempty,
)
from pipeline.stt_claude import _transcribe_with_claude  # noqa: F401
from pipeline.stt_clova import (  # noqa: F401
    _label_durations,
    _label_texts,
    _duration_role_map,
    _parse_role_map,
    _assign_clova_roles,
    _clova_to_turns,
    _get_clova_logger,
    _transcribe_with_clova,
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
    diarize: bool = True,  # 미사용 — 호출부 시그니처 통일용 (Whisper 는 화자 분리 안 함)
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


# STT 백엔드 설정 — whisper(openai) | claude | clova
STT_BACKEND = os.getenv("STT_BACKEND", "whisper")


def transcribe(
    source: str,
    model_size: str = "medium",
    debug: bool = False,
    logger: Callable[[str], None] | None = None,
    stt_backend: str | None = None,
    diarize: bool = True,
) -> TranscriptResult:
    """
    입력 소스를 텍스트로 변환한다.

    Args:
        source: YouTube URL, 로컬 파일 경로, 또는 텍스트
        model_size: (미사용, 호환성 유지)
        stt_backend: "whisper" 또는 "claude" (None이면 STT_BACKEND 환경변수 사용)
        diarize: False 면 화자 분리(상대방/본인 역할 배정 = CLOVA 경로의 Claude 호출)를
            건너뛰고 전사 텍스트만 반환(turns=[]). Live 즉시 검출 경로용. 기본 True.

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
            result = _do_stt(audio_path, logger=logger, diarize=diarize)
        result = _maybe_correct(result, logger=logger)
        return TranscriptResult(
            text=result["text"],
            language=result.get("language", "ko"),
            segments=result.get("segments", []),
            turns=result.get("turns"),  # CLOVA 만 채워짐, 나머지는 None
            source_type="youtube",
        )

    # 로컬 파일
    _ensure_audio_nonempty(source)
    result = _do_stt(source, logger=logger, diarize=diarize)
    result = _maybe_correct(result, logger=logger)
    return TranscriptResult(
        text=result["text"],
        language=result.get("language", "ko"),
        segments=result.get("segments", []),
        turns=result.get("turns"),
        source_type="file",
    )


def _maybe_correct(result: dict, logger: Callable[[str], None] | None = None) -> dict:
    """STT_CORRECT=1 이고 turns 가 있으면 LLM 후처리 교정 적용 (text 도 재구성).

    실패·비활성 시 result 그대로 — 회귀 없음. turns 없는 backend(Whisper 등)는 skip.
    """
    try:
        from pipeline import stt_correct
        if not stt_correct.enabled():
            return result
        turns = result.get("turns")
        if not turns:
            return result
        corrected = stt_correct.correct_turns(turns)
        result["turns"] = corrected
        result["text"] = stt_correct.corrected_full_text(corrected)
        if logger:
            logger("[STT] LLM 후처리 교정 적용")
    except Exception as exc:
        if logger:
            logger(f"[STT] 교정 skip: {exc}")
    return result
