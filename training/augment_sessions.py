"""증강 세션 관리자 — 백그라운드 subprocess 로 scripts.run_augment_session 을 띄우고
status / metrics / log / output 을 파일 기반으로 추적한다. FastAPI / 프론트가 폴링으로 사용.

`training/sessions.py` (학습 세션) 의 단순화 미러. 차이점:
- 산출물이 모델 체크포인트가 아니라 증강된 JSONL (`output.jsonl`)
- "활성화" 대신 `promote_output()` — 산출 JSONL 을 학습용 data/generated/ 로 병합

세션 디렉토리 (.scamguardian/augmentation_sessions/{session_id}/):
    status.json     — {seed_file, started_at, ended_at, exit_code, pid, params, ...}
    metrics.jsonl   — 러너가 씨앗 처리마다 한 줄 append ({kind: augment|done, ...})
    run.log         — subprocess stdout+stderr 합본
    output.jsonl    — 증강 산출물 (학습 입력 후보)
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(".scamguardian") / "augmentation_sessions"
GENERATED_DIR = Path("data") / "generated"
_MAX_CONCURRENCY = 16


@dataclass
class AugmentParams:
    seed_file: str
    variants: int = 5
    rounds: int = 1
    model: str = "claude-sonnet-4-6"
    concurrency: int = 8
    limit: int = 0
    scam_type: str | None = None        # 특정 유형 씨앗만 증강 (None = 전체)

    def to_dict(self) -> dict[str, Any]:
        return {
            "seed_file": self.seed_file,
            "variants": self.variants,
            "rounds": self.rounds,
            "model": self.model,
            "concurrency": self.concurrency,
            "limit": self.limit,
            "scam_type": self.scam_type,
        }


def _ensure_root() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)


def _session_dir(session_id: str) -> Path:
    return ROOT / session_id


def _status_path(session_id: str) -> Path:
    return _session_dir(session_id) / "status.json"


def _metrics_path(session_id: str) -> Path:
    return _session_dir(session_id) / "metrics.jsonl"


def _log_path(session_id: str) -> Path:
    return _session_dir(session_id) / "run.log"


def _output_path(session_id: str) -> Path:
    return _session_dir(session_id) / "output.jsonl"


def _augment_python_command() -> list[str]:
    """학습 세션과 동일한 인터프리터 선택 규칙 (capstone conda env 우선)."""
    explicit = (os.getenv("SCAMGUARDIAN_TRAIN_PYTHON") or "").strip()
    if explicit:
        return [explicit]
    conda_env = (os.getenv("SCAMGUARDIAN_TRAIN_CONDA_ENV") or os.getenv("CONDA_ENV") or "").strip()
    if conda_env:
        return ["conda", "run", "--no-capture-output", "-n", conda_env, "python"]
    capstone_python = Path.home() / "anaconda3" / "envs" / "capstone" / "bin" / "python"
    if capstone_python.exists():
        return [str(capstone_python)]
    return [sys.executable]


def _read_status(session_id: str) -> dict[str, Any] | None:
    p = _status_path(session_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_status(session_id: str, data: dict[str, Any]) -> None:
    p = _status_path(session_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


def _check_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _has_done_metric(session_id: str) -> bool:
    rows = read_metrics(session_id, max_rows=3)
    return bool(rows) and rows[-1].get("kind") == "done"


def _refresh_status(session_id: str) -> dict[str, Any] | None:
    """status.json 을 읽고, running 인데 pid 죽었으면 done 메트릭 유무로 보정."""
    data = _read_status(session_id)
    if data is None:
        return None
    if data.get("status") == "running":
        pid = int(data.get("pid") or 0)
        done = _has_done_metric(session_id)
        if done:
            rows = read_metrics(session_id, max_rows=1)
            data["status"] = "completed"
            data["ended_at"] = (rows[-1].get("ts") if rows else None) or time.time()
            data["exit_code"] = 0
            if rows:
                data["last_metrics"] = rows[-1]
            _write_status(session_id, data)
        elif pid and not _check_pid_alive(pid):
            # 프로세스가 done 없이 죽음 → 실패
            data["status"] = "failed"
            data["ended_at"] = time.time()
            data["exit_code"] = data.get("exit_code", -1)
            _write_status(session_id, data)
    return data


def read_metrics(session_id: str, max_rows: int = 500) -> list[dict[str, Any]]:
    p = _metrics_path(session_id)
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if len(rows) > max_rows:
        step = max(1, len(rows) // max_rows)
        sampled = rows[::step]
        sampled = sampled[:-30] + rows[-30:]
        return sampled
    return rows


def read_log_tail(session_id: str, max_bytes: int = 8000) -> str:
    p = _log_path(session_id)
    if not p.exists():
        return ""
    size = p.stat().st_size
    with p.open("rb") as fp:
        if size > max_bytes:
            fp.seek(size - max_bytes)
        chunk = fp.read()
    return chunk.decode("utf-8", errors="replace")


def list_sessions(limit: int = 50) -> list[dict[str, Any]]:
    _ensure_root()
    entries: list[tuple[float, str]] = []
    for child in ROOT.iterdir():
        if not child.is_dir():
            continue
        status_file = child / "status.json"
        if not status_file.exists():
            continue
        entries.append((status_file.stat().st_mtime, child.name))
    entries.sort(reverse=True)
    out: list[dict[str, Any]] = []
    for _, sid in entries[:limit]:
        data = _refresh_status(sid)
        if data is not None:
            out.append(data)
    return out


def get_session(session_id: str) -> dict[str, Any] | None:
    return _refresh_status(session_id)


def start_session(params: AugmentParams) -> dict[str, Any]:
    seed_path = Path(params.seed_file)
    if not seed_path.exists():
        raise FileNotFoundError(f"씨앗 파일을 찾을 수 없습니다: {params.seed_file}")
    if params.variants < 1:
        raise ValueError("variants 는 1 이상이어야 합니다.")
    concurrency = max(1, min(_MAX_CONCURRENCY, int(params.concurrency)))

    _ensure_root()
    session_id = uuid.uuid4().hex[:12]
    sdir = _session_dir(session_id)
    sdir.mkdir(parents=True, exist_ok=True)
    output_path = _output_path(session_id)

    cmd: list[str] = [
        *_augment_python_command(), "-u", "-m", "scripts.run_augment_session",
        "--seed-file", str(seed_path),
        "--output", str(output_path),
        "--variants", str(params.variants),
        "--rounds", str(params.rounds),
        "--model", params.model,
        "--concurrency", str(concurrency),
        "--limit", str(params.limit),
    ]
    if params.scam_type:
        cmd += ["--scam-type", params.scam_type]

    env = os.environ.copy()
    env["SCAMGUARDIAN_AUGMENT_METRICS"] = str(_metrics_path(session_id))
    env["SCAMGUARDIAN_AUGMENT_SESSION_ID"] = session_id

    log_handle = _log_path(session_id).open("ab", buffering=0)
    process = subprocess.Popen(
        cmd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=env,
        cwd=Path.cwd(),
        preexec_fn=os.setsid if os.name == "posix" else None,
    )

    info = {
        "session_id": session_id,
        "model": params.model,
        "status": "running",
        "started_at": time.time(),
        "ended_at": None,
        "exit_code": None,
        "pid": process.pid,
        "params": params.to_dict(),
        "output_file": str(output_path),
        "last_metrics": None,
        "command": cmd,
    }
    _write_status(session_id, info)

    threading.Thread(
        target=_watch_process,
        args=(session_id, process, log_handle),
        daemon=True,
    ).start()
    return info


def _watch_process(session_id: str, process: subprocess.Popen, log_handle) -> None:
    try:
        rc = process.wait()
    finally:
        try:
            log_handle.close()
        except Exception:
            pass
    data = _read_status(session_id) or {}
    if data.get("status") == "cancelled":
        data["exit_code"] = rc
        _write_status(session_id, data)
        return
    data["status"] = "completed" if rc == 0 else "failed"
    data["ended_at"] = time.time()
    data["exit_code"] = rc
    rows = read_metrics(session_id, max_rows=1)
    if rows:
        data["last_metrics"] = rows[-1]
    _write_status(session_id, data)


def cancel_session(session_id: str) -> bool:
    data = _refresh_status(session_id)
    if data is None or data.get("status") != "running":
        return False
    pid = int(data.get("pid") or 0)
    if pid <= 0:
        return False
    try:
        if os.name == "posix":
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        else:
            os.kill(pid, signal.SIGTERM)
    except OSError:
        return False
    data["status"] = "cancelled"
    data["ended_at"] = time.time()
    _write_status(session_id, data)
    return True


def emit_metric(record: dict[str, Any]) -> None:
    """러너 subprocess 가 호출. ENV 의 경로에 한 줄 append."""
    target = os.getenv("SCAMGUARDIAN_AUGMENT_METRICS")
    if not target:
        return
    p = Path(target)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {**record, "ts": time.time()}
    with p.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")


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


def promote_output(session_id: str, target_name: str) -> dict[str, Any]:
    """세션 output.jsonl 을 data/generated/{target_name}.jsonl 로 병합 (text 중복 제거).

    training 폼의 extra_jsonl 로 바로 사용 가능한 경로를 반환한다.
    """
    data = _refresh_status(session_id)
    if data is None:
        raise FileNotFoundError("세션을 찾을 수 없습니다.")
    if data.get("status") != "completed":
        raise ValueError(f"완료된 세션만 내보낼 수 있습니다 (현재 status={data.get('status')}).")
    src = _output_path(session_id)
    new_rows = _read_jsonl(src)
    if not new_rows:
        raise ValueError("증강 산출물이 비어 있습니다.")

    safe = "".join(c for c in target_name if c.isalnum() or c in "-_") or "augmented"
    if not safe.endswith(".jsonl"):
        safe = f"{safe}.jsonl"
    dest = GENERATED_DIR / safe
    dest.parent.mkdir(parents=True, exist_ok=True)

    existing = _read_jsonl(dest)
    seen = {str(r.get("text", "")).strip() for r in existing}
    added = 0
    with dest.open("a", encoding="utf-8") as fp:
        for r in new_rows:
            text = str(r.get("text", "")).strip()
            if not text or text in seen:
                continue
            seen.add(text)
            fp.write(json.dumps(r, ensure_ascii=False) + "\n")
            added += 1
    return {"path": str(dest), "added": added, "total": len(seen)}
