"""Short-lived tokens for browser Live WebSocket (no API key in URL)."""

from __future__ import annotations

import secrets
import time

_TOKENS: dict[str, dict[str, str | float | None]] = {}
_DEFAULT_TTL = 3600


def mint_live_ws_token(
    *, ttl_sec: int | None = None, session_token: str | None = None
) -> tuple[str, int]:
    ttl = ttl_sec if ttl_sec is not None else _DEFAULT_TTL
    token = secrets.token_urlsafe(16)
    _TOKENS[token] = {
        "expires_at": time.monotonic() + ttl,
        "session_token": (session_token or "").strip() or None,
    }
    _prune()
    return token, ttl


def validate_live_ws_token(token: str | None, *, session_token: str | None = None) -> bool:
    if not token:
        return False
    entry = _TOKENS.get(token)
    if entry is None:
        return False
    exp = float(entry.get("expires_at") or 0)
    if time.monotonic() > exp:
        _TOKENS.pop(token, None)
        return False
    required_session = (entry.get("session_token") or "").strip()
    if required_session:
        return required_session == (session_token or "").strip()
    return True


def _prune() -> None:
    now = time.monotonic()
    stale = [k for k, entry in _TOKENS.items() if float(entry.get("expires_at") or 0) <= now]
    for k in stale:
        _TOKENS.pop(k, None)
