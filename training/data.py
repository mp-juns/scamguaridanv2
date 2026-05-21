"""학습 데이터 로더 — `human_annotations` + 외부 JSONL 을 받아
content_label 중심으로 학습용 데이터셋을 구성한다.

content_label 재설계 (3단계 캐스케이드):
    - load_content_gate_dataset() → Stage 1 게이트 분류기 학습용
      (normal / scam_attempt / scam_news_edu, label = content_label)
    - load_classifier_dataset()   → scam_type 분류기 학습용
      (content_label == scam_attempt 인 샘플만, label = scam_type)
    - load_review_queue()         → suspicious_insufficient / undetermined
      (기본 학습셋에서 제외, 검수 대상)
    - load_gliner_dataset()       → GLiNER 학습용 (entity span)

뉴스 원문은 scam_attempt 가 아니라 scam_news_edu 다 — 뉴스 문장을 scam_attempt 로
학습시키면 "사기·피해·경찰" 같은 단어만 보고 오탐한다. 뉴스에서 확인된 수법은
synthetic_scam_message (sample_kind) 로 *재구성한 메시지형 샘플*만 scam_attempt
학습에 쓴다. 자세한 라벨링 기준은 docs/labeling_guide.md 참고.

DB 가 비어 있으면 외부 JSONL 도 함께 받을 수 있게 `extra_jsonl` 인자 지원.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable

from db import repository
from pipeline.config import (
    CONTENT_LABEL_SCAM_TYPE_TARGET,
    CONTENT_LABELS,
    CONTENT_LABELS_FOR_GATE_TRAINING,
    CONTENT_LABELS_REVIEW_ONLY,
    GATE_NORMAL,
    GATE_SCAM_ATTEMPT,
    GATE_SCAM_NEWS_EDU,
    GATE_SUSPICIOUS_INSUFFICIENT,
    GATE_UNDETERMINED,
    SAMPLE_KIND_NORMAL,
    SAMPLE_KIND_REAL_SCAM,
    SAMPLE_KIND_REVIEW,
    SAMPLE_KIND_SCAM_NEWS_EDU,
)

DEFAULT_SEED = 17
# 하위호환용 — content_label 재설계 전 zero-shot 분류기의 negative 라벨.
# scam_type 학습셋에는 더 이상 들어가지 않는다 (게이트가 정상/뉴스를 거름).
NEGATIVE_LABEL = "정상 대화"


@dataclass
class ClassifierExample:
    text: str
    label: str                      # scam_type 또는 content_label (로더에 따라)
    run_id: str | None = None
    source: str = "annotation"
    content_label: str = ""          # normal/scam_attempt/scam_news_edu/...
    sample_kind: str = ""            # real_scam_message/synthetic_scam_message/...
    source_ref: str | None = None    # synthetic 샘플의 원본 뉴스 URL 등


@dataclass
class GlinerExample:
    text: str
    ner: list[tuple[int, int, str]] = field(default_factory=list)  # (start, end, label)
    run_id: str | None = None


# ──────────────────────────────────────────────
# content_label / sample_kind 정규화
# ──────────────────────────────────────────────

_SAMPLE_KIND_BY_CONTENT: dict[str, str] = {
    GATE_SCAM_ATTEMPT: SAMPLE_KIND_REAL_SCAM,
    GATE_SCAM_NEWS_EDU: SAMPLE_KIND_SCAM_NEWS_EDU,
    GATE_NORMAL: SAMPLE_KIND_NORMAL,
    GATE_SUSPICIOUS_INSUFFICIENT: SAMPLE_KIND_REVIEW,
    GATE_UNDETERMINED: SAMPLE_KIND_REVIEW,
}


def resolve_content_label(content_label: str | None, scam_type: str | None) -> str:
    """content_label 정규화 + fallback (하위호환).

    명시값이 유효하면 그대로 사용. 없으면:
      - scam_type 이 명확(비어있지 않고 NEGATIVE_LABEL 아님) → scam_attempt 로 추정
      - 그 외 → undetermined
    """
    cl = (content_label or "").strip()
    if cl in CONTENT_LABELS:
        return cl
    st = (scam_type or "").strip()
    if st and st != NEGATIVE_LABEL:
        return GATE_SCAM_ATTEMPT
    return GATE_UNDETERMINED


def infer_sample_kind(content_label: str) -> str:
    """sample_kind 가 비어 있을 때 content_label 로 추정."""
    return _SAMPLE_KIND_BY_CONTENT.get(content_label, SAMPLE_KIND_REVIEW)


def _resolve_text(record: dict[str, Any]) -> str:
    return (
        record.get("transcript_corrected_text")
        or record.get("transcript_text")
        or ""
    ).strip()


def _spans_for_entity(text: str, target: str) -> list[tuple[int, int]]:
    """text 안에서 target 문자열의 모든 출현 위치(start, end) 반환."""
    if not target:
        return []
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        idx = text.find(target, start)
        if idx < 0:
            break
        spans.append((idx, idx + len(target)))
        start = idx + 1
    return spans


def _ner_from_annotation(text: str, entities: list[dict[str, Any]]) -> list[tuple[int, int, str]]:
    """엔티티 정답 리스트 → GLiNER (start, end, label) 형식.

    annotation 에 start/end 가 있으면 그대로, 없으면 text 검색으로 채운다.
    겹치는 span 은 첫 번째만 유지.
    """
    out: list[tuple[int, int, str]] = []
    used: list[tuple[int, int]] = []
    for ent in entities:
        ent_text = (ent.get("text") or "").strip()
        label = (ent.get("label") or "").strip()
        if not ent_text or not label:
            continue
        if isinstance(ent.get("start"), int) and isinstance(ent.get("end"), int):
            spans = [(ent["start"], ent["end"])]
        else:
            spans = _spans_for_entity(text, ent_text)
        for s, e in spans:
            if any(not (e <= us or s >= ue) for us, ue in used):
                continue
            out.append((s, e, label))
            used.append((s, e))
    out.sort(key=lambda x: (x[0], x[1]))
    return out


def _load_jsonl(path: Path) -> Iterable[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _normalize_jsonl_record(record: dict[str, Any]) -> dict[str, Any]:
    """외부 JSONL 한 줄을 표준 형태로 정규화한다.

    신규 스키마: {text, content_label, scam_type, sample_kind, source_ref, ...}
    구 스키마 호환: `label` 을 scam_type 으로 간주 (content_label 은 fallback).
    """
    text = (record.get("text") or "").strip()
    scam_type = (record.get("scam_type") or record.get("label") or "").strip()
    if scam_type == NEGATIVE_LABEL:
        scam_type = ""
    content_label = resolve_content_label(record.get("content_label"), scam_type)
    sample_kind = (record.get("sample_kind") or "").strip() or infer_sample_kind(content_label)
    return {
        "text": text,
        "scam_type": scam_type,
        "content_label": content_label,
        "sample_kind": sample_kind,
        "source_ref": record.get("source_ref"),
        "run_id": record.get("run_id"),
        "source": record.get("source", "extra_jsonl"),
    }


def _all_content_examples(extra_jsonl: Path | None = None) -> list[ClassifierExample]:
    """DB 라벨 + JSONL 을 모두 ClassifierExample 로 정규화한다.

    각 example 은 content_label 이 채워진 상태(fallback 적용). `label` 에는 scam_type
    이 들어간다 — content_label 기준 로더(gate/review)는 이를 content_label 로 덮어쓴다.
    """
    out: list[ClassifierExample] = []
    for row in repository.fetch_annotated_pairs():
        text = _resolve_text(row)
        if not text:
            continue
        content_label = resolve_content_label(
            row.get("content_label"), row.get("scam_type_gt")
        )
        sample_kind = (row.get("sample_kind") or "").strip() or infer_sample_kind(content_label)
        out.append(
            ClassifierExample(
                text=text,
                label=(row.get("scam_type_gt") or "").strip(),
                run_id=row.get("run_id"),
                source="annotation",
                content_label=content_label,
                sample_kind=sample_kind,
                source_ref=row.get("source_ref"),
            )
        )

    if extra_jsonl:
        for record in _load_jsonl(Path(extra_jsonl)):
            norm = _normalize_jsonl_record(record)
            if not norm["text"]:
                continue
            out.append(
                ClassifierExample(
                    text=norm["text"],
                    label=norm["scam_type"],
                    run_id=norm["run_id"],
                    source=norm["source"],
                    content_label=norm["content_label"],
                    sample_kind=norm["sample_kind"],
                    source_ref=norm["source_ref"],
                )
            )
    return out


def load_classifier_dataset(
    *,
    extra_jsonl: Path | None = None,
    include_negatives: bool = True,
) -> list[ClassifierExample]:
    """scam_type 분류기 학습 데이터 — content_label == scam_attempt 인 샘플만.

    Stage 1 게이트가 정상/뉴스를 먼저 거르므로, scam_type 분류기는 *사기 시도로
    확인된 콘텐츠 안에서 유형만* 구분하면 된다. label = scam_type.

    `include_negatives` 는 하위호환용 인자다 — content_label 재설계 후 scam_type
    학습셋에는 negative(정상 대화)가 들어가지 않으므로 무시된다.
    """
    _ = include_negatives  # 하위호환 — 의도적으로 미사용
    out: list[ClassifierExample] = []
    for ex in _all_content_examples(extra_jsonl):
        if ex.content_label != CONTENT_LABEL_SCAM_TYPE_TARGET:
            continue
        if not ex.label:  # scam_attempt 인데 scam_type 미상 → 학습 타깃 없음
            continue
        out.append(ex)
    return out


def load_content_gate_dataset(
    *,
    extra_jsonl: Path | None = None,
) -> list[ClassifierExample]:
    """Stage 1 게이트(콘텐츠) 분류기 학습 데이터.

    content_label 이 normal / scam_attempt / scam_news_edu 인 샘플만. label 은
    content_label 로 설정한다. suspicious_insufficient / undetermined 는 제외
    (load_review_queue 로 분리).
    """
    out: list[ClassifierExample] = []
    for ex in _all_content_examples(extra_jsonl):
        if ex.content_label not in CONTENT_LABELS_FOR_GATE_TRAINING:
            continue
        out.append(replace(ex, label=ex.content_label))
    return out


def load_review_queue(
    *,
    extra_jsonl: Path | None = None,
) -> list[ClassifierExample]:
    """기본 학습셋에서 제외된 샘플 — content_label 이 suspicious_insufficient
    또는 undetermined. 학습이 아니라 검수(review) 대상이다."""
    out: list[ClassifierExample] = []
    for ex in _all_content_examples(extra_jsonl):
        if ex.content_label not in CONTENT_LABELS_REVIEW_ONLY:
            continue
        out.append(replace(ex, label=ex.content_label))
    return out


def load_gliner_dataset(*, extra_jsonl: Path | None = None) -> list[GlinerExample]:
    """엔티티 정답이 있는 라벨링 + (옵션) JSONL.

    extra_jsonl 의 각 라인은 {"text": "...", "ner": [[start, end, "label"], ...]} 또는
    {"text": "...", "entities": [{"text", "label", "start"?, "end"?}]} 둘 다 지원.
    """
    rows = repository.fetch_annotated_pairs()
    examples: list[GlinerExample] = []
    for row in rows:
        text = _resolve_text(row)
        ner = _ner_from_annotation(text, row.get("entities_gt") or [])
        if not text or not ner:
            continue
        examples.append(GlinerExample(text=text, ner=ner, run_id=row.get("run_id")))

    if extra_jsonl:
        for record in _load_jsonl(Path(extra_jsonl)):
            text = (record.get("text") or "").strip()
            if not text:
                continue
            ner = record.get("ner")
            if isinstance(ner, list) and all(len(t) == 3 for t in ner):
                spans = [(int(s), int(e), str(l)) for s, e, l in ner]
            else:
                spans = _ner_from_annotation(text, record.get("entities") or [])
            if not spans:
                continue
            examples.append(GlinerExample(text=text, ner=spans, run_id=record.get("run_id")))
    return examples


def train_val_split(
    examples: list,
    val_ratio: float = 0.1,
    seed: int = DEFAULT_SEED,
) -> tuple[list, list]:
    rng = random.Random(seed)
    indices = list(range(len(examples)))
    rng.shuffle(indices)
    n_val = max(1, int(len(examples) * val_ratio))
    val_idx = set(indices[:n_val])
    train: list = []
    val: list = []
    for i, ex in enumerate(examples):
        (val if i in val_idx else train).append(ex)
    return train, val


def stratified_split(
    examples: list[ClassifierExample],
    val_ratio: float = 0.1,
    seed: int = DEFAULT_SEED,
) -> tuple[list[ClassifierExample], list[ClassifierExample]]:
    """라벨별 균형 split — 적은 클래스가 val 에 누락되지 않게."""
    rng = random.Random(seed)
    by_label: dict[str, list[ClassifierExample]] = {}
    for ex in examples:
        by_label.setdefault(ex.label, []).append(ex)
    train: list[ClassifierExample] = []
    val: list[ClassifierExample] = []
    for label, items in by_label.items():
        rng.shuffle(items)
        n_val = max(1, int(len(items) * val_ratio)) if len(items) > 1 else 0
        val.extend(items[:n_val])
        train.extend(items[n_val:])
    rng.shuffle(train)
    rng.shuffle(val)
    return train, val


def label_distribution(examples: list[ClassifierExample]) -> dict[str, int]:
    out: dict[str, int] = {}
    for ex in examples:
        out[ex.label] = out.get(ex.label, 0) + 1
    return dict(sorted(out.items(), key=lambda x: -x[1]))


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="라벨링 데이터 통계 점검")
    parser.add_argument("--extra-jsonl", default=None)
    args = parser.parse_args()

    gate = load_content_gate_dataset(extra_jsonl=args.extra_jsonl)
    cls = load_classifier_dataset(extra_jsonl=args.extra_jsonl)
    review = load_review_queue(extra_jsonl=args.extra_jsonl)
    gli = load_gliner_dataset(extra_jsonl=args.extra_jsonl)

    print(f"[content gate] examples: {len(gate)}")
    for label, n in label_distribution(gate).items():
        print(f"  {n:>4} | {label}")
    print()
    print(f"[scam_type classifier] examples: {len(cls)} (content_label == scam_attempt)")
    for label, n in label_distribution(cls).items():
        print(f"  {n:>4} | {label}")
    print()
    print(f"[review queue] examples: {len(review)} (학습 제외)")
    for label, n in label_distribution(review).items():
        print(f"  {n:>4} | {label}")
    print()
    print(f"[gliner] examples: {len(gli)}")
    if gli:
        avg_ner = sum(len(e.ner) for e in gli) / len(gli)
        avg_len = sum(len(e.text) for e in gli) / len(gli)
        print(f"  평균 엔티티/문서: {avg_ner:.1f}")
        print(f"  평균 문서 길이(자): {avg_len:.0f}")
