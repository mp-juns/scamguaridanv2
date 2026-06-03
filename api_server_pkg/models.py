"""Pydantic 모델 — 요청 페이로드 정의 모음."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from pipeline.config import CONTENT_LABELS, GATE_SCAM_ATTEMPT, SAMPLE_KINDS


class AnalyzeRequest(BaseModel):
    source: str | None = None
    text: str | None = None
    whisper_model: str = Field(
        default="medium",
        pattern="^(tiny|base|small|medium|large)$",
    )
    skip_verification: bool = True
    use_llm: bool = True
    use_rag: bool = False


class HumanAnnotationRequest(BaseModel):
    labeler: str | None = None
    # content_label 재설계: scam_type_gt 는 더 이상 무조건 필수가 아니다.
    # content_label == scam_attempt 일 때만 필수 (아래 validator).
    scam_type_gt: str = ""
    entities_gt: list[dict[str, Any]] = Field(default_factory=list)
    triggered_flags_gt: list[dict[str, Any]] = Field(default_factory=list)
    transcript_corrected_text: str | None = None
    stt_quality: int | None = Field(default=None, ge=1, le=5)
    notes: str = ""
    # 콘텐츠 성격 라벨 (Stage 1 게이트와 동일 어휘). 미지정 시 학습 로더가 fallback.
    content_label: str = ""
    sample_kind: str = ""
    source_ref: str | None = None

    @model_validator(mode="after")
    def _validate_content_label(self) -> "HumanAnnotationRequest":
        cl = (self.content_label or "").strip()
        if cl and cl not in CONTENT_LABELS:
            raise ValueError(f"content_label 은 {CONTENT_LABELS} 중 하나여야 합니다.")
        sk = (self.sample_kind or "").strip()
        if sk and sk not in SAMPLE_KINDS:
            raise ValueError(f"sample_kind 은 {SAMPLE_KINDS} 중 하나여야 합니다.")
        # scam_type 은 scam_attempt 일 때만 강제. normal/scam_news_edu 등에는 강제 안 함.
        if cl == GATE_SCAM_ATTEMPT and not (self.scam_type_gt or "").strip():
            raise ValueError("content_label 이 scam_attempt 이면 scam_type_gt 가 필요합니다.")
        return self


class ScamTypeCatalogRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=200)
    labels: list[str] = Field(default_factory=list)


class ClaimRunRequest(BaseModel):
    labeler: str


class AdminLoginRequest(BaseModel):
    token: str


class CreateApiKeyRequest(BaseModel):
    label: str
    monthly_quota: int = 1000
    rpm_limit: int = 30
    monthly_usd_quota: float = 5.0


class StartTrainingRequest(BaseModel):
    model: str
    # 여러 모델을 보내면(예: ["classifier", "gliner"]) 순차 학습. 없으면 단일 `model`.
    models: list[str] | None = None
    epochs: int = 3
    batch_size: int = 8
    lora: bool = False
    extra_jsonl: str | None = None
    val_ratio: float = 0.1
    seed: int = 17
    base_model: str | None = None
    early_stopping_patience: int = 2
    early_stopping_threshold: float = 0.0


class AugmentStartRequest(BaseModel):
    """데이터 증강 세션 시작 — 씨앗 파일을 Claude 로 병렬 패러프레이즈."""
    seed_file: str | None = None        # 없으면 admin_seeds.jsonl 기본값
    variants: int = 5
    rounds: int = 1
    model: str = "claude-sonnet-4-6"
    concurrency: int = 8
    limit: int = 0
    scam_type: str | None = None        # 특정 유형 씨앗만 (None = 전체)


class SeedCreateRequest(BaseModel):
    """관리자가 직접 작성하는 씨앗 1개 (굶은 유형 보강용)."""
    text: str
    scam_type: str
    content_label: str = GATE_SCAM_ATTEMPT


class DummyLinkRequest(BaseModel):
    """더미 피싱앱 다운로드 링크 발급 — APK 검출 e2e 테스트용."""
    variant_id: str
    ttl_seconds: int = 3600
    filename: str | None = None        # 다운로드 시 보일 파일명 (피싱 배포처 모사)
