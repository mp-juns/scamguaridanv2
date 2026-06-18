"""
ScamGuardian — 설정: Stage 1 콘텐츠 게이트 + 학습 라벨 정책

GATE_BUCKETS(5종)·실행 강도 profile·content_label/sample_kind 어휘.
순수 데이터만 — 프로젝트 모듈 import 금지.
외부 소비자는 `pipeline.config` facade 를 통해 import 한다.
"""

from __future__ import annotations

from typing import Any

# ──────────────────────────────────────────────
# Stage 1 콘텐츠 게이트 (내부 라우팅 전용)
#
# Identity Boundary: 게이트 결과는 *외부 API 응답에 노출하지 않는다*. 파이프라인
# 실행 강도 라우팅 + 라벨링 metadata 에만 쓴다. 검출(detection)이 아니라 내부
# 라우팅 신호다. 게이트가 normal 로 오판해도 룰 기반 신호검출은 항상 수행된다.
# ──────────────────────────────────────────────
GATE_NORMAL = "normal"
GATE_SCAM_ATTEMPT = "scam_attempt"
GATE_SCAM_NEWS_EDU = "scam_news_edu"
GATE_SUSPICIOUS_INSUFFICIENT = "suspicious_insufficient"
GATE_UNDETERMINED = "undetermined"

GATE_BUCKETS: list[str] = [
    GATE_NORMAL,
    GATE_SCAM_ATTEMPT,
    GATE_SCAM_NEWS_EDU,
    GATE_SUSPICIOUS_INSUFFICIENT,
    GATE_UNDETERMINED,
]

# 한국어 라벨 — 내부 로그·라벨링 metadata 용 (외부 응답엔 안 나감)
GATE_LABELS_KO: dict[str, str] = {
    GATE_NORMAL: "정상",
    GATE_SCAM_ATTEMPT: "사기 시도",
    GATE_SCAM_NEWS_EDU: "사기 뉴스·교육",
    GATE_SUSPICIOUS_INSUFFICIENT: "의심되지만 불충분",
    GATE_UNDETERMINED: "판단 불가",
}

# bucket 별 실행 강도. 룰 기반 신호검출은 *항상* 수행하므로 표에 없다.
#   run_scam_type      : Stage 2 유형 분류 수행 여부
#   serper_max_entities: Serper 교차검증 대상 엔티티 상한 (0 = OFF)
#   use_llm            : LLM 보조 검출 수행 여부
# 이 profile 은 호출자 인자(use_llm·skip_verification)를 *상한선으로 줄이기만* 한다.
GATE_EXECUTION_PROFILE: dict[str, dict[str, Any]] = {
    GATE_NORMAL:                  {"run_scam_type": False, "serper_max_entities": 0,  "use_llm": False},
    GATE_SCAM_NEWS_EDU:           {"run_scam_type": False, "serper_max_entities": 0,  "use_llm": False},
    GATE_SUSPICIOUS_INSUFFICIENT: {"run_scam_type": True,  "serper_max_entities": 8,  "use_llm": True},
    GATE_UNDETERMINED:            {"run_scam_type": True,  "serper_max_entities": 8,  "use_llm": True},
    GATE_SCAM_ATTEMPT:            {"run_scam_type": True,  "serper_max_entities": 15, "use_llm": True},
}

# 게이트 분류 실패·예외 시 fallback bucket — 검출 누락 방지를 위해 풀에 가까운
# 파이프라인을 도는 UNDETERMINED 로 보낸다 (사기로 *단정*하지 않으면서 안전).
GATE_FALLBACK_BUCKET = GATE_UNDETERMINED

# 이 글자 수 미만이면 LLM 호출 없이 바로 UNDETERMINED (방향조차 못 정함)
GATE_MIN_CHARS = 10

# 안전 버킷(normal/scam_news_edu) 판단을 "확정"으로 취급하는 최소 신뢰도.
# 미만이면 결과 표시를 "추가 확인 필요"로 보수화 + 심층 분석 권장 (파이프라인
# 실행 강도는 그대로 — 표시 레이어만). 1인칭 검찰 사칭이 scam_news_edu 0.51 로
# 오판되어 신호 0건으로 끝난 사례가 동기 (2026-06-13).
GATE_LOW_CONFIDENCE_THRESHOLD = 0.70

# ──────────────────────────────────────────────
# 학습/라벨링 데이터 — content_label + sample_kind
#
# content_label: 인간 라벨러가 매기는 콘텐츠 성격 ground truth. Stage 1 게이트
# 분류기의 출력 공간(GATE_BUCKETS)과 *반드시 동일한 어휘* — 게이트를 훈련하는
# 라벨이므로. 별도 어휘를 두지 않고 GATE_BUCKETS 를 그대로 재사용한다.
# ──────────────────────────────────────────────
CONTENT_LABELS: list[str] = list(GATE_BUCKETS)

# sample_kind: 샘플의 출처·성격. 학습 정책 분기 + 합성 샘플 추적용.
SAMPLE_KIND_REAL_SCAM = "real_scam_message"            # 실제 사기 문자/대화/통화 스크립트
SAMPLE_KIND_SYNTHETIC_SCAM = "synthetic_scam_message"  # 뉴스/사례 기반 재구성 메시지형 샘플
SAMPLE_KIND_SCAM_NEWS_EDU = "scam_news_education"       # 뉴스/예방/교육 콘텐츠
SAMPLE_KIND_NORMAL = "normal_content"                  # 정상 콘텐츠
SAMPLE_KIND_REVIEW = "review_needed"                   # 판단 보류

SAMPLE_KINDS: list[str] = [
    SAMPLE_KIND_REAL_SCAM,
    SAMPLE_KIND_SYNTHETIC_SCAM,
    SAMPLE_KIND_SCAM_NEWS_EDU,
    SAMPLE_KIND_NORMAL,
    SAMPLE_KIND_REVIEW,
]

# 학습 정책 — 어떤 content_label 이 어떤 학습에 들어가나
#   scam_type 분류기: scam_attempt 만 (label = scam_type)
#   content gate 분류기: normal / scam_attempt / scam_news_edu (label = content_label)
#   suspicious_insufficient / undetermined: 기본 학습셋 제외 → review queue
CONTENT_LABEL_SCAM_TYPE_TARGET: str = GATE_SCAM_ATTEMPT
CONTENT_LABELS_FOR_GATE_TRAINING: list[str] = [
    GATE_NORMAL, GATE_SCAM_ATTEMPT, GATE_SCAM_NEWS_EDU,
]
CONTENT_LABELS_REVIEW_ONLY: list[str] = [
    GATE_SUSPICIOUS_INSUFFICIENT, GATE_UNDETERMINED,
]
