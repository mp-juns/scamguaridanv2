"""content_label 3-class gate eval — normal / scam_news_edu / scam_attempt.

normal hard negative 추가 효과(특히 FP 억제)를 측정하기 위한 gate. scam_category 가 아니라
**content_label** 을 라벨로 쓴다. `group_split_experiment.py` 와 동일한 group-split(누수 0) 철학.

- 입력: data/generated/user_samples_augmented.jsonl (전체 4,347 — scam_attempt/normal/scam_news_edu)
- group = (source_ref, seed_text) — 같은 seed 변형은 train/val 한쪽에만.
- stratify: content_label 별로 val_ratio 만큼 group 을 val 로.
- active_models 미변경. 체크포인트는 세션 디렉토리에만 저장.

기본 동작(= 검증 only): 데이터 로딩/분포/split/누수/커버리지만 출력하고 **학습하지 않는다**.
실제 학습+평가는 `--train` 플래그가 있을 때만:
  python scripts/content_label_gate.py --input data/generated/user_samples_augmented.jsonl --train

검증만(학습 X):
  python scripts/content_label_gate.py --input data/generated/user_samples_augmented.jsonl
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

BASE_MODEL = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"
SEED = 17
CONTENT_LABELS = ["normal", "scam_attempt", "scam_news_edu"]
# 집중 확인 오류 셀 (true → pred)
WATCH_CELLS = [
    ("normal", "scam_attempt"),       # 정상 → 사기 오탐 (가장 중요: HN 목적)
    ("normal", "scam_news_edu"),       # 정상 → 사기예방 오분류
    ("scam_news_edu", "scam_attempt"), # 사기예방 → 사기 오분류
    ("scam_attempt", "normal"),        # 사기 → 정상 미탐
]


def load_records(path: Path) -> list[dict]:
    out = []
    for l in path.read_text(encoding="utf-8").splitlines():
        l = l.strip()
        if not l:
            continue
        o = json.loads(l)
        cl = (o.get("content_label") or "").strip()
        if cl not in CONTENT_LABELS:
            continue
        out.append({
            "text": (o.get("text") or "").strip(),
            "label": cl,
            "source_ref": o.get("source_ref", ""),
            "group": (o.get("source_ref", ""), (o.get("seed_text") or "").strip()),
            "is_hn": o.get("source_ref", "").startswith("augment_llm/user-normal-hn-")
                     or "user-normal-hn-cj-appdown-url" in o.get("source_ref", ""),
        })
    return out


def group_split(records: list[dict], val_ratio: float, seed: int) -> set:
    """content_label 로 stratify 한 group(seed) 단위 split. 같은 group 은 한쪽에만."""
    rng = random.Random(seed)
    groups_by_label: dict[str, set] = defaultdict(set)
    for r in records:
        groups_by_label[r["label"]].add(r["group"])
    val_groups: set = set()
    for cl, gset in groups_by_label.items():
        gs = sorted(gset)
        rng.shuffle(gs)
        n_val = max(1, round(len(gs) * val_ratio)) if len(gs) > 1 else 0
        val_groups.update(gs[:n_val])
    return val_groups


def verify(records: list[dict], val_groups: set) -> None:
    train = [r for r in records if r["group"] not in val_groups]
    val = [r for r in records if r["group"] in val_groups]
    leak = {r["group"] for r in train} & {r["group"] for r in val}

    print(f"전체 레코드 수 : {len(records)}")
    print(f"고유 group(seed): {len({r['group'] for r in records})}")
    print(f"\n[content_label 분포 — 전체]")
    for cl in CONTENT_LABELS:
        print(f"  {cl:14s} {sum(1 for r in records if r['label']==cl):5d}")
    print(f"\n[train/val 분포]  train {len(train)} / val {len(val)}  | val group {len(val_groups)}")
    for cl in CONTENT_LABELS:
        tr = sum(1 for r in train if r["label"] == cl)
        va = sum(1 for r in val if r["label"] == cl)
        print(f"  {cl:14s} train {tr:5d} / val {va:4d}")
    print(f"\ngroup 누수(train∩val): {len(leak)}  ← 0 이어야")
    assert not leak, "group 누수 발생!"

    val_classes = {r["label"] for r in val}
    print(f"\nval 클래스 커버리지(3개 모두 ≥1): {sorted(val_classes)} → {'OK' if set(CONTENT_LABELS)<=val_classes else '누락!'}")
    for cl in CONTENT_LABELS:
        assert sum(1 for r in val if r["label"] == cl) >= 1, f"{cl} val 0건!"

    # normal hard negative 가 val 에 포함되는지
    hn_total = sum(1 for r in records if r["is_hn"])
    hn_val = sum(1 for r in val if r["is_hn"])
    hn_val_groups = {r["group"] for r in val if r["is_hn"]}
    print(f"\nnormal HN(이번 추가분) — 전체 {hn_total}건 / val {hn_val}건 (val HN seed {len(hn_val_groups)}개)")
    print(f"  val 에 normal HN 포함: {'OK' if hn_val>0 else '없음(seed 조정 필요)'}")
    print(f"\n집중 확인 예정 오류 셀(true→pred): {WATCH_CELLS}")
    print("\n✅ 검증 통과 — 데이터/split 준비 완료. 학습은 --train 으로 실행.")


def run_eval(records: list[dict], val_groups: set, out_dir: Path, epochs: int) -> dict:
    import numpy as np
    from sklearn.metrics import (
        accuracy_score, confusion_matrix, f1_score,
        precision_recall_fscore_support,
    )
    from transformers import (
        AutoModelForSequenceClassification, AutoTokenizer,
        DataCollatorWithPadding, EarlyStoppingCallback, Trainer, TrainingArguments,
    )
    from peft import LoraConfig, TaskType, get_peft_model
    import torch

    labels_sorted = CONTENT_LABELS
    label2id = {l: i for i, l in enumerate(labels_sorted)}
    id2label = {i: l for l, i in label2id.items()}
    train = [r for r in records if r["group"] not in val_groups]
    val = [r for r in records if r["group"] in val_groups]
    assert not ({r["group"] for r in train} & {r["group"] for r in val}), "group 누수!"
    print(f"[content_label] labels={len(labels_sorted)} | train {len(train)} / val {len(val)}")

    tok = AutoTokenizer.from_pretrained(BASE_MODEL)

    def mk(rows):
        from datasets import Dataset
        ds = Dataset.from_dict({
            "text": [r["text"] for r in rows],
            "labels": [label2id[r["label"]] for r in rows],
        })
        return ds.map(lambda b: tok(b["text"], truncation=True, max_length=256), batched=True)

    train_ds, val_ds = mk(train), mk(val)
    model = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL, num_labels=len(label2id), id2label=id2label, label2id=label2id,
        ignore_mismatched_sizes=True,
    )
    model = get_peft_model(model, LoraConfig(
        task_type=TaskType.SEQ_CLS, r=16, lora_alpha=32, lora_dropout=0.1,
        modules_to_save=["classifier", "pooler"],
    ))

    def compute_metrics(ep):
        logits, labs = ep
        preds = np.argmax(logits, axis=-1)
        return {"accuracy": accuracy_score(labs, preds),
                "macro_f1": f1_score(labs, preds, average="macro")}

    args = TrainingArguments(
        output_dir=str(out_dir), num_train_epochs=epochs, per_device_train_batch_size=7,
        per_device_eval_batch_size=16, learning_rate=2e-5, eval_strategy="epoch",
        save_strategy="epoch", load_best_model_at_end=True, metric_for_best_model="macro_f1",
        greater_is_better=True, logging_steps=50, seed=SEED, report_to=[], save_total_limit=1,
    )
    tr = Trainer(model=model, args=args, train_dataset=train_ds, eval_dataset=val_ds,
                 processing_class=tok, data_collator=DataCollatorWithPadding(tok),
                 compute_metrics=compute_metrics,
                 callbacks=[EarlyStoppingCallback(early_stopping_patience=2)])
    tr.train()

    pred = tr.predict(val_ds)
    y_pred = np.argmax(pred.predictions, axis=-1)
    y_true = pred.label_ids
    acc = accuracy_score(y_true, y_pred)
    mf = f1_score(y_true, y_pred, average="macro")
    p, r, f, sup = precision_recall_fscore_support(y_true, y_pred, labels=list(range(len(labels_sorted))), zero_division=0)
    cm = confusion_matrix(y_true, y_pred, labels=list(range(len(labels_sorted))))

    print(f"\n=== content_label gate 결과 ===")
    print(f"accuracy={acc:.4f}  macro_f1={mf:.4f}")
    print(f"\n[per-class precision/recall/F1]")
    print(f"  {'label':14s} {'P':>7} {'R':>7} {'F1':>7} {'support':>8}")
    for i, l in enumerate(labels_sorted):
        print(f"  {l:14s} {p[i]:7.3f} {r[i]:7.3f} {f[i]:7.3f} {int(sup[i]):8d}")
    print(f"\n[confusion matrix] 행=true, 열=pred  순서: {labels_sorted}")
    print(f"  {'':14s}" + "".join(f"{l[:10]:>12}" for l in labels_sorted))
    for i, l in enumerate(labels_sorted):
        print(f"  {l:14s}" + "".join(f"{cm[i][j]:>12}" for j in range(len(labels_sorted))))
    print(f"\n[집중 오류 셀]")
    watch = []
    for t, pr in WATCH_CELLS:
        ti, pi = label2id[t], label2id[pr]
        denom = int(cm[ti].sum())
        rate = (cm[ti][pi] / denom) if denom else 0.0
        print(f"  {t:14s} → {pr:14s}: {cm[ti][pi]:4d} / {denom} ({rate*100:.1f}%)")
        watch.append({"true": t, "pred": pr, "count": int(cm[ti][pi]), "denom": denom, "rate": float(rate)})
    return {
        "accuracy": float(acc),
        "macro_f1": float(mf),
        "labels": labels_sorted,
        "per_class": {l: {"precision": float(p[i]), "recall": float(r[i]),
                          "f1": float(f[i]), "support": int(sup[i])}
                      for i, l in enumerate(labels_sorted)},
        "confusion": [[int(x) for x in row] for row in cm],
        "watch_cells": watch,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="content_label 3-class gate eval")
    ap.add_argument("--input", default="data/generated/user_samples_augmented.jsonl")
    ap.add_argument("--val-ratio", type=float, default=0.1)
    ap.add_argument("--seed", type=int, default=SEED)
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--train", action="store_true", help="실제 학습+평가 실행(기본은 검증 only)")
    ap.add_argument("--session-id", default="content_label_gate_20260610",
                    help="게이트 세션 디렉토리 이름 (이전 실행 보존하려면 새 값)")
    args = ap.parse_args()

    records = load_records(Path(args.input))
    val_groups = group_split(records, args.val_ratio, args.seed)
    if not args.train:
        verify(records, val_groups)
        return 0
    verify(records, val_groups)
    import time
    session_id = args.session_id
    out_dir = Path(f".scamguardian/training_sessions/{session_id}/output")
    out_dir.mkdir(parents=True, exist_ok=True)
    started = time.time()
    metrics = run_eval(records, val_groups, out_dir, args.epochs)
    # 게이트(평가 전용) 세션으로 어드민 training 페이지에 등록 (적용 불가, kind=gate)
    try:
        from training import sessions as tsess
        tsess.record_gate_session(
            session_id,
            gate_name="gate · content_label 3-class",
            params={"input": args.input, "val_ratio": args.val_ratio, "seed": args.seed,
                    "epochs": args.epochs, "base_model": BASE_MODEL, "labels": CONTENT_LABELS},
            metrics=metrics,
            started_at=started,
            output_dir=str(out_dir),
        )
        print(f"\n[gate 세션 등록됨] /admin/training 목록에 '{session_id}' (kind=gate) 노출")
    except Exception as exc:
        print(f"⚠️ 게이트 세션 등록 실패(평가 결과는 위 출력 참조): {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
