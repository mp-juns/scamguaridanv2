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
    epochs: int = 3
    batch_size: int = 8
    lora: bool = False
    extra_jsonl: str | None = None
    val_ratio: float = 0.1
    seed: int = 17
    base_model: str | None = None
    early_stopping_patience: int = 2
    early_stopping_threshold: float = 0.0
