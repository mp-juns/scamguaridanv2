from __future__ import annotations

from fastapi.testclient import TestClient

from api_server import app
from api_server_pkg import state
from api_server_pkg.live_session_token import (
    consume_live_session_token,
    get_live_session,
    issue_live_session_token,
)


def test_live_session_token_issue_and_consume_once():
    state.live_session_tokens.clear()
    token, ttl = issue_live_session_token(user_id="user-1", ttl_sec=60)
    assert token
    assert ttl == 60

    entry = get_live_session(token)
    assert entry is not None
    assert entry.get("user_id") == "user-1"

    consumed, reason = consume_live_session_token(token, expected_user_id="user-1")
    assert reason == "ok"
    assert consumed is not None

    consumed_again, reason_again = consume_live_session_token(token, expected_user_id="user-1")
    assert consumed_again is None
    assert reason_again == "already_used"


def test_live_session_token_user_mismatch():
    state.live_session_tokens.clear()
    token, _ = issue_live_session_token(user_id="user-a", ttl_sec=60)
    consumed, reason = consume_live_session_token(token, expected_user_id="user-b")
    assert consumed is None
    assert reason == "user_mismatch"


def test_live_session_endpoint_preview_then_consume():
    state.live_session_tokens.clear()
    token, _ = issue_live_session_token(user_id="kakao-user", ttl_sec=60)
    client = TestClient(app)

    preview = client.get(f"/api/live-session/{token}?consume=false")
    assert preview.status_code == 200
    assert preview.json().get("consumed") is False

    consume = client.get(f"/api/live-session/{token}?consume=true")
    assert consume.status_code == 200
    body = consume.json()
    assert body.get("consumed") is True
    assert body.get("ws_token")
    assert body.get("session_token") == token

    second = client.get(f"/api/live-session/{token}?consume=true")
    assert second.status_code == 410
