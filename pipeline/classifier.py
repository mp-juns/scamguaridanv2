"""
ScamGuardian v2 — 스캠 유형 분류 모듈
mDeBERTa zero-shot classification + 키워드 부스팅으로 스캠 유형을 판별한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    pipeline as hf_pipeline,
)

from pipeline.config import (
    CLASSIFICATION_THRESHOLD,
    KEYWORD_BOOST,
    KEYWORD_BOOST_WEIGHT,
    KEYWORD_NO_MATCH_PENALTY,
    MODELS,
    STAGE2_CANDIDATE_TOP_N,
    STAGE2_DOMINANCE_GAP,
    get_runtime_scam_taxonomy,
)
from pipeline import active_models

_classifier = None
_finetuned = None
_finetuned_path: str | None = None


def _resolve_local_hf_snapshot(model_id: str) -> str | None:
    cache_root = Path.home() / ".cache" / "huggingface" / "hub"
    model_dir = cache_root / f"models--{model_id.replace('/', '--')}"
    refs_main = model_dir / "refs" / "main"
    if not refs_main.exists():
        return None

    revision = refs_main.read_text().strip()
    snapshot_dir = model_dir / "snapshots" / revision
    return str(snapshot_dir) if snapshot_dir.exists() else None


@dataclass
class ClassificationResult:
    scam_type: str
    confidence: float
    all_scores: dict[str, float] = field(default_factory=dict)
    is_uncertain: bool = False


def _get_classifier():
    global _classifier
    if _classifier is None:
        model_source = _resolve_local_hf_snapshot(MODELS["classifier"]) or MODELS["classifier"]
        tokenizer = AutoTokenizer.from_pretrained(model_source, local_files_only=model_source != MODELS["classifier"])
        model = AutoModelForSequenceClassification.from_pretrained(
            model_source,
            local_files_only=model_source != MODELS["classifier"],
        )
        _classifier = hf_pipeline(
            "zero-shot-classification",
            model=model,
            tokenizer=tokenizer,
            device="cpu",
        )
    return _classifier


def _get_finetuned() -> dict | None:
    """`/admin/training` 에서 활성화된 분류기 체크포인트가 있으면 task-specific
    pipeline 을 반환. 없거나 무효 경로면 None.

    반환 dict 키:
        pipe : transformers Pipeline (text-classification)
        path : 체크포인트 디렉토리
        labels : id→label 매핑 (모델 config 에서 추출)
    """
    global _finetuned, _finetuned_path
    path = active_models.get_active_path("classifier")
    if path is None:
        if _finetuned_path is not None:
            # 직전엔 활성이었지만 비활성화 됨 → 캐시 비우기
            _finetuned = None
            _finetuned_path = None
        return None
    if _finetuned is not None and _finetuned_path == path:
        return _finetuned

    try:
        tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
        model = AutoModelForSequenceClassification.from_pretrained(path, local_files_only=True)
        pipe = hf_pipeline(
            "text-classification",
            model=model,
            tokenizer=tokenizer,
            device="cpu",
            top_k=None,        # 모든 라벨 점수 반환
            truncation=True,
            max_length=512,
        )
    except Exception as exc:
        print(f"[분류] fine-tuned 모델 로드 실패({path}): {exc} — zero-shot 으로 fallback")
        _finetuned = None
        _finetuned_path = None
        return None

    id2label = getattr(model.config, "id2label", {}) or {}
    labels = {int(k): str(v) for k, v in id2label.items()} if id2label else {}
    _finetuned = {"pipe": pipe, "path": path, "labels": labels}
    _finetuned_path = path
    return _finetuned


def _compute_keyword_boost(text: str) -> dict[str, float]:
    """텍스트 내 키워드 매칭 비율로 각 스캠 유형의 부스트/감점을 계산한다."""
    text_lower = text.lower()
    boosts: dict[str, float] = {}
    for scam_type, keywords in KEYWORD_BOOST.items():
        matched = sum(1 for kw in keywords if kw in text_lower)
        if matched == 0:
            boosts[scam_type] = -KEYWORD_NO_MATCH_PENALTY
        else:
            ratio = matched / len(keywords) if keywords else 0
            boosts[scam_type] = min(ratio * KEYWORD_BOOST_WEIGHT * 3, KEYWORD_BOOST_WEIGHT)
    return boosts


def classify(text: str) -> ClassificationResult:
    """
    STT 텍스트를 입력받아 스캠 유형을 분류한다.

    1) `/admin/training` 에서 fine-tuned 분류기가 활성화돼 있으면 task-specific
       multi-class 분류 결과를 직접 사용 (키워드 부스팅·NLI hypothesis 없이도
       도메인 특화 정확도가 더 높음).
    2) 없으면 기존 zero-shot NLI + 키워드 부스팅 흐름.
    """
    finetuned = _get_finetuned()
    if finetuned is not None:
        return _classify_finetuned(text, finetuned)

    clf = _get_classifier()
    taxonomy = get_runtime_scam_taxonomy()

    truncated = text[:2000]
    descriptive_labels = list(taxonomy["descriptions"].keys())

    result = clf(
        truncated,
        descriptive_labels,
        hypothesis_template="이 내용은 {}하는 것이다.",
        multi_label=False,
    )

    # NLI 스코어를 짧은 이름으로 매핑
    nli_scores: dict[str, float] = {}
    for label, score in zip(result["labels"], result["scores"]):
        short_name = taxonomy["descriptions"][label]
        nli_scores[short_name] = score

    # 키워드 부스팅 적용
    boosts = _compute_keyword_boost(truncated)
    combined: dict[str, float] = {}
    for scam_type in nli_scores:
        combined[scam_type] = nli_scores[scam_type] + boosts.get(scam_type, 0)

    # 결합 점수 기준 재정렬
    sorted_types = sorted(combined.items(), key=lambda x: -x[1])
    top_type = sorted_types[0][0]
    top_score = sorted_types[0][1]

    # 항상 확률처럼 해석 가능한 [0, 1] 점수로 정규화한다.
    # total이 0 이하가 될 수 있으므로 min-shift 후 합으로 나눈다.
    min_score = min(combined.values())
    shifted = {k: v - min_score for k, v in combined.items()}
    shifted_total = sum(shifted.values())
    if shifted_total == 0:
        # 모든 점수가 동일하면 균등 분포로 처리
        uniform = 1.0 / len(shifted) if shifted else 0.0
        all_scores = {k: uniform for k in shifted}
    else:
        all_scores = {k: v / shifted_total for k, v in shifted.items()}

    return ClassificationResult(
        scam_type=top_type,
        confidence=all_scores[top_type],
        all_scores=all_scores,
        is_uncertain=all_scores[top_type] < CLASSIFICATION_THRESHOLD,
    )


def _classify_finetuned(text: str, finetuned: dict) -> ClassificationResult:
    """fine-tuned 분류기로 직접 multi-class 분류."""
    pipe = finetuned["pipe"]
    truncated = text[:2000]
    raw = pipe(truncated, truncation=True)
    # raw 형태: top_k=None 일 때 [[{label, score}, ...]] (배치 차원)
    if isinstance(raw, list) and raw and isinstance(raw[0], list):
        items = raw[0]
    elif isinstance(raw, list):
        items = raw
    else:
        items = [raw]

    all_scores: dict[str, float] = {}
    for item in items:
        label = str(item.get("label", "")).strip()
        score = float(item.get("score", 0.0))
        if label:
            all_scores[label] = score

    if not all_scores:
        return ClassificationResult(scam_type="", confidence=0.0, is_uncertain=True)

    top = max(all_scores.items(), key=lambda x: x[1])
    return ClassificationResult(
        scam_type=top[0],
        confidence=top[1],
        all_scores=all_scores,
        is_uncertain=top[1] < CLASSIFICATION_THRESHOLD,
    )


def candidate_scam_types(
    all_scores: dict[str, float],
    top_n: int = STAGE2_CANDIDATE_TOP_N,
    dominance_gap: float = STAGE2_DOMINANCE_GAP,
) -> list[str]:
    """Stage 2 — multi-label 추출 라우팅용 후보 유형 list 를 만든다.

    - all_scores 가 비어 있으면 [] — 호출부가 기존 top-1 라우팅으로 fallback.
    - top1 - top2 점수 차가 dominance_gap 이상이면 top-1 이 충분히 우세 → [top-1].
    - 그 외 → 상위 top_n 개.

    scam_type 필드 자체는 바꾸지 않는다 — 이건 *엔티티 추출 라우팅* 용 후보일 뿐이고
    외부 응답에는 노출하지 않는다.
    """
    if not all_scores:
        return []
    ranked = sorted(all_scores.items(), key=lambda kv: -kv[1])
    if len(ranked) == 1:
        return [ranked[0][0]]
    if ranked[0][1] - ranked[1][1] >= dominance_gap:
        return [ranked[0][0]]
    return [name for name, _ in ranked[:top_n]]
