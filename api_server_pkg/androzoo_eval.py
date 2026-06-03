"""AndroZoo 벤치마크 — 무작위 실제 악성 APK 샘플을 받아 *우리 검출 신호 vs vt_detection* 비교.

웹 어드민(/admin/apk-dynamic/androzoo)에서 "악성 샘플 N개 받아 비교" 를 누르면 백그라운드 잡으로:
  1. AndroZoo 리스트 스트리밍 → vt_detection >= min_vt 인 샘플 N개 선별
  2. 각 APK 다운로드 (gitignore data/androzoo/)
  3. apk_analyzer 정적(Lv1) + bytecode(Lv2) 분석 → 검출 flag 수집
  4. AndroZoo vt_detection(70개 백신 합의)과 나란히 비교 + 검출률 요약

Identity Boundary: 검출 신호만 보고. self_signed 단독은 약한 신호이므로 strong(그 외 flag) 도 별도 집계.
호스트에서 APK *실행* 없음 — 정적 읽기만.
"""
from __future__ import annotations

import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import androzoo_client as az

try:  # androguard 의 loguru DEBUG 폭주 억제
    from loguru import logger as _loguru
    _loguru.disable("androguard")
except Exception:  # noqa: BLE001
    pass

router = APIRouter()
_TAG = "Admin — APK Dynamic"

_OUT_DIR = Path("data") / "androzoo" / "malware"
_jobs: dict[str, dict[str, Any]] = {}
_guard = threading.Lock()
_run_lock = threading.Lock()  # 동시 벤치마크 1개 (네트워크/androguard 부하 제한)
_active_id: str | None = None  # 현재 활성 벤치마크 — 새 요청이 이걸 취소하고 대체


def _is_cancelled(bid: str) -> bool:
    with _guard:
        rec = _jobs.get(bid)
        return bool(rec and rec.get("cancelled"))

# self_signed 는 거의 모든 sideload APK 에 떠서 약한 신호 — strong 집계에서 제외.
_WEAK_FLAGS = {"apk_self_signed"}


class BenchmarkRequest(BaseModel):
    count: int = 5
    min_vt: int = 10
    pkg_grep: str | None = None


def _analyze_one(sha256: str, meta: dict) -> dict[str, Any]:
    from pipeline import apk_analyzer as A

    rec: dict[str, Any] = {
        "sha256": sha256,
        "pkg_name": meta.get("pkg_name", ""),
        "vt_detection": meta.get("vt_detection"),
        "apk_size": meta.get("apk_size", ""),
        "static_flags": [],
        "bytecode_flags": [],
        "error": None,
    }
    try:
        path = az.download_apk(sha256, _OUT_DIR)
    except az.AndroZooError as exc:
        rec["error"] = f"다운로드 실패: {exc}"
        return rec
    try:
        st = A.analyze_apk_static(str(path))
        rec["static_flags"] = list(st.detected_flags)
        rec["package_name"] = st.package_name
        rec["is_self_signed"] = st.is_self_signed
        rec["permission_count"] = len(st.permissions)
    except Exception as exc:  # noqa: BLE001
        rec["error"] = f"정적 분석 오류: {exc}"
    try:
        bc = A.analyze_apk_bytecode(str(path))
        rec["bytecode_flags"] = list(bc.detected_flags)
    except Exception as exc:  # noqa: BLE001
        rec["error"] = (rec["error"] or "") + f" bytecode 오류: {exc}"

    all_flags = list(dict.fromkeys(rec["static_flags"] + rec["bytecode_flags"]))
    strong = [f for f in all_flags if f not in _WEAK_FLAGS]
    rec["all_flags"] = all_flags
    rec["detected"] = bool(all_flags)            # 신호 1개 이상
    rec["strong_detected"] = bool(strong)        # self_signed 외 신호

    # VT 패밀리 라벨 (best-effort — 키 없으면 None). "무슨 멀웨어인지" 한 칸.
    try:
        from pipeline import safety
        rec["vt_label"] = safety.family_label_by_sha256(sha256)
    except Exception:  # noqa: BLE001
        rec["vt_label"] = None
    return rec


def _flag_info(flags) -> dict[str, dict[str, str]]:
    """각 flag 의 한글 라벨 + 학술/법적 근거 + 출처 (config 에서)."""
    from pipeline.config import FLAG_LABELS_KO, FLAG_RATIONALE
    info: dict[str, dict[str, str]] = {}
    for f in flags:
        rat = FLAG_RATIONALE.get(f) or {}
        info[f] = {
            "label_ko": FLAG_LABELS_KO.get(f, f),
            "rationale": rat.get("rationale", ""),
            "source": rat.get("source", ""),
        }
    return info


def _summarize(results: list[dict]) -> dict[str, Any]:
    done = [r for r in results if not r.get("error")]
    detected = [r for r in done if r.get("detected")]
    strong = [r for r in done if r.get("strong_detected")]
    freq: dict[str, int] = {}
    for r in done:
        for f in r.get("all_flags", []):
            freq[f] = freq.get(f, 0) + 1
    import os
    n = len(done) or 1
    return {
        "analyzed": len(done),
        "detected": len(detected),
        "strong_detected": len(strong),
        "detection_rate": round(len(detected) / n, 3),
        "strong_detection_rate": round(len(strong) / n, 3),
        "flag_frequency": dict(sorted(freq.items(), key=lambda kv: -kv[1])),
        "flag_info": _flag_info(freq.keys()),
        "vt_enabled": bool(os.getenv("VIRUSTOTAL_API_KEY")),
    }


def _run_benchmark(bid: str, req: BenchmarkRequest) -> None:
    # 앞선(취소된) 벤치마크가 스트리밍을 멈추고 락을 놓을 때까지 대기 후 진행.
    with _run_lock:
        if _is_cancelled(bid):
            _update(bid, status="cancelled", phase="cancelled", message="취소됨")
            return
        try:
            pkg_filters = [p.strip() for p in (req.pkg_grep or "").split(",") if p.strip()]
            _update(bid, phase="sampling", message="AndroZoo 리스트 스트리밍 중… (0행)")

            def _progress(scanned: int, found: int) -> bool:
                if _is_cancelled(bid):
                    return True
                _update(bid, message=f"리스트 스트리밍 중… {scanned:,}행 스캔, {found}개 발견")
                return False

            picked = az.sample_malware(
                req.count, min_vt=req.min_vt, pkg_filters=pkg_filters, progress=_progress
            )
            if _is_cancelled(bid):
                _update(bid, status="cancelled", phase="cancelled", message="취소됨")
                return
            if not picked:
                _update(bid, status="error", phase="error",
                        message="조건에 맞는 악성 샘플을 못 찾았습니다 (min_vt 낮추거나 pkg 필터 완화).")
                return
            _update(bid, phase="analyzing", total=len(picked),
                    message=f"{len(picked)}개 샘플 다운로드 + 분석…")
            results: list[dict] = []
            for i, meta in enumerate(picked):
                if _is_cancelled(bid):
                    _update(bid, status="cancelled", phase="cancelled", message="취소됨")
                    return
                rec = _analyze_one(meta["sha256"], meta)
                results.append(rec)
                _update(bid, results=list(results), done=i + 1,
                        summary=_summarize(results))
            _update(bid, status="done", phase="done",
                    message="완료", results=results, summary=_summarize(results))
        except Exception as exc:  # noqa: BLE001
            _update(bid, status="error", phase="error", message=f"벤치마크 오류: {exc}")


def _update(bid: str, **fields: Any) -> None:
    with _guard:
        rec = _jobs.get(bid)
        if rec is not None:
            rec.update(fields)


def start_benchmark(req: BenchmarkRequest) -> dict[str, Any]:
    global _active_id
    bid = uuid.uuid4().hex[:12]
    rec = {
        "benchmark_id": bid, "status": "running", "phase": "queued",
        "message": "대기 중…", "total": req.count, "done": 0,
        "results": [], "summary": None, "cancelled": False,
        "params": {"count": req.count, "min_vt": req.min_vt, "pkg_grep": req.pkg_grep},
    }
    with _guard:
        # 직전 활성 벤치마크가 아직 돌고 있으면 취소 표시 → 그 스레드가 곧 멈추고 락을 놓는다.
        prev = _jobs.get(_active_id) if _active_id else None
        if prev is not None and prev.get("status") == "running":
            prev["cancelled"] = True
            prev["message"] = "새 벤치마크로 대체됨 (취소 중)…"
        _jobs[bid] = rec
        _active_id = bid
    threading.Thread(target=_run_benchmark, args=(bid, req), daemon=True).start()
    return {"benchmark_id": bid, "status": "running"}


def cancel_active() -> dict[str, Any]:
    """현재 활성 벤치마크를 취소한다 (멈춘 잡 정리용)."""
    with _guard:
        rec = _jobs.get(_active_id) if _active_id else None
        if rec is not None and rec.get("status") == "running":
            rec["cancelled"] = True
            return {"cancelled": True, "benchmark_id": rec["benchmark_id"]}
    return {"cancelled": False}


@router.post(
    "/api/admin/apk-dynamic/androzoo/benchmark",
    tags=[_TAG],
    summary="AndroZoo 무작위 악성 샘플 벤치마크 시작",
    description=(
        "AndroZoo 에서 vt_detection >= `min_vt` 인 실제 악성 APK 를 `count` 개 받아 "
        "정적(Lv1)+bytecode(Lv2) 검출 신호를 추출하고 vt_detection 과 비교한다. "
        "`ANDROZOO_API_KEY` 필요. 결과는 `/benchmark/{id}` 로 폴링."
    ),
)
async def androzoo_benchmark_start(payload: BenchmarkRequest) -> dict[str, Any]:
    try:
        az.api_key()
    except az.AndroZooError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if payload.count < 1 or payload.count > 30:
        raise HTTPException(status_code=400, detail="count 는 1~30 범위여야 합니다.")
    return start_benchmark(payload)


@router.get(
    "/api/admin/apk-dynamic/androzoo/benchmark/{benchmark_id}",
    tags=[_TAG],
    summary="벤치마크 진행/결과 폴링",
)
async def androzoo_benchmark_status(benchmark_id: str) -> dict[str, Any]:
    with _guard:
        rec = _jobs.get(benchmark_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="벤치마크를 찾을 수 없습니다.")
    return rec


@router.post(
    "/api/admin/apk-dynamic/androzoo/benchmark/cancel",
    tags=[_TAG],
    summary="현재 활성 벤치마크 취소 (멈춘 잡 정리)",
)
async def androzoo_benchmark_cancel() -> dict[str, Any]:
    return cancel_active()
