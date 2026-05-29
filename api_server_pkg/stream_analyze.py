"""POST /api/analyze-stream — 긴 음성 파일 chunk 단위 streaming 분석.

10분짜리 파일도 `chunk_seconds` (기본 60초) 단위로 잘라 각 chunk 의 STT +
키워드 alert 결과를 NDJSON 으로 즉시 흘려준다. 클라이언트는 fetch 의
ReadableStream 을 line-by-line 으로 파싱해 chunk 별 결과를 실시간 표시
가능. v4 Live Call Guard (5초 chunk 실시간 검출) 의 사전 녹음 simulation.

각 라인 schema:
  {"type": "start", "total_chunks": N, "chunk_seconds": 60, "source_filename": "..."}
  {"type": "chunk", "chunk_index": i, "start_sec": s, "end_sec": e,
   "transcript": str, "alert_level": 0-3, "matches": [{flag, label_ko, level, snippet}],
   "latency_ms": int}
  {"type": "done", "total_chunks": N, "full_transcript": str,
   "cumulative_matches": [...], "cumulative_alert_level": 0-3}
  {"type": "error", "message": str}
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

router = APIRouter()
LOG = logging.getLogger("api_analyze_stream")

# (flag, regex, level, label_ko) — level: 1 watch / 2 warn / 3 danger
_ALERT_PATTERNS: list[tuple[str, str, int, str]] = [
    ("urgent_transfer_demand", r"(즉시|지금|당장|빨리|얼른).{0,12}(송금|이체|보내|입금)", 3, "즉각 송금 요구"),
    ("safe_account_phrase", r"안전\s*(계좌|입금|보관)", 3, "안전계좌 사기 키워드"),
    ("fake_government_agency", r"(검찰청|금융감독원|경찰청|국정원|금감원|검사)", 2, "공공기관 사칭"),
    ("ssn_request", r"주민(등록)?\s*번호", 3, "주민번호 요구"),
    ("otp_request", r"(OTP|일회용\s*비밀번호|보안카드|인증번호)", 3, "OTP/보안카드/인증번호 요구"),
    ("transfer_agree", r"(보내드릴|이체할|송금할|입금할).{0,10}(요|게요|겠습니다|드릴)", 2, "송금 동의 발화"),
    ("meta_aware", r"(사기.{0,5}같|이상한데|진짜.{0,3}인가|이거.{0,3}사기)", 1, "메타인식 의심"),
    ("password_request", r"비밀번호.{0,5}(알려|입력|뭐|뭘|어떻)", 2, "비밀번호 요구"),
    ("app_install_lure", r"(앱|어플|어플리케이션|보안.{0,3}프로그램|업데이트).{0,8}(설치|다운로드)", 1, "앱 설치 유도"),
    ("urgent_call_demand", r"(끊지\s*마|전화\s*끊지|통화\s*유지)", 2, "통화 유지 압박"),
]
_COMPILED = [(flag, re.compile(pat), lvl, ko) for flag, pat, lvl, ko in _ALERT_PATTERNS]


def _scan_text(text: str) -> tuple[int, list[dict]]:
    matches: list[dict] = []
    max_level = 0
    for flag, regex, level, label in _COMPILED:
        for m in regex.finditer(text):
            matches.append({
                "flag": flag,
                "label_ko": label,
                "level": level,
                "snippet": m.group(0),
            })
            if level > max_level:
                max_level = level
    return max_level, matches


def _ndjson(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


@router.post(
    "/api/analyze-stream",
    tags=["Public"],
    summary="긴 음성 파일 chunk 스트리밍 분석 (NDJSON)",
    description=(
        "긴 음성 파일을 `chunk_seconds` 단위로 잘라 각 chunk 의 STT + 키워드 alert "
        "결과를 NDJSON 으로 즉시 흘려준다.\n\n"
        "**Form fields**:\n"
        "- `file` — 음성/영상 파일 (필수)\n"
        "- `chunk_seconds` — 청크 길이 초 단위 (기본 60)\n\n"
        "**응답**: `application/x-ndjson` — 각 줄이 한 개의 JSON 이벤트 "
        "(`start` / `chunk` / `done` / `error`)\n\n"
        "**인증**: API key 필수."
    ),
    responses={
        400: {"description": "파일 비어있음 / 코덱 오류"},
        401: {"description": "API key 누락 또는 무효"},
        429: {"description": "Rate limit 초과"},
    },
)
async def analyze_stream(
    file: UploadFile = File(...),
    chunk_seconds: int = Form(60),
) -> StreamingResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="업로드된 파일 이름이 비어 있습니다.")
    if chunk_seconds < 5 or chunk_seconds > 600:
        raise HTTPException(status_code=400, detail="chunk_seconds 는 5~600 범위여야 합니다.")

    suffix = Path(file.filename).suffix
    upload_dir = Path(".scamguardian") / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    tmp_handle = tempfile.NamedTemporaryFile(
        mode="wb", delete=False, dir=str(upload_dir),
        prefix="stream_", suffix=suffix,
    )
    tmp_path = Path(tmp_handle.name)
    wav_path = tmp_path.with_suffix(".wav")
    chunks_dir = Path(tempfile.mkdtemp(prefix="stream_chunks_", dir=str(upload_dir)))

    # 파일 저장 + wav 변환 — generator 시작 전에 동기로 마쳐서 에러는 HTTPException 으로 깔끔히
    try:
        with tmp_handle:
            if file.file is None:
                raise HTTPException(status_code=400, detail="업로드된 파일 본문을 읽을 수 없습니다.")
            shutil.copyfileobj(file.file, tmp_handle)
        if tmp_path.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="업로드된 파일이 비어 있습니다(0 bytes).")

        # wav 변환 + 음향 전처리 — VAD (침묵 제거) + 음량 정규화.
        # silenceremove: 1초 이상 -40dB 이하 침묵 제거 (Whisper hallucination 근본 차단)
        # dynaudnorm: 피해자 측 작은 발화 증폭
        extract = subprocess.run(
            ["ffmpeg", "-y", "-i", str(tmp_path),
             "-vn", "-ac", "1", "-ar", "16000",
             "-af", "silenceremove=stop_periods=-1:stop_duration=1:stop_threshold=-40dB,dynaudnorm=f=150:g=15",
             "-f", "wav", str(wav_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        if extract.returncode != 0 or not wav_path.exists() or wav_path.stat().st_size == 0:
            raise HTTPException(
                status_code=400,
                detail="업로드된 파일에서 오디오를 추출하지 못했습니다. 다른 파일(코덱)로 시도해주세요.",
            )
    except HTTPException:
        for p in (tmp_path, wav_path):
            try: p.unlink(missing_ok=True)
            except Exception: pass
        try: shutil.rmtree(chunks_dir, ignore_errors=True)
        except Exception: pass
        raise

    async def event_stream() -> AsyncIterator[bytes]:
        try:
            from pipeline import diarize as _diarize
            from pipeline import stt as _stt

            # wav → wav chunks (동일 코덱 copy)
            seg_pattern = str(chunks_dir / "chunk_%04d.wav")
            split = subprocess.run(
                ["ffmpeg", "-y", "-i", str(wav_path),
                 "-f", "segment", "-segment_time", str(chunk_seconds),
                 "-c", "copy", seg_pattern],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
            if split.returncode != 0:
                yield _ndjson({"type": "error", "message": "audio segmentation failed"})
                return

            chunk_files = sorted(chunks_dir.glob("chunk_*.wav"))
            total = len(chunk_files)
            if total == 0:
                yield _ndjson({"type": "error", "message": "분할된 chunk 가 없습니다."})
                return

            yield _ndjson({
                "type": "start",
                "total_chunks": total,
                "chunk_seconds": chunk_seconds,
                "source_filename": file.filename,
            })

            full_text_parts: list[str] = []
            cumulative_matches: list[dict] = []
            for idx, cf in enumerate(chunk_files):
                started = time.monotonic()
                text = ""
                stt_result = None
                try:
                    stt_result = await asyncio.to_thread(_stt.transcribe, str(cf))
                    text = stt_result.text or ""
                except Exception as exc:
                    LOG.warning("chunk %d STT 실패: %s", idx, exc)
                full_text_parts.append(text)
                # 화자 분리 — STT 백엔드 (CLOVA) 가 직접 분리한 경우 그것 사용.
                # 아니면 Sonnet diarize + entity extraction.
                turns_dicts: list[dict] = []
                stt_native_turns = getattr(stt_result, "turns", None) if stt_result else None
                if stt_native_turns:
                    turns_dicts = stt_native_turns
                else:
                    try:
                        turns = await asyncio.to_thread(
                            _diarize.diarize, text, _diarize.SONNET_MODEL, True,
                        )
                        turns_dicts = _diarize.turns_to_dict(turns)
                    except Exception as exc:
                        LOG.warning("chunk %d diarize 실패: %s", idx, exc)
                level, matches = _scan_text(text)
                cumulative_matches.extend(matches)
                latency_ms = int((time.monotonic() - started) * 1000)
                yield _ndjson({
                    "type": "chunk",
                    "chunk_index": idx,
                    "start_sec": idx * chunk_seconds,
                    "end_sec": (idx + 1) * chunk_seconds,
                    "transcript": text,
                    "turns": turns_dicts,
                    "alert_level": level,
                    "matches": matches,
                    "latency_ms": latency_ms,
                })

            cum_level = max((m["level"] for m in cumulative_matches), default=0)
            yield _ndjson({
                "type": "done",
                "total_chunks": total,
                "full_transcript": "\n".join(full_text_parts).strip(),
                "cumulative_matches": cumulative_matches,
                "cumulative_alert_level": cum_level,
            })
        finally:
            try: tmp_path.unlink(missing_ok=True)
            except Exception: pass
            try: wav_path.unlink(missing_ok=True)
            except Exception: pass
            try: shutil.rmtree(chunks_dir, ignore_errors=True)
            except Exception: pass

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
