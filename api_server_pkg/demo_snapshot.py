"""공개 시연 스냅샷 — ML 파트별 데이터·증강·학습 세션 상태 (읽기 전용)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from pipeline import active_models

router = APIRouter()


def _sanitize_session(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": raw.get("session_id") or raw.get("id") or "",
        "status": raw.get("status") or "unknown",
        "model": raw.get("model"),
        "started_at": raw.get("started_at"),
        "ended_at": raw.get("ended_at"),
        "exit_code": raw.get("exit_code"),
    }


def _recent_training(model: str, *, limit: int = 3) -> list[dict[str, Any]]:
    try:
        from training import sessions as ts

        items = ts.list_sessions(limit=50)
        if model == "gate":
            filtered = [s for s in items if s.get("kind") == "gate" or s.get("model") == "gate"]
        else:
            filtered = [s for s in items if s.get("model") == model and s.get("kind") != "gate"]
        return [_sanitize_session(s) for s in filtered[:limit]]
    except Exception:
        return []


def _recent_augment(*, limit: int = 3) -> list[dict[str, Any]]:
    try:
        from training import augment_sessions as aug

        items = aug.list_sessions(limit=limit)
        out: list[dict[str, Any]] = []
        for s in items:
            out.append({
                "id": s.get("session_id") or "",
                "status": s.get("status") or "unknown",
                "seed_file": Path(str(s.get("seed_file") or "")).name,
                "started_at": s.get("started_at"),
                "ended_at": s.get("ended_at"),
            })
        return out
    except Exception:
        return []


def _label_queue() -> dict[str, int]:
    try:
        from db import repository

        if not repository.database_configured():
            return {"pending": 0, "annotated": 0, "total": 0}
        stats = repository.get_dashboard_stats()
        return {
            "pending": int(stats.get("unlabeled_runs") or 0),
            "annotated": int(stats.get("labeled_runs") or 0),
            "total": int(stats.get("total_runs") or 0),
        }
    except Exception:
        return {"pending": 0, "annotated": 0, "total": 0}


def _build_ml_snapshot() -> dict[str, Any]:
    from api_server_pkg.admin_augment import _compute_seed_stats

    seed_stats = _compute_seed_stats()
    gate_seeds = sum((seed_stats.get("by_content_label") or {}).values())
    classifier_data = 0
    gliner_data = 0
    try:
        from training import data as tdata

        classifier_data = len(tdata.load_classifier_dataset())
        gliner_data = len(tdata.load_gliner_dataset())
    except Exception:
        pass

    active = {
        "gate": active_models.get_active_path("gate"),
        "classifier": active_models.get_active_path("classifier"),
        "gliner": active_models.get_active_path("gliner"),
    }

    augment_sessions = _recent_augment(limit=5)

    return {
        "gate": {
            "data_count": gate_seeds,
            "data_label": "씨앗 content_label 합계",
            "augment_sessions": augment_sessions,
            "training_sessions": _recent_training("gate"),
            "active_model_path": active.get("gate"),
            "admin_links": {
                "data": "/admin/browse",
                "augment": "/admin/augment",
                "training": "/admin/training",
            },
        },
        "classifier": {
            "data_count": classifier_data,
            "data_label": "classifier 학습 샘플",
            "augment_sessions": augment_sessions,
            "training_sessions": _recent_training("classifier"),
            "active_model_path": active.get("classifier"),
            "admin_links": {
                "data": "/admin",
                "augment": "/admin/augment",
                "training": "/admin/training",
            },
        },
        "gliner": {
            "data_count": gliner_data,
            "data_label": "GLiNER 학습 샘플",
            "augment_sessions": augment_sessions,
            "training_sessions": _recent_training("gliner"),
            "active_model_path": active.get("gliner"),
            "admin_links": {
                "data": "/admin/browse",
                "augment": "/admin/augment",
                "training": "/admin/training",
            },
        },
        "label_queue": _label_queue(),
        "seed_stats_summary": {
            "total_scam_seeds": seed_stats.get("total"),
            "starved_types": seed_stats.get("starved") or [],
        },
        "runtime_demos": [
            {"id": "live", "title": "실시간 통화 분석", "href": "/demo/live", "badge": "Live v4"},
            {"id": "content", "title": "콘텐츠 분석 (텍스트·URL·파일)", "href": "/demo/content", "badge": "시연"},
            {"id": "apk", "title": "APK 검사 데모", "href": "/demo/apk", "badge": "시연"},
        ],
    }


@router.get(
    "/api/demo/ml-snapshot",
    tags=["Public"],
    summary="시연모드 ML 스냅샷 (읽기 전용)",
    description=(
        "메인 화면 시연모드용 — Gate/Classifier/GLiNER 파트별 데이터·증강·학습 세션 상태. "
        "민감 정보·쓰기 API 없음. 조작은 /admin 링크."
    ),
)
async def demo_ml_snapshot() -> dict[str, Any]:
    return await asyncio.to_thread(_build_ml_snapshot)
