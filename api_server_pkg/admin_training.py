"""어드민 — 학습 세션 관리 (mDeBERTa 분류기 / GLiNER 엔티티)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from .admin_training_compare import (
    CompareAnalysisRequest,
    _compare_analysis,
    _compare_classifier_session,
)
from .admin_training_summary import (
    _latest_synthetic_corpus,
    _synthetic_attempt_summary,
    _synthetic_graph,
)
from .models import StartTrainingRequest

router = APIRouter()

_ADMIN_RESPONSES: dict[int | str, dict] = {
    401: {"description": "어드민 토큰 누락 또는 무효"},
    500: {"description": "서버 내부 오류"},
}


@router.get(
    "/api/admin/training/data-stats",
    tags=["Admin — Training"],
    summary="학습 데이터 통계",
    description="현재 라벨링 데이터 라벨 분포 + 엔티티 수 — 학습 시작 전 충분성 판단용.",
    responses=_ADMIN_RESPONSES,
)
async def admin_training_data_stats() -> dict[str, Any]:
    """현재 라벨링 데이터 통계 — 라벨 분포, 학습 가능 여부."""
    try:
        from training import data as tdata
        cls = await asyncio.to_thread(tdata.load_classifier_dataset)
        extra_path = _latest_synthetic_corpus()
        gli_base = await asyncio.to_thread(tdata.load_gliner_dataset)
        gli = await asyncio.to_thread(tdata.load_gliner_dataset, extra_jsonl=extra_path)
        entity_labels: dict[str, int] = {}
        for example in gli:
            for _, _, label in example.ner:
                entity_labels[label] = entity_labels.get(label, 0) + 1
        return {
            "classifier": {
                "total": len(cls),
                "labels": tdata.label_distribution(cls),
            },
            "gliner": {
                "total": len(gli),
                "base_total": len(gli_base),
                "total_entities": sum(len(e.ner) for e in gli),
                "base_total_entities": sum(len(e.ner) for e in gli_base),
                "labels": dict(sorted(entity_labels.items(), key=lambda item: (-item[1], item[0]))),
                "label_count": len(entity_labels),
                "extra_jsonl": str(extra_path),
            },
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/api/admin/training/synthetic-summary",
    tags=["Admin — Training"],
    summary="synthetic classifier 학습 결과 요약",
    description=(
        "직접 실행한 synthetic classifier 학습 산출물을 스캔해 초심자용 시각화에 필요한 "
        "데이터셋 분포, 시도별 평가 지표, 활성화 보류 이유를 반환한다."
    ),
    responses=_ADMIN_RESPONSES,
)
async def admin_training_synthetic_summary() -> dict[str, Any]:
    try:
        from training import data as tdata
        from training.train_classifier import _ensure_min_per_class

        extra_path = _latest_synthetic_corpus()
        examples = _ensure_min_per_class(
            tdata.load_classifier_dataset(extra_jsonl=extra_path),
            5,
        )
        labels = tdata.label_distribution(examples)

        root = Path(".scamguardian") / "training_sessions"
        attempts: list[dict[str, Any]] = []
        if root.exists():
            for session_dir in sorted(root.glob("synthetic_classifier_*")):
                summary = _synthetic_attempt_summary(session_dir)
                if summary:
                    attempts.append(summary)

        attempts.sort(
            key=lambda item: float(
                (item.get("final_eval") or {}).get("eval_macro_f1") or -1
            ),
            reverse=True,
        )
        best = attempts[0] if attempts else None

        return {
            "dataset": {
                "path": str(extra_path),
                "total": len(examples),
                "labels": labels,
                "label_count": len(labels),
                "min_per_label": min(labels.values()) if labels else 0,
                "max_per_label": max(labels.values()) if labels else 0,
            },
            "graph": _synthetic_graph(extra_path),
            "attempts": attempts,
            "best_attempt": best,
            "status": {
                "headline": "학습과 재로드는 성공, 자동 적용은 보류",
                "activation_ready": False,
                "reason": (
                    "synthetic validation 은 높지만, 실제 운영 문장과 더 비슷한 hard smoke set "
                    "검증이 아직 없어서 active model 로 자동 swap 하지 않았다."
                ),
                "next_step": "실전형 smoke set 100-300개를 만들고 통과 기준을 정한 뒤 적용",
            },
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/api/admin/training/sessions",
    tags=["Admin — Training"],
    summary="fine-tune 세션 시작",
    description=(
        "subprocess 로 학습 세션 spawn — `.scamguardian/training_sessions/{id}/` 에 "
        "`status.json` / `metrics.jsonl` / `train.log` 출력.\n\n"
        "**Body** (`StartTrainingRequest`):\n"
        "- `model` — `classifier` (mDeBERTa) / `gliner` / `gate` (content_label 3-class 평가, 단일 세션)\n"
        "- `models` — `['classifier', 'gliner']` 처럼 보내면 선택된 모델을 각각 학습\n"
        "- `epochs` (기본 3), `batch_size` (기본 8), `lora` (LoRA 사용)\n"
        "- `extra_jsonl` — 추가 데이터셋 경로 (gate 는 평가 입력 JSONL 로 사용)\n"
        "- `val_ratio` (기본 0.1), `seed` (기본 17), `base_model`"
    ),
    responses={**_ADMIN_RESPONSES, 400: {"description": "유효성 실패"}},
)
async def admin_training_start(payload: StartTrainingRequest) -> dict[str, Any]:
    try:
        from training import sessions as tsess
        requested_models = payload.models if payload.models is not None else [payload.model]
        models = []
        for model in requested_models:
            model_name = str(model or "").strip()
            if model_name and model_name not in models:
                models.append(model_name)
        if not models:
            raise ValueError("학습할 모델을 하나 이상 선택해야 합니다.")

        # 순차 학습 기본 순서: classifier 먼저, 그 다음 gliner.
        ordered_models = (
            ["classifier", "gliner"]
            if set(models) == {"classifier", "gliner"}
            else models
        )
        params_list: list[Any] = []
        for model_name in ordered_models:
            params_list.append(tsess.SessionParams(
                model=model_name,
                epochs=payload.epochs,
                batch_size=payload.batch_size,
                lora=payload.lora,
                extra_jsonl=payload.extra_jsonl,
                val_ratio=payload.val_ratio,
                seed=payload.seed,
                base_model=payload.base_model,
                early_stopping_patience=payload.early_stopping_patience,
                early_stopping_threshold=payload.early_stopping_threshold,
            ))

        if len(params_list) == 1:
            return await asyncio.to_thread(tsess.start_session, params_list[0])
        cooldown_seconds = int(__import__("os").getenv("SCAMGUARDIAN_TRAINING_COOLDOWN_SECONDS", "120"))
        return await asyncio.to_thread(
            tsess.start_sequential_sessions,
            params_list,
            cooldown_seconds=cooldown_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/api/admin/training/sessions",
    tags=["Admin — Training"],
    summary="학습 세션 목록 + 활성 모델",
    description="모든 세션 메타 + 현재 파이프라인이 사용하는 active 모델 경로 (`active_models.json`).",
    responses=_ADMIN_RESPONSES,
)
async def admin_training_list(limit: int = 50) -> dict[str, Any]:
    try:
        from training import sessions as tsess
        items = await asyncio.to_thread(tsess.list_sessions, limit)
        return {"sessions": items, "active_models": tsess.get_active_models()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/api/admin/training/sessions/{session_id}",
    tags=["Admin — Training"],
    summary="세션 상세 + metrics tail + log tail",
    description="`session` 메타 + 마지막 500 metric 이벤트 + 마지막 8KB 로그.",
    responses={**_ADMIN_RESPONSES, 404: {"description": "session not found"}},
)
async def admin_training_detail(session_id: str) -> dict[str, Any]:
    try:
        from training import sessions as tsess
        info = await asyncio.to_thread(tsess.get_session, session_id)
        if info is None:
            raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
        metrics = await asyncio.to_thread(tsess.read_metrics, session_id, 500)
        log_tail = await asyncio.to_thread(tsess.read_log_tail, session_id, 8000)
        loss_spikes = await asyncio.to_thread(tsess.read_loss_spikes, session_id, 80)
        return {"session": info, "metrics": metrics, "log_tail": log_tail, "loss_spikes": loss_spikes}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/api/admin/training/sessions/{session_id}/cancel",
    tags=["Admin — Training"],
    summary="학습 세션 취소",
    description="실행 중 subprocess 종료 + status `cancelled` 갱신.",
    responses={**_ADMIN_RESPONSES, 409: {"description": "취소할 수 없는 상태 (이미 끝남)"}},
)
async def admin_training_cancel(session_id: str) -> dict[str, Any]:
    try:
        from training import sessions as tsess
        ok = await asyncio.to_thread(tsess.cancel_session, session_id)
        if not ok:
            raise HTTPException(status_code=409, detail="취소할 수 없는 상태입니다.")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/api/admin/training/sessions/{session_id}/activate",
    tags=["Admin — Training"],
    summary="학습 결과를 파이프라인에 적용",
    description=(
        "체크포인트 경로를 `.scamguardian/active_models.json` 에 기록 → "
        "`pipeline.active_models` 60s TTL 캐시가 무효화되어 즉시 swap.\n\n"
        "분류기 / GLiNER 각 1개씩 활성 가능. 경로 무효 시 base 모델로 fallback."
    ),
    responses={
        **_ADMIN_RESPONSES,
        400: {"description": "유효성 실패 (e.g. 체크포인트 경로 없음)"},
        404: {"description": "session not found 또는 모델 파일 없음"},
    },
)
async def admin_training_activate(session_id: str) -> dict[str, Any]:
    try:
        from training import sessions as tsess
        result = await asyncio.to_thread(tsess.activate_session, session_id)
        return {"ok": True, **result}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/api/admin/training/sessions/{session_id}/compare",
    tags=["Admin — Training"],
    summary="raw classifier 와 fine-tuned classifier 비교",
    description=(
        "완료된 classifier 세션의 output checkpoint 를 로드해, 같은 smoke 문장 세트에서 "
        "raw zero-shot classifier 와 fine-tuned classifier 의 예측을 비교한다."
    ),
    responses={**_ADMIN_RESPONSES, 400: {"description": "비교 불가 세션"}, 404: {"description": "session not found"}},
)
async def admin_training_compare_classifier(session_id: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_compare_classifier_session, session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/api/admin/training/compare-analysis",
    tags=["Admin — Training"],
    summary="입력 기반 모델 비교 분석",
    description=(
        "텍스트나 링크를 받아 같은 transcript 에 대해 기존 raw classifier, Claude/LLM 분석, "
        "fine-tuned classifier checkpoint 결과를 나란히 반환한다."
    ),
    responses={**_ADMIN_RESPONSES, 400: {"description": "비교 요청 오류"}},
)
async def admin_training_compare_analysis(payload: CompareAnalysisRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_compare_analysis, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EnvironmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
