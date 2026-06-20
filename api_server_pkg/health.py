"""/health 와 공개 정적·메타 응답."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter()
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@router.get(
    "/health",
    tags=["Health"],
    summary="서버 헬스체크",
    description=(
        "단순 liveness probe. 로드밸런서·모니터링 용도.\n\n"
        "- **인증**: 불필요\n"
        "- **응답**: `{\"status\": \"ok\"}`"
    ),
    responses={200: {"content": {"application/json": {"example": {"status": "ok"}}}}},
)
def healthcheck() -> dict[str, str]:
    return {"status": "ok"}


@router.get(
    "/api/config/runtime",
    tags=["Public"],
    summary="런타임 STT 백엔드 표시",
    description=(
        "현재 음성 전사에 사용 중인 백엔드를 노출. UI 배지 용도.\n\n"
        "- `stt_backend`: `openai_whisper` 또는 `claude` — `pipeline/stt.py` 의 "
        "`STT_BACKEND` 분기와 동일 라벨\n"
        "- `*_key_present`: 해당 백엔드 키가 환경에 존재하는지 (실제 키 값은 노출 X)\n\n"
        "**인증**: 불필요"
    ),
)
def get_runtime_config() -> dict[str, Any]:
    from pipeline.live_stt import live_chunk_sec

    backend = os.getenv("STT_BACKEND", "whisper").strip().lower()
    ws_enabled = os.getenv("LIVE_WS_ENABLED", "1").strip().lower() in {"1", "true", "yes", "on"}
    api_base = (os.getenv("SCAMGUARDIAN_PUBLIC_URL") or os.getenv("SCAMGUARDIAN_API_URL") or "http://127.0.0.1:8000").rstrip("/")
    live_ws_url = (os.getenv("NEXT_PUBLIC_LIVE_WS_URL") or os.getenv("LIVE_WS_URL") or "").strip()
    if not live_ws_url and ws_enabled:
        if api_base.startswith("https://"):
            live_ws_url = api_base.replace("https://", "wss://", 1) + "/ws/live-transcribe"
        elif api_base.startswith("http://"):
            live_ws_url = api_base.replace("http://", "ws://", 1) + "/ws/live-transcribe"
    return {
        "stt_backend": "claude" if backend == "claude" else ("clova" if backend == "clova" else "openai_whisper"),
        "openai_key_present": bool(os.getenv("OPENAI_API_KEY")),
        "anthropic_key_present": bool(os.getenv("ANTHROPIC_API_KEY")),
        "live_transport": "websocket" if ws_enabled else "http",
        "live_ws_enabled": ws_enabled,
        "live_ws_url": live_ws_url,
        "live_chunk_sec": live_chunk_sec(),
    }


def _build_live_ws_url() -> str:
    api_base = (
        os.getenv("SCAMGUARDIAN_PUBLIC_URL")
        or os.getenv("SCAMGUARDIAN_FUNNEL_URL")
        or os.getenv("SCAMGUARDIAN_API_URL")
        or "http://127.0.0.1:8000"
    ).rstrip("/")
    live_ws_url = (os.getenv("NEXT_PUBLIC_LIVE_WS_URL") or os.getenv("LIVE_WS_URL") or "").strip()
    if live_ws_url:
        return live_ws_url
    if api_base.startswith("https://"):
        return api_base.replace("https://", "wss://", 1) + "/ws/live-transcribe"
    if api_base.startswith("http://"):
        return api_base.replace("http://", "ws://", 1) + "/ws/live-transcribe"
    return ""


@router.get(
    "/api/live-ws-token",
    tags=["Public"],
    summary="Live WebSocket 세션 토큰 발급",
    description="브라우저 Live v4 WebSocket 연결용 1시간 TTL 토큰. API key URL 노출 없이 사용.",
)
def get_live_ws_token() -> dict[str, Any]:
    from api_server_pkg.live_ws_token import mint_live_ws_token

    token, ttl = mint_live_ws_token()
    return {"token": token, "ttl_sec": ttl}


@router.get(
    "/api/live-session/{token}",
    tags=["Public"],
    summary="카카오 라이브 보이스피싱 1회용 세션 검증",
    description=(
        "카카오에서 발급한 라이브 전용 1회용 링크 토큰을 검증한다. "
        "`consume=true`(기본)이면 즉시 1회 사용 처리하고 WS 접속 토큰을 함께 반환한다. "
        "`consume=false`면 유효성만 확인한다."
    ),
)
def get_live_session(token: str, consume: bool = True) -> dict[str, Any]:
    from api_server_pkg.live_session_token import consume_live_session_token, get_live_session
    from api_server_pkg.live_ws_token import mint_live_ws_token

    if consume:
        entry, reason = consume_live_session_token(token)
        if reason == "ok" and entry is not None:
            remaining = max(60, int(float(entry.get("expires_at") or 0) - time.time()))
            ws_ttl = min(900, remaining)
            ws_token, ttl = mint_live_ws_token(ttl_sec=ws_ttl, session_token=token)
            return {
                "ok": True,
                "session_token": token,
                "ws_token": ws_token,
                "ttl_sec": ttl,
                "ws_url": _build_live_ws_url(),
                "consumed": True,
            }
        if reason in {"expired", "already_used"}:
            raise HTTPException(status_code=410, detail="라이브 세션 링크가 만료되었거나 이미 사용되었습니다.")
        if reason == "user_mismatch":
            raise HTTPException(status_code=403, detail="해당 사용자에게 발급된 세션이 아닙니다.")
        raise HTTPException(status_code=404, detail="라이브 세션을 찾을 수 없습니다.")

    entry = get_live_session(token)
    if not entry:
        raise HTTPException(status_code=404, detail="라이브 세션을 찾을 수 없습니다.")
    if entry.get("consumed_at"):
        raise HTTPException(status_code=410, detail="이미 사용된 라이브 세션입니다.")
    return {
        "ok": True,
        "session_token": token,
        "expires_at": entry.get("expires_at"),
        "consumed": False,
    }


@router.get(
    "/api/methodology",
    tags=["Public"],
    summary="검출 신호 카탈로그 + 학술/법적 근거",
    description=(
        "ScamGuardian 이 검출하는 위험 신호 카탈로그와 각 신호의 학술·법적 근거. "
        "통합 기업이 자체 판정 logic 을 설계할 때 참조용.\n\n"
        "**Identity**: ScamGuardian 은 점수·등급 산정 안 함 — 검출 신호 보고만.\n\n"
        "응답 필드:\n"
        "- **flags**: `[{flag, label_ko, rationale, source}]` — 검출 가능한 신호 카탈로그 "
        "(영문 키, 한국어 라벨, 학술/법적 근거, 출처 기관)\n"
        "- **weights**: 내부 검출 임계값 (LLM 신호 채택 confidence, 분류 임계 등)\n"
        "- **models**: 파이프라인이 사용하는 모델명 (Whisper / mDeBERTa / GLiNER / Claude)\n\n"
        "**인증**: 선택 (API key 있으면 사용량 기록).\n\n"
        "**curl**:\n"
        "```bash\n"
        "curl https://api.example.com/api/methodology | jq '.flags[:3]'\n"
        "```"
    ),
)
def get_methodology() -> dict[str, Any]:
    """검출 신호 카탈로그 + 학술/법적 근거 메타 정보."""
    from pipeline import config as pcfg

    flags: list[dict[str, Any]] = []
    for key in pcfg.DETECTED_FLAGS:
        info = pcfg.FLAG_RATIONALE.get(key, {})
        flags.append({
            "flag": key,
            "label_ko": pcfg.FLAG_LABELS_KO.get(key, key),
            "rationale": info.get("rationale", ""),
            "source": info.get("source", ""),
        })
    flags.sort(key=lambda x: x["flag"])

    return {
        "flags": flags,
        "weights": {
            "llm_entity_merge_threshold": pcfg.LLM_ENTITY_MERGE_THRESHOLD,
            "llm_flag_detection_confidence_threshold": pcfg.LLM_FLAG_DETECTION_CONFIDENCE_THRESHOLD,
            "llm_scam_type_override_threshold": pcfg.LLM_SCAM_TYPE_OVERRIDE_THRESHOLD,
            "classification_threshold": pcfg.CLASSIFICATION_THRESHOLD,
            "gliner_threshold": pcfg.GLINER_THRESHOLD,
            "keyword_boost_weight": pcfg.KEYWORD_BOOST_WEIGHT,
        },
        "models": pcfg.MODELS,
    }


@router.get(
    "/api/evidence",
    tags=["Public"],
    summary="검출 신호 근거 문서 원문",
    description=(
        "`.scamguardian/EVIDENCE.md` 정본을 반환한다. 웹 `/evidence` 페이지가 이 endpoint를 "
        "runtime fetch 하므로 Next.js 빌드가 repository 밖 파일을 trace하지 않는다.\n\n"
        "**인증**: 불필요"
    ),
)
def get_evidence() -> dict[str, Any]:
    evidence_path = PROJECT_ROOT / ".scamguardian" / "EVIDENCE.md"
    try:
        markdown = evidence_path.read_text(encoding="utf-8")
        return {
            "markdown": markdown,
            "source_path": ".scamguardian/EVIDENCE.md",
            "found": True,
        }
    except FileNotFoundError:
        return {
            "markdown": "# EVIDENCE.md\n\n파일을 찾을 수 없습니다 (`.scamguardian/EVIDENCE.md`).",
            "source_path": ".scamguardian/EVIDENCE.md",
            "found": False,
        }
