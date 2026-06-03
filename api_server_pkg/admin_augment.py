"""어드민 — 데이터 증강 세션 + 씨앗 작성.

씨앗 유형 커버리지 갭(굶은 유형)을 관리자가 씨앗을 직접 작성해 보강하고,
Claude 로 병렬 증강한다. training 세션 라우터(`admin_training.py`)의 미러.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from pipeline.config import CONTENT_LABELS, DEFAULT_SCAM_TYPES, GATE_SCAM_ATTEMPT
from .models import AugmentStartRequest, SeedCreateRequest

router = APIRouter()

_ADMIN_RESPONSES: dict[int | str, dict] = {
    401: {"description": "어드민 토큰 누락 또는 무효"},
    500: {"description": "서버 내부 오류"},
}

SEED_DIR = Path("data") / "processed"
ADMIN_SEEDS = SEED_DIR / "admin_seeds.jsonl"
_STARVED_THRESHOLD = 3   # 씨앗 ≤3개 유형은 "굶은" 것으로 표시


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def _compute_seed_stats() -> dict[str, Any]:
    """data/processed/*.jsonl 의 scam_attempt 씨앗을 유형별 카운트 (12종 0 초기화)."""
    by_type: dict[str, int] = {t: 0 for t in DEFAULT_SCAM_TYPES}
    total = 0
    SEED_DIR.mkdir(parents=True, exist_ok=True)
    for jsonl_file in sorted(SEED_DIR.glob("*.jsonl")):
        for rec in _read_jsonl(jsonl_file):
            if (rec.get("content_label") or "") != GATE_SCAM_ATTEMPT:
                continue
            st = (rec.get("scam_type") or "").strip()
            if st in by_type:
                by_type[st] += 1
                total += 1
    starved = [t for t in DEFAULT_SCAM_TYPES if by_type[t] <= _STARVED_THRESHOLD]
    return {
        "scam_types": list(DEFAULT_SCAM_TYPES),
        "by_scam_type": by_type,
        "starved": starved,
        "starved_threshold": _STARVED_THRESHOLD,
        "total": total,
    }


# ── 씨앗 통계 ────────────────────────────────────────────────────
@router.get(
    "/api/admin/augment/seed-stats",
    tags=["Admin — Augment"],
    summary="씨앗 유형별 분포 + 커버리지 갭",
    description="data/processed 씨앗을 scam_type 별로 집계 — 굶은 유형(≤3) 노출.",
    responses=_ADMIN_RESPONSES,
)
async def augment_seed_stats() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_compute_seed_stats)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── 씨앗 CRUD ────────────────────────────────────────────────────
@router.get(
    "/api/admin/augment/seeds",
    tags=["Admin — Augment"],
    summary="관리자 작성 씨앗 목록",
    responses=_ADMIN_RESPONSES,
)
async def augment_seeds_list() -> dict[str, Any]:
    try:
        rows = await asyncio.to_thread(_read_jsonl, ADMIN_SEEDS)
        seeds = [{"idx": i, **r} for i, r in enumerate(rows)]
        return {"seeds": seeds, "path": str(ADMIN_SEEDS)}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _append_seed(payload: SeedCreateRequest) -> dict[str, Any]:
    text = (payload.text or "").strip()
    if not text:
        raise ValueError("씨앗 text 가 비어 있습니다.")
    scam_type = (payload.scam_type or "").strip()
    if scam_type not in DEFAULT_SCAM_TYPES:
        raise ValueError(f"scam_type 은 다음 중 하나여야 합니다: {DEFAULT_SCAM_TYPES}")
    content_label = (payload.content_label or GATE_SCAM_ATTEMPT).strip()
    if content_label not in CONTENT_LABELS:
        raise ValueError(f"content_label 은 다음 중 하나여야 합니다: {CONTENT_LABELS}")
    rec = {
        "text": text,
        "content_label": content_label,
        "scam_type": scam_type,
        "sample_kind": "manual_seed",
        "source_ref": "admin-ui",
    }
    ADMIN_SEEDS.parent.mkdir(parents=True, exist_ok=True)
    with ADMIN_SEEDS.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


@router.post(
    "/api/admin/augment/seeds",
    tags=["Admin — Augment"],
    summary="씨앗 1개 추가 (굶은 유형 보강)",
    responses={**_ADMIN_RESPONSES, 400: {"description": "유효성 실패"}},
)
async def augment_seeds_create(payload: SeedCreateRequest) -> dict[str, Any]:
    try:
        rec = await asyncio.to_thread(_append_seed, payload)
        return {"ok": True, "seed": rec}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _delete_seed(idx: int) -> bool:
    rows = _read_jsonl(ADMIN_SEEDS)
    if idx < 0 or idx >= len(rows):
        return False
    del rows[idx]
    with ADMIN_SEEDS.open("w", encoding="utf-8") as fp:
        for r in rows:
            fp.write(json.dumps(r, ensure_ascii=False) + "\n")
    return True


@router.delete(
    "/api/admin/augment/seeds/{idx}",
    tags=["Admin — Augment"],
    summary="작성 씨앗 삭제",
    responses={**_ADMIN_RESPONSES, 404: {"description": "씨앗 인덱스 없음"}},
)
async def augment_seeds_delete(idx: int) -> dict[str, Any]:
    try:
        ok = await asyncio.to_thread(_delete_seed, idx)
        if not ok:
            raise HTTPException(status_code=404, detail="해당 씨앗을 찾을 수 없습니다.")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── 증강 세션 ────────────────────────────────────────────────────
@router.post(
    "/api/admin/augment/sessions",
    tags=["Admin — Augment"],
    summary="증강 세션 시작 (병렬)",
    description=(
        "subprocess 로 `scripts.run_augment_session` spawn — "
        "`.scamguardian/augmentation_sessions/{id}/` 에 status/metrics/run.log/output.jsonl 출력."
    ),
    responses={**_ADMIN_RESPONSES, 400: {"description": "유효성 실패"}},
)
async def augment_start(payload: AugmentStartRequest) -> dict[str, Any]:
    try:
        from training import augment_sessions as asess
        seed_file = (payload.seed_file or str(ADMIN_SEEDS)).strip()
        params = asess.AugmentParams(
            seed_file=seed_file,
            variants=payload.variants,
            rounds=payload.rounds,
            model=payload.model,
            concurrency=payload.concurrency,
            limit=payload.limit,
            scam_type=payload.scam_type,
        )
        return await asyncio.to_thread(asess.start_session, params)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/api/admin/augment/sessions",
    tags=["Admin — Augment"],
    summary="증강 세션 목록",
    responses=_ADMIN_RESPONSES,
)
async def augment_list(limit: int = 50) -> dict[str, Any]:
    try:
        from training import augment_sessions as asess
        items = await asyncio.to_thread(asess.list_sessions, limit)
        return {"sessions": items}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/api/admin/augment/sessions/{session_id}",
    tags=["Admin — Augment"],
    summary="증강 세션 상세 + metrics + log tail",
    responses={**_ADMIN_RESPONSES, 404: {"description": "session not found"}},
)
async def augment_detail(session_id: str) -> dict[str, Any]:
    try:
        from training import augment_sessions as asess
        info = await asyncio.to_thread(asess.get_session, session_id)
        if info is None:
            raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
        metrics = await asyncio.to_thread(asess.read_metrics, session_id, 500)
        log_tail = await asyncio.to_thread(asess.read_log_tail, session_id, 8000)
        return {"session": info, "metrics": metrics, "log_tail": log_tail}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/api/admin/augment/sessions/{session_id}/cancel",
    tags=["Admin — Augment"],
    summary="증강 세션 취소",
    responses={**_ADMIN_RESPONSES, 409: {"description": "취소할 수 없는 상태"}},
)
async def augment_cancel(session_id: str) -> dict[str, Any]:
    try:
        from training import augment_sessions as asess
        ok = await asyncio.to_thread(asess.cancel_session, session_id)
        if not ok:
            raise HTTPException(status_code=409, detail="취소할 수 없는 상태입니다.")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/api/admin/augment/sessions/{session_id}/promote",
    tags=["Admin — Augment"],
    summary="증강 산출물을 학습 데이터로 내보내기",
    description="세션 output.jsonl 을 data/generated/{target}.jsonl 로 병합 → training extra_jsonl 로 사용.",
    responses={**_ADMIN_RESPONSES, 400: {"description": "내보낼 수 없는 상태"}, 404: {"description": "session not found"}},
)
async def augment_promote(session_id: str, target: str = "user_samples_augmented") -> dict[str, Any]:
    try:
        from training import augment_sessions as asess
        result = await asyncio.to_thread(asess.promote_output, session_id, target)
        return {"ok": True, **result}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
