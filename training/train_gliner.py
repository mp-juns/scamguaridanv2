"""
GLiNER 도메인 특화 fine-tuning — 27개 스캠 엔티티 라벨로 `taeminlee/gliner_ko` 를
SFT. 라벨 데이터에 없는 entity 는 학습에서 제외된다.

사용법:
    python -m training.train_gliner \\
        --output-dir checkpoints/gliner-v1 \\
        --epochs 5

데이터 포맷 (GLiNER 표준):
    {"tokenized_text": ["어떤", "단어", ...], "ner": [[start_tok, end_tok, "label"], ...]}

본 스크립트는 character span → token span 변환을 처리한다.
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import shutil
from pathlib import Path

from training.data import (
    GlinerExample,
    load_gliner_dataset,
    train_val_split,
)
from training.sessions import emit_metric

log = logging.getLogger("train_gliner")

DEFAULT_BASE_MODEL = "taeminlee/gliner_ko"


# 한국어/영어/숫자 구분 단순 토크나이저 — GLiNER 학습 포맷에 맞춰 토큰별 character span 유지
_TOKEN_RE = re.compile(r"[가-힣]+|[A-Za-z]+|\d+|[^\s]")


def _tokenize_with_spans(text: str) -> tuple[list[str], list[tuple[int, int]]]:
    tokens: list[str] = []
    spans: list[tuple[int, int]] = []
    for m in _TOKEN_RE.finditer(text):
        tokens.append(m.group(0))
        spans.append((m.start(), m.end()))
    return tokens, spans


def _char_to_token_span(
    char_start: int, char_end: int, token_spans: list[tuple[int, int]],
) -> tuple[int, int] | None:
    start_idx = None
    end_idx = None
    for i, (s, e) in enumerate(token_spans):
        if start_idx is None and s >= char_start:
            start_idx = i
        if e <= char_end:
            end_idx = i
        if s >= char_end:
            break
    if start_idx is None or end_idx is None or end_idx < start_idx:
        return None
    return start_idx, end_idx


def to_gliner_records(examples: list[GlinerExample]) -> list[dict]:
    records: list[dict] = []
    skipped = 0
    for ex in examples:
        tokens, spans = _tokenize_with_spans(ex.text)
        if not tokens:
            skipped += 1
            continue
        ner_tok: list[list] = []
        for cs, ce, label in ex.ner:
            tok_span = _char_to_token_span(cs, ce, spans)
            if tok_span is None:
                continue
            ner_tok.append([tok_span[0], tok_span[1], label])
        if not ner_tok:
            skipped += 1
            continue
        records.append({"tokenized_text": tokens, "ner": ner_tok})
    if skipped:
        log.warning("토큰 변환 실패로 제외된 샘플: %d", skipped)
    return records


def truncate_gliner_records(records: list[dict], max_tokens: int) -> tuple[list[dict], dict[str, int]]:
    if max_tokens <= 0:
        return records, {"truncated": 0, "dropped_examples": 0, "dropped_entities": 0}

    out: list[dict] = []
    truncated = 0
    dropped_examples = 0
    dropped_entities = 0
    for rec in records:
        tokens = rec["tokenized_text"]
        ner = rec["ner"]
        if len(tokens) <= max_tokens:
            out.append(rec)
            continue
        truncated += 1
        kept_ner = [span for span in ner if int(span[1]) < max_tokens]
        dropped_entities += len(ner) - len(kept_ner)
        if not kept_ner:
            dropped_examples += 1
            continue
        out.append({"tokenized_text": tokens[:max_tokens], "ner": kept_ner})
    return out, {
        "truncated": truncated,
        "dropped_examples": dropped_examples,
        "dropped_entities": dropped_entities,
    }


def _link_or_copy(src: Path, dst: Path) -> None:
    if dst.exists() or dst.is_symlink():
        return
    try:
        dst.symlink_to(src)
    except OSError:
        shutil.copy2(src, dst)


def _local_snapshot(repo_or_path: str) -> Path:
    path = Path(repo_or_path).expanduser()
    if path.exists():
        return path.resolve()

    from huggingface_hub import snapshot_download

    return Path(snapshot_download(repo_id=repo_or_path, local_files_only=True)).resolve()


def _prepare_local_base_model(base_model: str, out_path: Path) -> str:
    """Make GLiNER config point at local backbone cache to avoid Hub metadata calls."""
    base_src = _local_snapshot(base_model)
    config_path = base_src / "gliner_config.json"
    if not config_path.exists():
        return str(base_src)

    config = json.loads(config_path.read_text(encoding="utf-8"))
    model_name = str(config.get("model_name") or "")
    if model_name and not Path(model_name).expanduser().exists():
        config["model_name"] = str(_local_snapshot(model_name))

    local_dir = out_path / "_local_base_model"
    local_dir.mkdir(parents=True, exist_ok=True)
    for src in base_src.iterdir():
        dst = local_dir / src.name
        if src.name == "gliner_config.json":
            dst.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
        elif src.is_file():
            _link_or_copy(src.resolve(), dst)
    return str(local_dir.resolve())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-model", default=DEFAULT_BASE_MODEL)
    parser.add_argument("--output-dir", default="checkpoints/gliner-v1")
    parser.add_argument("--extra-jsonl", default=None)
    parser.add_argument("--epochs", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--lr", type=float, default=5e-6)
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--max-types", type=int, default=30, help="문서당 최대 라벨 수")
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=int(os.getenv("SCAMGUARDIAN_GLINER_MAX_TOKENS", "384")),
        help="문서별 tokenized_text 최대 길이. 0 이하면 자르지 않음.",
    )
    parser.add_argument("--max-steps", type=int, default=None, help="GLiNER trainer max_steps override")
    parser.add_argument("--logging-steps", type=int, default=20)
    parser.add_argument("--save-steps", type=int, default=None)
    parser.add_argument("--no-bf16", action="store_true", help="CUDA bf16 자동 사용 비활성화")
    parser.add_argument(
        "--no-gradient-checkpointing",
        action="store_true",
        help="gradient checkpointing 비활성화",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cuda", "cpu"),
        default=os.getenv("SCAMGUARDIAN_GLINER_DEVICE", "auto"),
        help="GLiNER 학습 장치. cuda 는 CUDA 없으면 즉시 실패.",
    )
    parser.add_argument(
        "--local-files-only",
        action="store_true",
        default=os.getenv("SCAMGUARDIAN_HF_LOCAL_ONLY", "").lower() in {"1", "true", "yes"},
        help="HuggingFace Hub HTTP 확인 없이 로컬 캐시/경로만 사용",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    examples = load_gliner_dataset(extra_jsonl=args.extra_jsonl)
    total_entities = sum(len(e.ner) for e in examples)
    labels_seen = sorted({l for ex in examples for _, _, l in ex.ner})
    log.info("총 %d 샘플 (엔티티 합계 %d)", len(examples), total_entities)

    if args.dry_run:
        return

    if len(examples) < 30:
        log.error("샘플이 너무 적습니다(%d < 30). 라벨 더 모아주세요.", len(examples))
        emit_metric({
            "kind": "error",
            "model": "gliner",
            "step": 0,
            "epoch": 0,
            "gliner_progress": 0,
            "train_size": len(examples),
            "entity_count": total_entities,
            "label_count": len(labels_seen),
            "error": "too_few_samples",
        })
        return

    train_ex, val_ex = train_val_split(examples, val_ratio=args.val_ratio, seed=args.seed)
    train_records = to_gliner_records(train_ex)
    val_records = to_gliner_records(val_ex)
    train_records, train_trunc = truncate_gliner_records(train_records, args.max_tokens)
    val_records, val_trunc = truncate_gliner_records(val_records, args.max_tokens)
    if train_trunc["truncated"] or val_trunc["truncated"]:
        log.info(
            "max_tokens=%d 적용: train truncated=%d dropped_examples=%d dropped_entities=%d / "
            "val truncated=%d dropped_examples=%d dropped_entities=%d",
            args.max_tokens,
            train_trunc["truncated"],
            train_trunc["dropped_examples"],
            train_trunc["dropped_entities"],
            val_trunc["truncated"],
            val_trunc["dropped_examples"],
            val_trunc["dropped_entities"],
        )
    log.info("train=%d val=%d", len(train_records), len(val_records))
    emit_metric({
        "kind": "start",
        "model": "gliner",
        "step": 0,
        "epoch": 0,
        "gliner_progress": 0,
        "train_size": len(train_records),
        "val_size": len(val_records),
        "entity_count": total_entities,
        "label_count": len(labels_seen),
        "max_tokens": args.max_tokens,
    })

    out_path = Path(args.output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / "train.json").write_text(
        json.dumps(train_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_path / "val.json").write_text(
        json.dumps(val_records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    emit_metric({
        "kind": "prepared",
        "model": "gliner",
        "step": 1,
        "epoch": 0,
        "gliner_progress": 0.15,
        "train_size": len(train_records),
        "val_size": len(val_records),
        "entity_count": total_entities,
        "label_count": len(labels_seen),
        "max_tokens": args.max_tokens,
    })

    # GLiNER 학습 — 버전별 API 호환
    if args.local_files_only:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    from gliner import GLiNER
    import torch

    base_model = (
        _prepare_local_base_model(args.base_model, out_path)
        if args.local_files_only
        else args.base_model
    )
    model = GLiNER.from_pretrained(
        base_model,
        local_files_only=args.local_files_only,
    )
    if args.device == "cuda":
        if not torch.cuda.is_available():
            emit_metric({
                "kind": "error",
                "model": "gliner",
                "step": 2,
                "epoch": 0,
                "gliner_progress": 0.2,
                "train_size": len(train_records),
                "val_size": len(val_records),
                "entity_count": total_entities,
                "label_count": len(labels_seen),
                "error": "cuda_unavailable",
            })
            log.error("GLiNER device=cuda 로 요청됐지만 torch.cuda.is_available() == False 입니다.")
            raise SystemExit(3)
        model.to("cuda")
        log.info("GLiNER CUDA 학습 장치: %s", torch.cuda.get_device_name(0))
    elif args.device == "auto" and torch.cuda.is_available():
        model.to("cuda")
        log.info("GLiNER CUDA 자동 사용: %s", torch.cuda.get_device_name(0))
    elif args.device == "auto":
        log.warning("CUDA 를 찾지 못해 GLiNER 가 CPU 로 학습됩니다. 웹 세션은 기본적으로 cuda 를 요구합니다.")
    else:
        log.info("GLiNER CPU 학습 모드로 실행합니다.")

    if hasattr(model, "fit"):
        emit_metric({
            "kind": "fit_start",
            "model": "gliner",
            "step": 2,
            "epoch": 0,
            "gliner_progress": 0.2,
            "train_size": len(train_records),
            "val_size": len(val_records),
            "label_count": len(labels_seen),
        })
        model.fit(
            train_records,
            val_data=val_records,
            num_epochs=args.epochs,
            batch_size=args.batch_size,
            lr=args.lr,
            save_path=str(out_path),
        )
        emit_metric({
            "kind": "done",
            "model": "gliner",
            "step": max(3, args.epochs),
            "epoch": args.epochs,
            "gliner_progress": 1,
            "train_size": len(train_records),
            "val_size": len(val_records),
            "label_count": len(labels_seen),
            "epochs": args.epochs,
        })
        log.info("GLiNER 학습 완료 → %s", out_path)
    elif hasattr(model, "train_model"):
        steps_per_epoch = max(1, math.ceil(len(train_records) / max(1, args.batch_size)))
        max_steps = args.max_steps or max(1, steps_per_epoch * max(1, args.epochs))
        save_steps = args.save_steps or max(1, min(max_steps, steps_per_epoch))
        use_bf16 = (
            not args.no_bf16
            and args.device != "cpu"
            and torch.cuda.is_available()
            and torch.cuda.is_bf16_supported()
        )
        use_gradient_checkpointing = (
            not args.no_gradient_checkpointing
            and hasattr(model, "gradient_checkpointing_enable")
        )
        if not args.no_gradient_checkpointing and not use_gradient_checkpointing:
            log.info("GLiNER 모델이 gradient_checkpointing_enable 을 지원하지 않아 비활성화합니다.")
        emit_metric({
            "kind": "train_model_start",
            "model": "gliner",
            "step": 2,
            "epoch": 0,
            "gliner_progress": 0.2,
            "train_size": len(train_records),
            "val_size": len(val_records),
            "entity_count": total_entities,
            "label_count": len(labels_seen),
            "steps_per_epoch": steps_per_epoch,
            "max_steps": max_steps,
            "max_tokens": args.max_tokens,
            "bf16": use_bf16,
            "gradient_checkpointing": use_gradient_checkpointing,
        })
        log.info(
            "GLiNER train_model 시작: max_steps=%d batch_size=%d lr=%g save_steps=%d "
            "bf16=%s gradient_checkpointing=%s save_only_model=True",
            max_steps,
            args.batch_size,
            args.lr,
            save_steps,
            use_bf16,
            use_gradient_checkpointing,
        )
        trainer = model.train_model(
            train_records,
            val_records,
            output_dir=str(out_path),
            learning_rate=args.lr,
            per_device_train_batch_size=args.batch_size,
            per_device_eval_batch_size=args.batch_size,
            max_steps=max_steps,
            save_steps=save_steps,
            logging_steps=max(1, args.logging_steps),
            save_strategy="no",
            save_only_model=True,
            save_total_limit=1,
            report_to="none",
            use_cpu=args.device == "cpu",
            bf16=use_bf16,
            gradient_checkpointing=use_gradient_checkpointing,
            dataloader_pin_memory=args.device != "cpu",
            dataloader_num_workers=0,
        )
        trainer.save_model(str(out_path))
        emit_metric({
            "kind": "done",
            "model": "gliner",
            "step": max_steps,
            "epoch": args.epochs,
            "gliner_progress": 1,
            "train_size": len(train_records),
            "val_size": len(val_records),
            "entity_count": total_entities,
            "label_count": len(labels_seen),
            "epochs": args.epochs,
            "max_steps": max_steps,
        })
        log.info("GLiNER 학습 완료 → %s", out_path)
    else:
        (out_path / "labels.json").write_text(
            json.dumps(labels_seen, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        emit_metric({
            "kind": "trainer_unavailable",
            "model": "gliner",
            "step": 2,
            "epoch": 0,
            "gliner_progress": 0.2,
            "train_size": len(train_records),
            "val_size": len(val_records),
            "entity_count": total_entities,
            "label_count": len(labels_seen),
            "gliner_version": getattr(__import__("gliner"), "__version__", "?"),
        })
        log.warning(
            "현재 GLiNER 버전(%s)에 fit() 메서드가 없습니다. train.json/val.json 만 저장했어요.\n"
            "공식 가이드(https://github.com/urchade/GLiNER#fine-tune-on-your-own-data) 의 "
            "trainer 스크립트를 base_model=%s 로 직접 돌리세요.",
            getattr(__import__("gliner"), "__version__", "?"),
            args.base_model,
        )
        raise SystemExit(2)

    # 추론 시 라벨 후보로 쓰일 unique label 목록도 같이 저장
    (out_path / "labels.json").write_text(
        json.dumps(labels_seen, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("라벨 %d종 저장: %s", len(labels_seen), labels_seen[:8])


if __name__ == "__main__":
    main()
