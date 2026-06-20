"""WebSocket /ws/live-transcribe — Live v4 PCM 스트리밍 STT."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api_server_pkg.live_ws_token import validate_live_ws_token
from pipeline.live_stt import LiveSessionState, PCMBuffer, live_chunk_sec, transcribe_pcm_chunk

router = APIRouter()
LOG = logging.getLogger("live_ws")

_STT_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="live_stt")


def _ws_enabled() -> bool:
    return os.getenv("LIVE_WS_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}


def _extract_api_key(websocket: WebSocket) -> str | None:
    q = websocket.query_params.get("api_key", "").strip()
    if q:
        return q
    auth = websocket.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(None, 1)[1].strip() or None
    return websocket.headers.get("x-api-key", "").strip() or None


def _validate_api_key(plaintext: str | None) -> bool:
    if not plaintext:
        return False
    try:
        from platform_layer import api_keys as api_key_module

        rec = api_key_module.lookup(plaintext)
        return rec is not None and rec.get("status") == "active"
    except Exception:
        return False


def _ws_auth_ok(websocket: WebSocket) -> bool:
    live_token = websocket.query_params.get("live_token", "").strip()
    live_session_token = websocket.query_params.get("live_session_token", "").strip()
    if validate_live_ws_token(live_token, session_token=live_session_token):
        return True
    api_key = _extract_api_key(websocket)
    return _validate_api_key(api_key) or _internal_key_allowed(api_key)


async def _send_json(ws: WebSocket, payload: dict[str, Any]) -> None:
    await ws.send_text(json.dumps(payload, ensure_ascii=False))


async def _process_chunk(
    ws: WebSocket,
    state: LiveSessionState,
    wav_path: Path,
    *,
    start_sec: float,
    end_sec: float,
) -> None:
    loop = asyncio.get_running_loop()
    try:
        text, latency_ms = await loop.run_in_executor(_STT_POOL, transcribe_pcm_chunk, wav_path)
    except Exception as exc:
        await _send_json(ws, {"type": "error", "message": str(exc)})
        return
    finally:
        try:
            shutil.rmtree(wav_path.parent, ignore_errors=True)
        except Exception:
            pass

    state.ingest_chunk_text(text)
    new_matches, tier, tier_changed = state.apply_scan(text)
    await _send_json(
        ws,
        {
            "type": "chunk",
            "seq": state.seq,
            "chunk_index": state.seq - 1,
            "start_sec": round(start_sec, 2),
            "end_sec": round(end_sec, 2),
            "transcript": text,
            "full_transcript": state.full_transcript,
            "matches": new_matches,
            "cumulative_matches": state.matches,
            "tier": tier,
            "tier_changed": tier_changed,
            "latency_ms": latency_ms,
        },
    )


@router.websocket("/ws/live-transcribe")
async def live_transcribe_ws(websocket: WebSocket) -> None:
    if not _ws_enabled():
        await websocket.close(code=1008, reason="LIVE_WS_ENABLED=0")
        return

    if not _ws_auth_ok(websocket):
        await websocket.close(code=1008, reason="missing_or_invalid_api_key")
        return

    await websocket.accept()
    chunk_sec = live_chunk_sec()
    buffer = PCMBuffer(chunk_sec=chunk_sec)
    state = LiveSessionState()
    session_start = time.monotonic()
    flush_lock = asyncio.Lock()
    stop_requested = False

    await _send_json(
        websocket,
        {
            "type": "ready",
            "chunk_sec": chunk_sec,
            "sample_rate": 16000,
            "transport": "websocket",
        },
    )

    async def _flush_if_ready() -> None:
        async with flush_lock:
            while buffer.ready_to_flush():
                wav_path = buffer.flush_chunk()
                if wav_path is None:
                    break
                idx = buffer.chunk_index - 1
                start_sec = idx * chunk_sec
                end_sec = start_sec + chunk_sec
                await _process_chunk(websocket, state, wav_path, start_sec=start_sec, end_sec=end_sec)

    try:
        while True:
            message = await websocket.receive()
            if message.get("type") == "websocket.disconnect":
                break

            if "bytes" in message and message["bytes"]:
                buffer.append(message["bytes"])
                if buffer.ready_to_flush():
                    await _flush_if_ready()
                continue

            if "text" not in message:
                continue

            try:
                data = json.loads(message["text"])
            except json.JSONDecodeError:
                await _send_json(websocket, {"type": "error", "message": "invalid JSON"})
                continue

            msg_type = data.get("type")
            if msg_type == "auth":
                # query 로 이미 검증됨 — noop
                continue
            if msg_type == "start":
                await _send_json(websocket, {"type": "started", "chunk_sec": chunk_sec})
                continue
            if msg_type == "stop":
                stop_requested = True
                break
            if msg_type == "ping":
                await _send_json(websocket, {"type": "pong"})
                continue

    except WebSocketDisconnect:
        stop_requested = True
    finally:
        if stop_requested:
            async with flush_lock:
                tail = buffer.flush_remainder()
                if tail is not None:
                    dur = PCMBuffer.wav_duration_sec(tail)
                    end_sec = buffer.duration_sec
                    start_sec = max(0.0, end_sec - dur)
                    await _process_chunk(
                        websocket,
                        state,
                        tail,
                        start_sec=start_sec,
                        end_sec=end_sec,
                    )

            try:
                await _send_json(
                    websocket,
                    {
                        "type": "final",
                        "full_transcript": state.full_transcript,
                        "turns": [],
                        "cumulative_matches": state.matches,
                        "tier": state.tier,
                        "duration_sec": round(time.monotonic() - session_start, 2),
                    },
                )
            except Exception:
                pass

        try:
            await websocket.close()
        except Exception:
            pass
