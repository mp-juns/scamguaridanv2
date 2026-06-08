"""seed-level group split 실험 — 누수 없는 정직한 일반화 평가.

같은 seed((source_ref, seed_text))에서 나온 변형은 train/val 에 **동시에 들어가지 않게** 그룹 단위로
분리한 뒤, 12-class(scam_type)와 6-class(scam_category)를 **동일 group split**으로 각각 재학습·평가한다.
기존 stratified(변형 단위) split 의 seed 누수를 제거해, "본 적 없는 seed 의 사기 문구"에 대한 진짜
일반화 성능을 측정한다.

hparam 은 기존 실험과 동일: mDeBERTa-v3-base-mnli-xnli + LoRA, ep10 bs7 lr2e-5 max_len512,
early stopping(patience2, macro_f1). active_models 미변경. 체크포인트는 세션 디렉토리에만 저장.

사용:
  python scripts/group_split_experiment.py --input data/generated/user_samples_augmented.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.make_category_dataset import SCAM_CATEGORY_MAP

BASE_MODEL = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
SEED = 17


def load_records(path: Path) -> list[dict]:
    out = []
    for l in path.read_text(encoding="utf-8").splitlines():
        l = l.strip()
        if not l:
            continue
        o = json.loads(l)
        if o.get("content_label") != "scam_attempt":
            continue
        st = (o.get("scam_type") or "").strip()
        if not st:
            continue
        out.append({
            "text": o.get("text", "").strip(),
            "scam_type": st,
            "category": SCAM_CATEGORY_MAP.get(st, st),
            "group": (o.get("source_ref", ""), (o.get("seed_text") or "").strip()),
        })
    return out


def group_split(records: list[dict], val_ratio: float, seed: int):
    """그룹(seed) 단위 split. scam_type 으로 stratify — 클래스별 그룹의 val_ratio 를 val 로.
    같은 group 의 모든 변형은 한쪽에만 간다. (양쪽 동일 split 재사용 위해 group→side 맵 반환)"""
    rng = random.Random(seed)
    groups_by_type: dict[str, list] = defaultdict(set)
    for r in records:
        groups_by_type[r["scam_type"]].add(r["group"])
    val_groups: set = set()
    for st, gset in groups_by_type.items():
        gs = sorted(gset)
        rng.shuffle(gs)
        n_val = max(1, round(len(gs) * val_ratio)) if len(gs) > 1 else 0
        val_groups.update(gs[:n_val])
    return val_groups


def run_one(records: list[dict], val_groups: set, label_field: str, out_dir: Path, tag: str) -> dict:
    import numpy as np
    import torch
    from datasets import Dataset
    from peft import LoraConfig, TaskType, get_peft_model
    from sklearn.metrics import (
        accuracy_score, classification_report, confusion_matrix,
        precision_recall_fscore_support,
    )
    from transformers import (
        AutoModelForSequenceClassification, AutoTokenizer,
        DataCollatorWithPadding, EarlyStoppingCallback, Trainer, TrainingArguments,
    )

    train = [r for r in records if r["group"] not in val_groups]
    val = [r for r in records if r["group"] in val_groups]
    labels_sorted = sorted({r[label_field] for r in records})
    label2id = {l: i for i, l in enumerate(labels_sorted)}
    id2label = {i: l for l, i in label2id.items()}

    # 누수 0 확인: train/val group 교집합 없어야
    assert not ({r["group"] for r in train} & {r["group"] for r in val}), "group 누수!"
    print(f"\n[{tag}] labels={len(labels_sorted)} | train {len(train)} / val {len(val)} "
          f"| train groups {len({r['group'] for r in train})} / val groups {len(val_groups)}")

    tok = AutoTokenizer.from_pretrained(BASE_MODEL)

    def mk(rows):
        ds = Dataset.from_dict({
            "text": [r["text"] for r in rows],
            "label": [label2id[r[label_field]] for r in rows],
        })
        return ds.map(lambda b: tok(b["text"], truncation=True, max_length=512), batched=True,
                      remove_columns=["text"])

    train_ds, val_ds = mk(train), mk(val)
    model = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL, num_labels=len(label2id), id2label=id2label, label2id=label2id,
        ignore_mismatched_sizes=True,
    )
    model = get_peft_model(model, LoraConfig(
        task_type=TaskType.SEQ_CLS, r=16, lora_alpha=32, lora_dropout=0.1, bias="none",
        target_modules=["query_proj", "value_proj", "key_proj", "dense"],
        modules_to_save=["classifier", "pooler"],
    ))

    def metrics(ep):
        preds = np.argmax(ep.predictions, axis=-1)
        labs = ep.label_ids
        p, r, f, _ = precision_recall_fscore_support(labs, preds, average="macro", zero_division=0)
        return {"accuracy": accuracy_score(labs, preds), "macro_f1": f,
                "macro_precision": p, "macro_recall": r}

    out_dir.mkdir(parents=True, exist_ok=True)
    args = TrainingArguments(
        output_dir=str(out_dir), num_train_epochs=10, per_device_train_batch_size=7,
        per_device_eval_batch_size=16, learning_rate=2e-5, eval_strategy="epoch",
        save_strategy="epoch", load_best_model_at_end=True, metric_for_best_model="macro_f1",
        greater_is_better=True, logging_steps=50, seed=SEED, report_to=[], save_total_limit=1,
    )
    tr = Trainer(model=model, args=args, train_dataset=train_ds, eval_dataset=val_ds,
                 processing_class=tok, data_collator=DataCollatorWithPadding(tok),
                 compute_metrics=metrics, callbacks=[EarlyStoppingCallback(early_stopping_patience=2)])
    tr.train()

    # 최종 평가 (per-label + confusion)
    pred = tr.predict(val_ds)
    y_pred = [id2label[int(i)] for i in np.argmax(pred.predictions, axis=-1)]
    y_true = [r[label_field] for r in val]
    labs = sorted(set(y_true) | set(y_pred))
    acc = accuracy_score(y_true, y_pred)
    mp, mr, mf, _ = precision_recall_fscore_support(y_true, y_pred, average="macro", labels=labs, zero_division=0)
    rep = classification_report(y_true, y_pred, labels=labs, zero_division=0, digits=4)
    cm = confusion_matrix(y_true, y_pred, labels=labs)
    print(f"\n=== [{tag}] group-split 결과 ===")
    print(f"eval_accuracy={acc:.4f}  macro_f1={mf:.4f}  macro_precision={mp:.4f}  macro_recall={mr:.4f}")
    print(rep)
    print("[confusion matrix] (행=true, 열=pred)")
    print("true\\pred".ljust(16) + "".join(f"{l[:7]:>9}" for l in labs))
    for i, l in enumerate(labs):
        print(l[:15].ljust(16) + "".join(f"{cm[i][j]:>9d}" for j in range(len(labs))))
    return {"tag": tag, "accuracy": acc, "macro_f1": mf, "n_val": len(val), "n_labels": len(labels_sorted)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/generated/user_samples_augmented.jsonl")
    ap.add_argument("--val-ratio", type=float, default=0.1)
    args = ap.parse_args()

    records = load_records(Path(args.input))
    val_groups = group_split(records, args.val_ratio, SEED)
    print(f"총 {len(records)} 변형 / {len({r['group'] for r in records})} 그룹(seed) | val 그룹 {len(val_groups)}")

    base = Path(".scamguardian/training_sessions")
    r12 = run_one(records, val_groups, "scam_type", base / "cls12_group_20260608/output", "12-class group")
    r6 = run_one(records, val_groups, "category", base / "cat6_group_20260608/output", "6-class group")
    print("\n================ 요약 ================")
    for r in (r12, r6):
        print(f"  {r['tag']}: acc={r['accuracy']:.4f} macro_f1={r['macro_f1']:.4f} (val {r['n_val']}, {r['n_labels']}라벨)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
