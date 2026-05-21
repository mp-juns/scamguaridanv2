"""DB 의 analysis_runs → 학습용 JSONL 초안 export.

목적: 이미 웹/카카오로 분석된 run 들의 transcript·예측 결과를 JSONL 한 줄씩
초안으로 뽑아, 사람이 content_label·scam_type·sample_kind 만 빠르게 검수·수정한
뒤 training/train_classifier 에 `--extra-jsonl` 로 바로 던질 수 있게 한다.

각 줄 schema:
    {
      "run_id":        analysis_runs.id,
      "text":          transcript_corrected_text or transcript_text,
      "content_label": gate.bucket 이 scam_news_edu 면 'scam_news_edu', 그 외 'undetermined',
      "sample_kind":   "review_needed",
      "scam_type":     classification_scanner.scam_type (예측값 그대로),
      "entities":      entities_predicted [{text, label}] (예측값),
      "risk_flags":    triggered_flags_predicted 중 DETECTED_FLAGS 화이트리스트 통과만,
      "source_ref":    input_source 가 http(s) 면 그 URL, else None,
      "notes":         "needs_human_review"
    }

규칙은 모두 *초안* — 사람이 한 줄씩 보고 content_label / scam_type / sample_kind
를 손으로 정정한다. 초안 단계에서 scam_attempt 로 자동 confirm 하지 않는 이유는
검수자가 scam_type 예측을 *항상* 한 번 검토하게 강제하기 위해서다.

사용:
    python -m scripts.export_runs_to_jsonl_draft
    python -m scripts.export_runs_to_jsonl_draft \
        --output data/run_drafts.jsonl --limit 100 --only-unlabeled
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Iterable

from db import repository
from pipeline.config import DETECTED_FLAGS

DEFAULT_OUTPUT = Path("data/run_drafts.jsonl")
_HTTP_RE = re.compile(r"^https?://", re.IGNORECASE)


def _infer_content_label(metadata: dict[str, Any] | None) -> str:
    """gate.bucket 이 scam_news_edu 일 때만 명시 라벨, 그 외 undetermined.

    scam_attempt / normal / suspicious 도 예측은 있지만 *검수자가 직접 확인하도록*
    초안 단계에선 undetermined 로 둔다 (scam_news_edu 만 거의 자동 confirm 가능한 케이스).
    """
    gate = (metadata or {}).get("gate") or {}
    bucket = str(gate.get("bucket") or "").strip()
    if bucket == "scam_news_edu":
        return "scam_news_edu"
    return "undetermined"


def _source_ref(input_source: str | None) -> str | None:
    """input_source 가 URL 일 때만 source_ref. 텍스트/파일 경로는 None."""
    if not input_source:
        return None
    text = input_source.strip()
    if _HTTP_RE.match(text):
        return text
    return None


def _clean_entities(entities: list[Any] | None) -> list[dict[str, str]]:
    """예측 엔티티에서 {text, label} 만 추출 + 비어있는 항목 제거."""
    out: list[dict[str, str]] = []
    for ent in entities or []:
        if not isinstance(ent, dict):
            continue
        text = str(ent.get("text") or "").strip()
        label = str(ent.get("label") or "").strip()
        if text and label:
            out.append({"text": text, "label": label})
    return out


def _clean_flags(flags: list[Any] | None) -> list[dict[str, str]]:
    """예측 flag 중 DETECTED_FLAGS 화이트리스트만 통과 + 중복 제거."""
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for item in flags or []:
        if isinstance(item, dict):
            flag = str(item.get("flag") or "").strip()
        elif isinstance(item, str):
            flag = item.strip()
        else:
            continue
        if not flag or flag in seen or flag not in DETECTED_FLAGS:
            continue
        seen.add(flag)
        out.append({"flag": flag})
    return out


def build_draft(
    run_id: str,
    run: dict[str, Any],
) -> dict[str, Any] | None:
    """단일 run dict → JSONL 한 줄 dict. transcript 비어 있으면 None."""
    text = (run.get("transcript_corrected_text") or run.get("transcript_text") or "").strip()
    if not text:
        return None
    classification = run.get("classification_scanner") or {}
    scam_type = str(classification.get("scam_type") or "").strip()
    metadata = run.get("metadata") or {}
    return {
        "run_id": str(run_id),
        "text": text,
        "content_label": _infer_content_label(metadata),
        "sample_kind": "review_needed",
        "scam_type": scam_type,
        "entities": _clean_entities(run.get("entities_predicted")),
        "risk_flags": _clean_flags(run.get("triggered_flags_predicted")),
        "source_ref": _source_ref(run.get("input_source")),
        "notes": "needs_human_review",
    }


def _iter_run_ids(
    *,
    only_unlabeled: bool,
    batch_size: int = 200,
) -> Iterable[tuple[str, bool]]:
    """list_runs_for_labeling 으로 페이지네이션 — (run_id, has_annotation) yield."""
    offset = 0
    while True:
        page = repository.list_runs_for_labeling(limit=batch_size, offset=offset)
        if not page:
            break
        for entry in page:
            has_ann = (entry.get("status") or "") == "완료"
            if only_unlabeled and has_ann:
                continue
            yield entry["id"], has_ann
        if len(page) < batch_size:
            break
        offset += batch_size


def export_drafts(
    *,
    output_path: Path,
    limit: int | None = None,
    only_unlabeled: bool = False,
    scam_type_filter: str | None = None,
) -> dict[str, int]:
    """DB 의 run 들을 순회하며 JSONL 초안을 output_path 에 기록.

    Returns: {"written": int, "skipped_empty_text": int, "skipped_filter": int}.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    skipped_empty = 0
    skipped_filter = 0
    with output_path.open("w", encoding="utf-8") as fp:
        for run_id, _has_ann in _iter_run_ids(only_unlabeled=only_unlabeled):
            if limit is not None and written >= limit:
                break
            detail = repository.get_run_detail(run_id)
            if not detail:
                continue
            run = detail.get("run") or {}
            if scam_type_filter:
                predicted = (run.get("classification_scanner") or {}).get("scam_type") or ""
                if str(predicted).strip() != scam_type_filter:
                    skipped_filter += 1
                    continue
            draft = build_draft(run_id, run)
            if draft is None:
                skipped_empty += 1
                continue
            fp.write(json.dumps(draft, ensure_ascii=False) + "\n")
            written += 1
    return {
        "written": written,
        "skipped_empty_text": skipped_empty,
        "skipped_filter": skipped_filter,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"출력 JSONL 경로 (기본 {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="최대 export 건수 (없으면 전체)",
    )
    parser.add_argument(
        "--only-unlabeled",
        action="store_true",
        help="이미 human_annotations 가 있는 run 은 건너뜀",
    )
    parser.add_argument(
        "--scam-type",
        default=None,
        help="예측 scam_type 으로 필터 (예: '대출 사기')",
    )
    args = parser.parse_args()

    stats = export_drafts(
        output_path=args.output,
        limit=args.limit,
        only_unlabeled=args.only_unlabeled,
        scam_type_filter=args.scam_type,
    )
    print(
        f"[export] written={stats['written']}  "
        f"skipped_empty_text={stats['skipped_empty_text']}  "
        f"skipped_filter={stats['skipped_filter']}  → {args.output}"
    )


if __name__ == "__main__":
    main()
