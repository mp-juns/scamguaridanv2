"""
Live v4 — 실시간 PCM 버퍼 + Whisper chunk STT + 세션 상태.

WebSocket 핸들러(`api_server_pkg/live_ws.py`)가 사용한다.
experiments/v4_whisper/chunker.py 의 파일 기반 로직을 in-memory PCM 으로 승격.
"""

from __future__ import annotations

import os
import tempfile
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SAMPLE_RATE = 16000
BYTES_PER_SAMPLE = 2  # int16 mono


def live_chunk_sec() -> int:
    # 데모 UX 기준: 첫 전사는 chunk 길이 + Whisper 지연이다.
    # 5초는 안정적이지만 체감이 느려 기본값은 3초로 낮춘다. 운영에서 정확도를 더
    # 중시하면 LIVE_CHUNK_SEC=5 로 되돌릴 수 있다.
    raw = os.getenv("LIVE_CHUNK_SEC", "3").strip()
    try:
        sec = int(raw)
    except ValueError:
        sec = 3
    return max(2, min(sec, 30))


def samples_for_chunk(chunk_sec: int | None = None) -> int:
    sec = chunk_sec if chunk_sec is not None else live_chunk_sec()
    return SAMPLE_RATE * sec


class PCMBuffer:
    """16kHz mono int16 PCM 누적 버퍼 — chunk_sec 마다 flush."""

    def __init__(self, chunk_sec: int | None = None) -> None:
        self.chunk_sec = chunk_sec if chunk_sec is not None else live_chunk_sec()
        self._chunk_samples = samples_for_chunk(self.chunk_sec)
        self._bytes: bytearray = bytearray()
        self.chunk_index = 0
        self.total_samples = 0

    @property
    def duration_sec(self) -> float:
        return self.total_samples / SAMPLE_RATE

    def append(self, pcm: bytes) -> None:
        if not pcm:
            return
        self._bytes.extend(pcm)
        self.total_samples += len(pcm) // BYTES_PER_SAMPLE

    def ready_to_flush(self) -> bool:
        return len(self._bytes) >= self._chunk_samples * BYTES_PER_SAMPLE

    def flush_chunk(self) -> Path | None:
        """chunk_sec 분량 PCM → 임시 wav. 부족하면 None."""
        need = self._chunk_samples * BYTES_PER_SAMPLE
        if len(self._bytes) < need:
            return None
        chunk_bytes = bytes(self._bytes[:need])
        del self._bytes[:need]
        path = Path(tempfile.mkdtemp(prefix="live_pcm_")) / f"chunk_{self.chunk_index:04d}.wav"
        self._write_wav(path, chunk_bytes)
        self.chunk_index += 1
        return path

    def flush_remainder(self) -> Path | None:
        """stop 시 남은 PCM (0.7s 미만이면 None)."""
        min_bytes = int(0.7 * SAMPLE_RATE) * BYTES_PER_SAMPLE
        if len(self._bytes) < min_bytes:
            return None
        chunk_bytes = bytes(self._bytes)
        self._bytes.clear()
        path = Path(tempfile.mkdtemp(prefix="live_pcm_")) / f"tail_{self.chunk_index:04d}.wav"
        self._write_wav(path, chunk_bytes)
        self.chunk_index += 1
        return path

    @staticmethod
    def _write_wav(path: Path, pcm: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(BYTES_PER_SAMPLE)
            wf.setframerate(SAMPLE_RATE)
            wf.writeframes(pcm)

    @staticmethod
    def wav_duration_sec(path: Path) -> float:
        try:
            with wave.open(str(path), "rb") as wf:
                return wf.getnframes() / float(wf.getframerate())
        except Exception:
            return 0.0


def transcribe_pcm_chunk(wav_path: Path, *, language: str = "ko") -> tuple[str, int]:
    """OpenAI Whisper API — chunk 1개 전사. (text, latency_ms)."""
    from openai import OpenAI

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY 가 설정되지 않았습니다.")

    t0 = time.monotonic()
    client = OpenAI(api_key=api_key)
    with wav_path.open("rb") as f:
        response = client.audio.transcriptions.create(
            model="whisper-1",
            file=f,
            language=language,
        )
    text = (response.text or "").strip()
    latency_ms = int((time.monotonic() - t0) * 1000)

    duration = PCMBuffer.wav_duration_sec(wav_path)
    if duration > 0:
        try:
            from platform_layer.cost import record_openai_whisper

            record_openai_whisper(duration)
        except Exception:
            pass

    return text, latency_ms


def _match_key(m: dict[str, Any]) -> str:
    return f"{m.get('flag')}|{m.get('snippet')}|{m.get('speaker') or ''}"


@dataclass
class LiveSessionState:
    """누적 transcript + monotonic tier + dedup matches."""

    full_transcript: str = ""
    matches: list[dict[str, Any]] = field(default_factory=list)
    tier: int = 0
    seq: int = 0

    def ingest_chunk_text(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        if self.full_transcript:
            self.full_transcript = f"{self.full_transcript} {text}".strip()
        else:
            self.full_transcript = text

    def apply_scan(self, chunk_text: str) -> tuple[list[dict[str, Any]], int, bool]:
        """chunk 텍스트 스캔 → (new_matches, tier, tier_changed)."""
        from api_server_pkg.stream_analyze import _compute_tier, _scan_text

        _, incoming = _scan_text(chunk_text or "")
        prev_tier = self.tier
        seen = {_match_key(m) for m in self.matches}
        new_matches = [m for m in incoming if _match_key(m) not in seen]
        if new_matches:
            self.matches.extend(new_matches)

        instant = any(m.get("instant") for m in self.matches)
        cum = sum(m.get("level", 0) for m in self.matches if not m.get("instant"))
        new_tier = _compute_tier(cum, instant, bool(self.matches))
        tier_changed = new_tier > self.tier
        self.tier = max(self.tier, new_tier)
        self.seq += 1
        return new_matches, self.tier, tier_changed
