"""
mDeBERTa 스캠 유형 분류기 fine-tuning (LoRA 옵션 지원).

기존 zero-shot NLI 분류기(`MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`) 를 task-specific
multi-class classification 으로 SFT. PEFT/LoRA 적용해서 메모리 효율적으로 학습.

사용법:
    python -m training.train_classifier \\
        --output-dir checkpoints/classifier-v1 \\
        --epochs 3 \\
        --lora

데이터:
    pipeline/eval.py 와 동일한 fetch_annotated_pairs 를 사용. extra_jsonl 로 AI Hub
    데이터를 추가 가능 (정상 콜센터 대화를 negative 로 활용).
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from training.data import (
    NEGATIVE_LABEL,
    ClassifierExample,
    label_distribution,
    load_classifier_dataset,
    stratified_split,
)
from training.sessions import emit_metric

log = logging.getLogger("train_classifier")

DEFAULT_BASE_MODEL = "MoritzLaurer/mDeBERTa-v3-base-mnli-xnli"


def _ensure_min_per_class(examples: list[ClassifierExample], min_count: int) -> list[ClassifierExample]:
    """라벨당 min_count 미만인 샘플은 제외 (학습 안정성)."""
    counts = Counter(e.label for e in examples)
    keep_labels = {label for label, n in counts.items() if n >= min_count}
    dropped = sorted(set(counts) - keep_labels)
    if dropped:
        log.warning("샘플 부족(<%d)으로 제외된 라벨: %s", min_count, dropped)
    return [e for e in examples if e.label in keep_labels]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-model", default=DEFAULT_BASE_MODEL)
    parser.add_argument("--output-dir", default="checkpoints/classifier-v1")
    parser.add_argument("--extra-jsonl", default=None, help="추가 학습 데이터 JSONL")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=2e-5)
    parser.add_argument("--max-length", type=int, default=512)
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument("--min-per-class", type=int, default=5)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--lora", action="store_true", help="PEFT/LoRA 어댑터 적용")
    parser.add_argument("--lora-r", type=int, default=16)
    parser.add_argument("--lora-alpha", type=int, default=32)
    parser.add_argument("--lora-dropout", type=float, default=0.1)
    parser.add_argument("--fp16", action="store_true", help="CUDA mixed precision FP16 사용")
    parser.add_argument("--bf16", action="store_true", help="CUDA mixed precision BF16 사용")
    parser.add_argument("--early-stopping-patience", type=int, default=2, help="eval macro-F1 개선이 멈춘 epoch 허용 횟수. 0 이하면 비활성화")
    parser.add_argument("--early-stopping-threshold", type=float, default=0.0, help="개선으로 인정할 최소 eval macro-F1 증가폭")
    parser.add_argument("--diagnostic-loss-threshold", type=float, default=3.0, help="이 값 이상의 batch loss 는 loss_spikes.jsonl 에 배치 진단을 기록")
    parser.add_argument("--diagnostic-max-records", type=int, default=200, help="한 학습 세션에서 기록할 loss spike 최대 개수")
    parser.add_argument("--no-negatives", action="store_true", help="정상 대화 샘플 제외")
    parser.add_argument("--dry-run", action="store_true", help="데이터 통계만 출력하고 학습 X")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # 1) 데이터 로드 + 통계
    examples = load_classifier_dataset(
        extra_jsonl=args.extra_jsonl,
        include_negatives=not args.no_negatives,
    )
    examples = _ensure_min_per_class(examples, args.min_per_class)

    log.info("총 %d 샘플", len(examples))
    for label, n in label_distribution(examples).items():
        log.info("  %4d | %s", n, label)

    if args.dry_run:
        return

    if len(examples) < 20:
        log.error("샘플이 너무 적습니다(%d < 20). 라벨 더 모아주세요.", len(examples))
        return

    train_examples, val_examples = stratified_split(
        examples, val_ratio=args.val_ratio, seed=args.seed,
    )
    log.info("train=%d val=%d", len(train_examples), len(val_examples))

    # 2) 라벨 인코딩
    labels_sorted = sorted({e.label for e in examples})
    label2id = {label: i for i, label in enumerate(labels_sorted)}
    id2label = {i: label for label, i in label2id.items()}

    # 3) 모델 / 토크나이저 (필요한 시점에만 import — dry-run 빠르게)
    try:
        import torch
        from transformers import (
            AutoModelForSequenceClassification,
            AutoTokenizer,
            DataCollatorWithPadding,
            Trainer,
            TrainingArguments,
        )
        from datasets import Dataset
    except ModuleNotFoundError as exc:
        missing = exc.name or str(exc)
        raise SystemExit(
            f"학습 의존성 '{missing}' 패키지가 현재 Python 환경에 없습니다.\n"
            "다음 명령으로 fine-tuning 전용 의존성을 설치한 뒤 다시 실행하세요:\n"
            "  pip install -r training/requirements-train.txt"
        ) from exc

    tokenizer = AutoTokenizer.from_pretrained(args.base_model)

    def to_hf(examples: list[ClassifierExample]) -> Dataset:
        return Dataset.from_dict({
            "text": [e.text for e in examples],
            "label": [label2id[e.label] for e in examples],
            "example_idx": list(range(len(examples))),
            "text_len": [len(e.text) for e in examples],
        })

    train_ds = to_hf(train_examples)
    val_ds = to_hf(val_examples)
    train_meta: dict[int, dict[str, Any]] = {
        i: {
            "idx": i,
            "label": e.label,
            "source": e.source,
            "content_label": e.content_label,
            "sample_kind": e.sample_kind,
            "run_id": e.run_id,
            "source_ref": e.source_ref,
            "text_len": len(e.text),
            "preview": e.text[:180].replace("\n", " "),
        }
        for i, e in enumerate(train_examples)
    }

    def tokenize(batch):
        return tokenizer(
            batch["text"],
            truncation=True,
            max_length=args.max_length,
            padding=False,
        )

    train_ds = train_ds.map(tokenize, batched=True, remove_columns=["text"])
    val_ds = val_ds.map(tokenize, batched=True, remove_columns=["text"])

    model = AutoModelForSequenceClassification.from_pretrained(
        args.base_model,
        num_labels=len(label2id),
        id2label=id2label,
        label2id=label2id,
        ignore_mismatched_sizes=True,
    )

    # LoRA — 메모리 절약 옵션
    if args.lora:
        from peft import LoraConfig, TaskType, get_peft_model

        lora_cfg = LoraConfig(
            task_type=TaskType.SEQ_CLS,
            r=args.lora_r,
            lora_alpha=args.lora_alpha,
            lora_dropout=args.lora_dropout,
            bias="none",
            target_modules=["query_proj", "value_proj", "key_proj", "dense"],
            modules_to_save=["classifier", "pooler"],
        )
        model = get_peft_model(model, lora_cfg)
        model.print_trainable_parameters()

    # 4) 평가 metric
    def compute_metrics(eval_pred):
        from sklearn.metrics import accuracy_score, f1_score, precision_recall_fscore_support
        preds = np.argmax(eval_pred.predictions, axis=-1)
        labels = eval_pred.label_ids
        prec, rec, f1, _ = precision_recall_fscore_support(
            labels, preds, average="macro", zero_division=0
        )
        return {
            "accuracy": accuracy_score(labels, preds),
            "macro_f1": f1,
            "macro_precision": prec,
            "macro_recall": rec,
        }

    # 5) Trainer + 진행률 콜백 (UI 폴링용 metrics.jsonl 에 기록)
    from transformers import EarlyStoppingCallback, TrainerCallback

    out_path = Path(args.output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    diag_path = out_path / "loss_spikes.jsonl"

    class MetricsEmitCallback(TrainerCallback):
        """매 logging step / eval / epoch 마다 sessions.emit_metric() 으로 기록."""

        def on_log(self, args, state, control, logs=None, **kwargs):
            if not logs:
                return
            emit_metric({
                "kind": "log",
                "step": state.global_step,
                "epoch": state.epoch,
                **{k: v for k, v in logs.items() if isinstance(v, (int, float))},
            })

        def on_evaluate(self, args, state, control, metrics=None, **kwargs):
            if not metrics:
                return
            emit_metric({
                "kind": "eval",
                "step": state.global_step,
                "epoch": state.epoch,
                **{k: v for k, v in metrics.items() if isinstance(v, (int, float))},
            })

        def on_epoch_end(self, args, state, control, **kwargs):
            emit_metric({
                "kind": "epoch_end",
                "step": state.global_step,
                "epoch": state.epoch,
                "max_epoch": args.num_train_epochs,
            })

    class DiagnosticTrainer(Trainer):
        """High-loss batch 를 역추적하기 위한 per-sample 진단을 남긴다."""

        def __init__(self, *trainer_args, **trainer_kwargs):
            super().__init__(*trainer_args, **trainer_kwargs)
            self._diagnostic_records = 0

        def compute_loss(self, model, inputs, return_outputs=False, **kwargs):
            import torch
            import torch.nn.functional as F

            example_idx = inputs.pop("example_idx", None)
            text_len = inputs.pop("text_len", None)
            labels = inputs.get("labels")
            outputs = model(**inputs)
            logits = outputs.logits
            per_sample_loss = F.cross_entropy(logits, labels, reduction="none")
            loss = per_sample_loss.mean()

            should_record = (
                self.model.training
                and args.diagnostic_loss_threshold > 0
                and self._diagnostic_records < args.diagnostic_max_records
                and float(loss.detach().cpu()) >= args.diagnostic_loss_threshold
            )
            if should_record:
                probs = torch.softmax(logits.detach(), dim=-1)
                preds = torch.argmax(probs, dim=-1)
                top_values, top_positions = torch.topk(
                    per_sample_loss.detach(),
                    k=min(3, int(per_sample_loss.numel())),
                )
                example_idx_list = example_idx.detach().cpu().tolist() if example_idx is not None else []
                text_len_list = text_len.detach().cpu().tolist() if text_len is not None else []
                labels_list = labels.detach().cpu().tolist()
                preds_list = preds.detach().cpu().tolist()
                probs_list = probs.detach().cpu().tolist()
                examples_payload: list[dict[str, Any]] = []
                for value, position in zip(top_values.cpu().tolist(), top_positions.cpu().tolist()):
                    idx = int(example_idx_list[position]) if position < len(example_idx_list) else -1
                    gold_id = int(labels_list[position])
                    pred_id = int(preds_list[position])
                    meta = train_meta.get(idx, {"idx": idx})
                    examples_payload.append({
                        **meta,
                        "sample_loss": float(value),
                        "gold_id": gold_id,
                        "gold_label": id2label.get(gold_id, str(gold_id)),
                        "pred_id": pred_id,
                        "pred_label": id2label.get(pred_id, str(pred_id)),
                        "pred_confidence": float(probs_list[position][pred_id]),
                        "batch_text_len": int(text_len_list[position]) if position < len(text_len_list) else None,
                    })
                payload = {
                    "kind": "loss_spike",
                    "model": "classifier",
                    "step": int(self.state.global_step),
                    "epoch": self.state.epoch,
                    "loss": float(loss.detach().cpu()),
                    "max_sample_loss": float(top_values[0].detach().cpu()),
                    "batch_size": int(per_sample_loss.numel()),
                    "learning_rate": self._get_learning_rate(),
                    "examples": examples_payload,
                    "ts": time.time(),
                }
                with diag_path.open("a", encoding="utf-8") as fp:
                    fp.write(json.dumps(payload, ensure_ascii=False) + "\n")
                emit_metric({
                    "kind": "loss_spike",
                    "model": "classifier",
                    "step": payload["step"],
                    "epoch": payload["epoch"],
                    "loss": payload["loss"],
                    "max_sample_loss": payload["max_sample_loss"],
                    "batch_size": payload["batch_size"],
                    "learning_rate": payload["learning_rate"],
                })
                self._diagnostic_records += 1

            return (loss, outputs) if return_outputs else loss

    emit_metric({"kind": "start", "model": "classifier", "labels": labels_sorted, "train_size": len(train_examples), "val_size": len(val_examples)})

    training_args = TrainingArguments(
        output_dir=args.output_dir,
        num_train_epochs=args.epochs,
        per_device_train_batch_size=args.batch_size,
        per_device_eval_batch_size=args.batch_size,
        learning_rate=args.lr,
        eval_strategy="epoch",
        save_strategy="epoch",
        load_best_model_at_end=True,
        metric_for_best_model="macro_f1",
        greater_is_better=True,
        logging_steps=20,
        warmup_ratio=0.06,
        weight_decay=0.01,
        seed=args.seed,
        fp16=args.fp16,
        bf16=args.bf16,
        report_to=["none"],
        remove_unused_columns=False,
    )

    callbacks: list[TrainerCallback] = [MetricsEmitCallback()]
    if args.early_stopping_patience > 0:
        callbacks.append(
            EarlyStoppingCallback(
                early_stopping_patience=args.early_stopping_patience,
                early_stopping_threshold=args.early_stopping_threshold,
            )
        )
        log.info(
            "early stopping 활성화: patience=%d threshold=%s metric=eval_macro_f1",
            args.early_stopping_patience,
            args.early_stopping_threshold,
        )

    trainer = DiagnosticTrainer(
        model=model,
        args=training_args,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        processing_class=tokenizer,
        data_collator=DataCollatorWithPadding(tokenizer),
        compute_metrics=compute_metrics,
        callbacks=callbacks,
    )

    trainer.train()
    metrics = trainer.evaluate()
    log.info("최종 평가: %s", json.dumps(metrics, ensure_ascii=False, indent=2))

    # label2id 같이 저장 — 추론 시 필요
    (out_path / "label2id.json").write_text(
        json.dumps(label2id, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if args.lora and hasattr(trainer.model, "merge_and_unload"):
        (out_path / "adapter").mkdir(parents=True, exist_ok=True)
        trainer.model.save_pretrained(out_path / "adapter")
        merged_model = trainer.model.merge_and_unload()
        merged_model.config.label2id = label2id
        merged_model.config.id2label = id2label
        merged_model.save_pretrained(args.output_dir)
        tokenizer.save_pretrained(args.output_dir)
    else:
        trainer.save_model(args.output_dir)
    emit_metric({"kind": "done", "final_metrics": metrics})
    log.info("저장 완료 → %s", args.output_dir)


if __name__ == "__main__":
    main()
