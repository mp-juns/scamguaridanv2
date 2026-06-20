"""File-backed training session storage helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(".scamguardian") / "training_sessions"
ACTIVE_POINTER = Path(".scamguardian") / "active_models.json"


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


def _read_status(session_id: str) -> dict[str, Any] | None:
    path = _status_path(session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_status(session_id: str, data: dict[str, Any]) -> None:
    path = _status_path(session_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def read_metrics(session_id: str, max_rows: int = 500) -> list[dict[str, Any]]:
    path = _metrics_path(session_id)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fp:
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
    path = _log_path(session_id)
    if not path.exists():
        return ""
    size = path.stat().st_size
    with path.open("rb") as fp:
        if size > max_bytes:
            fp.seek(size - max_bytes)
        chunk = fp.read()
    try:
        return chunk.decode("utf-8", errors="replace")
    except Exception:
        return ""


def read_loss_spikes(session_id: str, max_rows: int = 80) -> list[dict[str, Any]]:
    path = _session_dir(session_id) / "output" / "loss_spikes.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-max_rows:]
