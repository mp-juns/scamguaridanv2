"""/health 와 /api/methodology — 정적·메타 응답."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter

router = APIRouter()


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
    backend = os.getenv("STT_BACKEND", "whisper").strip().lower()
    return {
        "stt_backend": "claude" if backend == "claude" else "openai_whisper",
        "openai_key_present": bool(os.getenv("OPENAI_API_KEY")),
        "anthropic_key_present": bool(os.getenv("ANTHROPIC_API_KEY")),
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
