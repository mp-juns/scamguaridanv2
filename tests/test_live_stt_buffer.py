"""Live v4 PCM buffer tests."""

from __future__ import annotations

import struct
import wave

from pipeline.live_stt import LiveSessionState, PCMBuffer, samples_for_chunk


def test_pcm_buffer_flush_exact_chunk():
    buf = PCMBuffer(chunk_sec=5)
    pcm = struct.pack(f"<{samples_for_chunk(5)}h", *([0] * samples_for_chunk(5)))
    buf.append(pcm)
    assert buf.ready_to_flush()
    path = buf.flush_chunk()
    assert path is not None
    assert path.exists()
    with wave.open(str(path), "rb") as wf:
        assert wf.getnframes() == samples_for_chunk(5)
        assert wf.getframerate() == 16000


def test_pcm_buffer_partial_no_flush():
    buf = PCMBuffer(chunk_sec=5)
    buf.append(b"\x00\x01" * 100)
    assert not buf.ready_to_flush()
    assert buf.flush_chunk() is None


def test_pcm_buffer_remainder_too_short():
    buf = PCMBuffer(chunk_sec=5)
    buf.append(b"\x00\x01" * 100)
    assert buf.flush_remainder() is None


def test_live_session_state_dedup():
    state = LiveSessionState()
    state.ingest_chunk_text("주민번호 알려드릴게요")
    new, tier, changed = state.apply_scan("주민번호 알려드릴게요")
    assert len(new) >= 1
    assert tier >= 1
    assert changed is True
    _, tier2, changed2 = state.apply_scan("주민번호 알려드릴게요")
    assert tier2 == tier
    assert changed2 is False
