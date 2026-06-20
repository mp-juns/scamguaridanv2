"""Gate 분류기 정량 평가 스크립트.

라벨링된 평가 데이터셋(JSONL)을 읽어 pipeline/gate.py의 classify_gate()를 호출하고
예측 라벨과 정답 라벨을 비교해 정확도·Precision·Recall·F1·혼동행렬을 산출한다.

지표 의미:
  accuracy  : 전체 샘플 중 맞춘 비율
  precision : 해당 라벨로 예측한 것 중 실제 정답 비율
  recall    : 실제 해당 라벨 중 모델이 맞춘 비율
  F1-score  : precision과 recall의 조화 평균

사용 예:
  python scripts/evaluate_gate.py --dataset eval/gate_eval_dataset.jsonl
  python scripts/evaluate_gate.py --dataset eval/gate_eval_dataset.jsonl --json-out eval/gate_eval_report.json

주의:
  - Gate는 기본적으로 Claude Haiku를 사용하므로 ANTHROPIC_API_KEY가 필요합니다.
  - fine-tuned 게이트가 활성화된 경우 로컬 모델을 사용합니다.
  - undetermined 라벨 중 10자 미만 텍스트는 heuristic fast-path로 처리됩니다.
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

LABELS = ["normal", "scam_attempt", "scam_news_edu", "suspicious_insufficient", "undetermined"]

LABELS_KO = {
    "normal": "정상",
    "scam_attempt": "사기 시도",
    "scam_news_edu": "사기 뉴스·교육",
    "suspicious_insufficient": "의심·불충분",
    "undetermined": "판단 불가",
}


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
                if obj["label"] not in LABELS:
                    print(f"  [경고] {i}행: 알 수 없는 라벨 '{obj['label']}' — 건너뜀", file=sys.stderr)
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


def compute_metrics(y_true: list[str], y_pred: list[str], labels: list[str]) -> dict:
    n = len(y_true)
    correct = sum(t == p for t, p in zip(y_true, y_pred))
    accuracy = correct / n if n > 0 else 0.0

    per_label: dict[str, dict] = {}
    for label in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == label and p != label)
        support = sum(1 for t in y_true if t == label)
        p, r, f1 = _prf(tp, fp, fn)
        per_label[label] = {"precision": p, "recall": r, "f1": f1,
                             "tp": tp, "fp": fp, "fn": fn, "support": support}

    # macro 평균 (라벨 존재 여부 무관)
    active = [l for l in labels if per_label[l]["support"] > 0]
    macro_p = sum(per_label[l]["precision"] for l in active) / len(active) if active else 0.0
    macro_r = sum(per_label[l]["recall"] for l in active) / len(active) if active else 0.0
    macro_f1 = sum(per_label[l]["f1"] for l in active) / len(active) if active else 0.0

    # 혼동 행렬
    cm: dict[str, dict[str, int]] = {t: {p: 0 for p in labels} for t in labels}
    for t, p in zip(y_true, y_pred):
        if t in cm and p in labels:
            cm[t][p] += 1

    # normal false positive rate (정상을 사기로 오분류한 비율)
    normal_total = per_label["normal"]["support"]
    normal_fp_count = sum(
        1 for t, p in zip(y_true, y_pred)
        if t == "normal" and p != "normal"
    )
    normal_fpr = normal_fp_count / normal_total if normal_total > 0 else 0.0

    # scam_news_edu → scam_attempt 혼동 건수
    news_edu_as_scam = sum(
        1 for t, p in zip(y_true, y_pred)
        if t == "scam_news_edu" and p == "scam_attempt"
    )

    return {
        "n": n,
        "correct": correct,
        "wrong": n - correct,
        "accuracy": accuracy,
        "macro_precision": macro_p,
        "macro_recall": macro_r,
        "macro_f1": macro_f1,
        "per_label": per_label,
        "confusion_matrix": cm,
        "normal_false_positive_rate": normal_fpr,
        "normal_fp_count": normal_fp_count,
        "news_edu_misclassified_as_scam_attempt": news_edu_as_scam,
    }


def compute_calibration(
    y_true: list[str], y_pred: list[str], confidences: list[float]
) -> dict:
    """예측 confidence 와 실제 정오를 비교해 calibration 지표를 산출한다."""
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


def print_report(metrics: dict, labels: list[str], cal: dict | None = None) -> None:
    n = metrics["n"]
    acc = metrics["accuracy"]
    print("\n" + "=" * 70)
    print("  ScamGuardian — Gate 분류기 정량 평가 결과")
    print("=" * 70)
    print(f"  전체 샘플 수  : {n}")
    print(f"  맞춘 건수     : {metrics['correct']}")
    print(f"  틀린 건수     : {metrics['wrong']}")
    print(f"  전체 정확도   : {acc:.1%} ({acc:.4f})")
    print(f"  Macro P/R/F1  : {metrics['macro_precision']:.4f} / {metrics['macro_recall']:.4f} / {metrics['macro_f1']:.4f}")
    print()
    print("  [라벨별 성능]")
    hdr = f"  {'라벨':<22} {'Support':>7} {'Precision':>10} {'Recall':>8} {'F1':>8}"
    print(hdr)
    print("  " + "-" * 60)
    for label in labels:
        m = metrics["per_label"][label]
        ko = LABELS_KO.get(label, label)
        print(f"  {ko:<22} {m['support']:>7d} {m['precision']:>9.4f} {m['recall']:>8.4f} {m['f1']:>8.4f}")
    print()

    print("  [혼동 행렬] (행=정답, 열=예측)")
    col_w = 8
    header = "  정답\\예측".ljust(24) + "".join(LABELS_KO.get(l, l)[:6].rjust(col_w) for l in labels)
    print(header)
    print("  " + "-" * (24 + col_w * len(labels)))
    cm = metrics["confusion_matrix"]
    for t in labels:
        row_label = LABELS_KO.get(t, t)[:20].ljust(24)
        cells = "".join(str(cm[t].get(p, 0)).rjust(col_w) for p in labels)
        print(f"  {row_label}{cells}")
    print()

    print("  [주요 지표]")
    sa = metrics["per_label"]["scam_attempt"]
    print(f"  ▶ 사기 시도 Precision : {sa['precision']:.4f} ({sa['precision']:.1%})")
    print(f"  ▶ 사기 시도 Recall    : {sa['recall']:.4f} ({sa['recall']:.1%})  ← 사기 놓치지 않은 비율")
    print(f"  ▶ 사기 시도 F1-score  : {sa['f1']:.4f}")
    print(f"  ▶ 정상 오분류율(FPR)  : {metrics['normal_false_positive_rate']:.4f} "
          f"({metrics['normal_fp_count']}/{metrics['per_label']['normal']['support']} 건) "
          f"← 정상을 사기로 잘못 판단한 비율")
    print(f"  ▶ 사기뉴스→사기시도 혼동: {metrics['news_edu_misclassified_as_scam_attempt']}건 "
          f"← 사기 교육 콘텐츠를 실제 사기로 오분류한 횟수")
    print()

    if cal is not None:
        print_calibration(cal)

    # 교수님께 보여드릴 요약 문장
    print("  [교수님께 보여드릴 요약]")
    print("-" * 70)
    print(
        f"  총 {n}개 평가 샘플 기준 Gate 분류기의 전체 정확도는 {acc:.1%}였으며,\n"
        f"  사기 시도 라벨의 precision은 {sa['precision']:.1%},\n"
        f"  recall은 {sa['recall']:.1%}, F1-score는 {sa['f1']:.1%}로 나타났습니다.\n"
        f"  정상 메시지를 사기로 오분류한 비율은 {metrics['normal_false_positive_rate']:.1%}였으며,\n"
        f"  사기 교육·뉴스 콘텐츠를 실제 사기로 혼동한 건수는 "
        f"{metrics['news_edu_misclassified_as_scam_attempt']}건이었습니다."
    )
    print("=" * 70)


def save_json(metrics: dict, labels: list[str], path: Path) -> None:
    out = {
        "n": metrics["n"],
        "correct": metrics["correct"],
        "wrong": metrics["wrong"],
        "accuracy": round(metrics["accuracy"], 6),
        "macro_precision": round(metrics["macro_precision"], 6),
        "macro_recall": round(metrics["macro_recall"], 6),
        "macro_f1": round(metrics["macro_f1"], 6),
        "per_label": {
            label: {k: (round(v, 6) if isinstance(v, float) else v)
                    for k, v in m.items()}
            for label, m in metrics["per_label"].items()
        },
        "confusion_matrix": {
            t: dict(row) for t, row in metrics["confusion_matrix"].items()
        },
        "normal_false_positive_rate": round(metrics["normal_false_positive_rate"], 6),
        "normal_fp_count": metrics["normal_fp_count"],
        "news_edu_misclassified_as_scam_attempt": metrics["news_edu_misclassified_as_scam_attempt"],
    }
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  JSON 리포트 저장: {path}")


def save_confusion_csv(metrics: dict, labels: list[str], path: Path) -> None:
    cm = metrics["confusion_matrix"]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["정답\\예측"] + [LABELS_KO.get(l, l) for l in labels])
        for t in labels:
            row = [LABELS_KO.get(t, t)] + [cm[t].get(p, 0) for p in labels]
            writer.writerow(row)
    print(f"  혼동 행렬 CSV 저장: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate 분류기 정량 평가 — accuracy / precision / recall / F1 / 혼동행렬"
    )
    parser.add_argument(
        "--dataset",
        default="eval/gate_eval_dataset.jsonl",
        help="평가 데이터셋 JSONL 경로 (기본: eval/gate_eval_dataset.jsonl)",
    )
    parser.add_argument(
        "--json-out",
        default="eval/gate_eval_report.json",
        help="JSON 리포트 저장 경로 (기본: eval/gate_eval_report.json)",
    )
    parser.add_argument(
        "--csv-out",
        default="eval/gate_confusion_matrix.csv",
        help="혼동 행렬 CSV 저장 경로 (기본: eval/gate_confusion_matrix.csv)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="API 호출 간 딜레이(초). Haiku 사용 시 rate limit 방지 (기본: 0.5)",
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

    from pipeline.gate import classify_gate

    samples = load_dataset(dataset_path)
    if args.limit > 0:
        samples = samples[: args.limit]

    print(f"\n  데이터셋: {dataset_path} ({len(samples)}건)")
    dist = Counter(s["label"] for s in samples)
    for label in LABELS:
        if dist[label]:
            print(f"    {LABELS_KO.get(label, label):<18}: {dist[label]}건")

    print(f"\n  Gate 분류 시작... (딜레이: {args.delay}s/건)")
    y_true: list[str] = []
    y_pred: list[str] = []
    confidences: list[float] = []
    errors: list[str] = []

    for i, sample in enumerate(samples, 1):
        text = sample["text"]
        true_label = sample["label"]
        conf = 0.0
        try:
            result = classify_gate(text)
            pred_label = result.bucket
            conf = result.confidence
        except Exception as e:
            pred_label = "undetermined"
            errors.append(f"샘플 {i}: {e}")

        y_true.append(true_label)
        y_pred.append(pred_label)
        confidences.append(conf)

        mark = "✓" if pred_label == true_label else "✗"
        short_text = text[:40].replace("\n", " ")
        print(f"  [{i:3d}/{len(samples)}] {mark} 정답={LABELS_KO.get(true_label,''):<8} "
              f"예측={LABELS_KO.get(pred_label,''):<8} conf={conf:.2f} | {short_text!r}")

        if args.delay > 0 and i < len(samples):
            time.sleep(args.delay)

    if errors:
        print(f"\n  [경고] 오류 {len(errors)}건:")
        for e in errors:
            print(f"    {e}")

    metrics = compute_metrics(y_true, y_pred, LABELS)
    cal = compute_calibration(y_true, y_pred, confidences)
    print_report(metrics, LABELS, cal)

    json_out.parent.mkdir(parents=True, exist_ok=True)
    out_data = {
        "n": metrics["n"],
        "correct": metrics["correct"],
        "wrong": metrics["wrong"],
        "accuracy": round(metrics["accuracy"], 6),
        "macro_precision": round(metrics["macro_precision"], 6),
        "macro_recall": round(metrics["macro_recall"], 6),
        "macro_f1": round(metrics["macro_f1"], 6),
        "per_label": {
            label: {k: (round(v, 6) if isinstance(v, float) else v)
                    for k, v in m.items()}
            for label, m in metrics["per_label"].items()
        },
        "confusion_matrix": {t: dict(row) for t, row in metrics["confusion_matrix"].items()},
        "normal_false_positive_rate": round(metrics["normal_false_positive_rate"], 6),
        "normal_fp_count": metrics["normal_fp_count"],
        "news_edu_misclassified_as_scam_attempt": metrics["news_edu_misclassified_as_scam_attempt"],
        "calibration": {
            k: (round(v, 6) if isinstance(v, float) else v)
            for k, v in cal.items() if k != "bins"
        } | {"bins": [{k2: (round(v2, 6) if isinstance(v2, float) else v2)
                        for k2, v2 in b.items()} for b in cal["bins"]]},
    }
    json_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.write_text(json.dumps(out_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  JSON 리포트 저장: {json_out}")
    save_confusion_csv(metrics, LABELS, csv_out)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
