"""Stage 3 — 검출 신호(flag) 평가 + baseline/current 라벨 커버리지 비교.

세 가지 평가:
    1. evaluate_flags(records)        — 세부 flag id 단위 P/R/F1 (per-flag + micro)
    2. evaluate_groups(records)       — flag_groups.group_of 로 묶은 그룹 단위 P/R/F1
    3. compare_label_coverage(records) — baseline(top-1 LABEL_SET) vs current
       (COMMON_RISK_LABELS + top-N 후보 LABEL_SET) 의 *추출 라벨셋 커버리지* 비교.
       "투자 사기 top-1 + 주민번호 요구" 같은 입력에서 개인정보 항목 라벨이
       추출 대상에 포함됐는지 비교 — Stage 2 개선 정량화.

records (모두 list[dict]) — 각 평가에 필요한 필드만 있으면 됨:
    {
      "scam_type_gt": "투자 사기",
      "content_label_gt": "scam_attempt",
      "entities_gt": [{"label": "수익 퍼센트", "text": "연 30%"}, ...],
      "triggered_flags_gt": [{"flag": "abnormal_return_rate"}, ...],
      "triggered_flags_predicted": [{"flag": "abnormal_return_rate"}, ...],
      "candidate_scam_types": ["투자 사기", "코인 사기"],  # 선택
    }

CLI:
    python -m training.eval_signals --records eval_signals.jsonl --mode flags
    python -m training.eval_signals --records eval_signals.jsonl --mode groups
    python -m training.eval_signals --records eval_signals.jsonl --mode coverage
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable

from pipeline.config import COMMON_RISK_LABELS, LABEL_SETS
from pipeline.flag_groups import group_of, OTHER_GROUP_ID
from training.eval_gate import _f1_from_pr, _load_records


SCAM_ATTEMPT = "scam_attempt"

# baseline/current 커버리지 비교 시 강조할 핵심 라벨 (사용자 관심 영역).
KEY_RISK_LABELS: list[str] = [
    "개인정보 항목",
    "악성 URL",
    "계좌번호",
    "사칭 기관명",
]


# ──────────────────────────────────────────────
# flag 추출 헬퍼
# ──────────────────────────────────────────────

def _flag_id(item: Any) -> str:
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return str(item.get("flag", "")).strip()
    return ""


def _flag_set(items: Any) -> set[str]:
    if not items:
        return set()
    return {fid for fid in (_flag_id(it) for it in items) if fid}


def _group_set(flag_set: set[str]) -> set[str]:
    return {group_of(f) for f in flag_set}


# ──────────────────────────────────────────────
# flag-level 평가
# ──────────────────────────────────────────────

def evaluate_flags(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """세부 flag id 단위 평가. 모든 record 누적."""
    rec_list = list(records)
    n = len(rec_list)

    per_flag_counts: dict[str, dict[str, int]] = {}
    tp_total = fp_total = fn_total = 0

    for r in rec_list:
        gt = _flag_set(r.get("triggered_flags_gt"))
        pred = _flag_set(r.get("triggered_flags_predicted"))
        tp = gt & pred
        fp = pred - gt
        fn = gt - pred
        tp_total += len(tp)
        fp_total += len(fp)
        fn_total += len(fn)
        for f in tp:
            per_flag_counts.setdefault(f, {"tp": 0, "fp": 0, "fn": 0})["tp"] += 1
        for f in fp:
            per_flag_counts.setdefault(f, {"tp": 0, "fp": 0, "fn": 0})["fp"] += 1
        for f in fn:
            per_flag_counts.setdefault(f, {"tp": 0, "fp": 0, "fn": 0})["fn"] += 1

    micro_precision = tp_total / (tp_total + fp_total) if (tp_total + fp_total) else 0.0
    micro_recall = tp_total / (tp_total + fn_total) if (tp_total + fn_total) else 0.0
    micro_f1 = _f1_from_pr(micro_precision, micro_recall)

    per_flag: dict[str, dict[str, float]] = {}
    for flag, c in per_flag_counts.items():
        tp, fp, fn = c["tp"], c["fp"], c["fn"]
        support = tp + fn
        p = tp / (tp + fp) if (tp + fp) else 0.0
        r = tp / (tp + fn) if (tp + fn) else 0.0
        per_flag[flag] = {
            "precision": p,
            "recall": r,
            "f1": _f1_from_pr(p, r),
            "support": support,
        }

    macro_f1 = (
        sum(m["f1"] for m in per_flag.values() if m["support"] > 0)
        / max(1, sum(1 for m in per_flag.values() if m["support"] > 0))
    )

    return {
        "n_records": n,
        "micro": {
            "precision": micro_precision,
            "recall": micro_recall,
            "f1": micro_f1,
            "tp": tp_total,
            "fp": fp_total,
            "fn": fn_total,
        },
        "macro_f1": macro_f1,
        "per_flag": per_flag,
    }


# ──────────────────────────────────────────────
# group-level 평가
# ──────────────────────────────────────────────

def evaluate_groups(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """flag_groups.group_of 로 매핑된 그룹 단위 P/R/F1. 알 수 없는 flag 는 other_signals."""
    rec_list = list(records)
    n = len(rec_list)
    per_group_counts: dict[str, dict[str, int]] = {}
    tp_total = fp_total = fn_total = 0

    for r in rec_list:
        gt_groups = _group_set(_flag_set(r.get("triggered_flags_gt")))
        pred_groups = _group_set(_flag_set(r.get("triggered_flags_predicted")))
        tp = gt_groups & pred_groups
        fp = pred_groups - gt_groups
        fn = gt_groups - pred_groups
        tp_total += len(tp)
        fp_total += len(fp)
        fn_total += len(fn)
        for g in tp:
            per_group_counts.setdefault(g, {"tp": 0, "fp": 0, "fn": 0})["tp"] += 1
        for g in fp:
            per_group_counts.setdefault(g, {"tp": 0, "fp": 0, "fn": 0})["fp"] += 1
        for g in fn:
            per_group_counts.setdefault(g, {"tp": 0, "fp": 0, "fn": 0})["fn"] += 1

    micro_precision = tp_total / (tp_total + fp_total) if (tp_total + fp_total) else 0.0
    micro_recall = tp_total / (tp_total + fn_total) if (tp_total + fn_total) else 0.0
    micro_f1 = _f1_from_pr(micro_precision, micro_recall)

    per_group: dict[str, dict[str, float]] = {}
    for group, c in per_group_counts.items():
        tp, fp, fn = c["tp"], c["fp"], c["fn"]
        support = tp + fn
        p = tp / (tp + fp) if (tp + fp) else 0.0
        r = tp / (tp + fn) if (tp + fn) else 0.0
        per_group[group] = {
            "precision": p,
            "recall": r,
            "f1": _f1_from_pr(p, r),
            "support": support,
        }
    macro_f1 = (
        sum(m["f1"] for m in per_group.values() if m["support"] > 0)
        / max(1, sum(1 for m in per_group.values() if m["support"] > 0))
    )

    return {
        "n_records": n,
        "micro": {
            "precision": micro_precision,
            "recall": micro_recall,
            "f1": micro_f1,
            "tp": tp_total,
            "fp": fp_total,
            "fn": fn_total,
        },
        "macro_f1": macro_f1,
        "per_group": per_group,
    }


# ──────────────────────────────────────────────
# baseline vs current 라벨 커버리지 비교
# ──────────────────────────────────────────────

def _baseline_labels(record: dict[str, Any]) -> set[str]:
    """기존 top-1 라우팅: LABEL_SETS[scam_type_gt] 만 (COMMON_RISK 없음)."""
    st = str(record.get("scam_type_gt", "")).strip()
    return set(LABEL_SETS.get(st, []))


def _current_labels(record: dict[str, Any]) -> set[str]:
    """Stage 2 라우팅: COMMON_RISK_LABELS + ⋃LABEL_SETS[candidate].
    candidate_scam_types 가 없으면 [scam_type_gt] 만 사용 (최소 Stage 2 — COMMON_RISK 기여만)."""
    candidates = record.get("candidate_scam_types")
    if not candidates:
        st = str(record.get("scam_type_gt", "")).strip()
        candidates = [st] if st else []
    labels: set[str] = set(COMMON_RISK_LABELS)
    for c in candidates:
        labels.update(LABEL_SETS.get(str(c), []))
    return labels


def _gt_entity_labels(record: dict[str, Any]) -> set[str]:
    out: set[str] = set()
    for e in record.get("entities_gt") or []:
        if isinstance(e, dict):
            lbl = str(e.get("label", "")).strip()
            if lbl:
                out.add(lbl)
    return out


def compare_label_coverage(
    records: Iterable[dict[str, Any]],
    baseline_resolver: Callable[[dict[str, Any]], set[str]] | None = None,
    current_resolver: Callable[[dict[str, Any]], set[str]] | None = None,
) -> dict[str, Any]:
    """baseline / current 의 *추출 라벨셋 커버리지* 비교.

    각 record 의 gt 엔티티 라벨 중 추출 라벨셋(baseline / current)에 포함된 비율을 본다.
    Stage 2 가 추가한 COMMON_RISK_LABELS + 후보 합집합이 실제로 커버리지를 끌어올리는지 정량화.

    *기본 동작*:
        baseline_resolver = LABEL_SETS[scam_type_gt] (top-1 only)
        current_resolver  = COMMON_RISK_LABELS + ⋃LABEL_SETS[candidate_scam_types or [scam_type_gt]]

    scam_attempt 가 아닌 record 는 건너뛴다 (라우팅 비교는 scam_attempt 학습 영역 한정).
    """
    baseline_resolver = baseline_resolver or _baseline_labels
    current_resolver = current_resolver or _current_labels

    n_records = 0
    skipped_non_scam_attempt = 0
    total_gt_entities = 0
    baseline_covered = 0
    current_covered = 0

    # 핵심 라벨별 커버리지 — support = gt 에 해당 라벨이 1회 이상 등장한 record 수
    by_label: dict[str, dict[str, int]] = {
        l: {"support": 0, "baseline_covered": 0, "current_covered": 0}
        for l in KEY_RISK_LABELS
    }

    for r in records:
        cl = str(r.get("content_label_gt", "")).strip()
        if cl and cl != SCAM_ATTEMPT:
            skipped_non_scam_attempt += 1
            continue
        n_records += 1
        gt_labels = _gt_entity_labels(r)
        if not gt_labels:
            continue
        base = baseline_resolver(r)
        curr = current_resolver(r)
        for lbl in gt_labels:
            total_gt_entities += 1
            if lbl in base:
                baseline_covered += 1
            if lbl in curr:
                current_covered += 1
        for key in KEY_RISK_LABELS:
            if key in gt_labels:
                by_label[key]["support"] += 1
                if key in base:
                    by_label[key]["baseline_covered"] += 1
                if key in curr:
                    by_label[key]["current_covered"] += 1

    overall_baseline = baseline_covered / total_gt_entities if total_gt_entities else 0.0
    overall_current = current_covered / total_gt_entities if total_gt_entities else 0.0

    by_label_rates: dict[str, dict[str, float]] = {}
    for key, c in by_label.items():
        support = c["support"]
        by_label_rates[key] = {
            "support": support,
            "baseline_rate": (c["baseline_covered"] / support) if support else 0.0,
            "current_rate": (c["current_covered"] / support) if support else 0.0,
            "delta": (
                (c["current_covered"] - c["baseline_covered"]) / support
                if support else 0.0
            ),
        }

    return {
        "n_records": n_records,
        "skipped_non_scam_attempt": skipped_non_scam_attempt,
        "n_gt_entities": total_gt_entities,
        "overall_baseline_coverage": overall_baseline,
        "overall_current_coverage": overall_current,
        "overall_delta": overall_current - overall_baseline,
        "by_key_label": by_label_rates,
    }


# ──────────────────────────────────────────────
# 포맷 + CLI
# ──────────────────────────────────────────────

def _format_pr_table(per: dict[str, dict[str, float]], header: str) -> list[str]:
    lines = [header]
    for name, m in sorted(per.items(), key=lambda kv: -kv[1]["support"]):
        lines.append(
            f"  {name:<36s}  P={m['precision']:.3f}  R={m['recall']:.3f}  "
            f"F1={m['f1']:.3f}  support={int(m['support'])}"
        )
    return lines


def format_flags_metrics(m: dict[str, Any]) -> str:
    lines = [
        f"n_records = {m['n_records']}",
        f"micro: P={m['micro']['precision']:.3f}  R={m['micro']['recall']:.3f}  "
        f"F1={m['micro']['f1']:.3f}  (tp={m['micro']['tp']}, fp={m['micro']['fp']}, fn={m['micro']['fn']})",
        f"macro F1 = {m['macro_f1']:.3f}",
        "",
    ]
    lines.extend(_format_pr_table(m["per_flag"], "per-flag:"))
    return "\n".join(lines)


def format_groups_metrics(m: dict[str, Any]) -> str:
    lines = [
        f"n_records = {m['n_records']}",
        f"micro: P={m['micro']['precision']:.3f}  R={m['micro']['recall']:.3f}  "
        f"F1={m['micro']['f1']:.3f}  (tp={m['micro']['tp']}, fp={m['micro']['fp']}, fn={m['micro']['fn']})",
        f"macro F1 = {m['macro_f1']:.3f}",
        "",
    ]
    lines.extend(_format_pr_table(m["per_group"], "per-group:"))
    return "\n".join(lines)


def format_coverage_metrics(m: dict[str, Any]) -> str:
    lines = [
        f"n_records = {m['n_records']}  (non-scam_attempt skip: {m['skipped_non_scam_attempt']})",
        f"gt entities = {m['n_gt_entities']}",
        "",
        f"overall coverage  baseline = {m['overall_baseline_coverage']:.4f}  "
        f"current = {m['overall_current_coverage']:.4f}  Δ = {m['overall_delta']:+.4f}",
        "",
        "per-label coverage (support / baseline / current / Δ):",
    ]
    for key, c in m["by_key_label"].items():
        lines.append(
            f"  {key:<20s}  support={c['support']:>4d}  "
            f"baseline={c['baseline_rate']:.3f}  current={c['current_rate']:.3f}  "
            f"Δ={c['delta']:+.3f}"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=["flags", "groups", "coverage"],
        default="flags",
        help="평가 종류",
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    records = _load_records(args.records)
    if args.mode == "flags":
        metrics = evaluate_flags(records)
        text = format_flags_metrics(metrics)
    elif args.mode == "groups":
        metrics = evaluate_groups(records)
        text = format_groups_metrics(metrics)
    else:
        metrics = compare_label_coverage(records)
        text = format_coverage_metrics(metrics)

    if args.json:
        print(json.dumps(metrics, ensure_ascii=False, indent=2))
    else:
        print(text)


if __name__ == "__main__":
    main()
