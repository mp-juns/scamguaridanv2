"""Stage 2 — scam_type 분류 평가 (content_label == scam_attempt 만).

학습 정책과 동일: normal / scam_news_edu / suspicious / undetermined 는 평가 대상 제외.

records 입력 형식 — 각 record dict:
    {
      "content_label_gt": "scam_attempt",  # 다른 값은 평가에서 제외
      "scam_type_gt": "투자 사기",
      "scam_type_predicted": "투자 사기",        # top-1
      "top_k_predicted": ["투자 사기", "코인 사기", "대출 사기"],  # 선택 — Top-3 평가용
      "all_scores": {"투자 사기": 0.45, ...},     # top_k 없을 때 여기서 derive
    }

CLI:
    python -m training.eval_scam_type --records eval_scam_type.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from training.eval_gate import _f1_from_pr, _load_records


SCAM_ATTEMPT = "scam_attempt"


def _derive_top_k(record: dict[str, Any], k: int) -> list[str]:
    """top_k_predicted 또는 all_scores 에서 상위 k 추출. 없으면 [scam_type_predicted]."""
    top_k = record.get("top_k_predicted")
    if isinstance(top_k, list) and top_k:
        return [str(x) for x in top_k[:k]]
    scores = record.get("all_scores")
    if isinstance(scores, dict) and scores:
        ranked = sorted(scores.items(), key=lambda kv: -float(kv[1]))
        return [str(name) for name, _ in ranked[:k]]
    pred = record.get("scam_type_predicted")
    return [str(pred)] if pred else []


def evaluate_scam_type(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """scam_attempt 만 평가."""
    filtered: list[dict[str, Any]] = []
    skipped_non_scam_attempt = 0
    skipped_missing = 0
    for r in records:
        cl = str(r.get("content_label_gt", "")).strip()
        if cl != SCAM_ATTEMPT:
            skipped_non_scam_attempt += 1
            continue
        gt = str(r.get("scam_type_gt", "")).strip()
        if not gt:
            skipped_missing += 1
            continue
        filtered.append(r)

    n = len(filtered)
    if n == 0:
        return {
            "n": 0,
            "top1_accuracy": 0.0,
            "top3_accuracy": 0.0,
            "macro_f1": 0.0,
            "weighted_f1": 0.0,
            "per_class": {},
            "skipped_non_scam_attempt": skipped_non_scam_attempt,
            "skipped_missing": skipped_missing,
        }

    labels: set[str] = set()
    pairs_top1: list[tuple[str, str]] = []
    top3_hits = 0

    for r in filtered:
        gt = str(r["scam_type_gt"]).strip()
        labels.add(gt)
        top3 = _derive_top_k(r, 3)
        for x in top3:
            if x:
                labels.add(x)
        pred1 = top3[0] if top3 else ""
        pairs_top1.append((gt, pred1))
        if gt in top3:
            top3_hits += 1

    correct_top1 = sum(1 for gt, p in pairs_top1 if gt == p)
    top1_accuracy = correct_top1 / n
    top3_accuracy = top3_hits / n

    label_list = sorted(labels)
    per_class: dict[str, dict[str, float]] = {}
    for label in label_list:
        tp = sum(1 for gt, p in pairs_top1 if gt == label and p == label)
        fp = sum(1 for gt, p in pairs_top1 if gt != label and p == label)
        fn = sum(1 for gt, p in pairs_top1 if gt == label and p != label)
        support = tp + fn
        if support == 0 and (tp + fp) == 0:
            # 예측·정답 모두 없는 label — 평가 외
            continue
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": _f1_from_pr(precision, recall),
            "support": support,
        }

    if per_class:
        macro_f1 = sum(m["f1"] for m in per_class.values()) / len(per_class)
        total_support = sum(m["support"] for m in per_class.values())
        weighted_f1 = (
            sum(m["f1"] * m["support"] for m in per_class.values()) / total_support
            if total_support
            else 0.0
        )
    else:
        macro_f1 = 0.0
        weighted_f1 = 0.0

    return {
        "n": n,
        "top1_accuracy": top1_accuracy,
        "top3_accuracy": top3_accuracy,
        "macro_f1": macro_f1,
        "weighted_f1": weighted_f1,
        "per_class": per_class,
        "skipped_non_scam_attempt": skipped_non_scam_attempt,
        "skipped_missing": skipped_missing,
    }


def format_metrics(metrics: dict[str, Any]) -> str:
    lines = [
        f"n = {metrics['n']}  (non-scam_attempt skip: {metrics['skipped_non_scam_attempt']}, "
        f"missing gt: {metrics['skipped_missing']})",
        f"top-1 accuracy = {metrics['top1_accuracy']:.4f}",
        f"top-3 accuracy = {metrics['top3_accuracy']:.4f}",
        f"macro F1       = {metrics['macro_f1']:.4f}",
        f"weighted F1    = {metrics['weighted_f1']:.4f}",
        "",
        "per-class:",
    ]
    for label, m in metrics["per_class"].items():
        lines.append(
            f"  {label:<24s}  P={m['precision']:.3f}  R={m['recall']:.3f}  "
            f"F1={m['f1']:.3f}  support={int(m['support'])}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    metrics = evaluate_scam_type(_load_records(args.records))
    if args.json:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
    else:
        print(format_metrics(metrics))


if __name__ == "__main__":
    main()
