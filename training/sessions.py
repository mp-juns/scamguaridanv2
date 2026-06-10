"""
학습 세션 관리자 — 백그라운드 subprocess 로 train_classifier / train_gliner 를 띄우고
status / metrics / log 를 파일 기반으로 추적한다. FastAPI / 프론트가 폴링으로 사용.

세션 디렉토리 구조 (.scamguardian/training_sessions/{session_id}/):
    status.json     — {model, started_at, ended_at, exit_code, pid, params, ...}
    metrics.jsonl   — 학습 콜백이 매 step/epoch 마다 한 줄 append
    train.log       — subprocess stdout+stderr 합본
    output/         — 모델 체크포인트 (--output-dir 으로 전달)
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

ROOT = Path(".scamguardian") / "training_sessions"
ALLOWED_MODELS = ("classifier", "gliner")
ACTIVE_POINTER = Path(".scamguardian") / "active_models.json"

_active_lock = threading.Lock()


@dataclass
class SessionParams:
    model: str                          # "classifier" | "gliner"
    epochs: int = 3
    batch_size: int = 8
    lora: bool = False
    extra_jsonl: str | None = None
    val_ratio: float = 0.1
    seed: int = 17
    base_model: str | None = None       # 비우면 train script 의 기본값
    early_stopping_patience: int = 2
    early_stopping_threshold: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "epochs": self.epochs,
            "batch_size": self.batch_size,
            "lora": self.lora,
            "extra_jsonl": self.extra_jsonl,
            "val_ratio": self.val_ratio,
            "seed": self.seed,
            "base_model": self.base_model,
            "early_stopping_patience": self.early_stopping_patience,
            "early_stopping_threshold": self.early_stopping_threshold,
        }


@dataclass
class SessionInfo:
    session_id: str
    model: str
    status: str              # "running" | "completed" | "failed" | "cancelled"
    started_at: float
    ended_at: float | None = None
    exit_code: int | None = None
    pid: int | None = None
    params: dict[str, Any] = field(default_factory=dict)
    output_dir: str = ""
    last_metrics: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "model": self.model,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "exit_code": self.exit_code,
            "pid": self.pid,
            "params": self.params,
            "output_dir": self.output_dir,
            "last_metrics": self.last_metrics,
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
    return _session_dir(session_id) / "train.log"


def _training_python_command() -> list[str]:
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


def _latest_activity_time(session_id: str) -> float | None:
    latest: float | None = None
    for path in (_metrics_path(session_id), _log_path(session_id)):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        latest = mtime if latest is None else max(latest, mtime)
    return latest


def _has_recent_training_activity(session_id: str, *, seconds: int = 120) -> bool:
    latest = _latest_activity_time(session_id)
    return latest is not None and (time.time() - latest) <= seconds


def _refresh_status(session_id: str) -> dict[str, Any] | None:
    """status.json 을 읽고, running 인데 pid 가 죽었으면 failed 로 보정."""
    data = _read_status(session_id)
    if data is None:
        return None
    if data.get("status") == "completed" and data.get("model") == "gliner":
        output_dir = Path(str(data.get("output_dir") or ""))
        if not _has_model_artifacts("gliner", output_dir):
            data["status"] = "failed"
            data["exit_code"] = data.get("exit_code") or 2
            data["ended_at"] = data.get("ended_at") or time.time()
            data["failure_reason"] = (
                "GLiNER 모델 가중치가 없어 완료 세션으로 인정할 수 없습니다. "
                "train.json/val.json/labels.json 은 학습 데이터 산출물일 뿐입니다."
            )
            rows = read_metrics(session_id, max_rows=1)
            if rows:
                data["last_metrics"] = rows[-1]
            _write_status(session_id, data)
            return data
    if data.get("status") == "failed":
        ended_at = float(data.get("ended_at") or 0)
        latest_activity = _latest_activity_time(session_id) or 0
        if latest_activity > ended_at and _has_recent_training_activity(session_id):
            data["status"] = "running"
            data["ended_at"] = None
            data["exit_code"] = None
            rows = read_metrics(session_id, max_rows=1)
            if rows:
                data["last_metrics"] = rows[-1]
            _write_status(session_id, data)
    if data.get("status") in {"running", "failed"} and _has_success_artifacts(session_id, data):
        rows = read_metrics(session_id, max_rows=1)
        data["status"] = "completed"
        data["ended_at"] = (rows[-1].get("ts") if rows else None) or data.get("ended_at") or time.time()
        data["exit_code"] = 0
        if rows:
            data["last_metrics"] = rows[-1]
        _write_status(session_id, data)
        return data
    if data.get("status") == "running":
        pid = data.get("pid") or 0
        if pid and not _check_pid_alive(pid):
            if _has_recent_training_activity(session_id):
                rows = read_metrics(session_id, max_rows=1)
                if rows:
                    data["last_metrics"] = rows[-1]
                    _write_status(session_id, data)
                return data
            data["status"] = "failed"
            data["ended_at"] = time.time()
            data["exit_code"] = data.get("exit_code", -1)
            _write_status(session_id, data)
    return data


def _has_model_artifacts(model: str | None, output_dir: Path) -> bool:
    if not output_dir.exists():
        return False
    if model == "classifier":
        return (output_dir / "label2id.json").exists() and (
            (output_dir / "adapter_model.safetensors").exists()
            or (output_dir / "model.safetensors").exists()
            or (output_dir / "pytorch_model.bin").exists()
        )
    if model == "gliner":
        weight_files = {
            "model.safetensors",
            "pytorch_model.bin",
            "adapter_model.safetensors",
        }
        has_weights = any(path.name in weight_files for path in output_dir.rglob("*") if path.is_file())
        has_config = any(
            (output_dir / name).exists()
            for name in ("config.json", "gliner_config.json", "tokenizer_config.json")
        )
        return has_weights and has_config
    return False


def _has_success_artifacts(session_id: str, data: dict[str, Any]) -> bool:
    """Detect a completed run even if process watching missed the clean exit."""
    rows = read_metrics(session_id, max_rows=5)
    if not rows or rows[-1].get("kind") != "done":
        return False
    output_dir = Path(str(data.get("output_dir") or ""))
    model = data.get("model")
    return _has_model_artifacts(model, output_dir)


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
        # 너무 많으면 균등 샘플링 + 끝쪽 우선 보존
        step = max(1, len(rows) // max_rows)
        sampled = rows[::step]
        # 마지막 30개는 그대로
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
    try:
        return chunk.decode("utf-8", errors="replace")
    except Exception:
        return ""


def read_loss_spikes(session_id: str, max_rows: int = 80) -> list[dict[str, Any]]:
    p = _session_dir(session_id) / "output" / "loss_spikes.jsonl"
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
    return rows[-max_rows:]


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
        if data is None:
            continue
        out.append(data)
    return out


def get_session(session_id: str) -> dict[str, Any] | None:
    return _refresh_status(session_id)


def _attach_queue_state(session_id: str, queue_state: dict[str, Any]) -> None:
    data = _read_status(session_id)
    if data is None:
        return
    data["queued_sequence"] = queue_state
    _write_status(session_id, data)


def start_sequential_sessions(
    params_list: list[SessionParams],
    *,
    cooldown_seconds: int = 120,
) -> dict[str, Any]:
    """Start one training job now, then launch the rest after successful completion."""
    if not params_list:
        raise ValueError("학습할 모델을 하나 이상 선택해야 합니다.")

    first = start_session(params_list[0])
    queue_state: dict[str, Any] = {
        "mode": "sequential",
        "cooldown_seconds": cooldown_seconds,
        "current_session_id": first["session_id"],
        "items": [
            {
                "model": params.model,
                "status": "running" if idx == 0 else "queued",
                "session_id": first["session_id"] if idx == 0 else None,
            }
            for idx, params in enumerate(params_list)
        ],
    }
    _attach_queue_state(first["session_id"], queue_state)

    def _runner(anchor_session_id: str) -> None:
        nonlocal queue_state
        for idx in range(1, len(params_list)):
            prev_session_id = str(queue_state["items"][idx - 1]["session_id"])
            while True:
                prev = get_session(prev_session_id)
                status = (prev or {}).get("status")
                if status in {"completed", "failed", "cancelled"}:
                    break
                time.sleep(5)

            if status != "completed":
                queue_state["items"][idx]["status"] = "skipped"
                queue_state["items"][idx]["reason"] = f"previous_{status}"
                _attach_queue_state(anchor_session_id, queue_state)
                return

            queue_state["items"][idx]["status"] = "cooldown"
            queue_state["cooldown_started_at"] = time.time()
            _attach_queue_state(anchor_session_id, queue_state)
            time.sleep(max(0, cooldown_seconds))

            started = start_session(params_list[idx])
            queue_state["items"][idx]["status"] = "running"
            queue_state["items"][idx]["session_id"] = started["session_id"]
            queue_state["current_session_id"] = started["session_id"]
            _attach_queue_state(anchor_session_id, queue_state)

        final_session_id = str(queue_state["items"][-1]["session_id"])
        while True:
            final = get_session(final_session_id)
            status = (final or {}).get("status")
            if status in {"completed", "failed", "cancelled"}:
                queue_state["items"][-1]["status"] = status
                queue_state["status"] = "completed" if status == "completed" else status
                _attach_queue_state(anchor_session_id, queue_state)
                return
            time.sleep(5)

    if len(params_list) > 1:
        threading.Thread(target=_runner, args=(first["session_id"],), daemon=True).start()

    first["queued_sequence"] = queue_state
    return {
        "session_id": first["session_id"],
        "status": "running",
        "model": "multi" if len(params_list) > 1 else first["model"],
        "sessions": [first],
        "queued_sequence": queue_state,
    }


def start_session(params: SessionParams) -> dict[str, Any]:
    if params.model not in (*ALLOWED_MODELS, "gate"):
        raise ValueError(f"model 은 {(*ALLOWED_MODELS, 'gate')} 중 하나여야 합니다.")
    _ensure_root()
    session_id = uuid.uuid4().hex[:12]
    sdir = _session_dir(session_id)
    sdir.mkdir(parents=True, exist_ok=True)
    output_dir = sdir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd: list[str]
    if params.model == "gate":
        # content_label 3-class 게이트 평가 — 기존 standalone 스크립트를 그대로 호출.
        # 스크립트가 끝나면 record_gate_session() 으로 status/metrics/log 를 자가 등록한다.
        gate_input = params.extra_jsonl or "data/generated/user_samples_augmented.jsonl"
        cmd = [
            *_training_python_command(), "-u",
            "scripts/content_label_gate.py", "--train",
            "--session-id", session_id,
            "--input", gate_input,
            "--epochs", str(params.epochs),
            "--val-ratio", str(params.val_ratio),
            "--seed", str(params.seed),
        ]
    else:
        module = "training.train_classifier" if params.model == "classifier" else "training.train_gliner"
        cmd = [
            *_training_python_command(), "-u", "-m", module,
            "--output-dir", str(output_dir),
            "--epochs", str(params.epochs),
            "--batch-size", str(params.batch_size),
            "--val-ratio", str(params.val_ratio),
            "--seed", str(params.seed),
        ]
        if params.lora and params.model == "classifier":
            cmd.append("--lora")
        if params.model == "classifier":
            cmd += [
                "--early-stopping-patience",
                str(params.early_stopping_patience),
                "--early-stopping-threshold",
                str(params.early_stopping_threshold),
            ]
        if params.model == "gliner":
            cmd += ["--device", os.getenv("SCAMGUARDIAN_GLINER_DEVICE", "cuda")]
            cmd += ["--max-steps", os.getenv("SCAMGUARDIAN_GLINER_MAX_STEPS", "3000")]
        if params.extra_jsonl:
            cmd += ["--extra-jsonl", params.extra_jsonl]
        if params.base_model:
            cmd += ["--base-model", params.base_model]

    env = os.environ.copy()
    wsl_cuda_lib = "/usr/lib/wsl/lib"
    if Path(wsl_cuda_lib).exists():
        current_ld = env.get("LD_LIBRARY_PATH", "")
        parts = [part for part in current_ld.split(":") if part]
        if wsl_cuda_lib not in parts:
            env["LD_LIBRARY_PATH"] = ":".join([wsl_cuda_lib, *parts])
    # 학습 콜백이 metrics.jsonl 에 emit 할 수 있게 경로 알림
    env["SCAMGUARDIAN_TRAINING_METRICS"] = str(_metrics_path(session_id))
    env["SCAMGUARDIAN_TRAINING_SESSION_ID"] = session_id
    if params.model == "gliner":
        env.setdefault("SCAMGUARDIAN_HF_LOCAL_ONLY", "1")

    log_file = _log_path(session_id)
    log_handle = log_file.open("ab", buffering=0)
    process = subprocess.Popen(
        cmd,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=env,
        cwd=Path.cwd(),
        # 새 프로세스 그룹 — cancel 시 그룹 단위 SIGTERM
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
        "output_dir": str(output_dir),
        "last_metrics": None,
        "command": cmd,
    }
    if params.model == "gate":
        # 평가 전용 세션 — record_gate_session 과 동일한 마킹(적용 버튼 숨김·메트릭 보존).
        info["kind"] = "gate"
    _write_status(session_id, info)

    # subprocess 종료 감시 스레드 — exit_code 채우기
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
        # cancel 으로 이미 종료 상태 기록됨
        data["exit_code"] = rc
        _write_status(session_id, data)
        return
    if rc == 0 and data.get("model") == "gliner" and not _has_model_artifacts(
        "gliner",
        Path(str(data.get("output_dir") or "")),
    ):
        data["status"] = "failed"
        data["failure_reason"] = "GLiNER 학습이 모델 체크포인트를 만들지 못했습니다."
    else:
        data["status"] = "completed" if rc == 0 else "failed"
    data["ended_at"] = time.time()
    data["exit_code"] = rc
    # 마지막 metrics 행 한 번 더 읽어 last_metrics 갱신.
    # 단, 게이트 세션은 record_gate_session() 이 confusion/per_class/watch_cells 가 담긴
    # 풍부한 last_metrics 를 이미 써놨으므로 슬림한 metrics.jsonl 행으로 덮어쓰지 않는다.
    if data.get("kind") != "gate":
        rows = read_metrics(session_id, max_rows=1)
        if rows:
            data["last_metrics"] = rows[-1]
    _write_status(session_id, data)


def cancel_session(session_id: str) -> bool:
    data = _refresh_status(session_id)
    if data is None:
        return False
    if data.get("status") != "running":
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


# ──────────────────────────────────
# 학습 스크립트가 metrics 를 적는 헬퍼
# ──────────────────────────────────
def emit_metric(record: dict[str, Any]) -> None:
    """학습 스크립트(혹은 TrainerCallback) 가 호출. ENV 의 경로에 한 줄 append."""
    target = os.getenv("SCAMGUARDIAN_TRAINING_METRICS")
    if not target:
        return
    p = Path(target)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {**record, "ts": time.time()}
    with p.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(payload, ensure_ascii=False) + "\n")


# ──────────────────────────────────
# 모델 활성화 — 학습 끝난 체크포인트를 파이프라인에 swap
# ──────────────────────────────────
def _read_active() -> dict[str, str]:
    if not ACTIVE_POINTER.exists():
        return {}
    try:
        return json.loads(ACTIVE_POINTER.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_active(data: dict[str, str]) -> None:
    ACTIVE_POINTER.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_POINTER.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_active_models() -> dict[str, str]:
    with _active_lock:
        return dict(_read_active())


def activate_session(session_id: str) -> dict[str, Any]:
    data = _refresh_status(session_id)
    if data is None:
        raise FileNotFoundError("세션을 찾을 수 없습니다.")
    if data.get("kind") == "gate":
        raise ValueError("게이트(평가 전용) 세션은 파이프라인에 적용할 수 없습니다.")
    if data.get("status") != "completed":
        raise ValueError(f"완료된 세션만 활성화할 수 있습니다 (현재 status={data.get('status')}).")
    output_dir = data.get("output_dir") or ""
    output_path = Path(output_dir)
    if not output_dir or not output_path.exists():
        raise FileNotFoundError("체크포인트 디렉토리를 찾을 수 없습니다.")
    model = data.get("model")
    if not _has_model_artifacts(model, output_path):
        raise ValueError(
            "실제 모델 체크포인트가 없는 세션입니다. "
            "GLiNER 세션은 train.json/val.json/labels.json 만으로 활성화할 수 없습니다."
        )
    with _active_lock:
        active = _read_active()
        active[model] = output_dir
        active["_last_activated_at"] = str(time.time())
        _write_active(active)
    # 파이프라인의 캐시된 활성 경로 즉시 만료 — 다음 분석부터 새 모델 사용
    try:
        from pipeline import active_models as _am
        _am.invalidate()
    except Exception:
        pass
    return {"model": model, "path": output_dir}


def _format_gate_summary(gate_name: str, metrics: dict[str, Any]) -> str:
    """게이트 평가 결과를 사람이 읽을 텍스트로 — 세션 상세의 log tail 에 노출."""
    lines = [f"=== {gate_name} ===",
             f"accuracy={metrics.get('accuracy', 0):.4f}  macro_f1={metrics.get('macro_f1', 0):.4f}",
             "", "[per-class precision/recall/F1]"]
    per = metrics.get("per_class") or {}
    for label, m in per.items():
        lines.append(f"  {label:14s} P {m.get('precision', 0):.3f}  R {m.get('recall', 0):.3f}  "
                     f"F1 {m.get('f1', 0):.3f}  (support {m.get('support', 0)})")
    labels = metrics.get("labels") or list(per.keys())
    cm = metrics.get("confusion")
    if cm:
        lines += ["", f"[confusion matrix] 행=true, 열=pred  순서: {labels}"]
        header = " " * 16 + "".join(f"{str(l)[:10]:>12}" for l in labels)
        lines.append(header)
        for i, l in enumerate(labels):
            lines.append(f"  {str(l):14s}" + "".join(f"{cm[i][j]:>12}" for j in range(len(labels))))
    cells = metrics.get("watch_cells") or []
    if cells:
        lines += ["", "[집중 오류 셀 (true→pred)]"]
        for c in cells:
            lines.append(f"  {c.get('true',''):14s} → {c.get('pred',''):14s}: "
                         f"{c.get('count',0)} / {c.get('denom',0)} ({c.get('rate',0)*100:.1f}%)")
    return "\n".join(lines) + "\n"


def record_gate_session(
    session_id: str,
    *,
    gate_name: str,
    params: dict[str, Any],
    metrics: dict[str, Any],
    started_at: float,
    ended_at: float | None = None,
    status: str = "completed",
    exit_code: int = 0,
    output_dir: str | None = None,
) -> dict[str, Any]:
    """게이트(평가 전용) 실험을 학습 세션 목록에 등록.

    분류기/GLiNER 처럼 파이프라인에 '적용'하는 모델이 아니라 효과 측정용 세션이다
    (`kind="gate"`). `activate_session` 은 kind=gate 를 거부하고, 프론트엔드는 적용 버튼을
    숨긴다. status.json/metrics.jsonl/train.log 를 일반 세션과 같은 위치에 써서 목록·상세에
    그대로 노출된다.
    """
    _ensure_root()
    out_dir = output_dir if output_dir is not None else str(_session_dir(session_id) / "output")
    data = {
        "session_id": session_id,
        "kind": "gate",
        "model": gate_name,        # 목록 표시용 라벨
        "gate_name": gate_name,
        "status": status,
        "started_at": started_at,
        "ended_at": ended_at if ended_at is not None else time.time(),
        "exit_code": exit_code,
        "pid": None,
        "params": params,
        "output_dir": out_dir,
        "last_metrics": metrics,
    }
    _write_status(session_id, data)
    # metrics.jsonl — 상세 화면 metric tail 용 (최종 결과 한 줄)
    try:
        mp = _metrics_path(session_id)
        mp.parent.mkdir(parents=True, exist_ok=True)
        with mp.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"event": "gate_eval",
                                "eval_accuracy": metrics.get("accuracy"),
                                "eval_macro_f1": metrics.get("macro_f1")}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # train.log — 상세 화면 log tail 에 사람이 읽는 결과 노출
    try:
        with _log_path(session_id).open("a", encoding="utf-8") as f:
            f.write(_format_gate_summary(gate_name, metrics))
    except Exception:
        pass
    return data
