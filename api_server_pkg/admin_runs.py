"""어드민 라벨링 큐 + 분석 run 상세 + 미디어 스트리밍 + AI 초안.

엔드포인트:
- /api/admin/runs (목록·search·next)
- /api/admin/runs/{run_id} (상세·claim·annotations·ai-draft·media)
- /api/admin/metrics, /api/admin/stats
- /api/admin/scam-types
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from db import repository
from pipeline import eval as pipeline_eval
from pipeline.config import DEFAULT_SCAM_TYPES

from .common import normalize_catalog_payload, options_payload, require_db
from .models import ClaimRunRequest, HumanAnnotationRequest, ScamTypeCatalogRequest

router = APIRouter()

# 모든 admin 엔드포인트 공통: SCAMGUARDIAN_ADMIN_TOKEN 필요 (PlatformMiddleware 가 게이팅).
# 인증 헤더: `X-Admin-Token: <token>` 또는 `Authorization: Bearer admin-<token>`.
_ADMIN_RESPONSES: dict[int | str, dict] = {
    401: {"description": "어드민 토큰 누락 또는 무효"},
    400: {"description": "DB 미설정 (SCAMGUARDIAN_DATABASE_URL 또는 SQLITE_PATH)"},
    500: {"description": "서버 내부 오류"},
}


@router.get(
    "/api/admin/runs",
    tags=["Admin — Labeling"],
    summary="라벨링 큐 목록",
    description=(
        "라벨링 대기/진행/완료 큐 목록. `claimed_by` 로 누가 작업 중인지 표시.\n\n"
        "**Query**: `status` (in_progress|done|None), `limit` (기본 50), `offset`."
    ),
    responses=_ADMIN_RESPONSES,
)
async def admin_list_runs(
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    try:
        require_db()
        runs = await asyncio.to_thread(
            repository.list_runs_for_labeling,
            limit=limit,
            offset=offset,
            status_filter=status,
        )
        return {"runs": runs, "limit": limit, "offset": offset}
    except EnvironmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/api/admin/runs/{run_id}/claim",
    tags=["Admin — Labeling"],
    summary="run 검수 claim",
    description=(
        "검수자 이름으로 run 을 점유한다. `claimed_by` / `claimed_at` 컬럼 갱신. "
        "TTL 30분 — 다른 검수자가 해당 시간 안에 다시 claim 할 수 없다.\n\n"
        "**Body**: `{labeler: str}` — 빈 문자열이면 `\"Admin\"` 으로 저장.\n\n"
        "**409**: 다른 검수자가 이미 점유 중."
    ),
    responses={**_ADMIN_RESPONSES, 409: {"description": "다른 검수자가 점유 중"}},
)
async def admin_claim_run(run_id: str, payload: ClaimRunRequest) -> dict[str, Any]:
    try:
        require_db()
        labeler = payload.labeler.strip() or "Admin"
        ok = await asyncio.to_thread(repository.claim_run, run_id, labeler)
        if not ok:
            raise HTTPException(status_code=409, detail="다른 검수자가 이미 작업 중입니다.")
        return {"ok": True}
    except EnvironmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/api/admin/runs/search",
    tags=["Admin — Labeling"],
    summary="run 검색 (필터 다중)",
    description=(
        "transcript / scam_type / 라벨 여부로 필터링. "
        "`labeled=true` 면 사람 라벨 있는 것만, `false` 면 미라벨만."
    ),
    responses=_ADMIN_RESPONSES,
)
async def admin_search_runs(
    q: str | None = None,
    scam_type: str | None = None,
    labeled: str | None = None,
    limit: int = 30,
    offset: int = 0,
) -> dict[str, Any]:
    try:
        require_db()
        labeled_bool: bool | None = None
        if labeled == "true":
            labeled_bool = True
        elif labeled == "false":
            labeled_bool = False
        result = await asyncio.to_thread(
            repository.search_runs,
            query=q,
            scam_type=scam_type,
            labeled=labeled_bool,
            limit=limit,
            offset=offset,
        )
        return result
    except EnvironmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/api/admin/runs/next",
    tags=["Admin — Labeling"],
    summary="다음 미라벨 run 자동 할당",
    description="아직 사람 annotation 이 없는 가장 오래된 run 1개. `options` 필드는 분류 라벨/플래그 카탈로그.",
    responses=_ADMIN_RESPONSES,
)
async def admin_next_run() -> dict[str, Any]:
    try:
        require_db()
        run = await asyncio.to_thread(repository.get_next_unannotated_run)
        return {"run": run, "options": options_payload()}
    except EnvironmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/api/admin/runs/{run_id}",
    tags=["Admin — Labeling"],
    summary="run 상세 (라벨링 에디터용)",
    description=(
        "분석 run + 사람 annotation + 사용자 챗봇 컨텍스트 전체. "
        "`metadata.user_context.qa_pairs` (사용자 Q&A) + `metadata.chat_history` (전체 대화) 노출."
    ),
    responses={**_ADMIN_RESPONSES, 404: {"description": "run not found"}},
)
async def admin_run_detail(run_id: str) -> dict[str, Any]:
    try:
        require_db()
        detail = await asyncio.to_thread(repository.get_run_detail, run_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="해당 run을 찾을 수 없습니다.")
        detail["options"] = options_payload()
        return detail
    except HTTPException:
        raise
    except EnvironmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/api/admin/runs/{run_id}/annotations",
    tags=["Admin — Labeling"],
    summary="정답 라벨 저장 (upsert)",
    description=(
        "검수자의 정답 라벨을 저장. 기존 annotation 있으면 덮어쓰기.\n\n"
        "**Body** (`HumanAnnotationRequest`): content_label, scam_type_gt(scam_attempt 일 때만 필수), "
        "entities_gt, triggered_flags_gt, transcript_corrected_text(선택), stt_quality(1~5), notes, "
        "sample_kind, source_ref. content_label 미지정 시 학습 로더가 fallback 적용."
    ),
    responses={**_ADMIN_RESPONSES, 404: {"description": "run not found"}},
)
async def admin_save_annotation(run_id: str, payload: HumanAnnotationRequest) -> dict[str, Any]:
    try:
        require_db()
        run = await asyncio.to_thread(repository.get_run_detail, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="해당 run을 찾을 수 없습니다.")

        labeler = (payload.labeler or "").strip() or "Admin"
        annotation = await asyncio.to_thread(
            repository.upsert_human_annotation,
            run_id=run_id,
            scam_type_gt=payload.scam_type_gt,
            entities_gt=payload.entities_gt,
            triggered_flags_gt=payload.triggered_flags_gt,
            labeler=labeler,
            transcript_corrected_text=payload.transcript_corrected_text,
            stt_quality=payload.stt_quality,
            notes=payload.notes,
            content_label=payload.content_label,
            sample_kind=payload.sample_kind,
            source_ref=payload.source_ref,
        )
        return {"ok": True, "annotation": annotation}
    except HTTPException:
        raise
    except EnvironmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


_MEDIA_MIME_BY_SUFFIX = {
    ".mp4": "video/mp4",
    ".mov": "video/quicktime",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".aac": "audio/aac",
}


_UPLOADS_ROOT = (Path(".scamguardian") / "uploads").resolve()


def _resolve_admin_media_path(stored_path_str: str) -> Path:
    """저장된 미디어 경로가 uploads 디렉토리 안인지 검증 후 반환 (path traversal 방지)."""
    candidate = Path(stored_path_str).resolve()
    try:
        candidate.relative_to(_UPLOADS_ROOT)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="허용되지 않은 경로입니다.") from exc
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="미디어 파일을 찾을 수 없습니다.")
    return candidate


@router.get(
    "/api/admin/runs/{run_id}/media",
    tags=["Admin — Labeling"],
    summary="원본 업로드 파일 스트리밍",
    description=(
        "라벨링 도중 STT 정확도 검증용으로 원본 음성/영상/이미지 파일을 그대로 반환. "
        "path traversal 방지 — `.scamguardian/uploads/` 안 파일만 허용."
    ),
    responses={
        **_ADMIN_RESPONSES,
        400: {"description": "허용되지 않은 경로 (path traversal)"},
        404: {"description": "media 파일 없음"},
    },
)
async def admin_get_media(run_id: str) -> FileResponse:
    """라벨링용으로 보존된 원본 업로드 파일을 스트리밍한다."""
    try:
        require_db()
        detail = await asyncio.to_thread(repository.get_run_detail, run_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="해당 run을 찾을 수 없습니다.")
        media = (detail["run"].get("metadata") or {}).get("media") or {}
        stored = media.get("stored_path")
        if not stored:
            raise HTTPException(status_code=404, detail="저장된 미디어가 없습니다.")
        path = _resolve_admin_media_path(stored)
        suffix = path.suffix.lower()
        media_type = _MEDIA_MIME_BY_SUFFIX.get(suffix, "application/octet-stream")
        filename = media.get("original_filename") or path.name
        return FileResponse(path, media_type=media_type, filename=filename)
    except HTTPException:
        raise
    except EnvironmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/api/admin/metrics",
    tags=["Admin — Labeling"],
    summary="라벨링 품질 메트릭",
    description=(
        "사람 annotation 과 모델 예측 비교 — classification accuracy, entity micro F1, "
        "flag micro F1, per-labeler 통계, needs_review (재검토 권장 run 목록)."
    ),
    responses=_ADMIN_RESPONSES,
)
async def admin_metrics(scam_type: str | None = None) -> dict[str, Any]:
    try:
        require_db()
        records = await asyncio.to_thread(repository.fetch_annotated_pairs, scam_type)
        metrics = pipeline_eval.evaluate_annotated_runs(records)
        metrics["filters"] = {"scam_type": scam_type}
        return metrics
    except EnvironmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/api/admin/runs/{run_id}/ai-draft",
    tags=["Admin — Labeling"],
    summary="Claude 라벨링 초안 생성",
    description=(
        "Claude API 로 사람 라벨 *초안* 을 생성한다. 검수자는 초안 확인 후 수정/승인만. "
        "응답 `draft` 는 `entities/triggered_flags` 에 `source: \"ai-draft\"` 태깅됨."
    ),
    responses={**_ADMIN_RESPONSES, 404: {"description": "run not found"}},
)
async def admin_ai_draft(run_id: str) -> dict[str, Any]:
    """Claude API로 라벨링 초안을 자동 생성. 검수자는 초안 확인 후 수정/승인만."""
    try:
        require_db()
        detail = await asyncio.to_thread(repository.get_run_detail, run_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="해당 run을 찾을 수 없습니다.")

        from pipeline import claude_labeler

        run = detail["run"]
        transcript = run.get("transcript_text", "")
        predicted_scam_type = (run.get("classification_scanner") or {}).get("scam_type", "")
        predicted_entities = run.get("entities_predicted") or []
        predicted_flags = run.get("triggered_flags_predicted") or []

        draft = await asyncio.to_thread(
            claude_labeler.generate_draft,
            transcript,
            predicted_scam_type,
            predicted_entities,
            predicted_flags,
        )
        return {"ok": True, "draft": draft}
    except HTTPException:
        raise
    except EnvironmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/api/admin/stats",
    tags=["Admin — Labeling"],
    summary="대시보드 통계",
    description="총 run 수 / 라벨 진행률 / scam_type 분포 등 대시보드 카운터.",
    responses=_ADMIN_RESPONSES,
)
async def admin_stats() -> dict[str, Any]:
    try:
        require_db()
        stats = await asyncio.to_thread(repository.get_dashboard_stats)
        return stats
    except EnvironmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/api/admin/scam-types",
    tags=["Admin — Labeling"],
    summary="사용자 정의 스캠 유형 목록",
    description="DEFAULT_SCAM_TYPES 12종 외 어드민이 추가한 커스텀 분류 카탈로그.",
    responses=_ADMIN_RESPONSES,
)
async def admin_scam_types() -> dict[str, Any]:
    try:
        require_db()
        items = await asyncio.to_thread(repository.list_custom_scam_types)
        return {"items": items, "options": options_payload()}
    except EnvironmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/api/admin/scam-types",
    tags=["Admin — Labeling"],
    summary="사용자 정의 스캠 유형 추가",
    description=(
        "런타임 분류 카탈로그에 새 scam_type 추가. 기본 12종과 같은 이름은 거절(400). "
        "추가 즉시 `get_runtime_scam_taxonomy()` 에 반영되어 분류기·라벨링 UI 가 인식."
    ),
    responses={**_ADMIN_RESPONSES, 400: {"description": "이름 중복 또는 유효성 실패"}},
)
async def admin_add_scam_type(payload: ScamTypeCatalogRequest) -> dict[str, Any]:
    try:
        require_db()
        normalized = normalize_catalog_payload(payload)
        if not normalized["name"]:
            raise HTTPException(status_code=400, detail="스캠 유형 이름을 입력해주세요.")
        if normalized["name"] in DEFAULT_SCAM_TYPES:
            raise HTTPException(status_code=400, detail="기본 스캠 유형과 같은 이름은 추가할 수 없습니다.")

        item = await asyncio.to_thread(
            repository.upsert_custom_scam_type,
            name=normalized["name"],
            description=normalized["description"],
            labels=normalized["labels"],
        )
        return {"ok": True, "item": item, "options": options_payload()}
    except HTTPException:
        raise
    except EnvironmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
