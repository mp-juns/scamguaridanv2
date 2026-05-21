"""결과 상세 페이지 토큰 시스템 — 발급·만료·조회.

카카오 카드의 "자세히 보기" 링크가 가리키는 1시간 유효 토큰. 메모리 저장 (state.result_tokens).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any

from fastapi import APIRouter, HTTPException

from db import repository
from pipeline import kakao_formatter

from . import state

router = APIRouter()


# Stage 1 게이트 bucket 중 *비-판정* 버킷만 결과 페이지에 노출.
# - normal / scam_news_edu / undetermined → 콘텐츠 타입 정보 (Identity Boundary 안전)
# - scam_attempt / suspicious_insufficient → 노출 X ("사기 시도다" 판정에 해당)
SAFE_CONTENT_TYPE_BUCKETS: frozenset[str] = frozenset(
    {"normal", "scam_news_edu", "undetermined"}
)


def _safe_content_type(gate: dict[str, Any] | None) -> dict[str, str] | None:
    """게이트 metadata → 결과 응답의 `content_type` 필드.

    안전 버킷(normal/scam_news_edu/undetermined)만 통과. 사기 시도/의심 버킷은
    Identity Boundary 상 노출 안 함 (판정성 정보).
    """
    if not gate:
        return None
    bucket = str(gate.get("bucket") or "").strip()
    if bucket not in SAFE_CONTENT_TYPE_BUCKETS:
        return None
    label_ko = str(gate.get("label_ko") or "").strip() or bucket
    return {"bucket": bucket, "label_ko": label_ko}


def get_public_base_url() -> str:
    """결과 링크 베이스 URL 동적 조회. env 우선, 없으면 ngrok local API 자동 탐색.

    60초 캐시. ngrok 재시작 시에도 환경변수 따로 안 바꿔도 됨.
    """
    now = time.time()
    if now < state.public_url_cache.get("expires", 0):
        return state.public_url_cache.get("url", "")

    env = os.getenv("SCAMGUARDIAN_PUBLIC_URL", "").strip().rstrip("/")
    url = env
    if not url:
        try:
            import json as _json
            import urllib.request as _ureq
            ngrok_api = os.getenv("SCAMGUARDIAN_NGROK_API", "http://127.0.0.1:4040/api/tunnels").strip()
            with _ureq.urlopen(ngrok_api, timeout=1) as resp:
                data = _json.loads(resp.read().decode())
                for t in data.get("tunnels", []):
                    pu = (t.get("public_url") or "").strip()
                    if pu.startswith("https"):
                        url = pu.rstrip("/")
                        break
        except Exception:
            pass

    state.public_url_cache["url"] = url
    state.public_url_cache["expires"] = now + 60
    return url


def cleanup_expired_result_tokens() -> None:
    now = time.time()
    expired = [t for t, e in state.result_tokens.items() if e.get("expires_at", 0) < now]
    for t in expired:
        del state.result_tokens[t]


def issue_result_token(
    *,
    result: dict[str, Any],
    user_context: dict[str, Any] | None,
    input_type: kakao_formatter.InputType,
    user_id: str | None,
    chat_history: list[Any] | None = None,
) -> tuple[str, str | None]:
    """결과 상세 토큰 발급 + 공개 URL 반환. URL 은 SCAMGUARDIAN_PUBLIC_URL 미설정 시 None."""
    import secrets
    cleanup_expired_result_tokens()
    token = secrets.token_urlsafe(16)
    state.result_tokens[token] = {
        "result": result,
        "user_context": user_context,
        "input_type": input_type.value if hasattr(input_type, "value") else str(input_type),
        "expires_at": time.time() + state.RESULT_TOKEN_TTL,
        "user_id": user_id,
        "chat_history": [
            {"role": getattr(t, "role", ""), "message": getattr(t, "message", "")}
            for t in (chat_history or [])
        ],
    }
    base = get_public_base_url()
    url = f"{base}/result/{token}" if base else None

    logging.getLogger("token").info(
        "result_token issued: token=%s run_id=%s detected_signals=%d",
        token[:8],
        (result or {}).get("analysis_run_id"),
        len((result or {}).get("detected_signals") or []),
    )

    run_id = (result or {}).get("analysis_run_id")
    if run_id and repository.persistence_enabled():
        try:
            chat_dump = [
                {"role": getattr(t, "role", ""), "message": getattr(t, "message", "")}
                for t in (chat_history or [])
            ]
            partial = {}
            if user_context:
                partial["user_context"] = user_context
            if chat_dump:
                partial["chat_history"] = chat_dump
            if partial:
                repository.merge_run_metadata(run_id, partial)
        except Exception as exc:
            logging.getLogger("token").warning(
                "metadata merge 실패 (run_id=%s): %s", run_id, exc,
            )

    return token, url


@router.get(
    "/api/result/{token}",
    tags=["Public"],
    summary="결과 토큰으로 분석 결과 조회",
    description=(
        "카카오 챗봇 응답 카드의 '자세히 보기' 링크가 호출하는 엔드포인트. "
        "결과 발급 시점에 1시간 유효 토큰을 발급(`secrets.token_urlsafe(16)`)하고 "
        "메모리에 저장한다. 인메모리 저장이라 서버 재시작 시 토큰은 모두 만료.\n\n"
        "**응답**:\n"
        "- `result` — `DetectionReport.to_dict()` 전체 (`/api/analyze` 와 동일 schema)\n"
        "- `user_context` — 사용자가 챗봇과 나눈 Q&A 요약 (있을 때)\n"
        "- `input_type` — `TEXT|URL|VIDEO|FILE|IMAGE|PDF`\n"
        "- `chat_history` — 봇/사용자 대화 시간순 전체\n"
        "- `flag_rationale` — 검출된 신호별 `{rationale, source}` 매핑\n"
        "- `expires_at` — 토큰 만료 시각 (epoch sec)\n\n"
        "**인증**: 선택. 토큰 자체가 인증 역할 (URL 알면 누구나 조회).\n\n"
        "**에러**:\n"
        "- `404` — 토큰이 존재한 적 없음 또는 서버 재시작\n"
        "- `410` — 토큰 만료 (1시간 경과)\n\n"
        "**curl**:\n"
        "```bash\n"
        "curl https://api.example.com/api/result/abcd1234efgh5678\n"
        "```"
    ),
    responses={
        404: {"description": "토큰 없음"},
        410: {"description": "토큰 만료 — 결과 재요청 필요"},
    },
)
async def get_result_by_token(token: str) -> dict[str, Any]:
    """카카오 카드의 '자세히 보기' 링크 백엔드 — 토큰으로 분석 결과 반환.

    1시간 TTL. 토큰 없거나 만료 시 404/410.
    """
    cleanup_expired_result_tokens()
    entry = state.result_tokens.get(token)
    if entry is None:
        raise HTTPException(status_code=404, detail="결과를 찾을 수 없습니다.")
    if entry.get("expires_at", 0) < time.time():
        state.result_tokens.pop(token, None)
        raise HTTPException(status_code=410, detail="결과 링크가 만료됐어요 (1시간 후 만료).")
    from pipeline.config import flag_rationale
    # 검출된 신호의 학술/법적 근거 dictionary — 결과 페이지에서 "이 신호는 왜 위험?" 답변용
    flag_info: dict[str, dict[str, str]] = {}
    for s in (entry["result"].get("detected_signals") or []):
        key = (s.get("flag") or "").strip()
        if key and key not in flag_info:
            info = flag_rationale(key)
            if info:
                flag_info[key] = info

    # Stage 1 게이트 안전 버킷만 content_type 으로 노출 (DB metadata 기반).
    # 사기 시도/의심 버킷은 Identity Boundary 상 결과 페이지에 표시 안 함.
    content_type: dict[str, str] | None = None
    run_id = (entry["result"] or {}).get("analysis_run_id")
    if run_id:
        try:
            detail = await asyncio.to_thread(repository.get_run_detail, run_id)
            if detail:
                meta = (detail.get("run") or {}).get("metadata") or {}
                content_type = _safe_content_type(meta.get("gate"))
        except Exception as exc:
            logging.getLogger("token").debug(
                "content_type lookup 실패 (run_id=%s): %s", run_id, exc,
            )

    return {
        "result": entry["result"],
        "user_context": entry.get("user_context"),
        "input_type": entry.get("input_type"),
        "chat_history": entry.get("chat_history") or [],
        "flag_rationale": flag_info,
        "content_type": content_type,
        "expires_at": entry["expires_at"],
    }
