"""학습된 classifier 체크포인트를 val 세트에서 평가 — per-label P/R/F1 + confusion matrix.

train_classifier 가 내부에서만 내는 macro 지표 외에, 평가에 필요한 **클래스별 지표와
혼동행렬**을 따로 산출한다. val 세트는 train 과 동일한 파이프라인으로 재현한다:
    load_classifier_dataset(extra_jsonl) → _ensure_min_per_class(min) → stratified_split(seed, val_ratio)
→ seed/val_ratio/min 이 같으면 학습 때와 **동일한 held-out val** 이 나온다.

여러 체크포인트를 같은 val 세트에서 평가해 head-to-head 비교가 가능하다.
LoRA 어댑터 체크포인트(adapter_config.json 존재)와 풀 파인튜닝 둘 다 로드한다.

사용:
  python scripts/eval_classifier.py \
    --checkpoint .scamguardian/training_sessions/topup_retrain_20260607/output \
    --extra-jsonl data/generated/user_samples_augmented.jsonl \
    --seed 17 --val-ratio 0.1 --min-per-class 5 --json-out /tmp/eval_new.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _load_val(extra_jsonl: str | None, seed: int, val_ratio: float, min_per_class: int):
    from training.data import load_classifier_dataset, stratified_split
    from training.train_classifier import _ensure_min_per_class

    examples = load_classifier_dataset(extra_jsonl=Path(extra_jsonl) if extra_jsonl else None)
    examples = _ensure_min_per_class(examples, min_per_class)
    _, val = stratified_split(examples, val_ratio=val_ratio, seed=seed)
    return val


def _load_model(checkpoint: Path):
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    label2id = json.loads((checkpoint / "label2id.json").read_text(encoding="utf-8"))
    id2label = {int(v): k for k, v in label2id.items()}
    adapter_cfg = checkpoint / "adapter_config.json"

    if adapter_cfg.exists():
        cfg = json.loads(adapter_cfg.read_text(encoding="utf-8"))
        base = cfg.get("base_model_name_or_path") or "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
        from peft import PeftModel
        base_model = AutoModelForSequenceClassification.from_pretrained(
            base, num_labels=len(label2id), id2label=id2label, label2id=label2id,
            ignore_mismatched_sizes=True,
        )
        model = PeftModel.from_pretrained(base_model, str(checkpoint))
        # 토크나이저는 어댑터 디렉토리에 저장돼 있음 (train_classifier 가 같이 저장)
        tok_src = str(checkpoint) if (checkpoint / "tokenizer_config.json").exists() else base
    else:
        model = AutoModelForSequenceClassification.from_pretrained(str(checkpoint))
        tok_src = str(checkpoint)

    tokenizer = AutoTokenizer.from_pretrained(tok_src)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device).eval()
    return model, tokenizer, id2label, device


def _predict(model, tokenizer, texts: list[str], id2label: dict, device: str, max_length: int, batch_size: int = 16):
    import torch

    preds: list[str] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        enc = tokenizer(batch, truncation=True, max_length=max_length, padding=True, return_tensors="pt").to(device)
        with torch.no_grad():
            logits = model(**enc).logits
        for idx in logits.argmax(dim=-1).tolist():
            preds.append(id2label[int(idx)])
    return preds


def main() -> int:
    p = argparse.ArgumentParser(description="classifier 체크포인트 val 평가 (per-label + confusion)")
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--extra-jsonl", default="data/generated/user_samples_augmented.jsonl")
    p.add_argument("--seed", type=int, default=17)
    p.add_argument("--val-ratio", type=float, default=0.1)
    p.add_argument("--min-per-class", type=int, default=5)
    p.add_argument("--max-length", type=int, default=512)
    p.add_argument("--label", default="", help="이 라벨이면 평가 라벨 공간 고정 (생략 시 val 라벨에서 도출)")
    p.add_argument("--json-out", default="")
    args = p.parse_args()

    from sklearn.metrics import (
        accuracy_score,
        classification_report,
        confusion_matrix,
        precision_recall_fscore_support,
    )

    val = _load_val(args.extra_jsonl, args.seed, args.val_ratio, args.min_per_class)
    y_true = [e.label for e in val]
    texts = [e.text for e in val]
    print(f"val 세트: {len(val)}건 / 라벨 {len(set(y_true))}종 (seed={args.seed}, val_ratio={args.val_ratio}, min_per_class={args.min_per_class})")

    ckpt = Path(args.checkpoint)
    model, tokenizer, id2label, device = _load_model(ckpt)
    y_pred = _predict(model, tokenizer, texts, id2label, device, args.max_length)

    labels = sorted(set(y_true) | set(y_pred))
    acc = accuracy_score(y_true, y_pred)
    mp, mr, mf1, _ = precision_recall_fscore_support(y_true, y_pred, average="macro", labels=labels, zero_division=0)
    report = classification_report(y_true, y_pred, labels=labels, zero_division=0, digits=4)
    report_dict = classification_report(y_true, y_pred, labels=labels, zero_division=0, output_dict=True)
    cm = confusion_matrix(y_true, y_pred, labels=labels)

    print(f"\n=== {ckpt} ===")
    print(f"eval_accuracy={acc:.4f}  macro_f1={mf1:.4f}  macro_precision={mp:.4f}  macro_recall={mr:.4f}")
    print("\n[per-label]")
    print(report)
    print("[confusion matrix] (행=true, 열=pred)")
    hdr = "true\\pred".ljust(14) + "".join(f"{l[:7]:>9}" for l in labels)
    print(hdr)
    for i, l in enumerate(labels):
        print(l[:13].ljust(14) + "".join(f"{cm[i][j]:>9d}" for j in range(len(labels))))

    if args.json_out:
        Path(args.json_out).write_text(json.dumps({
            "checkpoint": str(ckpt), "n_val": len(val),
            "accuracy": acc, "macro_f1": mf1, "macro_precision": mp, "macro_recall": mr,
            "labels": labels, "per_label": report_dict,
            "confusion_matrix": cm.tolist(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\nJSON 저장: {args.json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
