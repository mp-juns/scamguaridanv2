"""
ScamGuardian — SQLite 연결·스키마 코어

경로 해석 + 커넥션 + init_db (스키마 생성·마이그레이션·seed 한 덩어리 — 분산 금지)
+ JSON 직렬화 헬퍼. runs/platform 모듈이 공유한다.
외부 소비자는 `db.sqlite_repository` facade 를 통해 import 한다.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_VECTOR_DIMENSION = 384
_ROOT_DIR = Path(__file__).resolve().parents[1]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_sqlite_path(required: bool = False) -> str:
    raw = os.getenv("SCAMGUARDIAN_SQLITE_PATH", "").strip()
    if required and not raw:
        raise EnvironmentError("SCAMGUARDIAN_SQLITE_PATH가 설정되지 않았습니다.")
    return raw


def database_configured() -> bool:
    return bool(get_sqlite_path(required=False))


def _resolved_db_path() -> Path:
    raw = get_sqlite_path(required=True)
    path = Path(raw)
    if not path.is_absolute():
        path = _ROOT_DIR / path
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_resolved_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    if not database_configured():
        return

    statements = [
        """
        CREATE TABLE IF NOT EXISTS analysis_runs (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            input_source TEXT NOT NULL,
            whisper_model TEXT NOT NULL,
            skip_verification INTEGER NOT NULL,
            use_llm INTEGER NOT NULL,
            use_rag INTEGER NOT NULL DEFAULT 0,
            transcript_text TEXT NOT NULL,
            transcript_corrected_text TEXT,
            classification_scanner TEXT NOT NULL,
            entities_predicted TEXT NOT NULL,
            verification_results TEXT NOT NULL,
            triggered_flags_predicted TEXT NOT NULL,
            total_score_predicted INTEGER NOT NULL,
            risk_level_predicted TEXT NOT NULL,
            llm_assessment TEXT,
            metadata TEXT NOT NULL DEFAULT '{}'
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS human_annotations (
            run_id TEXT PRIMARY KEY REFERENCES analysis_runs(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            labeler TEXT,
            scam_type_gt TEXT NOT NULL,
            entities_gt TEXT NOT NULL,
            triggered_flags_gt TEXT NOT NULL,
            transcript_corrected_text TEXT,
            stt_quality INTEGER,
            notes TEXT NOT NULL DEFAULT '',
            content_label TEXT,
            sample_kind TEXT,
            source_ref TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS transcript_embeddings (
            run_id TEXT PRIMARY KEY REFERENCES analysis_runs(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            model_name TEXT NOT NULL,
            embedding TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS scam_type_catalog (
            name TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            labels TEXT NOT NULL DEFAULT '[]'
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_analysis_runs_created_at ON analysis_runs(created_at DESC)",
        # ── v3 platform: API key + cost ledger + request log ──
        """
        CREATE TABLE IF NOT EXISTS api_keys (
            id TEXT PRIMARY KEY,
            key_hash TEXT NOT NULL UNIQUE,
            label TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_used_at TEXT,
            monthly_quota INTEGER NOT NULL DEFAULT 1000,
            rpm_limit INTEGER NOT NULL DEFAULT 30,
            monthly_usd_quota REAL NOT NULL DEFAULT 5.0,
            status TEXT NOT NULL DEFAULT 'active',
            usage_total INTEGER NOT NULL DEFAULT 0,
            usage_month INTEGER NOT NULL DEFAULT 0,
            usage_month_at TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS cost_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            request_id TEXT,
            api_key_id TEXT,
            provider TEXT NOT NULL,
            action TEXT NOT NULL,
            units REAL NOT NULL,
            usd_amount REAL NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}'
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_cost_events_created_at ON cost_events(created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_cost_events_api_key ON cost_events(api_key_id)",
        """
        CREATE TABLE IF NOT EXISTS request_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            request_id TEXT NOT NULL,
            api_key_id TEXT,
            method TEXT NOT NULL,
            path TEXT NOT NULL,
            status INTEGER NOT NULL,
            latency_ms INTEGER NOT NULL,
            error TEXT,
            extra TEXT NOT NULL DEFAULT '{}'
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_request_log_created_at ON request_log(created_at DESC)",
        # ── admin 사용자 승인 (master + approval) ──
        """
        CREATE TABLE IF NOT EXISTS admin_users (
            email TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'pending',
            requested_at TEXT NOT NULL,
            decided_at TEXT,
            decided_by TEXT
        )
        """,
    ]

    with _connect() as conn:
        for statement in statements:
            conn.execute(statement)
        # 마이그레이션: claim 컬럼 추가 (이미 있으면 무시)
        for col, col_type in [("claimed_by", "TEXT"), ("claimed_at", "TEXT")]:
            try:
                conn.execute(f"ALTER TABLE analysis_runs ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass
        # v3 platform: api_keys 마이그레이션 (이미 있으면 무시)
        for col, col_type in [
            ("monthly_usd_quota", "REAL NOT NULL DEFAULT 5.0"),
        ]:
            try:
                conn.execute(f"ALTER TABLE api_keys ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass
        # content_label 재설계: human_annotations 마이그레이션 (이미 있으면 무시)
        for col, col_type in [
            ("content_label", "TEXT"),
            ("sample_kind", "TEXT"),
            ("source_ref", "TEXT"),
        ]:
            try:
                conn.execute(f"ALTER TABLE human_annotations ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass
        # admin_users seed: 마스터(env) 외에 본인 계정 1개를 approved 로 부트스트랩 (락아웃 방지)
        _seed_now = _now_iso()
        conn.execute(
            "INSERT OR IGNORE INTO admin_users (email, status, requested_at, decided_at, decided_by) "
            "VALUES (?, 'approved', ?, ?, 'seed')",
            ("kimjunsung5@jnu.ac.kr", _seed_now, _seed_now),
        )
        conn.commit()


def _dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _load_json(value: str | None, default: Any) -> Any:
    if value is None or value == "":
        return default
    return json.loads(value)
