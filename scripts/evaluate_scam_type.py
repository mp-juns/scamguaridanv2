"""2차 사기 유형 분류기 정량 평가 스크립트.

라벨링된 평가 데이터셋(JSONL)을 읽어 pipeline/classifier.py의 classify()를 호출하고
예측 라벨과 정답 라벨을 비교해 정확도·P/R/F1·혼동행렬·Top-3 정확도를 산출한다.

지표 의미:
  top1 accuracy  : 최고 신뢰도 예측 라벨이 정답과 일치한 비율
  top3 accuracy  : 상위 3개 후보 중 정답이 포함된 비율 (all_scores 기준)
  macro F1       : 모든 라벨의 F1을 단순 평균 (클래스 불균형 무관)
  weighted F1    : 클래스별 support 비례 가중 평균
  uncertain rate : is_uncertain=True 비율
  smishing recall: 스미싱 라벨을 올바르게 잡은 비율

사용 예:
  python scripts/evaluate_scam_type.py --dataset eval/scam_type_eval_dataset.jsonl
  python scripts/evaluate_scam_type.py --dataset eval/scam_type_eval_dataset.jsonl \\
      --json-out eval/scam_type_eval_report.json

주의:
  - mDeBERTa zero-shot 모델이 로컬 캐시에 없으면 최초 실행 시 다운로드됩니다.
  - fine-tuned 분류기가 활성화된 경우 자동으로 해당 모델을 사용합니다.
  - ANTHROPIC_API_KEY 는 필요하지 않습니다 (분류기는 로컬 모델).
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SCAM_TYPES = [
    "투자 사기", "건강식품 사기", "부동산 사기", "코인 사기",
    "기관 사칭", "대출 사기", "메신저 피싱", "로맨스 스캠",
    "취업·알바 사기", "납치·협박형", "스미싱", "중고거래 사기",
]


def compute_calibration(
    y_true: list[str], y_pred: list[str], confidences: list[float]
) -> dict:
    correct = [t == p for t, p in zip(y_true, y_pred)]
    n = len(confidences)
    avg_conf = sum(confidences) / n if n > 0 else 0.0

    correct_confs = [c for c, ok in zip(confidences, correct) if ok]
    wrong_confs = [c for c, ok in zip(confidences, correct) if not ok]
    avg_conf_correct = sum(correct_confs) / len(correct_confs) if correct_confs else 0.0
    avg_conf_wrong = sum(wrong_confs) / len(wrong_confs) if wrong_confs else 0.0

    bins = [(0.0, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.001)]
    bin_stats = []
    for lo, hi in bins:
        idxs = [i for i, c in enumerate(confidences) if lo <= c < hi]
        if idxs:
            n_bin = len(idxs)
            n_correct = sum(1 for i in idxs if correct[i])
            acc = n_correct / n_bin
        else:
            n_bin, n_correct, acc = 0, 0, 0.0
        label = f"{lo:.1f}~{'1.0' if hi > 1.0 else f'{hi:.1f}'}"
        bin_stats.append({"range": label, "n": n_bin, "correct": n_correct, "accuracy": acc})

    return {
        "avg_confidence": avg_conf,
        "avg_confidence_correct": avg_conf_correct,
        "avg_confidence_wrong": avg_conf_wrong,
        "n_correct": len(correct_confs),
        "n_wrong": len(wrong_confs),
        "bins": bin_stats,
    }


def print_calibration(cal: dict) -> None:
    print("  [Confidence Calibration]")
    print(f"  ▶ 평균 confidence (전체)   : {cal['avg_confidence']:.4f} ({cal['avg_confidence']:.1%})")
    print(f"  ▶ 평균 confidence (맞춘 것): {cal['avg_confidence_correct']:.4f} ({cal['avg_confidence_correct']:.1%})"
          f"  (n={cal['n_correct']})")
    print(f"  ▶ 평균 confidence (틀린 것): {cal['avg_confidence_wrong']:.4f} ({cal['avg_confidence_wrong']:.1%})"
          f"  (n={cal['n_wrong']})")
    print()
    print(f"  {'구간':<12} {'샘플수':>6} {'맞춘수':>6} {'정확도':>8}")
    print("  " + "-" * 36)
    for b in cal["bins"]:
        acc_str = f"{b['accuracy']:.1%}" if b["n"] > 0 else "  N/A"
        print(f"  {b['range']:<12} {b['n']:>6d} {b['correct']:>6d} {acc_str:>8}")
    print()


def load_dataset(path: Path) -> list[dict]:
    samples = []
    with path.open(encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if "text" not in obj or "label" not in obj:
                    print(f"  [경고] {i}행: text/label 필드 없음 — 건너뜀", file=sys.stderr)
                    continue
                if obj["label"] not in SCAM_TYPES:
                    print(f"  [경고] {i}행: 알 수 없는 라벨 '{obj['label']}' — 건너뜀",
                          file=sys.stderr)
                    continue
                samples.append({"text": obj["text"], "label": obj["label"]})
            except json.JSONDecodeError as e:
                print(f"  [경고] {i}행 JSON 파싱 오류: {e} — 건너뜀", file=sys.stderr)
    return samples


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    return p, r, f1


def compute_metrics(
    y_true: list[str],
    y_pred: list[str],
    all_scores_list: list[dict[str, float]],
    uncertain_flags: list[bool],
    labels: list[str],
) -> dict:
    n = len(y_true)
    correct_top1 = sum(t == p for t, p in zip(y_true, y_pred))
    accuracy_top1 = correct_top1 / n if n > 0 else 0.0

    # Top-3 accuracy: 상위 3개 스코어 라벨 중 정답 포함 여부
    top3_hits = 0
    for true, scores in zip(y_true, all_scores_list):
        top3 = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
        top3_labels = [lbl for lbl, _ in top3]
        if true in top3_labels:
            top3_hits += 1
    accuracy_top3 = top3_hits / n if n > 0 else 0.0

    # uncertain rate
    n_uncertain = sum(uncertain_flags)
    uncertain_rate = n_uncertain / n if n > 0 else 0.0

    per_label: dict[str, dict] = {}
    for label in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == label and p != label)
        support = sum(1 for t in y_true if t == label)
        p, r, f1 = _prf(tp, fp, fn)
        per_label[label] = {"precision": p, "recall": r, "f1": f1,
                             "tp": tp, "fp": fp, "fn": fn, "support": support}

    active = [l for l in labels if per_label[l]["support"] > 0]
    macro_p = sum(per_label[l]["precision"] for l in active) / len(active) if active else 0.0
    macro_r = sum(per_label[l]["recall"] for l in active) / len(active) if active else 0.0
    macro_f1 = sum(per_label[l]["f1"] for l in active) / len(active) if active else 0.0

    total_support = sum(per_label[l]["support"] for l in active)
    weighted_f1 = (
        sum(per_label[l]["f1"] * per_label[l]["support"] for l in active) / total_support
        if total_support > 0 else 0.0
    )

    # 혼동 행렬
    cm: dict[str, dict[str, int]] = {t: {p: 0 for p in labels} for t in labels}
    for t, p in zip(y_true, y_pred):
        if t in cm and p in labels:
            cm[t][p] += 1

    # 라벨별 uncertain rate
    label_uncertain: dict[str, float] = {}
    for label in labels:
        idxs = [i for i, t in enumerate(y_true) if t == label]
        if idxs:
            unc_count = sum(1 for i in idxs if uncertain_flags[i])
            label_uncertain[label] = unc_count / len(idxs)
        else:
            label_uncertain[label] = 0.0

    # 스미싱 후처리 반영 지표:
    # 스미싱인데 다른 라벨로 예측된(=후처리로 변경됐을 가능성 있는) 케이스 건수
    smishing_missed = sum(
        1 for t, p in zip(y_true, y_pred) if t == "스미싱" and p != "스미싱"
    )

    return {
        "n": n,
        "correct_top1": correct_top1,
        "wrong_top1": n - correct_top1,
        "accuracy_top1": accuracy_top1,
        "accuracy_top3": accuracy_top3,
        "uncertain_count": n_uncertain,
        "uncertain_rate": uncertain_rate,
        "macro_precision": macro_p,
        "macro_recall": macro_r,
        "macro_f1": macro_f1,
        "weighted_f1": weighted_f1,
        "per_label": per_label,
        "label_uncertain_rate": label_uncertain,
        "confusion_matrix": cm,
        "smishing_missed": smishing_missed,
    }


def print_report(metrics: dict, labels: list[str]) -> None:
    n = metrics["n"]
    acc1 = metrics["accuracy_top1"]
    acc3 = metrics["accuracy_top3"]
    print("\n" + "=" * 75)
    print("  ScamGuardian — 2차 사기 유형 분류기 정량 평가 결과")
    print("=" * 75)
    print(f"  전체 샘플 수     : {n}")
    print(f"  맞춘 건수 (Top-1): {metrics['correct_top1']}")
    print(f"  틀린 건수 (Top-1): {metrics['wrong_top1']}")
    print(f"  Top-1 정확도     : {acc1:.1%} ({acc1:.4f})")
    print(f"  Top-3 정확도     : {acc3:.1%} ({acc3:.4f})  ← 상위 3 후보 중 정답 포함 비율")
    print(f"  Macro F1         : {metrics['macro_f1']:.4f}")
    print(f"  Weighted F1      : {metrics['weighted_f1']:.4f}")
    print(f"  Uncertain(불확실) : {metrics['uncertain_count']}건 ({metrics['uncertain_rate']:.1%})")
    print()

    print("  [라벨별 성능]")
    hdr = f"  {'라벨':<16} {'Support':>7} {'Prec':>8} {'Recall':>8} {'F1':>8} {'Uncertain':>10}"
    print(hdr)
    print("  " + "-" * 62)
    for label in labels:
        m = metrics["per_label"][label]
        unc = metrics["label_uncertain_rate"].get(label, 0.0)
        print(
            f"  {label:<16} {m['support']:>7d} "
            f"{m['precision']:>8.4f} {m['recall']:>8.4f} {m['f1']:>8.4f} {unc:>9.1%}"
        )
    print()

    # 혼동 행렬 (라벨이 많으므로 전체 행렬은 파일로, 여기선 주요 혼동 Top-10 출력)
    print("  [상위 혼동 쌍 Top-10] (정답 → 예측, 맞춘 것 제외)")
    cm = metrics["confusion_matrix"]
    confusion_pairs: list[tuple[int, str, str]] = []
    for t in labels:
        for p in labels:
            if t != p and cm[t][p] > 0:
                confusion_pairs.append((cm[t][p], t, p))
    confusion_pairs.sort(reverse=True)
    for count, t, p in confusion_pairs[:10]:
        print(f"    {t:<16} → {p:<16} : {count}건")
    print()

    print("  [주요 사기 유형 상세]")
    focus = ["스미싱", "투자 사기", "기관 사칭", "중고거래 사기"]
    for label in focus:
        if label not in metrics["per_label"]:
            continue
        m = metrics["per_label"][label]
        unc = metrics["label_uncertain_rate"].get(label, 0.0)
        print(f"  ▶ {label:<14} Prec={m['precision']:.1%}  Recall={m['recall']:.1%}  "
              f"F1={m['f1']:.1%}  Uncertain={unc:.1%}")
    print(f"  ▶ 스미싱 미탐 건수: {metrics['smishing_missed']}건 (후처리에서 걸러진 가능성 있음)")
    print()

    if "calibration" in metrics:
        print_calibration(metrics["calibration"])

    print("  [교수님께 보여드릴 요약]")
    print("-" * 75)
    sm = metrics["per_label"].get("스미싱", {})
    print(
        f"  총 {n}개 샘플(12개 사기 유형) 기준 분류기 Top-1 정확도는 {acc1:.1%},\n"
        f"  Top-3 정확도는 {acc3:.1%}였습니다.\n"
        f"  Macro F1은 {metrics['macro_f1']:.4f}, Weighted F1은 {metrics['weighted_f1']:.4f}입니다.\n"
        f"  모델이 불확실(uncertain)로 처리한 비율은 {metrics['uncertain_rate']:.1%}였으며,\n"
        f"  핵심 위험 유형인 스미싱의 Recall은 {sm.get('recall', 0):.1%},"
        f" F1은 {sm.get('f1', 0):.1%}로 측정되었습니다."
    )
    print("=" * 75)


def save_json(metrics: dict, labels: list[str], path: Path) -> None:
    def _round_floats(obj):
        if isinstance(obj, float):
            return round(obj, 6)
        if isinstance(obj, dict):
            return {k: _round_floats(v) for k, v in obj.items()}
        return obj

    out = {
        "n": metrics["n"],
        "correct_top1": metrics["correct_top1"],
        "wrong_top1": metrics["wrong_top1"],
        "accuracy_top1": round(metrics["accuracy_top1"], 6),
        "accuracy_top3": round(metrics["accuracy_top3"], 6),
        "uncertain_count": metrics["uncertain_count"],
        "uncertain_rate": round(metrics["uncertain_rate"], 6),
        "macro_precision": round(metrics["macro_precision"], 6),
        "macro_recall": round(metrics["macro_recall"], 6),
        "macro_f1": round(metrics["macro_f1"], 6),
        "weighted_f1": round(metrics["weighted_f1"], 6),
        "per_label": _round_floats(metrics["per_label"]),
        "label_uncertain_rate": _round_floats(metrics["label_uncertain_rate"]),
        "confusion_matrix": {t: dict(row) for t, row in metrics["confusion_matrix"].items()},
        "smishing_missed": metrics["smishing_missed"],
        "calibration": _round_floats(metrics.get("calibration", {})),
    }
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  JSON 리포트 저장: {path}")


def save_confusion_csv(metrics: dict, labels: list[str], path: Path) -> None:
    cm = metrics["confusion_matrix"]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["정답\\예측"] + labels)
        for t in labels:
            row = [t] + [cm[t].get(p, 0) for p in labels]
            writer.writerow(row)
    print(f"  혼동 행렬 CSV 저장: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="2차 사기 유형 분류기 정량 평가 — Top-1/3 accuracy, macro/weighted F1, 혼동행렬"
    )
    parser.add_argument(
        "--dataset",
        default="eval/scam_type_eval_dataset.jsonl",
        help="평가 데이터셋 JSONL 경로 (기본: eval/scam_type_eval_dataset.jsonl)",
    )
    parser.add_argument(
        "--json-out",
        default="eval/scam_type_eval_report.json",
        help="JSON 리포트 저장 경로 (기본: eval/scam_type_eval_report.json)",
    )
    parser.add_argument(
        "--csv-out",
        default="eval/scam_type_confusion_matrix.csv",
        help="혼동 행렬 CSV 저장 경로 (기본: eval/scam_type_confusion_matrix.csv)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.1,
        help="샘플 간 딜레이(초). 로컬 모델이므로 기본 0.1 (기본: 0.1)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="평가할 최대 샘플 수. 0이면 전체 (기본: 0)",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    dataset_path = Path(args.dataset) if Path(args.dataset).is_absolute() else root / args.dataset
    json_out = Path(args.json_out) if Path(args.json_out).is_absolute() else root / args.json_out
    csv_out = Path(args.csv_out) if Path(args.csv_out).is_absolute() else root / args.csv_out

    if not dataset_path.exists():
        print(f"[오류] 데이터셋 파일을 찾을 수 없습니다: {dataset_path}", file=sys.stderr)
        return 1

    from pipeline.classifier import classify

    samples = load_dataset(dataset_path)
    if args.limit > 0:
        samples = samples[: args.limit]

    print(f"\n  데이터셋: {dataset_path} ({len(samples)}건)")
    dist = Counter(s["label"] for s in samples)
    for label in SCAM_TYPES:
        if dist[label]:
            print(f"    {label:<16}: {dist[label]}건")

    print(f"\n  분류 시작... (딜레이: {args.delay}s/건)")
    y_true: list[str] = []
    y_pred: list[str] = []
    all_scores_list: list[dict[str, float]] = []
    uncertain_flags: list[bool] = []
    confidences: list[float] = []
    errors: list[str] = []

    for i, sample in enumerate(samples, 1):
        text = sample["text"]
        true_label = sample["label"]
        conf = 0.0
        try:
            result = classify(text)
            pred_label = result.scam_type
            all_scores = result.all_scores or {}
            is_uncertain = result.is_uncertain
            conf = result.confidence
        except Exception as e:
            pred_label = SCAM_TYPES[0]
            all_scores = {}
            is_uncertain = True
            errors.append(f"샘플 {i}: {e}")

        y_true.append(true_label)
        y_pred.append(pred_label)
        all_scores_list.append(all_scores)
        uncertain_flags.append(is_uncertain)
        confidences.append(conf)

        mark = "✓" if pred_label == true_label else "✗"
        unc_mark = " [?]" if is_uncertain else "    "
        short_text = text[:35].replace("\n", " ")
        print(f"  [{i:3d}/{len(samples)}] {mark}{unc_mark} "
              f"정답={true_label:<12} 예측={pred_label:<12} conf={conf:.2f} | {short_text!r}")

        if args.delay > 0 and i < len(samples):
            time.sleep(args.delay)

    if errors:
        print(f"\n  [경고] 오류 {len(errors)}건:")
        for e in errors:
            print(f"    {e}")

    cal = compute_calibration(y_true, y_pred, confidences)
    metrics = compute_metrics(y_true, y_pred, all_scores_list, uncertain_flags, SCAM_TYPES)
    metrics["calibration"] = cal
    print_report(metrics, SCAM_TYPES)

    json_out.parent.mkdir(parents=True, exist_ok=True)
    save_json(metrics, SCAM_TYPES, json_out)
    save_confusion_csv(metrics, SCAM_TYPES, csv_out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
