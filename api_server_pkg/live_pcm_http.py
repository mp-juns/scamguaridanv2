"""POST /api/live-pcm-chunk — WebSocket 없이 5s PCM chunk STT (동일 Whisper 경로)."""

from __future__ import annotations

import asyncio
import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

router = APIRouter()
LOG = logging.getLogger("live_pcm_http")


@router.post(
    "/api/live-pcm-chunk",
    tags=["Public"],
    summary="Live PCM chunk STT (HTTP fallback)",
    description="16kHz mono WAV chunk → Whisper → 신호 스캔. WebSocket 불가 시 사용.",
)
async def live_pcm_chunk(file: UploadFile = File(...)) -> dict:
    if not file.filename:
        raise HTTPException(status_code=400, detail="파일 이름이 비어 있습니다.")

    suffix = Path(file.filename).suffix.lower() or ".wav"
    tmp_dir = Path(tempfile.mkdtemp(prefix="live_pcm_http_"))
    wav_path = tmp_dir / f"chunk{suffix}"
    try:
        with wav_path.open("wb") as out:
            if file.file is None:
                raise HTTPException(status_code=400, detail="본문을 읽을 수 없습니다.")
            shutil.copyfileobj(file.file, out)
        if wav_path.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="빈 오디오입니다.")

        from pipeline.live_stt import PCMBuffer, transcribe_pcm_chunk

        dur = PCMBuffer.wav_duration_sec(wav_path)
        if dur < 0.3:
            return {
                "type": "chunk",
                "transcript": "",
                "matches": [],
                "tier": 0,
                "latency_ms": 0,
            }

        loop = asyncio.get_running_loop()
        text, latency_ms = await loop.run_in_executor(None, transcribe_pcm_chunk, wav_path)

        from api_server_pkg.stream_analyze import _compute_tier, _scan_text

        _, matches = _scan_text(text or "")
        instant = any(m.get("instant") for m in matches)
        cum = sum(m.get("level", 0) for m in matches if not m.get("instant"))
        tier = _compute_tier(cum, instant, bool(matches))

        return {
            "type": "chunk",
            "transcript": text,
            "matches": matches,
            "tier": tier,
            "latency_ms": latency_ms,
        }
    except HTTPException:
        raise
    except Exception as exc:
        LOG.error("/api/live-pcm-chunk: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
