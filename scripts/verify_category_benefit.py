"""6-class 이득이 진짜인가 vs 라벨공간이 쉬워진 착시인가 — 공정 검증.

문제: 12-class(9라벨) macro_f1 0.69 vs 6-class(5라벨) 0.88 를 직접 비교하면 불공정하다.
6-class 는 본질적으로 더 쉬운 과제(클래스 적고, 투자↔코인 같은 난해한 구분이 정답으로 흡수됨).

공정 검증: **동일 과제(5 카테고리)·동일 group-split val** 에서
  (A) 12-class 모델 예측 → 카테고리로 collapse  vs  (B) 직접 학습한 6-class 모델
두 방식 모두 같은 5 카테고리를 같은 val 에 예측 → apples-to-apples.
  - B >> A 면: 카테고리 직접 학습이 진짜 이득(경계가 깨끗).
  - B ≈ A 면: 이득은 라벨공간이 쉬워진 것뿐 → 12-class 유지 + 추론 시 collapse 가 동급(세부도 보존).
baseline(무작위·다수클래스)도 함께 — 절대 수준 가늠.

seed-level group split(누수 0), hparam 동일. active_models 미변경.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.group_split_experiment import BASE_MODEL, SEED, group_split, load_records
from scripts.make_category_dataset import SCAM_CATEGORY_MAP


def train_and_predict(train, val, label_field):
    """주어진 라벨필드로 학습 후 val 예측 리스트(문자열) 반환."""
    import numpy as np
    from datasets import Dataset
    from peft import LoraConfig, TaskType, get_peft_model
    from sklearn.metrics import accuracy_score, precision_recall_fscore_support
    from transformers import (
        AutoModelForSequenceClassification, AutoTokenizer, DataCollatorWithPadding,
        EarlyStoppingCallback, Trainer, TrainingArguments,
    )

    labels = sorted({r[label_field] for r in train + val})
    l2i = {l: i for i, l in enumerate(labels)}
    i2l = {i: l for l, i in l2i.items()}
    tok = AutoTokenizer.from_pretrained(BASE_MODEL)

    def mk(rows):
        return Dataset.from_dict({"text": [r["text"] for r in rows],
                                  "label": [l2i[r[label_field]] for r in rows]}).map(
            lambda b: tok(b["text"], truncation=True, max_length=512), batched=True, remove_columns=["text"])

    model = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL, num_labels=len(labels), id2label=i2l, label2id=l2i, ignore_mismatched_sizes=True)
    model = get_peft_model(model, LoraConfig(
        task_type=TaskType.SEQ_CLS, r=16, lora_alpha=32, lora_dropout=0.1, bias="none",
        target_modules=["query_proj", "value_proj", "key_proj", "dense"],
        modules_to_save=["classifier", "pooler"]))

    def met(ep):
        pr = np.argmax(ep.predictions, axis=-1)
        p, r, f, _ = precision_recall_fscore_support(ep.label_ids, pr, average="macro", zero_division=0)
        return {"accuracy": accuracy_score(ep.label_ids, pr), "macro_f1": f}

    args = TrainingArguments(
        output_dir=f"/tmp/verify_{label_field}", num_train_epochs=10, per_device_train_batch_size=7,
        per_device_eval_batch_size=16, learning_rate=2e-5, eval_strategy="epoch", save_strategy="epoch",
        load_best_model_at_end=True, metric_for_best_model="macro_f1", greater_is_better=True,
        seed=SEED, report_to=[], save_total_limit=1, logging_strategy="no", disable_tqdm=True)
    tr = Trainer(model=model, args=args, train_dataset=mk(train), eval_dataset=mk(val),
                 processing_class=tok, data_collator=DataCollatorWithPadding(tok),
                 compute_metrics=met, callbacks=[EarlyStoppingCallback(early_stopping_patience=2)])
    tr.train()
    import numpy as np2
    pred = tr.predict(mk(val))
    return [i2l[int(i)] for i in np2.argmax(pred.predictions, axis=-1)]


def cat_metrics(y_true, y_pred, tag):
    from sklearn.metrics import accuracy_score, classification_report, precision_recall_fscore_support
    labs = sorted(set(y_true) | set(y_pred))
    acc = accuracy_score(y_true, y_pred)
    mp, mr, mf, _ = precision_recall_fscore_support(y_true, y_pred, average="macro", labels=labs, zero_division=0)
    print(f"\n=== [{tag}] (5 카테고리, 동일 val) ===")
    print(f"accuracy={acc:.4f}  macro_f1={mf:.4f}")
    print(classification_report(y_true, y_pred, labels=labs, zero_division=0, digits=4))
    return acc, mf


def main():
    recs = load_records(Path("data/generated/user_samples_augmented.jsonl"))
    vg = group_split(recs, 0.1, SEED)
    train = [r for r in recs if r["group"] not in vg]
    val = [r for r in recs if r["group"] in vg]
    y_true_cat = [r["category"] for r in val]
    print(f"group-split: train {len(train)} / val {len(val)} (누수0)")

    # A) 12-class 학습 → 예측을 카테고리로 collapse
    pred12 = train_and_predict(train, val, "scam_type")
    pred12_cat = [SCAM_CATEGORY_MAP.get(p, p) for p in pred12]
    # B) 6-class 직접 학습
    pred6 = train_and_predict(train, val, "category")

    accA, mfA = cat_metrics(y_true_cat, pred12_cat, "A: 12-class → collapse")
    accB, mfB = cat_metrics(y_true_cat, pred6, "B: 6-class 직접")

    # baseline
    maj = Counter(y_true_cat).most_common(1)[0]
    rand = 1 / len(set(y_true_cat))
    print("\n================ 공정 비교 (5 카테고리 동일 과제) ================")
    print(f"  무작위 baseline acc ≈ {rand:.3f} | 다수클래스 acc = {maj[1]/len(y_true_cat):.3f} ('{maj[0]}')")
    print(f"  A) 12-class→collapse : acc={accA:.4f}  macro_f1={mfA:.4f}")
    print(f"  B) 6-class 직접학습   : acc={accB:.4f}  macro_f1={mfB:.4f}")
    print(f"  Δ(B−A) macro_f1 = {mfB-mfA:+.4f}  → {'6-class 직접 학습이 유의미하게 이득' if mfB-mfA>0.03 else '사실상 동급(라벨공간 효과일 뿐, 12-class 유지+collapse 권장)'}")


if __name__ == "__main__":
    raise SystemExit(main())
