"""Build and query a multi-view RAG index for synthetic ScamGuardian data.

Artifacts:
  data/generated/rag_index/synthetic_multiview_embeddings.npz
  data/generated/rag_index/synthetic_multiview_metadata.jsonl

Each synthetic sample contributes multiple views from rag_texts:
case, scenario, pattern, entity_pattern, evidence_terms.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from pipeline import rag

DEFAULT_INPUT = Path("data/generated/scamguardian_synthetic_3000.jsonl")
DEFAULT_OUTPUT_DIR = Path("data/generated/rag_index")
EMBEDDINGS_FILE = "synthetic_multiview_embeddings.npz"
METADATA_FILE = "synthetic_multiview_metadata.jsonl"
MANIFEST_FILE = "synthetic_multiview_manifest.json"
DEFAULT_VIEWS = ("case", "scenario", "pattern", "entity_pattern", "evidence_terms")
VIEW_WEIGHTS = {
    "case": 1.0,
    "scenario": 0.95,
    "pattern": 0.9,
    "entity_pattern": 0.75,
    "evidence_terms": 0.65,
}
TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def _metadata_for(row: dict[str, Any], view: str, view_text: str) -> dict[str, Any]:
    entity_labels: list[str] = []
    seen_labels: set[str] = set()
    for ent in row.get("entities", []):
        label = str(ent.get("label", ""))
        if label and label not in seen_labels:
            seen_labels.add(label)
            entity_labels.append(label)
    return {
        "synthetic_id": row.get("synthetic_id"),
        "view": view,
        "view_weight": VIEW_WEIGHTS.get(view, 1.0),
        "text": view_text,
        "scam_type": row.get("scam_type"),
        "content_label": row.get("content_label"),
        "source_ref": row.get("source_ref"),
        "template_id": row.get("template_id"),
        "scenario_id": row.get("scenario_id"),
        "scenario_ko": row.get("scenario_ko"),
        "risk_flags": row.get("risk_flags", []),
        "flag_groups": row.get("flag_groups", []),
        "entity_labels": entity_labels,
        "evidence_terms": row.get("rag_texts", {}).get("evidence_terms", ""),
    }


def _flatten_views(
    rows: list[dict[str, Any]],
    views: tuple[str, ...],
) -> tuple[list[str], list[dict[str, Any]]]:
    texts: list[str] = []
    metadata: list[dict[str, Any]] = []
    for row in rows:
        rag_texts = row.get("rag_texts") or {}
        for view in views:
            view_text = str(rag_texts.get(view, "")).strip()
            if not view_text:
                continue
            texts.append(view_text)
            metadata.append(_metadata_for(row, view, view_text))
    return texts, metadata


def _encode(texts: list[str], batch_size: int) -> np.ndarray:
    model = rag._get_model()  # Reuse the project cache/model resolver.
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=True,
        normalize_embeddings=True,
    )
    return np.asarray(vectors, dtype=np.float32)


def build_index(
    *,
    input_path: Path,
    output_dir: Path,
    views: tuple[str, ...],
    batch_size: int,
) -> dict[str, Any]:
    rows = _load_jsonl(input_path)
    texts, metadata = _flatten_views(rows, views)
    if not texts:
        raise ValueError("No rag_texts found to index.")

    embeddings = _encode(texts, batch_size=batch_size)
    if embeddings.shape[0] != len(metadata):
        raise RuntimeError("embedding/metadata length mismatch")

    output_dir.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output_dir / EMBEDDINGS_FILE,
        embeddings=embeddings,
    )
    with (output_dir / METADATA_FILE).open("w", encoding="utf-8") as fp:
        for item in metadata:
            fp.write(json.dumps(item, ensure_ascii=False) + "\n")

    by_view = Counter(item["view"] for item in metadata)
    by_type = Counter(item["scam_type"] for item in metadata)
    manifest = {
        "input": str(input_path),
        "embedding_model": rag.embedding_model_name(),
        "rows": len(rows),
        "vectors": int(embeddings.shape[0]),
        "dimension": int(embeddings.shape[1]),
        "views": list(views),
        "by_view": dict(by_view),
        "by_scam_type": dict(by_type),
        "files": {
            "embeddings": EMBEDDINGS_FILE,
            "metadata": METADATA_FILE,
        },
    }
    (output_dir / MANIFEST_FILE).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def _load_index(index_dir: Path) -> tuple[np.ndarray, list[dict[str, Any]], dict[str, Any]]:
    manifest_path = index_dir / MANIFEST_FILE
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    embeddings = np.load(index_dir / manifest["files"]["embeddings"])["embeddings"]
    metadata = _load_jsonl(index_dir / manifest["files"]["metadata"])
    if embeddings.shape[0] != len(metadata):
        raise RuntimeError("index is corrupt: embedding/metadata length mismatch")
    return embeddings, metadata, manifest


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_RE.findall(text) if len(token) >= 2}


def _lexical_boost(query_tokens: set[str], item: dict[str, Any]) -> float:
    if not query_tokens:
        return 0.0
    haystack = " ".join(
        [
            str(item.get("text") or ""),
            str(item.get("scenario_ko") or ""),
            str(item.get("evidence_terms") or ""),
            " ".join(str(flag) for flag in item.get("risk_flags") or []),
            " ".join(str(group) for group in item.get("flag_groups") or []),
            " ".join(str(label) for label in item.get("entity_labels") or []),
        ]
    )
    overlap = query_tokens & _tokens(haystack)
    return min(0.12, 0.025 * len(overlap))


def query_index(
    *,
    index_dir: Path,
    query: str,
    top_k: int,
    view: str | None = None,
    scam_type: str | None = None,
) -> list[dict[str, Any]]:
    embeddings, metadata, _manifest = _load_index(index_dir)
    query_vec = np.asarray(rag.compute_transcript_embedding(query), dtype=np.float32)
    scores = embeddings @ query_vec
    query_tokens = _tokens(query)

    ranked: list[tuple[float, int]] = []
    for idx, item in enumerate(metadata):
        if view and item.get("view") != view:
            continue
        if scam_type and item.get("scam_type") != scam_type:
            continue
        score = (
            float(scores[idx]) * float(item.get("view_weight") or 1.0)
            + _lexical_boost(query_tokens, item)
        )
        ranked.append((score, idx))
    ranked.sort(reverse=True, key=lambda x: x[0])

    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for score, idx in ranked:
        item = metadata[idx]
        key = str(item.get("synthetic_id") or f"{idx}:{item.get('view')}")
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "score": round(score, 4),
            **item,
        })
        if len(out) >= top_k:
            break
    return out


def cmd_build(args: argparse.Namespace) -> int:
    manifest = build_index(
        input_path=args.input,
        output_dir=args.output_dir,
        views=tuple(args.views.split(",")),
        batch_size=args.batch_size,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def cmd_query(args: argparse.Namespace) -> int:
    rows = query_index(
        index_dir=args.index_dir,
        query=args.query,
        top_k=args.top_k,
        view=args.view,
        scam_type=args.scam_type,
    )
    for i, row in enumerate(rows, 1):
        print(
            f"{i}. score={row['score']:.4f} view={row['view']} "
            f"type={row['scam_type']} scenario={row['scenario_id']}"
        )
        print(f"   {row['text'][:220]}")
        print(f"   flags={', '.join(row.get('risk_flags') or [])}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    build = sub.add_parser("build", help="Build index artifacts.")
    build.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    build.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    build.add_argument("--views", default=",".join(DEFAULT_VIEWS))
    build.add_argument("--batch-size", type=int, default=128)
    build.set_defaults(func=cmd_build)

    query = sub.add_parser("query", help="Query an existing index.")
    query.add_argument("query")
    query.add_argument("--index-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    query.add_argument("--top-k", type=int, default=5)
    query.add_argument("--view", default=None)
    query.add_argument("--scam-type", default=None)
    query.set_defaults(func=cmd_query)

    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
