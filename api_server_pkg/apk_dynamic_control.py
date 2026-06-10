"""APK 동적 분석(Lv3) VM 라이프사이클 + 분석 잡 컨트롤러.

`scripts/apk_dynamic_vm_ctl.sh` 를 subprocess 로 래핑한다 (WSL + Windows Multipass 전제).

설계:
- VM op(start/stop) 은 백그라운드 스레드 + 파일 로그(.scamguardian/apk_dynamic/ops/{id}.log)
  + in-memory 상태로 추적한다 (training/sessions.py 의 파일기반 진행 패턴과 동형).
- 동시 VM op 는 전역 락으로 1개만 허용한다.
- status 는 `vm_ctl.sh status-json` 호출 → JSON 파싱 + 단기 캐시(VM 을 켜지 않음).
- VM start 성공 시 `apk_analyzer.configure_remote()` 로 모듈 상수를 주입 → 서버 재시작 없이
  즉시 remote 동적 분석 가능. stop 시 enabled=False 로 되돌린다.
- 분석 잡은 백그라운드 스레드에서 `ScamGuardianPipeline.analyze()`(전체 tier) 또는
  `apk_analyzer.analyze_apk_dynamic()`(동적 강제) 을 실행한다.

⚠️ 로컬 실행 HARD BLOCK 은 `apk_analyzer` 레벨에서 그대로 유지된다 — 이 컨트롤러는 host 에서
APK 를 절대 실행하지 않는다. 분석은 항상 격리 remote VM 으로 위임된다.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from pipeline import apk_analyzer

ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPT = ROOT_DIR / "scripts" / "apk_dynamic_vm_ctl.sh"
OPS_DIR = ROOT_DIR / ".scamguardian" / "apk_dynamic" / "ops"

REMOTE_URL = (os.getenv("APK_DYNAMIC_REMOTE_URL", "").strip().rstrip("/")
              or "http://127.0.0.1:18002")
REMOTE_TOKEN = (
    os.getenv("APK_DYNAMIC_REMOTE_TOKEN")
    or os.getenv("APK_DYNAMIC_SERVER_TOKEN")
    or "dev-secret-123"
).strip()

VALID_OPS = ("start", "stop")
_STATUS_TIMEOUT = 30          # status-json subprocess timeout (초)
_STATUS_CACHE_TTL = 8.0       # status 캐시 수명 (초)
_FALSE_STATUS = {
    "vm_running": False,
    "redroid_booted": False,
    "frida_running": False,
    "server_up": False,
    "remote_url": REMOTE_URL,
}

_op_lock = threading.Lock()                     # VM op 동시 1개 보장
_ops: dict[str, dict[str, Any]] = {}
_ops_guard = threading.Lock()

_jobs: dict[str, dict[str, Any]] = {}
_jobs_guard = threading.Lock()

_status_cache: dict[str, Any] = {"at": 0.0, "value": None}
_status_guard = threading.Lock()

_pipeline = None
_pipeline_lock = threading.Lock()


def _now() -> float:
    return time.time()


def _tail(path: Path, max_bytes: int = 16000) -> str:
    try:
        data = path.read_bytes()
    except OSError:
        return ""
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    return data.decode("utf-8", errors="replace")


# ──────────────────────────────────────────────
# VM 상태
# ──────────────────────────────────────────────
def vm_status(force: bool = False) -> dict[str, Any]:
    """`vm_ctl.sh status-json` 으로 VM 상태를 조회한다 (VM 을 켜지 않음). 단기 캐시."""
    with _status_guard:
        cached = _status_cache["value"]
        if not force and cached is not None and (_now() - _status_cache["at"]) < _STATUS_CACHE_TTL:
            return {**cached, "cached": True, "active_op": _active_op()}
    status = _probe_status()
    with _status_guard:
        _status_cache["at"] = _now()
        _status_cache["value"] = status
    return {**status, "cached": False, "active_op": _active_op()}


def _probe_status() -> dict[str, Any]:
    if not SCRIPT.exists():
        return {"ok": False, "error": f"controller script not found: {SCRIPT}", **_FALSE_STATUS}
    try:
        proc = subprocess.run(
            ["bash", str(SCRIPT), "status-json"],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=_STATUS_TIMEOUT,
            env=os.environ.copy(),
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "status-json timeout (VM/multipass 응답 없음)", **_FALSE_STATUS}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}", **_FALSE_STATUS}

    lines = [ln for ln in (proc.stdout or "").splitlines() if ln.strip()]
    if lines:
        try:
            data = json.loads(lines[-1])
            data["ok"] = True
            return data
        except json.JSONDecodeError:
            pass
    detail = (proc.stderr or proc.stdout or "").strip()[:200]
    return {"ok": False, "error": f"status-json 파싱 실패 (rc={proc.returncode}): {detail}", **_FALSE_STATUS}


# ──────────────────────────────────────────────
# VM op (start / stop)
# ──────────────────────────────────────────────
def start_vm() -> dict[str, Any]:
    return _launch_op("start")


def stop_vm() -> dict[str, Any]:
    return _launch_op("stop")


def _launch_op(name: str) -> dict[str, Any]:
    if name not in VALID_OPS:
        raise ValueError(f"unknown VM op: {name}")
    if not SCRIPT.exists():
        raise RuntimeError(f"controller script not found: {SCRIPT}")
    if not _op_lock.acquire(blocking=False):
        raise RuntimeError("이미 VM 작업이 진행 중입니다. 끝난 뒤 다시 시도하세요.")
    op_id = uuid.uuid4().hex[:12]
    OPS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = OPS_DIR / f"{op_id}.log"
    rec = {
        "op_id": op_id,
        "op": name,
        "status": "running",
        "started_at": _now(),
        "ended_at": None,
        "exit_code": None,
        "log_path": str(log_path),
    }
    with _ops_guard:
        _ops[op_id] = rec
    threading.Thread(target=_run_op, args=(op_id, name, log_path), daemon=True).start()
    return _op_public(rec)


def _bridge_reachable(timeout: float = 4.0) -> bool:
    """api_server 가 격리 VM(브릿지 경유)에 실제로 닿는지 — REMOTE_URL/health ping."""
    if not REMOTE_URL:
        return False
    try:
        import requests

        headers = {"Authorization": f"Bearer {REMOTE_TOKEN}"} if REMOTE_TOKEN else {}
        resp = requests.get(f"{REMOTE_URL}/health", headers=headers, timeout=timeout)
        return resp.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def _ensure_bridge(log) -> bool:
    """VM start 후 api_server↔VM 도달을 보장 — 안 닿으면 WSL 브릿지를 (재)기동 후 재확인.

    `vm_ctl.sh start` 가 USE_BRIDGE=1 로 브릿지를 띄우긴 하지만, VM 을 admin 밖에서
    켰거나 브릿지 프로세스가 죽은 경우를 대비해 여기서 명시적으로 보장한다.
    """
    if _bridge_reachable():
        log("[bridge] 이미 도달 가능")
        return True
    log("[bridge] 미도달 — WSL 브릿지 (재)기동")
    try:
        subprocess.run(
            ["bash", str(SCRIPT), "bridge"],
            cwd=str(ROOT_DIR),
            capture_output=True,
            text=True,
            timeout=60,
            env=os.environ.copy(),
        )
    except Exception as exc:  # noqa: BLE001
        log(f"[bridge] 기동 실패: {type(exc).__name__}: {exc}")
        return False
    for _ in range(10):  # 브릿지 + VM /health 가 뜰 때까지 최대 ~20s 폴링
        if _bridge_reachable():
            log("[bridge] 재기동 후 도달 가능")
            return True
        time.sleep(2)
    log("[bridge] 재기동했지만 여전히 미도달 — VM/redroid 상태 확인 필요")
    return False


def _run_op(op_id: str, name: str, log_path: Path) -> None:
    rc: int | None = None
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(f"$ bash scripts/apk_dynamic_vm_ctl.sh {name}\n")
            f.flush()
            proc = subprocess.Popen(
                ["bash", str(SCRIPT), name],
                cwd=str(ROOT_DIR),
                stdout=f,
                stderr=subprocess.STDOUT,
                env=os.environ.copy(),
            )
            rc = proc.wait()
    except Exception as exc:  # noqa: BLE001
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(f"\n[controller error] {type(exc).__name__}: {exc}\n")
        except OSError:
            pass
        rc = -1
    finally:
        with _ops_guard:
            rec = _ops.get(op_id)
            if rec:
                rec["status"] = "done" if rc == 0 else "error"
                rec["ended_at"] = _now()
                rec["exit_code"] = rc
        with _status_guard:
            _status_cache["at"] = 0.0  # 다음 조회 시 강제 재프로브
        # op lock 을 *먼저* 해제 — 아래 후처리(특히 브릿지 도달 폴링 ~20s)가 lock 을
        # 잡고 있으면 다음 VM op 이 거짓으로 거절된다. 후처리는 동시성 보호 대상 아님.
        _op_lock.release()
        # start 성공 → remote 설정 주입(서버 재시작 없이 즉시 분석 가능). stop → 비활성으로.
        if name == "start" and rc == 0:
            apk_analyzer.configure_remote(REMOTE_URL, REMOTE_TOKEN, enabled=True)
            # 브릿지까지 보장 — api_server 가 VM 에 실제로 닿아야 Lv3 동적 분석이 실행됨.
            try:
                with open(log_path, "a", encoding="utf-8") as f:
                    _ensure_bridge(lambda m: (f.write(m + "\n"), f.flush()))
            except OSError:
                _ensure_bridge(lambda m: None)
        elif name == "stop":
            apk_analyzer.configure_remote(REMOTE_URL, REMOTE_TOKEN, enabled=False)


def _op_public(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "op_id": rec["op_id"],
        "op": rec["op"],
        "status": rec["status"],
        "started_at": rec["started_at"],
        "ended_at": rec["ended_at"],
        "exit_code": rec["exit_code"],
        "elapsed_ms": int(((rec["ended_at"] or _now()) - rec["started_at"]) * 1000),
    }


def _active_op() -> dict[str, Any] | None:
    with _ops_guard:
        for rec in _ops.values():
            if rec["status"] == "running":
                return _op_public(rec)
    return None


def get_op(op_id: str) -> dict[str, Any] | None:
    with _ops_guard:
        rec = _ops.get(op_id)
        if rec is None:
            return None
        snapshot = dict(rec)
    out = _op_public(snapshot)
    out["log"] = _tail(Path(snapshot["log_path"]))
    return out


# ──────────────────────────────────────────────
# 분석 잡
# ──────────────────────────────────────────────
def _get_pipeline():
    global _pipeline
    with _pipeline_lock:
        if _pipeline is None:
            from pipeline.runner import ScamGuardianPipeline
            _pipeline = ScamGuardianPipeline()
    return _pipeline


def start_analysis(apk_path: str, *, force_dynamic: bool = False, apk_name: str = "") -> dict[str, Any]:
    """업로드된 APK 에 대한 분석 잡을 백그라운드로 시작한다. 끝나면 임시 파일 삭제."""
    job_id = uuid.uuid4().hex[:12]
    rec = {
        "job_id": job_id,
        "status": "running",
        "force_dynamic": force_dynamic,
        "apk_name": apk_name or Path(apk_path).name,
        "started_at": _now(),
        "ended_at": None,
        "result": None,
        "error": None,
    }
    with _jobs_guard:
        _jobs[job_id] = rec
    threading.Thread(
        target=_run_analysis, args=(job_id, apk_path, force_dynamic), daemon=True
    ).start()
    return _job_public(rec)


def _run_analysis(job_id: str, apk_path: str, force_dynamic: bool) -> None:
    result: dict[str, Any] | None = None
    err: str | None = None
    try:
        if force_dynamic:
            # 정적 게이트 우회 — VM 동적 분석을 직접 호출 (검증/데모용).
            report = apk_analyzer.analyze_apk_dynamic(apk_path)
            result = {"mode": "force_dynamic", "apk_dynamic_check": report.to_dict()}
        else:
            pipeline = _get_pipeline()
            report = pipeline.analyze(
                apk_path, skip_verification=True, use_llm=False, use_rag=False
            )
            result = report.to_dict()
            result["mode"] = "full_pipeline"
    except Exception as exc:  # noqa: BLE001
        err = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            Path(apk_path).unlink(missing_ok=True)
        except OSError:
            pass
        with _jobs_guard:
            rec = _jobs.get(job_id)
            if rec:
                rec["status"] = "error" if err else "done"
                rec["ended_at"] = _now()
                rec["result"] = result
                rec["error"] = err


def _job_public(rec: dict[str, Any]) -> dict[str, Any]:
    return {
        "job_id": rec["job_id"],
        "status": rec["status"],
        "force_dynamic": rec["force_dynamic"],
        "apk_name": rec["apk_name"],
        "started_at": rec["started_at"],
        "ended_at": rec["ended_at"],
        "elapsed_ms": int(((rec["ended_at"] or _now()) - rec["started_at"]) * 1000),
        "result": rec["result"],
        "error": rec["error"],
    }


def get_job(job_id: str) -> dict[str, Any] | None:
    with _jobs_guard:
        rec = _jobs.get(job_id)
        if rec is None:
            return None
        return _job_public(rec)
