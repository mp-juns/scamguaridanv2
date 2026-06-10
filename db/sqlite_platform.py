"""
ScamGuardian — SQLite: v3 platform (API key·admin 승인·비용 ledger·요청 로그)

api_keys / admin_users / cost_events / request_log.
연결·스키마는 db.sqlite_core, 분석 run 은 db.sqlite_runs.
외부 소비자는 `db.sqlite_repository` facade 를 통해 import 한다.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from db.sqlite_core import _connect, _now_iso, init_db


# ──────────────────────────────────
# v3 platform: API key + cost ledger + request log
# ──────────────────────────────────
def _month_key(iso: str) -> str:
    return iso[:7]  # "YYYY-MM"


def create_api_key(
    *,
    label: str,
    key_hash: str,
    monthly_quota: int = 1000,
    rpm_limit: int = 30,
    monthly_usd_quota: float = 5.0,
) -> dict[str, Any]:
    init_db()
    key_id = uuid.uuid4().hex[:16]
    now = _now_iso()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO api_keys (id, key_hash, label, created_at, monthly_quota, rpm_limit, monthly_usd_quota, status, usage_total, usage_month, usage_month_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 0, 0, ?)
            """,
            (key_id, key_hash, label, now, monthly_quota, rpm_limit, monthly_usd_quota, _month_key(now)),
        )
    return {
        "id": key_id,
        "label": label,
        "monthly_quota": monthly_quota,
        "rpm_limit": rpm_limit,
        "monthly_usd_quota": monthly_usd_quota,
        "status": "active",
        "created_at": now,
    }


def get_monthly_usd_for_key(key_id: str) -> float:
    """이번 달 누적 USD 비용. cost_events 에서 같은 month 의 합."""
    init_db()
    now = _now_iso()
    month_prefix = _month_key(now)
    with _connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(usd_amount), 0) AS total FROM cost_events WHERE api_key_id = ? AND substr(created_at, 1, 7) = ?",
            (key_id, month_prefix),
        ).fetchone()
    return float(row["total"] or 0)


def get_api_key_by_hash(key_hash: str) -> dict[str, Any] | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT * FROM api_keys WHERE key_hash = ?", (key_hash,)
        ).fetchone()
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def list_api_keys(limit: int = 100) -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, label, created_at, last_used_at, monthly_quota, rpm_limit, status, usage_total, usage_month, usage_month_at FROM api_keys ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


def revoke_api_key(key_id: str) -> bool:
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            "UPDATE api_keys SET status = 'revoked' WHERE id = ?",
            (key_id,),
        )
        return cur.rowcount > 0


# ── admin_users (master + approval 시스템) ──

def upsert_access_request(email: str) -> dict[str, Any]:
    """모르는 email → pending 요청 생성. 이미 있으면 기존 레코드 반환."""
    init_db()
    email = (email or "").strip().lower()
    now = _now_iso()
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO admin_users (email, status, requested_at) VALUES (?, 'pending', ?)",
            (email, now),
        )
        row = conn.execute("SELECT * FROM admin_users WHERE email = ?", (email,)).fetchone()
    return {k: row[k] for k in row.keys()}


def get_admin_user(email: str) -> dict[str, Any] | None:
    init_db()
    email = (email or "").strip().lower()
    with _connect() as conn:
        row = conn.execute("SELECT * FROM admin_users WHERE email = ?", (email,)).fetchone()
    return {k: row[k] for k in row.keys()} if row else None


def list_admin_users() -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM admin_users ORDER BY "
            "CASE status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END, requested_at DESC"
        ).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


def set_admin_user_status(email: str, status: str, decided_by: str | None = None) -> dict[str, Any] | None:
    """승인/거부. 레코드 없으면 생성 후 상태 지정 (마스터가 직접 추가 가능)."""
    init_db()
    email = (email or "").strip().lower()
    now = _now_iso()
    with _connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO admin_users (email, status, requested_at) VALUES (?, 'pending', ?)",
            (email, now),
        )
        conn.execute(
            "UPDATE admin_users SET status = ?, decided_at = ?, decided_by = ? WHERE email = ?",
            (status, now, decided_by, email),
        )
        row = conn.execute("SELECT * FROM admin_users WHERE email = ?", (email,)).fetchone()
    return {k: row[k] for k in row.keys()} if row else None


def touch_api_key_usage(key_id: str) -> dict[str, Any] | None:
    """호출 1건 기록 — usage_total/month 증가, last_used_at 갱신."""
    init_db()
    now = _now_iso()
    month = _month_key(now)
    with _connect() as conn:
        row = conn.execute(
            "SELECT monthly_quota, usage_month, usage_month_at, status FROM api_keys WHERE id = ?",
            (key_id,),
        ).fetchone()
        if row is None:
            return None
        if row["status"] != "active":
            return {"status": row["status"], "remaining_month": 0}
        if row["usage_month_at"] != month:
            conn.execute(
                "UPDATE api_keys SET usage_month = 1, usage_month_at = ?, usage_total = usage_total + 1, last_used_at = ? WHERE id = ?",
                (month, now, key_id),
            )
            usage_month = 1
        else:
            conn.execute(
                "UPDATE api_keys SET usage_month = usage_month + 1, usage_total = usage_total + 1, last_used_at = ? WHERE id = ?",
                (now, key_id),
            )
            usage_month = row["usage_month"] + 1
        return {
            "status": "active",
            "monthly_quota": row["monthly_quota"],
            "usage_month": usage_month,
            "remaining_month": max(0, row["monthly_quota"] - usage_month),
        }


def insert_cost_event(
    *,
    request_id: str | None,
    api_key_id: str | None,
    provider: str,
    action: str,
    units: float,
    usd_amount: float,
    metadata: dict[str, Any] | None = None,
) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO cost_events (created_at, request_id, api_key_id, provider, action, units, usd_amount, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now_iso(),
                request_id,
                api_key_id,
                provider,
                action,
                float(units),
                float(usd_amount),
                json.dumps(metadata or {}, ensure_ascii=False),
            ),
        )


def aggregate_costs(*, days: int = 30) -> dict[str, Any]:
    """provider × api_key 별 USD 합계 + 일별 추이."""
    init_db()
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with _connect() as conn:
        by_provider = conn.execute(
            "SELECT provider, COUNT(*) AS calls, SUM(units) AS units, SUM(usd_amount) AS usd FROM cost_events WHERE created_at >= ? GROUP BY provider ORDER BY usd DESC",
            (cutoff,),
        ).fetchall()
        by_key = conn.execute(
            """
            SELECT
              ce.api_key_id,
              ak.label,
              COUNT(*) AS calls,
              SUM(ce.usd_amount) AS usd
            FROM cost_events ce
            LEFT JOIN api_keys ak ON ak.id = ce.api_key_id
            WHERE ce.created_at >= ?
            GROUP BY ce.api_key_id
            ORDER BY usd DESC
            LIMIT 50
            """,
            (cutoff,),
        ).fetchall()
        daily = conn.execute(
            "SELECT substr(created_at, 1, 10) AS day, SUM(usd_amount) AS usd, COUNT(*) AS calls FROM cost_events WHERE created_at >= ? GROUP BY day ORDER BY day",
            (cutoff,),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS calls, SUM(usd_amount) AS usd FROM cost_events WHERE created_at >= ?",
            (cutoff,),
        ).fetchone()
    return {
        "total": {"calls": total["calls"] or 0, "usd": float(total["usd"] or 0)},
        "by_provider": [{k: r[k] for k in r.keys()} for r in by_provider],
        "by_key": [{k: r[k] for k in r.keys()} for r in by_key],
        "daily": [{k: r[k] for k in r.keys()} for r in daily],
        "since": cutoff,
    }


def insert_request_log(
    *,
    request_id: str,
    api_key_id: str | None,
    method: str,
    path: str,
    status: int,
    latency_ms: int,
    error: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO request_log (created_at, request_id, api_key_id, method, path, status, latency_ms, error, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                _now_iso(),
                request_id,
                api_key_id,
                method,
                path,
                int(status),
                int(latency_ms),
                error,
                json.dumps(extra or {}, ensure_ascii=False),
            ),
        )


def request_log_recent(limit: int = 100) -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, request_id, api_key_id, method, path, status, latency_ms, error FROM request_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [{k: r[k] for k in r.keys()} for r in rows]


def request_log_summary(*, hours: int = 24) -> dict[str, Any]:
    """최근 N시간 요청 통계 — 총 건수, 에러율, p50/p95 지연."""
    init_db()
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with _connect() as conn:
        total = (
            conn.execute(
                "SELECT COUNT(*) AS n FROM request_log WHERE created_at >= ?", (cutoff,)
            ).fetchone()["n"]
            or 0
        )
        errors = (
            conn.execute(
                "SELECT COUNT(*) AS n FROM request_log WHERE created_at >= ? AND status >= 500",
                (cutoff,),
            ).fetchone()["n"]
            or 0
        )
        latencies = [
            r["latency_ms"]
            for r in conn.execute(
                "SELECT latency_ms FROM request_log WHERE created_at >= ? ORDER BY latency_ms",
                (cutoff,),
            ).fetchall()
        ]
        by_path = conn.execute(
            "SELECT path, COUNT(*) AS n, AVG(latency_ms) AS avg_ms FROM request_log WHERE created_at >= ? GROUP BY path ORDER BY n DESC LIMIT 20",
            (cutoff,),
        ).fetchall()
    p50 = latencies[len(latencies) // 2] if latencies else 0
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0
    return {
        "total": total,
        "errors": errors,
        "error_rate": (errors / total) if total else 0.0,
        "p50_ms": p50,
        "p95_ms": p95,
        "by_path": [{k: r[k] for k in r.keys()} for r in by_path],
        "since_hours": hours,
    }
