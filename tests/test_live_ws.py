"""Live WebSocket endpoint tests (mock STT)."""

from __future__ import annotations

import struct
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api_server import app
from pipeline.live_stt import samples_for_chunk


@pytest.fixture
def client():
    return TestClient(app)


def test_live_ws_rejects_without_key(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/live-transcribe") as ws:
            ws.receive_json()


def test_live_ws_accepts_live_token(client, monkeypatch):
    monkeypatch.setenv("LIVE_WS_ENABLED", "1")
    from api_server_pkg.live_ws_token import mint_live_ws_token

    token, _ = mint_live_ws_token(ttl_sec=60)

    with client.websocket_connect(f"/ws/live-transcribe?live_token={token}") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready"


def test_live_ws_accepts_internal_key(client, monkeypatch):
    monkeypatch.setenv("SCAMGUARDIAN_INTERNAL_API_KEY", "sg_test_internal_key")
    monkeypatch.setenv("LIVE_WS_ENABLED", "1")

    with patch("platform_layer.api_keys.lookup", return_value={"id": "k1", "status": "active"}):
        with client.websocket_connect("/ws/live-transcribe?api_key=sg_test_internal_key") as ws:
            ready = ws.receive_json()
            assert ready["type"] == "ready"
            assert ready["chunk_sec"] >= 2

            ws.send_json({"type": "start"})
            started = ws.receive_json()
            assert started["type"] == "started"

            ws.send_bytes(b"\x00\x00" * 100)
            ws.send_json({"type": "stop"})

            msg = ws.receive_json()
            assert msg["type"] in {"final", "chunk", "error"}


def test_live_ws_chunk_with_mock_stt(client, monkeypatch):
    monkeypatch.setenv("SCAMGUARDIAN_INTERNAL_API_KEY", "sg_test_internal_key")
    monkeypatch.setenv("LIVE_WS_ENABLED", "1")
    monkeypatch.setenv("LIVE_CHUNK_SEC", "2")

    pcm = struct.pack(f"<{samples_for_chunk(2)}h", *([0] * samples_for_chunk(2)))

    with patch("platform_layer.api_keys.lookup", return_value={"id": "k1", "status": "active"}):
        with patch("api_server_pkg.live_ws.transcribe_pcm_chunk", return_value=("테스트 전사", 42)):
            with client.websocket_connect("/ws/live-transcribe?api_key=sg_test_internal_key") as ws:
                ws.receive_json()
                ws.send_json({"type": "start"})
                ws.receive_json()
                ws.send_bytes(pcm)
                chunk = ws.receive_json()
                assert chunk["type"] == "chunk"
                assert chunk["transcript"] == "테스트 전사"
                ws.send_json({"type": "stop"})
                final = ws.receive_json()
                assert final["type"] == "final"


def test_live_ws_token_public(client):
    resp = client.get("/api/live-ws-token")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("token")


def test_live_pcm_chunk_mock(client, monkeypatch):
    monkeypatch.setenv("SCAMGUARDIAN_INTERNAL_API_KEY", "sg_test_internal_key")
    import io
    import struct
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(16000)
        wf.writeframes(struct.pack("<8000h", *([0] * 8000)))

    with patch("platform_layer.api_keys.lookup", return_value={"id": "k1", "status": "active", "rpm_limit": 9999, "monthly_quota": 999999}):
        with patch("platform_layer.rate_limit.check_and_consume"), patch(
            "platform_layer.rate_limit.consume_monthly_quota",
            return_value={"remaining": 999},
        ):
            with patch("pipeline.live_stt.transcribe_pcm_chunk", return_value=("안녕", 10)):
                resp = client.post(
                    "/api/live-pcm-chunk",
                    files={"file": ("c.wav", buf.getvalue(), "audio/wav")},
                    headers={"Authorization": "Bearer sg_test_internal_key"},
                )
    assert resp.status_code == 200
    assert resp.json()["transcript"] == "안녕"


def test_demo_ml_snapshot_public(client):
    resp = client.get("/api/demo/ml-snapshot")
    assert resp.status_code == 200
    data = resp.json()
    assert "gate" in data
    assert "classifier" in data
    assert "gliner" in data
    assert "runtime_demos" in data
