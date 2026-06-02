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
import re
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
    })

    # GLiNER 학습 — 0.2.x API
    import torch
    from gliner import GLiNER

    model = GLiNER.from_pretrained(args.base_model)

    # GLiNER 학습 API 는 버전마다 약간 다른데 0.2.x 는 model.train(...) 또는
    # 외부 trainer 가 필요. 여기서는 내장 학습 루프가 없으면 JSON 만 저장하고 안내한다.
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
    else:
        emit_metric({
            "kind": "trainer_unavailable",
            "model": "gliner",
            "step": 2,
            "epoch": 0,
            "gliner_progress": 1,
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

    # 추론 시 라벨 후보로 쓰일 unique label 목록도 같이 저장
    (out_path / "labels.json").write_text(
        json.dumps(labels_seen, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("라벨 %d종 저장: %s", len(labels_seen), labels_seen[:8])


if __name__ == "__main__":
    main()
