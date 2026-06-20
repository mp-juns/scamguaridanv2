"""SQLite-backed platform facade functions.

API key, cost ledger, and request-log helpers are currently implemented only for
the SQLite backend. Keeping them here keeps db.repository focused on run and
annotation persistence.
"""

from __future__ import annotations

import os

from db import sqlite_repository


def _get_db_backend() -> str:
    if sqlite_repository.database_configured():
        return "sqlite"
    if os.getenv("SCAMGUARDIAN_DATABASE_URL", "").strip():
        return "postgres"
    return ""


def _require_sqlite(name: str) -> None:
    if _get_db_backend() != "sqlite":
        raise NotImplementedError(
            f"{name}() 는 현재 SQLite 백엔드에서만 지원됩니다. "
            "Postgres 사용 시 별도 마이그레이션 필요."
        )


def create_api_key(**kwargs):
    _require_sqlite("create_api_key")
    return sqlite_repository.create_api_key(**kwargs)


def get_api_key_by_hash(key_hash: str):
    _require_sqlite("get_api_key_by_hash")
    return sqlite_repository.get_api_key_by_hash(key_hash)


def list_api_keys(limit: int = 100):
    _require_sqlite("list_api_keys")
    return sqlite_repository.list_api_keys(limit)


def revoke_api_key(key_id: str) -> bool:
    _require_sqlite("revoke_api_key")
    return sqlite_repository.revoke_api_key(key_id)


def touch_api_key_usage(key_id: str):
    _require_sqlite("touch_api_key_usage")
    return sqlite_repository.touch_api_key_usage(key_id)


def get_monthly_usd_for_key(key_id: str) -> float:
    _require_sqlite("get_monthly_usd_for_key")
    return sqlite_repository.get_monthly_usd_for_key(key_id)


def insert_cost_event(**kwargs) -> None:
    if _get_db_backend() != "sqlite":
        return
    sqlite_repository.insert_cost_event(**kwargs)


def aggregate_costs(*, days: int = 30):
    _require_sqlite("aggregate_costs")
    return sqlite_repository.aggregate_costs(days=days)


def insert_request_log(**kwargs) -> None:
    if _get_db_backend() != "sqlite":
        return
    sqlite_repository.insert_request_log(**kwargs)


def request_log_recent(limit: int = 100):
    _require_sqlite("request_log_recent")
    return sqlite_repository.request_log_recent(limit)


def request_log_summary(*, hours: int = 24):
    _require_sqlite("request_log_summary")
    return sqlite_repository.request_log_summary(hours=hours)
