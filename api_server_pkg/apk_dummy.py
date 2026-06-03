"""어드민 — 더미 피싱앱 다운로드 링크 생성 (APK 검출 e2e 테스트용).

`data_examples/apk/` 의 **무해 prebuilt 더미 APK**(dead-code, RFC5737/.tk 비라우팅)를
만료되는 공개 토큰 URL 로 발급한다. 발급된 링크를 메인 분석/kakao 챗봇에 붙여넣으면
파이프라인이 외부 배포처처럼 받아서(Phase 0 VT + 정적 Lv1/Lv2 + 동적 Lv3) 분석한다.

- 발급/카탈로그: `/api/admin/apk-dynamic/dummy/*` (admin 토큰 필요)
- 공개 다운로드: `/api/apk-dummy/{token}` (비-admin — 파이프라인/kakao 가 fetch)

⚠️ 서빙 대상은 `data_examples/apk/` 하위 prebuilt 무해 더미로 한정(arbitrary path 차단).
"""

from __future__ import annotations

import re
import secrets
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from . import state
from .models import DummyLinkRequest
from .result_token import get_public_base_url

router = APIRouter()

_TAG = "Admin — APK Dummy"
_ADMIN_RESPONSES: dict[int | str, dict] = {
    401: {"description": "어드민 토큰 누락 또는 무효"},
    500: {"description": "서버 내부 오류"},
}

DATA_DIR = Path("data_examples") / "apk"

_DUMMY_PATH_RE = re.compile(r"/api/apk-dummy/([A-Za-z0-9_-]+)/?$")


def resolve_dummy_url_to_path(url: str) -> str | None:
    """더미 APK 다운로드 URL 이 *이 서버* 가 발급한 것이면 네트워크 없이 로컬 파일 경로로 해석한다.

    cloudflare/ngrok 등 공개 호스트로 발급된 자기 자신 링크는 백엔드에서 그 공개 URL 을
    되받아 fetch 하면 루프백 DNS 가 깨질 수 있다. 따라서 host 는 무시하고 path 의 토큰만 보고
    `state.apk_dummy_tokens` 에서 직접 로컬 파일을 찾는다. 외부 호스트의 임의 APK URL 은 None
    (→ 호출측이 일반 HTTP 다운로드로 처리).
    """
    if not url:
        return None
    try:
        path = urlparse(url.strip()).path
    except Exception:  # noqa: BLE001
        return None
    m = _DUMMY_PATH_RE.search(path or "")
    if not m:
        return None
    rec = state.apk_dummy_tokens.get(m.group(1))
    if rec is None or rec.get("expires_at", 0) < time.time():
        return None
    p = Path(str(rec.get("file_path", ""))).resolve()
    if DATA_DIR.resolve() not in p.parents or not p.is_file():
        return None
    return str(p)

# 알려진 더미별 메타 (없는 파일은 generic fallback). expected_signals 는 data_examples/apk/README + build_families.sh 기준.
_META: dict[str, dict[str, Any]] = {
    "fake_phishing": {
        "title": "카카오톡 사칭 (정적 9종)",
        "family": "generic",
        "tier": "static",
        "impersonates": "카카오톡 (com.kakao.talk.secure)",
        "expected_signals": [
            "apk_suspicious_package_name", "apk_dangerous_permissions_combo", "apk_self_signed",
            "apk_sms_auto_send_code", "apk_call_state_listener", "apk_accessibility_abuse",
            "apk_impersonation_keywords", "apk_hardcoded_c2_url", "apk_device_admin_lock",
        ],
    },
    "dynamic_active": {
        "title": "런타임 행동 (동적 5종)",
        "family": "generic",
        "tier": "dynamic",
        "impersonates": "정적 신호 0 → 격리 VM 실행 필요",
        "expected_signals": [
            "apk_runtime_c2_network_call", "apk_runtime_sms_intercepted", "apk_runtime_overlay_attack",
            "apk_runtime_credential_exfiltration", "apk_runtime_persistence_install",
        ],
    },
    "krbanker": {
        "title": "KrBanker — KB국민은행 사칭",
        "family": "KrBanker",
        "tier": "static",
        "impersonates": "KB국민은행 보안 (com.kbstar.kbbank.update)",
        "expected_signals": [
            "apk_suspicious_package_name", "apk_dangerous_permissions_combo", "apk_self_signed",
            "apk_impersonation_keywords", "apk_accessibility_abuse",
        ],
    },
    "moqhao": {
        "title": "MoqHao — CJ대한통운 택배 사칭",
        "family": "MoqHao",
        "tier": "static",
        "impersonates": "CJ대한통운 택배조회 (com.cj.delivery.official)",
        "expected_signals": [
            "apk_suspicious_package_name", "apk_dangerous_permissions_combo", "apk_self_signed",
            "apk_sms_auto_send_code", "apk_hardcoded_c2_url",
        ],
    },
    "secretcalls": {
        "title": "SecretCalls — 모바일 백신 사칭",
        "family": "SecretCalls",
        "tier": "static",
        "impersonates": "모바일 백신 보안 (com.secure.vaccine.fake)",
        "expected_signals": [
            "apk_suspicious_package_name", "apk_dangerous_permissions_combo", "apk_self_signed",
            "apk_call_state_listener", "apk_impersonation_keywords",
        ],
    },
}

# 다운로드 시 보일 기본 파일명 (피싱 배포처 모사)
_DEFAULT_FILENAME: dict[str, str] = {
    "fake_phishing": "KakaoTalk_보안업데이트.apk",
    "dynamic_active": "Security_Scanner.apk",
    "krbanker": "KB국민은행_보안인증.apk",
    "moqhao": "CJ대한통운_택배조회.apk",
    "secretcalls": "모바일백신_설치.apk",
}


def _catalog() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if not DATA_DIR.exists():
        return out
    for apk in sorted(DATA_DIR.glob("*.apk")):
        vid = apk.stem
        meta = _META.get(vid, {
            "title": vid, "family": "unknown", "tier": "static",
            "impersonates": "-", "expected_signals": [],
        })
        out.append({
            "id": vid,
            "filename": apk.name,
            "size": apk.stat().st_size,
            "default_filename": _DEFAULT_FILENAME.get(vid, apk.name),
            **meta,
        })
    return out


def _resolve_variant(variant_id: str) -> Path:
    """variant_id → data_examples/apk 하위 실제 파일 경로 (검증)."""
    candidate = (DATA_DIR / f"{variant_id}.apk").resolve()
    base = DATA_DIR.resolve()
    if base not in candidate.parents or not candidate.is_file():
        raise HTTPException(status_code=404, detail=f"더미 변종을 찾을 수 없습니다: {variant_id}")
    return candidate


def cleanup_expired_dummy_tokens() -> None:
    now = time.time()
    expired = [t for t, rec in state.apk_dummy_tokens.items() if rec.get("expires_at", 0) < now]
    for t in expired:
        state.apk_dummy_tokens.pop(t, None)


@router.get(
    "/api/admin/apk-dynamic/dummy/catalog",
    tags=[_TAG],
    summary="더미 APK 카탈로그",
    description="data_examples/apk 의 무해 prebuilt 더미 목록 + 각 더미가 트립하는 검출 신호.",
    responses=_ADMIN_RESPONSES,
)
async def dummy_catalog() -> dict[str, Any]:
    return {"variants": _catalog()}


@router.post(
    "/api/admin/apk-dynamic/dummy/link",
    tags=[_TAG],
    summary="더미 다운로드 링크 발급",
    description="만료되는 공개 토큰 URL 발급. 발급 URL 을 메인 분석/kakao 에 붙여넣어 e2e 테스트.",
    responses={**_ADMIN_RESPONSES, 404: {"description": "변종 없음"}},
)
async def dummy_link(payload: DummyLinkRequest) -> dict[str, Any]:
    path = _resolve_variant(payload.variant_id)
    cleanup_expired_dummy_tokens()
    ttl = max(60, min(86400, int(payload.ttl_seconds or state.APK_DUMMY_TOKEN_TTL)))
    filename = (payload.filename or _DEFAULT_FILENAME.get(payload.variant_id) or path.name).strip()
    token = secrets.token_urlsafe(16)
    now = time.time()
    state.apk_dummy_tokens[token] = {
        "variant_id": payload.variant_id,
        "file_path": str(path),
        "filename": filename,
        "expires_at": now + ttl,
        "created_at": now,
    }
    download_path = f"/api/apk-dummy/{token}"
    base = get_public_base_url()
    return {
        "token": token,
        "variant_id": payload.variant_id,
        "filename": filename,
        "download_path": download_path,
        "download_url": f"{base}{download_path}" if base else None,
        "expires_at": now + ttl,
    }


@router.get(
    "/api/admin/apk-dynamic/dummy/links",
    tags=[_TAG],
    summary="활성 더미 링크 목록",
    description="만료되지 않은 발급 링크들.",
    responses=_ADMIN_RESPONSES,
)
async def dummy_links() -> dict[str, Any]:
    cleanup_expired_dummy_tokens()
    base = get_public_base_url()
    links: list[dict[str, Any]] = []
    for token, rec in sorted(state.apk_dummy_tokens.items(), key=lambda kv: -kv[1].get("created_at", 0)):
        download_path = f"/api/apk-dummy/{token}"
        links.append({
            "token": token,
            "variant_id": rec.get("variant_id"),
            "filename": rec.get("filename"),
            "download_path": download_path,
            "download_url": f"{base}{download_path}" if base else None,
            "expires_at": rec.get("expires_at"),
            "created_at": rec.get("created_at"),
        })
    return {"links": links}


@router.get(
    "/api/apk-dummy/{token}",
    tags=[_TAG],
    summary="더미 APK 다운로드 (공개)",
    description="발급 토큰으로 무해 더미 APK 를 받는다. 파이프라인/kakao 가 외부 URL 처럼 fetch.",
    responses={404: {"description": "토큰 없음"}, 410: {"description": "토큰 만료"}},
)
async def dummy_download(token: str) -> FileResponse:
    # cleanup 을 먼저 돌리면 만료 토큰이 사라져 404 가 되므로, 만료는 여기서 직접 410 처리
    rec = state.apk_dummy_tokens.get(token)
    if rec is None:
        raise HTTPException(status_code=404, detail="유효하지 않은 토큰입니다.")
    if rec.get("expires_at", 0) < time.time():
        state.apk_dummy_tokens.pop(token, None)
        raise HTTPException(status_code=410, detail="토큰이 만료되었습니다.")
    # 경로 재검증 — data_examples/apk 하위만 허용 (arbitrary path 차단)
    path = Path(str(rec.get("file_path", ""))).resolve()
    base = DATA_DIR.resolve()
    if base not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    return FileResponse(
        str(path),
        media_type="application/vnd.android.package-archive",
        filename=str(rec.get("filename") or path.name),
    )
