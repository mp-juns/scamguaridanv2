"""FastAPI 앱 빌더 — 미들웨어 + 라우터 include + startup 이벤트."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import repository
from pipeline.runner import ScamGuardianPipeline
from platform_layer.middleware import PlatformMiddleware

from . import (
    admin_augment,
    admin_platform,
    admin_runs,
    admin_training,
    admin_users,
    analyze,
    androzoo_eval,
    apk_dummy,
    apk_dynamic,
    apk_public,
    docs_ui,
    health,
    kakao,
    live_stream,
    result_token,
    stream_analyze,
    transcribe,
    v4_stream,
)

OPENAPI_TAGS = [
    {
        "name": "Public",
        "description": (
            "외부 통합 클라이언트용 — API key 필요. "
            "`/api/analyze`, `/api/analyze-upload`, `/api/result/{token}`, `/api/methodology` 4개. "
            "자세한 통합 가이드: `docs/INTEGRATION_GUIDE.md`."
        ),
    },
    {
        "name": "Webhook",
        "description": "카카오 챗봇 등 외부 플랫폼 webhook. 플랫폼 자체 인증 사용 (API key skip).",
    },
    {
        "name": "Admin — Labeling",
        "description": "라벨링 큐 / annotation / 검수 메트릭. `SCAMGUARDIAN_ADMIN_TOKEN` 필요.",
    },
    {
        "name": "Admin — Platform",
        "description": "API key 발급·revoke / cost ledger / request log / abuse 차단 관리.",
    },
    {
        "name": "Admin — Training",
        "description": "fine-tune 세션 — mDeBERTa 분류기 / GLiNER 추출기 도메인 특화 학습.",
    },
    {
        "name": "Admin — Augment",
        "description": "데이터 증강 세션 — 씨앗 작성 + Claude 병렬 패러프레이즈로 굶은 유형 보강.",
    },
    {
        "name": "Admin — APK Dynamic",
        "description": "APK Lv3 동적 분석 — 격리 VM(redroid+Frida) 라이프사이클 제어 + 분석 잡.",
    },
    {
        "name": "Admin — APK Dummy",
        "description": "무해 prebuilt 더미 APK 를 만료 공개 토큰 URL 로 발급 — 검출 e2e 테스트용.",
    },
    {
        "name": "Admin — Users",
        "description": "어드민 사용자 관리 — 마스터 + 승인요청(pending/approved/denied).",
    },
    {
        "name": "v4 (draft)",
        "description": (
            "**Live Call Guard — design preview only, not implemented.** "
            "실시간 통화 중 사기 탐지 endpoint 설계 미리보기. 모든 호출 `501 Not Implemented`. "
            "배경: CLAUDE.md `v4 계획` 섹션."
        ),
    },
    {
        "name": "Health",
        "description": "Liveness probe.",
    },
]


def create_app() -> FastAPI:
    app = FastAPI(
        title="ScamGuardian Signal Detection API",
        version="0.1.0",
        description=(
            "**한국어 사기 신호 검출 reference implementation** — 음성·텍스트·이미지·PDF·URL 입력에서 "
            "위험 신호를 검출하고 각 신호의 학술/법적 근거를 transparent 하게 보고한다.\n\n"
            "⚠️ **Identity Boundary** (CLAUDE.md): ScamGuardian 은 *사기 판정을 내리지 않는다*. "
            "VirusTotal 이 70개 백신의 검출 결과를 보고만 하는 모델과 동일. 판정 logic 은 통합한 "
            "기업(통신사·은행·메신저 앱)이 자기 risk tolerance 에 따라 구현한다.\n\n"
            "- **Public 4 endpoint** (`Public` 태그) — 외부 통합 시작점, `DetectionReport` 응답\n"
            "- **Webhook** (`Webhook` 태그) — 카카오 오픈빌더\n"
            "- **Admin** (3 태그) — 라벨링 / platform / training\n"
            "- **v4 draft** — Live Call Guard 설계 preview (구현 X)\n\n"
            "통합 가이드: [`docs/INTEGRATION_GUIDE.md`](https://github.com/example/scamguardian-v2/blob/main/docs/INTEGRATION_GUIDE.md)"
        ),
        openapi_tags=OPENAPI_TAGS,
        # 기본 /docs · /redoc 비활성 — docs_ui.install_custom_docs 가 Pretendard 적용한 커스텀 버전으로 대체.
        docs_url=None,
        redoc_url=None,
    )

    allowed_origins = [
        origin.strip()
        for origin in os.getenv(
            "SCAMGUARDIAN_CORS_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000",
        ).split(",")
        if origin.strip()
    ]

    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # v3 platform — API key + rate limit + request log + cost context + admin auth gating
    app.add_middleware(PlatformMiddleware)

    app.include_router(health.router)
    app.include_router(result_token.router)
    app.include_router(kakao.router)
    app.include_router(analyze.router)
    app.include_router(transcribe.router)
    app.include_router(stream_analyze.router)
    app.include_router(live_stream.router)
    app.include_router(admin_runs.router)
    app.include_router(admin_platform.router)
    app.include_router(admin_training.router)
    app.include_router(admin_augment.router)
    app.include_router(admin_users.router)
    app.include_router(apk_dynamic.router)
    app.include_router(apk_public.router)
    app.include_router(apk_dummy.router)
    app.include_router(androzoo_eval.router)
    app.include_router(v4_stream.router)

    # 커스텀 /docs (Swagger UI) + /redoc — Pretendard 폰트 + 가독성 폴리시.
    docs_ui.install_custom_docs(app)

    @app.on_event("startup")
    def _startup() -> None:
        log = logging.getLogger("startup")

        if repository.database_configured():
            repository.init_db()

        # 업로드 retention — 시작 시 1회 sweep + 백그라운드 24h 주기.
        try:
            from platform_layer import retention as _retention
            _retention.sweep()
            _retention.start_background_sweeper()
        except Exception as exc:  # noqa: BLE001
            log.warning("retention sweep init 실패 (무시): %s", exc)

        log.info("모델 워밍업 시작 (콜드스타트 방지)...")
        try:
            pipeline = ScamGuardianPipeline()
            pipeline.analyze("워밍업 테스트", skip_verification=True, use_llm=True, use_rag=False)
            # 위 analyze 는 skip_verification=True 라 Phase 4 가 안 돌고 SBERT 가 cold 상태로 남음.
            # 실제 사기 케이스 첫 요청에서 ~6s cold start 가 터지므로 여기서 미리 로드.
            from pipeline import verifier as _verifier
            _verifier._get_sbert_model()
            log.info("모델 워밍업 완료")
        except Exception as exc:
            log.warning("모델 워밍업 실패 (무시): %s", exc)

    return app
