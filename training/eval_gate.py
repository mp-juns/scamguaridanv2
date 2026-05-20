"""Stage 1 — content gate 평가 (normal / scam_attempt / scam_news_edu).

평가 정책 (학습과 동일):
    - 3-class only: normal / scam_attempt / scam_news_edu
    - suspicious_insufficient / undetermined gt 는 평가 대상 제외 (review queue)

records 입력 형식: 각 record dict 에서 다음 필드 중 하나 쌍을 사용
    {"content_label_gt": str, "content_label_predicted": str}
    혹은 {"gate_bucket_gt": str, "gate_bucket_predicted": str}

CLI:
    python -m training.eval_gate --records eval_gate.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from pipeline.config import CONTENT_LABELS_FOR_GATE_TRAINING


GATE_EVAL_LABELS: list[str] = list(CONTENT_LABELS_FOR_GATE_TRAINING)


def _gt(record: dict[str, Any]) -> str:
    return str(
        record.get("content_label_gt")
        or record.get("gate_bucket_gt")
        or ""
    ).strip()


def _pred(record: dict[str, Any]) -> str:
    return str(
        record.get("content_label_predicted")
        or record.get("gate_bucket_predicted")
        or ""
    ).strip()


def _f1_from_pr(precision: float, recall: float) -> float:
    return (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0


def evaluate_gate(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """3-class gate 평가. suspicious/undetermined gt 는 제외."""
    eval_set = {l for l in GATE_EVAL_LABELS}
    pairs: list[tuple[str, str]] = []
    skipped_out_of_scope = 0
    skipped_missing = 0
    for r in records:
        gt = _gt(r)
        pred = _pred(r)
        if not gt:
            skipped_missing += 1
            continue
        if gt not in eval_set:
            skipped_out_of_scope += 1
            continue
        pairs.append((gt, pred))

    n = len(pairs)
    if n == 0:
        return {
            "n": 0,
            "accuracy": 0.0,
            "macro_f1": 0.0,
            "weighted_f1": 0.0,
            "per_class": {},
            "confusion_matrix": {},
            "skipped_out_of_scope": skipped_out_of_scope,
            "skipped_missing": skipped_missing,
        }

    # confusion matrix
    confusion: dict[str, dict[str, int]] = {l: {l2: 0 for l2 in GATE_EVAL_LABELS} for l in GATE_EVAL_LABELS}
    confusion_other: dict[str, int] = {l: 0 for l in GATE_EVAL_LABELS}  # gt → pred 가 3-class 밖

    for gt, pred in pairs:
        if pred in eval_set:
            confusion[gt][pred] += 1
        else:
            confusion_other[gt] += 1

    correct = sum(confusion[l][l] for l in GATE_EVAL_LABELS)
    accuracy = correct / n

    per_class: dict[str, dict[str, float]] = {}
    for label in GATE_EVAL_LABELS:
        tp = confusion[label][label]
        fp = sum(confusion[l][label] for l in GATE_EVAL_LABELS if l != label)
        fn = sum(confusion[label][l] for l in GATE_EVAL_LABELS if l != label) + confusion_other[label]
        support = tp + fn
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": _f1_from_pr(precision, recall),
            "support": support,
        }

    macro_f1 = sum(m["f1"] for m in per_class.values()) / len(per_class)
    total_support = sum(m["support"] for m in per_class.values())
    weighted_f1 = (
        sum(m["f1"] * m["support"] for m in per_class.values()) / total_support
        if total_support
        else 0.0
    )

    # confusion matrix 출력용 dict — gt → predicted (out-of-scope 는 "_other" 키로)
    cm_out: dict[str, dict[str, int]] = {}
    for gt in GATE_EVAL_LABELS:
        row = dict(confusion[gt])
        if confusion_other[gt]:
            row["_other"] = confusion_other[gt]
        cm_out[gt] = row

    return {
        "n": n,
        "accuracy": accuracy,
        "macro_f1": macro_f1,
        "weighted_f1": weighted_f1,
        "per_class": per_class,
        "confusion_matrix": cm_out,
        "skipped_out_of_scope": skipped_out_of_scope,
        "skipped_missing": skipped_missing,
    }


def format_metrics(metrics: dict[str, Any]) -> str:
    lines = [
        f"n = {metrics['n']}  (out-of-scope skip: {metrics['skipped_out_of_scope']}, "
        f"missing gt: {metrics['skipped_missing']})",
        f"accuracy    = {metrics['accuracy']:.4f}",
        f"macro F1    = {metrics['macro_f1']:.4f}",
        f"weighted F1 = {metrics['weighted_f1']:.4f}",
        "",
        "per-class:",
    ]
    for label, m in metrics["per_class"].items():
        lines.append(
            f"  {label:<24s}  P={m['precision']:.3f}  R={m['recall']:.3f}  "
            f"F1={m['f1']:.3f}  support={int(m['support'])}"
        )
    lines.append("")
    lines.append("confusion matrix (rows=gt, cols=pred):")
    cm = metrics["confusion_matrix"]
    cols = GATE_EVAL_LABELS + (["_other"] if any("_other" in r for r in cm.values()) else [])
    header = " " * 26 + " ".join(f"{c[:14]:>14s}" for c in cols)
    lines.append(header)
    for gt in GATE_EVAL_LABELS:
        row = cm.get(gt, {})
        lines.append(
            f"  {gt[:24]:<24s}  " + " ".join(f"{row.get(c, 0):>14d}" for c in cols)
        )
    return "\n".join(lines)


def _load_records(path: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True, help="JSONL 입력")
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    args = parser.parse_args()

    metrics = evaluate_gate(_load_records(args.records))
    if args.json:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
    else:
        print(format_metrics(metrics))


# 라이브러리 헬퍼 — eval_scam_type / eval_signals 에서도 사용
__all__ = [
    "GATE_EVAL_LABELS",
    "evaluate_gate",
    "format_metrics",
    "_f1_from_pr",
    "_load_records",
]


if __name__ == "__main__":
    main()
