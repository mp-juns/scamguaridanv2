"""카카오 라이브 보이스피싱 전용 1회용 세션 토큰."""

from __future__ import annotations

import secrets
import time
from typing import Any, Literal

from . import state

ConsumeReason = Literal["ok", "not_found", "expired", "already_used", "user_mismatch"]


def _normalize_user_id(user_id: str | None) -> str:
    return (user_id or "").strip()


def cleanup_expired_live_session_tokens() -> None:
    now = time.time()
    expired = [
        token
        for token, entry in state.live_session_tokens.items()
        if float(entry.get("expires_at") or 0) <= now
    ]
    for token in expired:
        state.live_session_tokens.pop(token, None)


def issue_live_session_token(*, user_id: str, ttl_sec: int | None = None) -> tuple[str, int]:
    uid = _normalize_user_id(user_id)
    if not uid:
        raise ValueError("user_id is required")
    ttl = ttl_sec if ttl_sec is not None else state.LIVE_SESSION_TOKEN_TTL
    now = time.time()
    token = secrets.token_urlsafe(18)
    state.live_session_tokens[token] = {
        "user_id": uid,
        "issued_at": now,
        "expires_at": now + ttl,
        "consumed_at": None,
    }
    cleanup_expired_live_session_tokens()
    return token, ttl


def get_live_session(token: str | None) -> dict[str, Any] | None:
    cleanup_expired_live_session_tokens()
    if not token:
        return None
    entry = state.live_session_tokens.get(token)
    if not entry:
        return None
    return dict(entry)


def consume_live_session_token(
    token: str | None, *, expected_user_id: str | None = None
) -> tuple[dict[str, Any] | None, ConsumeReason]:
    cleanup_expired_live_session_tokens()
    if not token:
        return None, "not_found"
    entry = state.live_session_tokens.get(token)
    if entry is None:
        return None, "not_found"
    if float(entry.get("expires_at") or 0) <= time.time():
        state.live_session_tokens.pop(token, None)
        return None, "expired"
    if entry.get("consumed_at"):
        return None, "already_used"

    expected_uid = _normalize_user_id(expected_user_id)
    if expected_uid and expected_uid != _normalize_user_id(str(entry.get("user_id") or "")):
        return None, "user_mismatch"

    entry["consumed_at"] = time.time()
    return dict(entry), "ok"
