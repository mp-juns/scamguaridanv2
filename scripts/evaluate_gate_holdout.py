"""Gate fine-tuned 모델의 hold-out validation 평가.

학습 시 사용한 group_split (seed=17, val_ratio=0.1) 을 동일하게 재현해
hold-out val set 에서 checkpoint-5610 의 성능을 측정한다.

학습 코드 참조: scripts/content_label_gate.py
  - 데이터: data/generated/user_samples_augmented.jsonl
  - split: group = (source_ref, seed_text) 단위 group_split
  - seed=17, val_ratio=0.1
  - labels: normal / scam_attempt / scam_news_edu  (3-class)

사용:
  python scripts/evaluate_gate_holdout.py
  python scripts/evaluate_gate_holdout.py --json-out eval/gate_holdout_report.json
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data/generated/user_samples_augmented.jsonl"
CHECKPOINT = ROOT / ".scamguardian/training_sessions/content_label_gate_20260610/output/checkpoint-5610"
CONTENT_LABELS = ["normal", "scam_attempt", "scam_news_edu"]
LABELS_KO = {"normal": "정상", "scam_attempt": "사기 시도", "scam_news_edu": "사기 뉴스·교육"}

VAL_RATIO = 0.1
SEED = 17
MAX_LENGTH = 256
BATCH_SIZE = 32


# ── 학습 시 사용한 data loading + group_split 그대로 복사 ──────────────

def load_records(path: Path) -> list[dict]:
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        cl = (o.get("content_label") or "").strip()
        if cl not in CONTENT_LABELS:
            continue
        out.append({
            "text": (o.get("text") or "").strip(),
            "label": cl,
            "group": (o.get("source_ref", ""), (o.get("seed_text") or "").strip()),
        })
    return out


def group_split(records: list[dict], val_ratio: float, seed: int) -> set:
    """content_label 로 stratify 한 group 단위 split. 학습 코드와 동일."""
    rng = random.Random(seed)
    groups_by_label: dict[str, set] = defaultdict(set)
    for r in records:
        groups_by_label[r["label"]].add(r["group"])
    val_groups: set = set()
    for _cl, gset in groups_by_label.items():
        gs = sorted(gset)
        rng.shuffle(gs)
        n_val = max(1, round(len(gs) * val_ratio)) if len(gs) > 1 else 0
        val_groups.update(gs[:n_val])
    return val_groups


# ── checkpoint 로더 ────────────────────────────────────────────────────

def load_model_and_tokenizer(ckpt: Path):
    from peft import PeftModel
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    label2id = json.loads((ckpt / "label2id.json").read_text(encoding="utf-8"))
    id2label = {int(v): k for k, v in label2id.items()}

    base_name = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
    adapter_cfg = json.loads((ckpt / "adapter_config.json").read_text(encoding="utf-8"))
    base_name = adapter_cfg.get("base_model_name_or_path") or base_name

    base_model = AutoModelForSequenceClassification.from_pretrained(
        base_name,
        num_labels=len(label2id),
        id2label=id2label,
        label2id=label2id,
        ignore_mismatched_sizes=True,
    )
    model = PeftModel.from_pretrained(base_model, str(ckpt), local_files_only=True)
    model = model.float().eval()

    tok_src = str(ckpt) if (ckpt / "tokenizer_config.json").exists() else base_name
    tokenizer = AutoTokenizer.from_pretrained(tok_src)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)
    return model, tokenizer, id2label, device


# ── 배치 예측 ──────────────────────────────────────────────────────────

def predict(model, tokenizer, texts: list[str], id2label: dict, device: str) -> list[str]:
    preds = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i: i + BATCH_SIZE]
        enc = tokenizer(
            batch, truncation=True, max_length=MAX_LENGTH,
            padding=True, return_tensors="pt",
        ).to(device)
        with torch.no_grad():
            logits = model(**enc).logits
        for idx in logits.argmax(dim=-1).tolist():
            preds.append(id2label[int(idx)])
        if (i // BATCH_SIZE) % 5 == 0:
            print(f"  예측 진행: {min(i+BATCH_SIZE, len(texts))}/{len(texts)}", end="\r")
    print()
    return preds


# ── 지표 계산 ──────────────────────────────────────────────────────────

def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    r = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
    return p, r, f1


def compute_metrics(y_true: list[str], y_pred: list[str]) -> dict:
    labels = CONTENT_LABELS
    n = len(y_true)
    correct = sum(t == p for t, p in zip(y_true, y_pred))

    per_label = {}
    for label in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == label and p == label)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != label and p == label)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == label and p != label)
        support = sum(1 for t in y_true if t == label)
        p_, r_, f1_ = _prf(tp, fp, fn)
        per_label[label] = {"precision": p_, "recall": r_, "f1": f1_,
                            "tp": tp, "fp": fp, "fn": fn, "support": support}

    active = [l for l in labels if per_label[l]["support"] > 0]
    macro_p = sum(per_label[l]["precision"] for l in active) / len(active) if active else 0.0
    macro_r = sum(per_label[l]["recall"]    for l in active) / len(active) if active else 0.0
    macro_f1 = sum(per_label[l]["f1"]       for l in active) / len(active) if active else 0.0

    total_s = sum(per_label[l]["support"] for l in active)
    weighted_f1 = (
        sum(per_label[l]["f1"] * per_label[l]["support"] for l in active) / total_s
        if total_s > 0 else 0.0
    )

    cm: dict[str, dict[str, int]] = {t: {p: 0 for p in labels} for t in labels}
    for t, p in zip(y_true, y_pred):
        if t in cm and p in labels:
            cm[t][p] += 1

    normal_total = per_label["normal"]["support"]
    normal_fp_count = sum(1 for t, p in zip(y_true, y_pred) if t == "normal" and p != "normal")
    normal_fpr = normal_fp_count / normal_total if normal_total > 0 else 0.0

    news_as_scam = sum(
        1 for t, p in zip(y_true, y_pred)
        if t == "scam_news_edu" and p == "scam_attempt"
    )

    return {
        "n": n, "correct": correct, "wrong": n - correct,
        "accuracy": correct / n if n > 0 else 0.0,
        "macro_precision": macro_p, "macro_recall": macro_r, "macro_f1": macro_f1,
        "weighted_f1": weighted_f1,
        "per_label": per_label,
        "confusion_matrix": cm,
        "normal_false_positive_rate": normal_fpr,
        "normal_fp_count": normal_fp_count,
        "news_edu_misclassified_as_scam_attempt": news_as_scam,
    }


# ── 출력 ──────────────────────────────────────────────────────────────

def print_report(metrics: dict, train_dist: Counter, val_dist: Counter) -> None:
    labels = CONTENT_LABELS
    n = metrics["n"]
    acc = metrics["accuracy"]

    print("\n" + "=" * 72)
    print("  ScamGuardian — Gate fine-tuned 모델 Hold-out Val 평가")
    print("  (학습 시 group_split seed=17 val_ratio=0.1 동일 재현)")
    print("=" * 72)
    print(f"  학습 데이터  : data/generated/user_samples_augmented.jsonl")
    print(f"  체크포인트   : checkpoint-5610 (content_label_gate_20260610)")
    print(f"  분류 라벨    : {CONTENT_LABELS}  ← 3-class (5-class 아님)")
    print()
    print(f"  [Train/Val 분포]")
    for l in labels:
        print(f"    {LABELS_KO[l]:<12} train {train_dist[l]:5d} / val {val_dist[l]:4d}")
    print()
    print(f"  전체 val 샘플: {n}")
    print(f"  맞춘 건수    : {metrics['correct']}")
    print(f"  틀린 건수    : {metrics['wrong']}")
    print(f"  Overall Acc  : {acc:.4f} ({acc:.2%})")
    print(f"  Macro F1     : {metrics['macro_f1']:.4f}")
    print(f"  Weighted F1  : {metrics['weighted_f1']:.4f}")
    print(f"  Macro P/R    : {metrics['macro_precision']:.4f} / {metrics['macro_recall']:.4f}")
    print()

    print(f"  {'라벨':<16} {'Support':>7} {'Precision':>10} {'Recall':>9} {'F1':>8}")
    print("  " + "-" * 54)
    for label in labels:
        m = metrics["per_label"][label]
        ko = LABELS_KO[label]
        print(f"  {ko:<16} {m['support']:>7d} {m['precision']:>9.4f} {m['recall']:>9.4f} {m['f1']:>8.4f}")
    print()

    print("  [혼동 행렬] (행=정답, 열=예측)")
    col_w = 10
    header = "  정답\\예측".ljust(20) + "".join(LABELS_KO[l][:8].rjust(col_w) for l in labels)
    print(header)
    print("  " + "-" * (20 + col_w * len(labels)))
    cm = metrics["confusion_matrix"]
    for t in labels:
        row_label = LABELS_KO[t].ljust(20)
        cells = "".join(str(cm[t].get(p, 0)).rjust(col_w) for p in labels)
        print(f"  {row_label}{cells}")
    print()

    print("  [주요 지표]")
    sa = metrics["per_label"]["scam_attempt"]
    no = metrics["per_label"]["normal"]
    ne = metrics["per_label"]["scam_news_edu"]
    print(f"  ▶ 사기 시도 Precision   : {sa['precision']:.4f} ({sa['precision']:.2%})")
    print(f"  ▶ 사기 시도 Recall      : {sa['recall']:.4f} ({sa['recall']:.2%})  ← 사기 놓치지 않은 비율")
    print(f"  ▶ 사기 시도 F1          : {sa['f1']:.4f}")
    print(f"  ▶ 정상 Precision        : {no['precision']:.4f} ({no['precision']:.2%})")
    print(f"  ▶ 정상 Recall           : {no['recall']:.4f} ({no['recall']:.2%})")
    print(f"  ▶ 정상 오분류율 (FPR)   : {metrics['normal_false_positive_rate']:.4f} "
          f"({metrics['normal_fp_count']}/{no['support']}건)")
    print(f"  ▶ 뉴스교육 Precision    : {ne['precision']:.4f} ({ne['precision']:.2%})")
    print(f"  ▶ 뉴스교육 Recall       : {ne['recall']:.4f} ({ne['recall']:.2%})")
    print(f"  ▶ 사기뉴스→사기시도 혼동: {metrics['news_edu_misclassified_as_scam_attempt']}건")
    print()

    print("  [교수님께 보여드릴 요약]")
    print("-" * 72)
    print(
        f"  증강 데이터셋 hold-out val set {n}개 기준\n"
        f"  Gate 분류기 overall accuracy = {acc:.2%}, macro F1 = {metrics['macro_f1']:.4f}\n"
        f"  사기 시도 precision = {sa['precision']:.2%}, recall = {sa['recall']:.2%}, F1 = {sa['f1']:.4f}\n"
        f"  정상 오분류율(FPR) = {metrics['normal_false_positive_rate']:.2%}\n"
        f"  ※ Gate는 3-class (normal/scam_attempt/scam_news_edu) 분류기이며\n"
        f"     suspicious_insufficient / undetermined 라벨은 학습되지 않았습니다."
    )
    print("=" * 72)


def save_json(metrics: dict, path: Path) -> None:
    def _r(v): return round(v, 6) if isinstance(v, float) else v
    out = {
        "checkpoint": str(CHECKPOINT),
        "data": str(DATA_PATH),
        "split": {"seed": SEED, "val_ratio": VAL_RATIO, "method": "group_split"},
        "labels": CONTENT_LABELS,
        "n": metrics["n"], "correct": metrics["correct"], "wrong": metrics["wrong"],
        "accuracy": _r(metrics["accuracy"]),
        "macro_f1": _r(metrics["macro_f1"]),
        "weighted_f1": _r(metrics["weighted_f1"]),
        "macro_precision": _r(metrics["macro_precision"]),
        "macro_recall": _r(metrics["macro_recall"]),
        "per_label": {l: {k: _r(v) for k, v in m.items()} for l, m in metrics["per_label"].items()},
        "confusion_matrix": {t: dict(row) for t, row in metrics["confusion_matrix"].items()},
        "normal_false_positive_rate": _r(metrics["normal_false_positive_rate"]),
        "news_edu_misclassified_as_scam_attempt": metrics["news_edu_misclassified_as_scam_attempt"],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  JSON 저장: {path}")


def save_csv(metrics: dict, path: Path) -> None:
    labels = CONTENT_LABELS
    cm = metrics["confusion_matrix"]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["정답\\예측"] + [LABELS_KO[l] for l in labels])
        for t in labels:
            writer.writerow([LABELS_KO[t]] + [cm[t].get(p, 0) for p in labels])
    print(f"  혼동 행렬 CSV 저장: {path}")


# ── main ──────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Gate hold-out val 평가 (group_split 재현)")
    ap.add_argument("--data", default=str(DATA_PATH))
    ap.add_argument("--checkpoint", default=str(CHECKPOINT))
    ap.add_argument("--val-ratio", type=float, default=VAL_RATIO)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--json-out", default="eval/gate_holdout_report.json")
    ap.add_argument("--csv-out",  default="eval/gate_holdout_confusion.csv")
    args = ap.parse_args()

    data_path = Path(args.data)
    ckpt_path = Path(args.checkpoint)
    json_out  = Path(args.json_out) if Path(args.json_out).is_absolute() else ROOT / args.json_out
    csv_out   = Path(args.csv_out)  if Path(args.csv_out).is_absolute()  else ROOT / args.csv_out

    if not data_path.exists():
        print(f"[오류] 데이터 파일 없음: {data_path}", file=sys.stderr); return 1
    if not ckpt_path.exists():
        print(f"[오류] 체크포인트 없음: {ckpt_path}", file=sys.stderr); return 1

    print(f"\n  데이터 로드: {data_path}")
    records = load_records(data_path)
    print(f"  전체 레코드: {len(records)}")

    val_groups = group_split(records, args.val_ratio, args.seed)
    train_recs = [r for r in records if r["group"] not in val_groups]
    val_recs   = [r for r in records if r["group"]     in val_groups]

    # group 누수 검증
    leak = {r["group"] for r in train_recs} & {r["group"] for r in val_recs}
    assert not leak, f"group 누수 {len(leak)}건 — split 오류"

    train_dist = Counter(r["label"] for r in train_recs)
    val_dist   = Counter(r["label"] for r in val_recs)
    print(f"  Train {len(train_recs)} / Val {len(val_recs)}  (group 누수: {len(leak)}건)")
    for l in CONTENT_LABELS:
        print(f"    {LABELS_KO[l]:<12} train {train_dist[l]:5d} / val {val_dist[l]:4d}")

    print(f"\n  체크포인트 로드: {ckpt_path}")
    t0 = time.time()
    model, tokenizer, id2label, device = load_model_and_tokenizer(ckpt_path)
    print(f"  로드 완료 ({time.time()-t0:.1f}s, device={device})")

    texts   = [r["text"]  for r in val_recs]
    y_true  = [r["label"] for r in val_recs]

    print(f"\n  예측 시작 ({len(texts)}건)...")
    t0 = time.time()
    y_pred = predict(model, tokenizer, texts, id2label, device)
    print(f"  예측 완료 ({time.time()-t0:.1f}s)")

    metrics = compute_metrics(y_true, y_pred)
    print_report(metrics, train_dist, val_dist)

    save_json(metrics, json_out)
    save_csv(metrics, csv_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
