"""어드민 사용자 관리 — 마스터 + 승인요청 시스템.

- master = `SCAMGUARDIAN_MASTER_EMAILS` env (항상 허용, 락아웃 방지)
- 그 외 = `admin_users` 테이블 status (pending / approved / denied)

`/api/admin/access/check` 는 로그인 *전* NextAuth signIn 콜백이 호출 → 미들웨어 unauth 예외.
나머지는 admin 토큰 게이트(미들웨어) + 승인/거부는 `X-Admin-Email` ∈ masters 인 마스터만.
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from db import repository

router = APIRouter()
_TAG = "Admin — Users"
_ADMIN_RESPONSES: dict[int | str, dict] = {
    401: {"description": "어드민 토큰 누락 또는 무효"},
    403: {"description": "마스터 전용 작업"},
}


def _masters() -> set[str]:
    return {
        e.strip().lower()
        for e in os.getenv("SCAMGUARDIAN_MASTER_EMAILS", "").split(",")
        if e.strip()
    }


def _is_master(email: str | None) -> bool:
    return bool(email) and email.strip().lower() in _masters()


class EmailBody(BaseModel):
    email: str


@router.post(
    "/api/admin/access/check",
    tags=[_TAG],
    summary="로그인 허용 여부 확인 (로그인 전, unauth)",
    description="NextAuth signIn 콜백이 호출. master/approved 면 allowed, 모르는 계정은 pending 생성 후 거부.",
)
async def access_check(payload: EmailBody) -> dict:
    email = (payload.email or "").strip().lower()
    if not email:
        return {"allowed": False, "status": "invalid"}
    if _is_master(email):
        return {"allowed": True, "status": "approved", "role": "master"}
    user = repository.get_admin_user(email)
    if user and user["status"] == "approved":
        return {"allowed": True, "status": "approved", "role": "admin"}
    if user and user["status"] == "denied":
        return {"allowed": False, "status": "denied"}
    # unknown 또는 pending → pending 보장 (요청 적재)
    repository.upsert_access_request(email)
    return {"allowed": False, "status": "pending"}


def _require_master(x_admin_email: str | None) -> str:
    if not _is_master(x_admin_email):
        raise HTTPException(status_code=403, detail="마스터 전용 작업입니다.")
    return (x_admin_email or "").strip().lower()


@router.get(
    "/api/admin/users",
    tags=[_TAG],
    summary="admin 사용자 목록 (masters + pending/approved/denied)",
    responses=_ADMIN_RESPONSES,
)
async def list_users(x_admin_email: str | None = Header(default=None)) -> dict:
    return {
        "masters": sorted(_masters()),
        "you": (x_admin_email or "").strip().lower(),
        "is_master": _is_master(x_admin_email),
        "users": repository.list_admin_users(),
    }


@router.post(
    "/api/admin/users/approve",
    tags=[_TAG],
    summary="사용자 승인 (마스터 전용)",
    responses=_ADMIN_RESPONSES,
)
async def approve_user(payload: EmailBody, x_admin_email: str | None = Header(default=None)) -> dict:
    who = _require_master(x_admin_email)
    return repository.set_admin_user_status(payload.email, "approved", who) or {}


@router.post(
    "/api/admin/users/deny",
    tags=[_TAG],
    summary="사용자 거부 (마스터 전용)",
    responses=_ADMIN_RESPONSES,
)
async def deny_user(payload: EmailBody, x_admin_email: str | None = Header(default=None)) -> dict:
    who = _require_master(x_admin_email)
    return repository.set_admin_user_status(payload.email, "denied", who) or {}


@router.post(
    "/api/admin/users/revoke",
    tags=[_TAG],
    summary="승인 취소 (마스터 전용) — denied 로 전환",
    responses=_ADMIN_RESPONSES,
)
async def revoke_user(payload: EmailBody, x_admin_email: str | None = Header(default=None)) -> dict:
    who = _require_master(x_admin_email)
    if _is_master(payload.email):
        raise HTTPException(status_code=400, detail="마스터 계정은 취소할 수 없습니다 (env에서 관리).")
    return repository.set_admin_user_status(payload.email, "denied", who) or {}
