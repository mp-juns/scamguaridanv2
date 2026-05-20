"""학습 데이터 통계 요약 — content_label / sample_kind / scam_type / 출처별.

CLI 사용:
    python -m training.dataset_summary
    python -m training.dataset_summary --extra-jsonl data/labeling_samples.example.jsonl
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from pipeline.config import CONTENT_LABELS_FOR_GATE_TRAINING
from training.data import (
    NEGATIVE_LABEL,
    _all_content_examples,
)


def summarize_dataset(extra_jsonl: Path | None = None) -> dict[str, Any]:
    """전체 데이터셋 통계.

    Returns:
        {
          "total": int,
          "by_content_label": {label: count},
          "by_sample_kind": {kind: count},
          "by_scam_type_in_scam_attempt": {scam_type: count},  # scam_attempt 만
          "by_source": {"annotation": int, "extra_jsonl": int},
          "excluded_from_training": int,   # suspicious_insufficient + undetermined
        }
    """
    examples = _all_content_examples(extra_jsonl)
    total = len(examples)

    by_content_label = Counter(e.content_label for e in examples)
    by_sample_kind = Counter(e.sample_kind for e in examples)
    by_source = Counter(e.source for e in examples)

    # scam_type 분포는 content_label == scam_attempt 만 (학습 정책과 일치)
    by_scam_type = Counter(
        e.label for e in examples
        if e.content_label == "scam_attempt" and e.label and e.label != NEGATIVE_LABEL
    )

    excluded = sum(
        1 for e in examples
        if e.content_label not in CONTENT_LABELS_FOR_GATE_TRAINING
    )

    return {
        "total": total,
        "by_content_label": dict(by_content_label.most_common()),
        "by_sample_kind": dict(by_sample_kind.most_common()),
        "by_scam_type_in_scam_attempt": dict(by_scam_type.most_common()),
        "by_source": dict(by_source.most_common()),
        "excluded_from_training": excluded,
    }


def format_summary(summary: dict[str, Any]) -> str:
    """사람이 읽을 수 있는 multi-line text."""
    lines: list[str] = []
    lines.append(f"전체 샘플: {summary['total']}")
    lines.append("")
    lines.append("[content_label 별]")
    for label, count in summary["by_content_label"].items():
        lines.append(f"  {count:>5}  {label}")
    lines.append("")
    lines.append("[sample_kind 별]")
    for kind, count in summary["by_sample_kind"].items():
        lines.append(f"  {count:>5}  {kind}")
    lines.append("")
    lines.append("[scam_type 별 — content_label == scam_attempt 만]")
    if summary["by_scam_type_in_scam_attempt"]:
        for st, count in summary["by_scam_type_in_scam_attempt"].items():
            lines.append(f"  {count:>5}  {st}")
    else:
        lines.append("  (없음)")
    lines.append("")
    lines.append("[출처 별]")
    for source, count in summary["by_source"].items():
        lines.append(f"  {count:>5}  {source}")
    lines.append("")
    lines.append(
        f"학습 제외(suspicious_insufficient + undetermined): "
        f"{summary['excluded_from_training']}"
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--extra-jsonl",
        type=Path,
        default=None,
        help="외부 JSONL 파일 경로 (DB + JSONL 합산 집계).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="사람 읽기용 텍스트 대신 JSON 으로 출력.",
    )
    args = parser.parse_args()

    summary = summarize_dataset(extra_jsonl=args.extra_jsonl)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(format_summary(summary))


if __name__ == "__main__":
    main()
