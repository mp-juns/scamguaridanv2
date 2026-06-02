from __future__ import annotations

from pathlib import Path
from typing import Any

import torch
from sentence_transformers import SentenceTransformer

from db import repository
from pipeline.config import MODELS, RAG_MAX_CASES_IN_PROMPT

_embedding_model: SentenceTransformer | None = None


def _project_hf_cache_dir() -> Path:
    return Path(__file__).resolve().parents[1] / ".cache" / "huggingface"


def _resolve_local_hf_snapshot(model_id: str) -> str | None:
    candidate_roots = [
        _project_hf_cache_dir() / "hub",
        Path.home() / ".cache" / "huggingface" / "hub",
    ]
    for cache_root in candidate_roots:
        model_dir = cache_root / f"models--{model_id.replace('/', '--')}"
        refs_main = model_dir / "refs" / "main"
        if not refs_main.exists():
            continue

        revision = refs_main.read_text().strip()
        snapshot_dir = model_dir / "snapshots" / revision
        if snapshot_dir.exists():
            return str(snapshot_dir)
    return None


def _get_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model_name = MODELS["sbert_similarity"]
        model_source = _resolve_local_hf_snapshot(f"sentence-transformers/{model_name}")
        if model_source:
            _embedding_model = SentenceTransformer(model_source, device=device, local_files_only=True)
        else:
            _embedding_model = SentenceTransformer(
                model_name,
                device=device,
                cache_folder=str(_project_hf_cache_dir()),
            )
    return _embedding_model


def embedding_model_name() -> str:
    return MODELS["sbert_similarity"]


def compute_transcript_embedding(text: str) -> list[float]:
    vector = _get_model().encode(
        text or "",
        normalize_embeddings=True,
    )
    return vector.tolist()


def _summarize_case(case: dict[str, Any]) -> dict[str, Any]:
    entities = case.get("entities_gt", [])[:4]
    flags = case.get("triggered_flags_gt", [])[:4]
    return {
        "run_id": case.get("run_id"),
        "distance": round(float(case.get("distance", 0.0)), 4),
        "scam_type_gt": case.get("scam_type_gt", ""),
        "transcript_excerpt": case.get("transcript_excerpt", ""),
        "entities_gt": entities,
        "triggered_flags_gt": flags,
        "annotation_summary": {
            "entity_labels": [entity.get("label", "") for entity in entities],
            "flags": [flag.get("flag", "") for flag in flags],
        },
    }


def retrieve_similar_runs(
    query_embedding: list[float],
    k: int,
    scam_type: str | None = None,
) -> list[dict[str, Any]]:
    if not repository.database_configured():
        return []
    cases = repository.search_similar_annotated_runs(
        query_embedding,
        limit=max(1, k),
        scam_type=scam_type,
    )
    return [_summarize_case(case) for case in cases[:RAG_MAX_CASES_IN_PROMPT]]
