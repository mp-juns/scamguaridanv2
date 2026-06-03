"""어드민 — APK 동적 분석(Lv3) VM 제어 + 분석 콘솔.

`/api/admin/apk-dynamic/` 하위 6개 엔드포인트. `PlatformMiddleware` 가 admin 토큰을 강제한다.
실제 동작은 `apk_dynamic_control` 모듈(= `scripts/apk_dynamic_vm_ctl.sh` 래핑)에 위임.

- VM 라이프사이클: GET /vm, POST /vm/start, POST /vm/stop, GET /ops/{op_id}
- 분석: POST /analyze (APK 업로드), GET /jobs/{job_id}

⚠️ 로컬 실행 HARD BLOCK 유지 — host 에서 APK 를 실행하지 않고, 분석은 격리 remote VM 으로 위임.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from . import apk_dynamic_control as ctl

router = APIRouter()

_TAG = "Admin — APK Dynamic"
_ADMIN_RESPONSES: dict[int | str, dict] = {
    401: {"description": "어드민 토큰 누락 또는 무효"},
    500: {"description": "서버 내부 오류"},
}

_APK_ZIP_MAGIC = b"PK\x03\x04"
_MAX_APK_BYTES = 150 * 1024 * 1024  # 150MB


@router.get(
    "/api/admin/apk-dynamic/vm",
    tags=[_TAG],
    summary="APK 동적 분석 VM 상태",
    description="`vm_ctl.sh status-json` 으로 VM/redroid/frida/server 상태 조회 (VM 을 켜지 않음, 단기 캐시).",
    responses=_ADMIN_RESPONSES,
)
async def apk_dynamic_vm_status(force: bool = False) -> dict[str, Any]:
    return await asyncio.to_thread(ctl.vm_status, force)


@router.post(
    "/api/admin/apk-dynamic/vm/start",
    tags=[_TAG],
    summary="VM 기동",
    description="Multipass VM + redroid + frida-server + apk_dynamic_server + WSL bridge 를 기동한다 (백그라운드 op).",
    responses={**_ADMIN_RESPONSES, 409: {"description": "이미 VM 작업 진행 중"}},
)
async def apk_dynamic_vm_start() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(ctl.start_vm)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/api/admin/apk-dynamic/vm/stop",
    tags=[_TAG],
    summary="VM 정지",
    description="VM 을 정지하고 WSL bridge 를 종료한다 (VM 삭제는 안 함, 백그라운드 op).",
    responses={**_ADMIN_RESPONSES, 409: {"description": "이미 VM 작업 진행 중"}},
)
async def apk_dynamic_vm_stop() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(ctl.stop_vm)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get(
    "/api/admin/apk-dynamic/ops/{op_id}",
    tags=[_TAG],
    summary="VM op 진행 조회",
    description="start/stop op 의 status + 로그 tail 폴링.",
    responses={**_ADMIN_RESPONSES, 404: {"description": "op 없음"}},
)
async def apk_dynamic_op(op_id: str) -> dict[str, Any]:
    op = ctl.get_op(op_id)
    if op is None:
        raise HTTPException(status_code=404, detail="op_id 를 찾을 수 없습니다.")
    return op


@router.post(
    "/api/admin/apk-dynamic/analyze",
    tags=[_TAG],
    summary="APK 업로드 → 동적 분석 잡 시작",
    description=(
        "APK 파일을 multipart 로 업로드받아 분석 잡을 백그라운드로 시작한다.\n\n"
        "- `force_dynamic=false` (기본) — 전체 파이프라인(Lv1 정적 → Lv2 bytecode → Lv3 동적-if-needed).\n"
        "- `force_dynamic=true` — 정적 게이트 우회, VM 동적 분석 직접 실행 (검증/데모).\n\n"
        "VM 이 꺼져 있으면 동적 결과는 `disabled`/`error` 로 온다 — 먼저 `/vm/start` 로 기동."
    ),
    responses={**_ADMIN_RESPONSES, 400: {"description": "APK 아님 / 빈 파일 / 크기 초과"}},
)
async def apk_dynamic_analyze(
    file: UploadFile = File(...),
    force_dynamic: bool = Form(False),
) -> dict[str, Any]:
    if not file.filename:
        raise HTTPException(status_code=400, detail="업로드된 파일 이름이 비어 있습니다.")

    upload_dir = Path(".scamguardian") / "apk_dynamic" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename).suffix or ".apk"
    tmp = tempfile.NamedTemporaryFile(
        mode="wb", delete=False, dir=str(upload_dir), prefix="apk_", suffix=suffix
    )
    tmp_path = Path(tmp.name)
    try:
        total = 0
        first = b""
        with tmp:
            while chunk := await file.read(1024 * 1024):
                if not first:
                    first = chunk[:4]
                total += len(chunk)
                if total > _MAX_APK_BYTES:
                    raise HTTPException(status_code=400, detail="APK 가 150MB 를 초과합니다.")
                tmp.write(chunk)
        if total == 0:
            raise HTTPException(status_code=400, detail="업로드된 파일이 비어 있습니다.")
        if first != _APK_ZIP_MAGIC:
            raise HTTPException(status_code=400, detail="APK(ZIP) 형식이 아닙니다.")
    except HTTPException:
        tmp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001
        tmp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"업로드 처리 실패: {exc}") from exc

    return ctl.start_analysis(
        str(tmp_path), force_dynamic=force_dynamic, apk_name=file.filename
    )


@router.get(
    "/api/admin/apk-dynamic/jobs/{job_id}",
    tags=[_TAG],
    summary="분석 잡 진행/결과 조회",
    description="분석 잡 status + 완료 시 `DetectionReport`(또는 force_dynamic 결과) 폴링.",
    responses={**_ADMIN_RESPONSES, 404: {"description": "job 없음"}},
)
async def apk_dynamic_job(job_id: str) -> dict[str, Any]:
    job = ctl.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job_id 를 찾을 수 없습니다.")
    return job
