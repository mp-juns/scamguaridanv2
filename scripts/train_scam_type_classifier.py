"""12-class → 실제 데이터 기준 9-class 사기 유형 분류기 학습 + test 평가.

데이터 소스 (모두 scam_attempt content_label, scam_type 라벨 있는 것만):
  - data/generated/user_samples_augmented.jsonl  (주 소스, 3,126건)
  - data/processed/admin_seeds.jsonl             (153건)
  - .scamguardian/phh_training/phh_combined_classifier_20260529.jsonl (157건, 기타사기 제외)
  - data/processed/pending_*.jsonl               (~86건)

Split: stratified 70/15/15 (seed=42, 텍스트 exact dedup)

학습: LoRA (modules_to_save=["classifier","pooler"]) → classifier head shape 안전
결과: eval/scam_type_holdout_report.json, eval/scam_type_holdout_confusion_matrix.csv

사용:
  python scripts/train_scam_type_classifier.py
  python scripts/train_scam_type_classifier.py --dry-run       # 데이터 통계만
  python scripts/train_scam_type_classifier.py --epochs 5 --batch-size 8
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import random
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

log = logging.getLogger("train_scam_type")

# ── 데이터 소스 경로 ────────────────────────────────────────────────────

SOURCES = [
    ROOT / "data/generated/user_samples_augmented.jsonl",
    ROOT / "data/processed/admin_seeds.jsonl",
    ROOT / ".scamguardian/phh_training/phh_combined_classifier_20260529.jsonl",
] + sorted(ROOT.glob("data/processed/pending_*.jsonl"))

CKPT_DIR = ROOT / ".scamguardian/training_sessions/scam_type_9class_v1/output"
REPORT_JSON = ROOT / "eval/scam_type_holdout_report.json"
REPORT_CSV = ROOT / "eval/scam_type_holdout_confusion_matrix.csv"

BASE_MODEL = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
EXCLUDED_TYPES = {"기타 사기", ""}  # 12-class 기준에 없는 타입

SPLIT_SEED = 42
TRAIN_RATIO = 0.70
VAL_RATIO = 0.15
# test = 나머지 0.15
MIN_PER_CLASS = 10  # 이 미만이면 해당 유형 학습 제외


# ── 1. 데이터 수집 + dedup ──────────────────────────────────────────────

def load_all_samples() -> list[dict]:
    """모든 소스에서 scam_attempt + scam_type 있는 샘플 수집. 텍스트 exact dedup."""
    all_records = []
    seen_texts: set[str] = set()
    source_counts: dict[str, int] = {}

    for path in SOURCES:
        if not path.exists():
            log.warning("파일 없음, 건너뜀: %s", path)
            continue
        count_this = 0
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue

            cl = (o.get("content_label") or "").strip()
            st = (o.get("scam_type") or o.get("label") or "").strip()
            text = (o.get("text") or o.get("transcript_text") or "").strip()

            if cl != "scam_attempt":
                continue
            if not st or st in EXCLUDED_TYPES:
                continue
            if not text:
                continue
            if text in seen_texts:
                continue

            seen_texts.add(text)
            all_records.append({"text": text, "label": st})
            count_this += 1

        source_counts[path.name] = count_this

    log.info("소스별 신규 샘플:")
    for fname, n in source_counts.items():
        log.info("  %-55s %4d건", fname, n)

    return all_records


# ── 2. stratified 70/15/15 split ───────────────────────────────────────

def stratified_split_3way(
    records: list[dict], train_r: float, val_r: float, seed: int,
) -> tuple[list[dict], list[dict], list[dict]]:
    """label 기준 stratified 70/15/15 split. 나머지는 test."""
    rng = random.Random(seed)
    by_label: dict[str, list[dict]] = {}
    for r in records:
        by_label.setdefault(r["label"], []).append(r)

    train, val, test = [], [], []
    for label, items in by_label.items():
        shuffled = items[:]
        rng.shuffle(shuffled)
        n = len(shuffled)
        n_train = round(n * train_r)
        n_val = round(n * val_r)
        n_test = n - n_train - n_val
        train.extend(shuffled[:n_train])
        val.extend(shuffled[n_train: n_train + n_val])
        test.extend(shuffled[n_train + n_val:])
        log.info(
            "  %-14s  전체 %4d  → train %3d / val %3d / test %3d",
            label, n, n_train, n_val, n_test,
        )

    rng.shuffle(train); rng.shuffle(val); rng.shuffle(test)
    return train, val, test


def print_split_summary(
    all_records: list[dict],
    train: list[dict], val: list[dict], test: list[dict],
) -> None:
    print("\n" + "=" * 72)
    print("  [데이터셋 요약]")
    print(f"  전체: {len(all_records)}건  →  train {len(train)} / val {len(val)} / test {len(test)}")
    print(f"  split: stratified 70/15/15 (seed={SPLIT_SEED})")
    labels = sorted({r['label'] for r in all_records})
    print(f"\n  {'유형':<16} {'전체':>6} {'train':>7} {'val':>6} {'test':>6}")
    print("  " + "-" * 45)
    train_c = Counter(r['label'] for r in train)
    val_c   = Counter(r['label'] for r in val)
    test_c  = Counter(r['label'] for r in test)
    all_c   = Counter(r['label'] for r in all_records)
    for l in labels:
        print(f"  {l:<16} {all_c[l]:>6} {train_c[l]:>7} {val_c[l]:>6} {test_c[l]:>6}")
    missing_12 = ["건강식품 사기", "부동산 사기", "납치·협박형"]
    print(f"\n  ⚠ 실제 데이터 없어 제외된 3개 유형: {missing_12}")
    print("  ⚠ 이 유형들은 실제 학습 데이터가 0건 (run_drafts/DB 라벨은 오라벨)")
    print("=" * 72)


# ── 3. 학습 ────────────────────────────────────────────────────────────

def train(
    train_records: list[dict],
    val_records: list[dict],
    ckpt_dir: Path,
    *,
    base_model: str,
    epochs: int,
    batch_size: int,
    lr: float,
    max_length: int,
    lora_r: int,
    bf16: bool,
) -> dict:
    import numpy as np
    import torch
    from datasets import Dataset
    from peft import LoraConfig, TaskType, get_peft_model
    from sklearn.metrics import accuracy_score, f1_score, precision_recall_fscore_support
    from transformers import (
        AutoModelForSequenceClassification, AutoTokenizer,
        DataCollatorWithPadding, EarlyStoppingCallback, Trainer, TrainingArguments,
    )

    labels_sorted = sorted({r["label"] for r in train_records} | {r["label"] for r in val_records})
    label2id = {l: i for i, l in enumerate(labels_sorted)}
    id2label = {i: l for l, i in label2id.items()}

    log.info("분류 라벨 %d종: %s", len(labels_sorted), labels_sorted)
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    (ckpt_dir / "label2id.json").write_text(
        json.dumps(label2id, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    tokenizer = AutoTokenizer.from_pretrained(base_model)

    def mk_ds(records: list[dict]) -> Dataset:
        ds = Dataset.from_dict({
            "text":  [r["text"]  for r in records],
            "label": [label2id[r["label"]] for r in records],
        })
        return ds.map(
            lambda b: tokenizer(b["text"], truncation=True, max_length=max_length, padding=False),
            batched=True, remove_columns=["text"],
        )

    train_ds = mk_ds(train_records)
    val_ds   = mk_ds(val_records)

    model = AutoModelForSequenceClassification.from_pretrained(
        base_model,
        num_labels=len(label2id),
        id2label=id2label,
        label2id=label2id,
        ignore_mismatched_sizes=True,
    )
    model = get_peft_model(model, LoraConfig(
        task_type=TaskType.SEQ_CLS,
        r=lora_r, lora_alpha=lora_r * 2, lora_dropout=0.1,
        target_modules=["query_proj", "value_proj", "key_proj", "dense"],
        modules_to_save=["classifier", "pooler"],
    ))
    model.print_trainable_parameters()

    def compute_metrics(ep):
        preds = np.argmax(ep.predictions, axis=-1)
        labs  = ep.label_ids
        _, _, mf1, _ = precision_recall_fscore_support(labs, preds, average="macro", zero_division=0)
        return {"accuracy": accuracy_score(labs, preds), "macro_f1": mf1}

    device = "cuda" if torch.cuda.is_available() else "cpu"
    n_gpu  = torch.cuda.device_count() if device == "cuda" else 0

    training_args = TrainingArguments(
        output_dir=str(ckpt_dir),
        num_train_epochs=epochs,
        per_device_train_batch_size=batch_size,
        per_device_eval_batch_size=batch_size * 2,
        learning_rate=lr,
        weight_decay=0.01,
        warmup_ratio=0.06,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        greater_is_better=True,
        logging_steps=50,
        bf16=bf16 and device == "cuda",
        fp16=False,
        dataloader_num_workers=0,
        report_to="none",
        save_total_limit=2,
        seed=SPLIT_SEED,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        data_collator=DataCollatorWithPadding(tokenizer),
        compute_metrics=compute_metrics,
        callbacks=[EarlyStoppingCallback(early_stopping_patience=3)],
    )

    log.info("학습 시작 (train=%d, val=%d, epochs=%d, device=%s)",
             len(train_records), len(val_records), epochs, device)
    t0 = time.time()
    trainer.train()
    elapsed = time.time() - t0
    log.info("학습 완료 (%.0fs)", elapsed)

    # best checkpoint에 label2id 복사 (PEFT 로드 시 필요)
    best = trainer.state.best_model_checkpoint
    if best and Path(best) != ckpt_dir:
        (Path(best) / "label2id.json").write_text(
            json.dumps(label2id, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    log.info("체크포인트 저장: %s", ckpt_dir)
    return {"label2id": label2id, "id2label": id2label, "best_ckpt": best or str(ckpt_dir)}


# ── 4. 테스트셋 평가 ────────────────────────────────────────────────────

def evaluate_test(
    test_records: list[dict],
    label2id: dict,
    id2label: dict,
    ckpt_path: Path,
    max_length: int,
) -> dict:
    import torch
    from peft import PeftModel
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    labels = sorted(label2id, key=lambda l: label2id[l])
    n_labels = len(labels)

    # 체크포인트에 label2id.json 저장
    lbl_file = ckpt_path / "label2id.json"
    if not lbl_file.exists():
        lbl_file.write_text(json.dumps(label2id, ensure_ascii=False, indent=2), encoding="utf-8")

    adapter_cfg = ckpt_path / "adapter_config.json"
    if adapter_cfg.exists():
        base_name = json.loads(adapter_cfg.read_text())["base_model_name_or_path"]
    else:
        base_name = BASE_MODEL

    base = AutoModelForSequenceClassification.from_pretrained(
        base_name, num_labels=n_labels, id2label=id2label, label2id=label2id,
        ignore_mismatched_sizes=True,
    )
    model = PeftModel.from_pretrained(base, str(ckpt_path), local_files_only=True)
    model = model.float().eval()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = model.to(device)
    tok = AutoTokenizer.from_pretrained(str(ckpt_path) if (ckpt_path / "tokenizer_config.json").exists() else base_name)

    y_true, y_pred, y_probs = [], [], []
    BATCH = 32
    texts = [r["text"] for r in test_records]
    true_labels = [r["label"] for r in test_records]

    import torch as _torch
    for i in range(0, len(texts), BATCH):
        batch_t = texts[i: i + BATCH]
        enc = tok(batch_t, truncation=True, max_length=max_length, padding=True, return_tensors="pt").to(device)
        with _torch.no_grad():
            logits = model(**enc).logits
        probs = _torch.softmax(logits, dim=-1)
        for j, lgt in enumerate(logits):
            pred_idx = int(lgt.argmax())
            y_true.append(true_labels[i + j])
            y_pred.append(id2label[pred_idx])
            y_probs.append(probs[j].cpu().tolist())

    return _compute_test_metrics(y_true, y_pred, y_probs, labels, id2label)


def _compute_test_metrics(
    y_true: list[str], y_pred: list[str], y_probs: list[list[float]],
    labels: list[str], id2label: dict,
) -> dict:
    from sklearn.metrics import accuracy_score, f1_score, precision_recall_fscore_support

    n = len(y_true)
    correct = sum(t == p for t, p in zip(y_true, y_pred))
    acc = correct / n if n else 0.0

    # Top-3
    top3 = 0
    label_idx = {l: i for i, l in enumerate(labels)}
    for i, true_l in enumerate(y_true):
        probs = y_probs[i]
        top3_idxs = sorted(range(len(probs)), key=lambda x: -probs[x])[:3]
        top3_labels = [labels[k] for k in top3_idxs]
        if true_l in top3_labels:
            top3 += 1
    top3_acc = top3 / n if n else 0.0

    p_arr, r_arr, f1_arr, sup = precision_recall_fscore_support(
        y_true, y_pred, labels=labels, zero_division=0
    )
    macro_f1 = float(f1_arr.mean()) if len(f1_arr) > 0 else 0.0
    weighted_f1 = float(f1_score(y_true, y_pred, average="weighted", zero_division=0))

    per_label = {
        labels[i]: {
            "precision": float(p_arr[i]), "recall": float(r_arr[i]), "f1": float(f1_arr[i]),
            "support": int(sup[i]),
        }
        for i in range(len(labels))
    }

    cm: dict[str, dict[str, int]] = {t: {p: 0 for p in labels} for t in labels}
    for t, p in zip(y_true, y_pred):
        if t in cm and p in labels:
            cm[t][p] += 1

    uncertain_count = sum(
        1 for probs in y_probs if max(probs) < 0.50
    )

    return {
        "n": n, "correct": correct, "accuracy": acc,
        "top3_accuracy": top3_acc,
        "macro_f1": macro_f1, "weighted_f1": weighted_f1,
        "per_label": per_label,
        "confusion_matrix": cm,
        "uncertain_rate": uncertain_count / n if n else 0.0,
        "uncertain_count": uncertain_count,
    }


# ── 5. 보고서 출력 + 저장 ──────────────────────────────────────────────

def print_report(metrics: dict) -> None:
    labels_sorted = sorted(metrics["per_label"])
    n = metrics["n"]
    acc = metrics["accuracy"]
    top3 = metrics["top3_accuracy"]
    mf1 = metrics["macro_f1"]
    wf1 = metrics["weighted_f1"]

    print("\n" + "=" * 72)
    print("  ScamGuardian — 2차 사기 유형 분류기 (9-class) Hold-out Test 평가")
    print("=" * 72)
    print(f"  test 샘플 수    : {n}")
    print(f"  Top-1 Accuracy  : {acc:.4f} ({acc:.2%})")
    print(f"  Top-3 Accuracy  : {top3:.4f} ({top3:.2%})")
    print(f"  Macro F1        : {mf1:.4f}")
    print(f"  Weighted F1     : {wf1:.4f}")
    print(f"  Uncertain rate  : {metrics['uncertain_rate']:.2%} (max_prob < 0.50)")
    print()
    print(f"  {'유형':<16} {'Support':>7} {'P':>8} {'R':>8} {'F1':>8}")
    print("  " + "-" * 55)
    for l in labels_sorted:
        m = metrics["per_label"][l]
        print(f"  {l:<16} {m['support']:>7d} {m['precision']:>8.4f} {m['recall']:>8.4f} {m['f1']:>8.4f}")
    print()

    # 혼동 행렬
    cm = metrics["confusion_matrix"]
    print("  [혼동 행렬] (행=정답, 열=예측)")
    col_w = 8
    header = "  " + "정답\\예측".ljust(16)
    for l in labels_sorted:
        header += l[:6].rjust(col_w)
    print(header)
    print("  " + "-" * (16 + col_w * len(labels_sorted) + 2))
    for t in labels_sorted:
        row = f"  {t:<16}"
        for p in labels_sorted:
            v = cm.get(t, {}).get(p, 0)
            row += str(v).rjust(col_w)
        print(row)

    # 주요 유형 상세
    print()
    detail_types = ["스미싱", "투자 사기", "기관 사칭", "중고거래 사기"]
    for l in detail_types:
        if l in metrics["per_label"]:
            m = metrics["per_label"][l]
            print(f"  ▶ {l:<10} P={m['precision']:.2%}  R={m['recall']:.2%}  F1={m['f1']:.4f}")
    print()

    # 교수님 요약
    print("  [교수님께 보여드릴 요약]")
    print("-" * 72)
    sm = metrics["per_label"].get("스미싱", {})
    inv = metrics["per_label"].get("투자 사기", {})
    print(
        f"  2차 사기 유형 분류기는 9개 사기 유형 데이터셋에서 분리한\n"
        f"  hold-out test set {n}개 기준\n"
        f"  Top-1 accuracy {acc:.2%}, Top-3 accuracy {top3:.2%}, macro F1 {mf1:.4f}를\n"
        f"  기록했습니다.\n"
        f"  주요 유형인 스미싱의 precision {sm.get('precision',0):.2%},\n"
        f"  recall {sm.get('recall',0):.2%}, F1 {sm.get('f1',0):.4f}였고,\n"
        f"  투자 사기의 precision {inv.get('precision',0):.2%},\n"
        f"  recall {inv.get('recall',0):.2%}, F1 {inv.get('f1',0):.4f}였습니다.\n"
        f"  ※ 건강식품 사기/부동산 사기/납치·협박형은 실제 학습 데이터가\n"
        f"     존재하지 않아 본 분류기에서 제외되었습니다."
    )
    print("=" * 72)


def save_json(metrics: dict, path: Path) -> None:
    def _r(v):
        return round(v, 6) if isinstance(v, float) else v

    out = {
        "model": "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli + LoRA",
        "num_classes": len(metrics["per_label"]),
        "labels": sorted(metrics["per_label"]),
        "split": "stratified 70/15/15 (seed=42)",
        "n_test": metrics["n"],
        "top1_accuracy": _r(metrics["accuracy"]),
        "top3_accuracy": _r(metrics["top3_accuracy"]),
        "macro_f1": _r(metrics["macro_f1"]),
        "weighted_f1": _r(metrics["weighted_f1"]),
        "uncertain_rate": _r(metrics["uncertain_rate"]),
        "per_label": {l: {k: _r(v) for k, v in m.items()} for l, m in metrics["per_label"].items()},
        "confusion_matrix": {t: dict(row) for t, row in metrics["confusion_matrix"].items()},
        "excluded_types": ["건강식품 사기", "부동산 사기", "납치·협박형"],
        "excluded_reason": "실제 학습 데이터 없음 (run_drafts/DB 데이터는 오라벨 확인됨)",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  JSON 저장: {path}")


def save_csv(metrics: dict, path: Path) -> None:
    labels = sorted(metrics["per_label"])
    cm = metrics["confusion_matrix"]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["정답\\예측"] + labels)
        for t in labels:
            writer.writerow([t] + [cm.get(t, {}).get(p, 0) for p in labels])
    print(f"  혼동행렬 CSV: {path}")


# ── 6. active_models.json 업데이트 ─────────────────────────────────────

def update_active_models(ckpt_path: Path) -> None:
    am_path = ROOT / ".scamguardian/active_models.json"
    if not am_path.exists():
        data: dict = {}
    else:
        data = json.loads(am_path.read_text(encoding="utf-8"))

    # 이전 disabled 키 제거
    for key in list(data.keys()):
        if "disabled" in key.lower():
            del data[key]

    data["classifier"] = str(ckpt_path)
    am_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  active_models.json 업데이트: classifier → {ckpt_path}")

    # 캐시 invalidate
    try:
        from pipeline.active_models import invalidate
        invalidate()
    except Exception:
        pass


# ── main ────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--batch-size", type=int, default=8)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--max-length", type=int, default=256)
    ap.add_argument("--lora-r", type=int, default=16)
    ap.add_argument("--bf16", action="store_true", default=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-train", action="store_true", help="기존 ckpt 있으면 학습 skip, test만")
    ap.add_argument("--no-active-update", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [train_scam_type] %(levelname)s: %(message)s",
        stream=sys.stdout,
    )

    # 1. 데이터 수집
    log.info("데이터 수집 시작...")
    all_records = load_all_samples()
    all_records = [r for r in all_records if r["label"] not in EXCLUDED_TYPES]

    # min_per_class 필터
    counts = Counter(r["label"] for r in all_records)
    keep = {l for l, n in counts.items() if n >= MIN_PER_CLASS}
    dropped = sorted(set(counts) - keep)
    if dropped:
        log.warning("샘플 부족(<%d)으로 제외: %s", MIN_PER_CLASS, dropped)
        all_records = [r for r in all_records if r["label"] in keep]

    log.info("최종 학습 가능 유형 %d종, 총 %d건", len(keep), len(all_records))

    # 2. split
    log.info("stratified 70/15/15 split (seed=%d)...", SPLIT_SEED)
    train_recs, val_recs, test_recs = stratified_split_3way(
        all_records, TRAIN_RATIO, VAL_RATIO, SPLIT_SEED,
    )
    print_split_summary(all_records, train_recs, val_recs, test_recs)

    if args.dry_run:
        return 0

    # 3. 학습
    if args.skip_train and CKPT_DIR.exists():
        log.info("--skip-train: 학습 skip, 기존 체크포인트 사용")
        label2id = json.loads((CKPT_DIR / "label2id.json").read_text(encoding="utf-8"))
        id2label = {int(v): k for k, v in label2id.items()}
        best_ckpt = str(CKPT_DIR)
    else:
        train_result = train(
            train_recs, val_recs, CKPT_DIR,
            base_model=BASE_MODEL,
            epochs=args.epochs,
            batch_size=args.batch_size,
            lr=args.lr,
            max_length=args.max_length,
            lora_r=args.lora_r,
            bf16=args.bf16,
        )
        label2id = train_result["label2id"]
        id2label = {int(v): k for k, v in label2id.items()}
        best_ckpt = train_result["best_ckpt"]

    # best checkpoint에서 test 평가
    best_path = Path(best_ckpt)
    if not best_path.exists():
        best_path = CKPT_DIR
    log.info("test 평가: %s", best_path)

    metrics = evaluate_test(test_recs, label2id, id2label, best_path, args.max_length)
    print_report(metrics)
    save_json(metrics, REPORT_JSON)
    save_csv(metrics, REPORT_CSV)

    # 4. active_models 업데이트 (학습 성공 후에만)
    if not args.no_active_update:
        update_active_models(best_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
