"""
FastAPI middleware — request_id 주입, API key 검증, rate limit, request log.

적용 범위:
- 분석 엔드포인트(`/api/analyze`, `/api/analyze-upload`) — API key 필수
- 메서드ology / 결과 토큰 — API key 선택 (있으면 사용량 기록)
- webhook(`/webhook/kakao`) — 카카오 자체 인증 사용, skip
- admin (`/api/admin/*`) — 단일 admin token (`SCAMGUARDIAN_ADMIN_TOKEN`) 필수
  - `X-Admin-Token` 헤더 또는 `Authorization: Bearer admin-<token>` 로 전달
  - `/api/admin/login` 만 인증 면제 (토큰 검증 자체가 목적)

키 추출 우선순위:
1. `Authorization: Bearer sg_...`
2. `X-API-Key: sg_...`
"""

from __future__ import annotations

import hmac
import logging
import os
import re
import time
import uuid

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from db import repository
from platform_layer import api_keys as api_key_module
from platform_layer import cost as cost_module
from platform_layer import rate_limit

log = logging.getLogger("middleware")

# API key 가 *반드시* 필요한 경로
_REQUIRE_KEY_PATTERNS = [
    re.compile(r"^/api/analyze$"),
    re.compile(r"^/api/analyze-upload$"),
    re.compile(r"^/api/transcribe-upload$"),
    re.compile(r"^/api/analyze-stream$"),
    re.compile(r"^/api/live-analyze$"),
]
# API key 선택 (있으면 기록만)
_OPTIONAL_KEY_PATTERNS = [
    re.compile(r"^/api/result/"),
    re.compile(r"^/api/methodology$"),
]
# admin token 필수
_REQUIRE_ADMIN_PATTERNS = [
    re.compile(r"^/api/admin/"),
]
# admin 패턴 중 인증 면제 (login/health)
_ADMIN_PUBLIC_PATTERNS = [
    re.compile(r"^/api/admin/login$"),
]
# 인증 스킵
_SKIP_PATTERNS = [
    re.compile(r"^/webhook/"),
    re.compile(r"^/health$"),
    re.compile(r"^/docs"),
    re.compile(r"^/openapi"),
    re.compile(r"^/redoc"),
]


def _extract_admin_token(request: Request) -> str | None:
    explicit = request.headers.get("x-admin-token", "").strip()
    if explicit:
        return explicit
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer admin-"):
        return auth.split("admin-", 1)[1].strip() or None
    return None


def _admin_token_valid(provided: str | None) -> bool:
    expected = (os.getenv("SCAMGUARDIAN_ADMIN_TOKEN") or "").strip()
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected, provided)


def _admin_auth_disabled() -> bool:
    """env ADMIN_AUTH_DISABLED 가 true 면 어드민 인증 전체 bypass (개발용)."""
    return (os.getenv("ADMIN_AUTH_DISABLED", "").strip().lower() in {"1", "true", "yes", "on"})


def _extract_key(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth.split(None, 1)[1].strip() or None
    return request.headers.get("x-api-key", "").strip() or None


def _category(path: str) -> str:
    for pat in _SKIP_PATTERNS:
        if pat.search(path):
            return "skip"
    for pat in _ADMIN_PUBLIC_PATTERNS:
        if pat.search(path):
            return "admin_public"
    for pat in _REQUIRE_ADMIN_PATTERNS:
        if pat.search(path):
            return "admin"
    for pat in _REQUIRE_KEY_PATTERNS:
        if pat.search(path):
            return "require"
    for pat in _OPTIONAL_KEY_PATTERNS:
        if pat.search(path):
            return "optional"
    return "skip"  # 정의되지 않은 경로 — 기본 skip


class PlatformMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        path = request.url.path
        category = _category(path)

        if category == "admin" and not _admin_auth_disabled():
            if not _admin_token_valid(_extract_admin_token(request)):
                expected = (os.getenv("SCAMGUARDIAN_ADMIN_TOKEN") or "").strip()
                detail = (
                    "어드민 토큰이 없거나 잘못되었습니다."
                    if expected
                    else "SCAMGUARDIAN_ADMIN_TOKEN 환경변수가 설정되지 않아 어드민 접근이 비활성화되어 있습니다."
                )
                return JSONResponse(
                    {"detail": detail, "code": "admin_unauthorized"},
                    status_code=401,
                    headers={"x-request-id": request_id},
                )

        api_key_record = None
        api_key_id = None
        plaintext = _extract_key(request)

        if category in ("require", "optional") and plaintext:
            api_key_record = api_key_module.lookup(plaintext)

        if category == "require":
            if not plaintext or api_key_record is None:
                return JSONResponse(
                    {
                        "detail": "API key 가 필요합니다. 'Authorization: Bearer sg_...' 또는 'X-API-Key' 헤더로 전달하세요.",
                        "code": "missing_or_invalid_api_key",
                    },
                    status_code=401,
                    headers={"x-request-id": request_id},
                )
            if api_key_record.get("status") != "active":
                return JSONResponse(
                    {"detail": f"API key 상태: {api_key_record.get('status')}", "code": "key_revoked"},
                    status_code=403,
                    headers={"x-request-id": request_id},
                )

        if api_key_record is not None:
            api_key_id = api_key_record["id"]
            # rate limit
            try:
                rate_limit.check_and_consume(api_key_id, int(api_key_record.get("rpm_limit") or 30))
            except rate_limit.RateLimitExceeded as exc:
                return JSONResponse(
                    {"detail": "분당 호출 한도를 초과했습니다.", "code": f"rate_limit_{exc.scope}"},
                    status_code=429,
                    headers={"retry-after": str(exc.retry_after), "x-request-id": request_id},
                )
            # 월별 USD cap
            try:
                rate_limit.check_monthly_usd_cap(
                    api_key_id, float(api_key_record.get("monthly_usd_quota") or 0),
                )
            except rate_limit.RateLimitExceeded as exc:
                return JSONResponse(
                    {"detail": "월별 비용 한도를 초과했습니다.", "code": f"quota_{exc.scope}"},
                    status_code=429,
                    headers={"retry-after": str(exc.retry_after), "x-request-id": request_id},
                )
            # 월별 호출 수 쿼터
            try:
                rate_limit.consume_monthly_quota(api_key_id)
            except rate_limit.RateLimitExceeded as exc:
                return JSONResponse(
                    {"detail": "월별 호출 한도를 초과했습니다.", "code": f"quota_{exc.scope}"},
                    status_code=429,
                    headers={"retry-after": str(exc.retry_after), "x-request-id": request_id},
                )

        # cost / log context 주입
        cost_module.set_context(request_id=request_id, api_key_id=api_key_id)
        request.state.api_key_id = api_key_id

        started = time.time()
        status_code = 500
        error_msg: str | None = None
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["x-request-id"] = request_id
            return response
        except HTTPException as exc:
            status_code = exc.status_code
            error_msg = str(exc.detail)
            raise
        except Exception as exc:  # noqa: BLE001
            error_msg = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            latency_ms = int((time.time() - started) * 1000)
            try:
                repository.insert_request_log(
                    request_id=request_id,
                    api_key_id=api_key_id,
                    method=request.method,
                    path=path,
                    status=status_code,
                    latency_ms=latency_ms,
                    error=error_msg,
                )
            except Exception:
                pass
            cost_module.clear_context()
            log.info(
                "req=%s key=%s %s %s -> %s %dms%s",
                request_id,
                (api_key_id or "-")[:8],
                request.method,
                path,
                status_code,
                latency_ms,
                f" err={error_msg[:80]}" if error_msg else "",
            )
