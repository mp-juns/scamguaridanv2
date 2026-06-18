"""Short-lived tokens for browser Live WebSocket (no API key in URL)."""

from __future__ import annotations

import secrets
import time

_TOKENS: dict[str, float] = {}
_DEFAULT_TTL = 3600


def mint_live_ws_token(*, ttl_sec: int | None = None) -> tuple[str, int]:
    ttl = ttl_sec if ttl_sec is not None else _DEFAULT_TTL
    token = secrets.token_urlsafe(16)
    _TOKENS[token] = time.monotonic() + ttl
    _prune()
    return token, ttl


def validate_live_ws_token(token: str | None) -> bool:
    if not token:
        return False
    exp = _TOKENS.get(token)
    if exp is None:
        return False
    if time.monotonic() > exp:
        _TOKENS.pop(token, None)
        return False
    return True


def _prune() -> None:
    now = time.monotonic()
    stale = [k for k, exp in _TOKENS.items() if exp <= now]
    for k in stale:
        _TOKENS.pop(k, None)
