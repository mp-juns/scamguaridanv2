from __future__ import annotations

import json
import math
import os
import sqlite3
import uuid
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


def list_custom_scam_types() -> list[dict[str, Any]]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT name, created_at, updated_at, description, labels
            FROM scam_type_catalog
            ORDER BY created_at ASC, name ASC
            """
        ).fetchall()

    return [
        {
            "name": row["name"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "description": row["description"] or "",
            "labels": _load_json(row["labels"], []),
        }
        for row in rows
    ]


def upsert_custom_scam_type(
    *,
    name: str,
    description: str = "",
    labels: list[str] | None = None,
) -> dict[str, Any]:
    init_db()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT created_at FROM scam_type_catalog WHERE name = ?",
            (name,),
        ).fetchone()
        created_at = existing["created_at"] if existing is not None else _now_iso()
        updated_at = _now_iso()
        normalized_labels = [str(label).strip() for label in (labels or []) if str(label).strip()]
        conn.execute(
            """
            INSERT INTO scam_type_catalog (
                name,
                created_at,
                updated_at,
                description,
                labels
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                updated_at = excluded.updated_at,
                description = excluded.description,
                labels = excluded.labels
            """,
            (
                name,
                created_at,
                updated_at,
                description.strip(),
                _dump_json(normalized_labels),
            ),
        )
        conn.commit()

    return {
        "name": name,
        "created_at": created_at,
        "updated_at": updated_at,
        "description": description.strip(),
        "labels": normalized_labels,
    }


def save_analysis_run(
    *,
    input_source: str,
    whisper_model: str,
    skip_verification: bool,
    use_llm: bool,
    use_rag: bool,
    transcript_text: str,
    classification_scanner: dict[str, Any],
    entities_predicted: list[dict[str, Any]],
    verification_results: list[dict[str, Any]],
    triggered_flags_predicted: list[dict[str, Any]],
    total_score_predicted: int,
    risk_level_predicted: str,
    llm_assessment: dict[str, Any] | None,
    metadata: dict[str, Any] | None = None,
) -> str:
    init_db()
    run_id = str(uuid.uuid4())
    now = _now_iso()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO analysis_runs (
                id,
                created_at,
                input_source,
                whisper_model,
                skip_verification,
                use_llm,
                use_rag,
                transcript_text,
                classification_scanner,
                entities_predicted,
                verification_results,
                triggered_flags_predicted,
                total_score_predicted,
                risk_level_predicted,
                llm_assessment,
                metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                now,
                input_source,
                whisper_model,
                int(skip_verification),
                int(use_llm),
                int(use_rag),
                transcript_text,
                _dump_json(classification_scanner),
                _dump_json(entities_predicted),
                _dump_json(verification_results),
                _dump_json(triggered_flags_predicted),
                total_score_predicted,
                risk_level_predicted,
                _dump_json(llm_assessment) if llm_assessment is not None else None,
                _dump_json(metadata or {}),
            ),
        )
        conn.commit()
    return run_id


def merge_run_metadata(run_id: str, partial: dict[str, Any]) -> None:
    """기존 metadata 와 partial 을 머지(키 단위 덮어쓰기). row 없으면 무시."""
    if not partial:
        return
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT metadata FROM analysis_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return
        current = _load_json(row["metadata"], {})
        if not isinstance(current, dict):
            current = {}
        current.update(partial)
        conn.execute(
            "UPDATE analysis_runs SET metadata = ? WHERE id = ?",
            (_dump_json(current), run_id),
        )
        conn.commit()


def save_transcript_embedding(run_id: str, embedding: list[float], model_name: str) -> None:
    if len(embedding) != _VECTOR_DIMENSION:
        raise ValueError(
            f"임베딩 차원이 {_VECTOR_DIMENSION}이 아닙니다. 실제 차원: {len(embedding)}"
        )
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO transcript_embeddings (run_id, created_at, model_name, embedding)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                model_name = excluded.model_name,
                embedding = excluded.embedding
            """,
            (run_id, _now_iso(), model_name, _dump_json(embedding)),
        )
        conn.commit()


_CLAIM_TTL_SECONDS = 30 * 60  # 30분


def _run_status(row: sqlite3.Row, now_iso: str) -> str:
    """row에서 라벨링 상태를 계산한다."""
    if row["annotated"]:
        return "완료"
    claimed_at = row["claimed_at"]
    if claimed_at and claimed_at > _expire_iso(now_iso):
        return "진행중"
    return "미완료"


def _expire_iso(now_iso: str) -> str:
    from datetime import timedelta
    now = datetime.fromisoformat(now_iso)
    return (now - timedelta(seconds=_CLAIM_TTL_SECONDS)).isoformat()


def list_runs_for_labeling(
    limit: int = 50,
    offset: int = 0,
    status_filter: str | None = None,
) -> list[dict[str, Any]]:
    """
    라벨링 큐용 run 목록을 반환한다.

    status_filter: '미완료' | '진행중' | '완료' | None(전체)
    """
    init_db()
    now = _now_iso()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT
                ar.id,
                ar.created_at,
                ar.classification_scanner,
                ar.total_score_predicted,
                ar.risk_level_predicted,
                ar.transcript_text,
                ar.claimed_by,
                ar.claimed_at,
                ha.labeler,
                (ha.run_id IS NOT NULL) AS annotated
            FROM analysis_runs ar
            LEFT JOIN human_annotations ha ON ha.run_id = ar.id
            ORDER BY ar.created_at ASC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()

    result = []
    for row in rows:
        status = _run_status(row, now)
        if status_filter and status != status_filter:
            continue
        transcript = row["transcript_text"] or ""
        classification = _load_json(row["classification_scanner"], {})
        result.append({
            "id": row["id"],
            "created_at": row["created_at"],
            "transcript_preview": transcript[:120] + ("..." if len(transcript) > 120 else ""),
            "predicted_scam_type": classification.get("scam_type", ""),
            "predicted_confidence": classification.get("confidence", 0.0),
            "total_score_predicted": row["total_score_predicted"],
            "risk_level_predicted": row["risk_level_predicted"],
            "status": status,
            "claimed_by": row["claimed_by"] if status == "진행중" else None,
            "labeler": row["labeler"],
        })
    return result


def claim_run(run_id: str, labeler: str) -> bool:
    """
    run을 특정 라벨러가 클레임한다.
    이미 다른 사람이 클레임 중이면 False 반환.
    """
    init_db()
    now = _now_iso()
    expire_threshold = _expire_iso(now)
    with _connect() as conn:
        # 이미 완료된 run은 클레임 불가
        annotated = conn.execute(
            "SELECT 1 FROM human_annotations WHERE run_id = ?", (run_id,)
        ).fetchone()
        if annotated:
            return False

        # 본인이거나 만료된 클레임이면 덮어쓰기 가능
        result = conn.execute(
            """
            UPDATE analysis_runs
            SET claimed_by = ?, claimed_at = ?
            WHERE id = ?
              AND (claimed_by IS NULL OR claimed_by = ? OR claimed_at <= ?)
            """,
            (labeler, now, run_id, labeler, expire_threshold),
        )
        conn.commit()
        return result.rowcount > 0


def get_next_unannotated_run() -> dict[str, Any] | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
                ar.id,
                ar.created_at,
                ar.classification_scanner,
                ar.total_score_predicted,
                ar.risk_level_predicted,
                ar.transcript_text
            FROM analysis_runs ar
            LEFT JOIN human_annotations ha ON ha.run_id = ar.id
            WHERE ha.run_id IS NULL
            ORDER BY ar.created_at ASC
            LIMIT 1
            """
        ).fetchone()

    if row is None:
        return None

    transcript = row["transcript_text"] or ""
    classification = _load_json(row["classification_scanner"], {})
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "transcript_preview": transcript[:200] + ("..." if len(transcript) > 200 else ""),
        "predicted_scam_type": classification.get("scam_type", ""),
        "predicted_confidence": classification.get("confidence", 0.0),
        "total_score_predicted": row["total_score_predicted"],
        "risk_level_predicted": row["risk_level_predicted"],
    }


def get_run_detail(run_id: str) -> dict[str, Any] | None:
    init_db()
    with _connect() as conn:
        run_row = conn.execute(
            "SELECT * FROM analysis_runs WHERE id = ?",
            (run_id,),
        ).fetchone()
        if run_row is None:
            return None
        annotation_row = conn.execute(
            "SELECT * FROM human_annotations WHERE run_id = ?",
            (run_id,),
        ).fetchone()

    run = {
        "id": run_row["id"],
        "created_at": run_row["created_at"],
        "input_source": run_row["input_source"],
        "whisper_model": run_row["whisper_model"],
        "skip_verification": bool(run_row["skip_verification"]),
        "use_llm": bool(run_row["use_llm"]),
        "use_rag": bool(run_row["use_rag"]),
        "transcript_text": run_row["transcript_text"],
        "transcript_corrected_text": run_row["transcript_corrected_text"],
        "classification_scanner": _load_json(run_row["classification_scanner"], {}),
        "entities_predicted": _load_json(run_row["entities_predicted"], []),
        "verification_results": _load_json(run_row["verification_results"], []),
        "triggered_flags_predicted": _load_json(run_row["triggered_flags_predicted"], []),
        "total_score_predicted": run_row["total_score_predicted"],
        "risk_level_predicted": run_row["risk_level_predicted"],
        "llm_assessment": _load_json(run_row["llm_assessment"], None),
        "metadata": _load_json(run_row["metadata"], {}),
    }

    annotation = None
    if annotation_row is not None:
        annotation = {
            "run_id": annotation_row["run_id"],
            "created_at": annotation_row["created_at"],
            "updated_at": annotation_row["updated_at"],
            "labeler": annotation_row["labeler"],
            "scam_type_gt": annotation_row["scam_type_gt"],
            "entities_gt": _load_json(annotation_row["entities_gt"], []),
            "triggered_flags_gt": _load_json(annotation_row["triggered_flags_gt"], []),
            "transcript_corrected_text": annotation_row["transcript_corrected_text"],
            "stt_quality": annotation_row["stt_quality"],
            "notes": annotation_row["notes"] or "",
            "content_label": annotation_row["content_label"] or "",
            "sample_kind": annotation_row["sample_kind"] or "",
            "source_ref": annotation_row["source_ref"],
        }

    return {"run": run, "annotation": annotation}


def upsert_human_annotation(
    *,
    run_id: str,
    scam_type_gt: str,
    entities_gt: list[dict[str, Any]],
    triggered_flags_gt: list[dict[str, Any]],
    labeler: str | None = None,
    transcript_corrected_text: str | None = None,
    stt_quality: int | None = None,
    notes: str = "",
    content_label: str = "",
    sample_kind: str = "",
    source_ref: str | None = None,
) -> dict[str, Any]:
    init_db()
    with _connect() as conn:
        existing = conn.execute(
            "SELECT created_at FROM human_annotations WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        created_at = existing["created_at"] if existing is not None else _now_iso()
        updated_at = _now_iso()
        conn.execute(
            """
            INSERT INTO human_annotations (
                run_id,
                created_at,
                updated_at,
                labeler,
                scam_type_gt,
                entities_gt,
                triggered_flags_gt,
                transcript_corrected_text,
                stt_quality,
                notes,
                content_label,
                sample_kind,
                source_ref
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id) DO UPDATE SET
                updated_at = excluded.updated_at,
                labeler = excluded.labeler,
                scam_type_gt = excluded.scam_type_gt,
                entities_gt = excluded.entities_gt,
                triggered_flags_gt = excluded.triggered_flags_gt,
                transcript_corrected_text = excluded.transcript_corrected_text,
                stt_quality = excluded.stt_quality,
                notes = excluded.notes,
                content_label = excluded.content_label,
                sample_kind = excluded.sample_kind,
                source_ref = excluded.source_ref
            """,
            (
                run_id,
                created_at,
                updated_at,
                labeler,
                scam_type_gt,
                _dump_json(entities_gt),
                _dump_json(triggered_flags_gt),
                transcript_corrected_text,
                stt_quality,
                notes,
                content_label,
                sample_kind,
                source_ref,
            ),
        )
        conn.commit()

    return {
        "run_id": run_id,
        "created_at": created_at,
        "updated_at": updated_at,
        "labeler": labeler,
        "scam_type_gt": scam_type_gt,
        "entities_gt": entities_gt,
        "triggered_flags_gt": triggered_flags_gt,
        "transcript_corrected_text": transcript_corrected_text,
        "stt_quality": stt_quality,
        "notes": notes,
        "content_label": content_label,
        "sample_kind": sample_kind,
        "source_ref": source_ref,
    }


def fetch_annotated_pairs(scam_type: str | None = None) -> list[dict[str, Any]]:
    init_db()
    query = """
        SELECT
            ar.id,
            ar.created_at,
            ar.transcript_text,
            ar.classification_scanner,
            ar.entities_predicted,
            ar.triggered_flags_predicted,
            ha.scam_type_gt,
            ha.entities_gt,
            ha.triggered_flags_gt,
            ha.labeler,
            ha.transcript_corrected_text,
            ha.stt_quality,
            ha.content_label,
            ha.sample_kind,
            ha.source_ref
        FROM analysis_runs ar
        INNER JOIN human_annotations ha ON ha.run_id = ar.id
        WHERE (? IS NULL OR ha.scam_type_gt = ?)
        ORDER BY ar.created_at DESC
    """
    with _connect() as conn:
        rows = conn.execute(query, (scam_type, scam_type)).fetchall()

    return [
        {
            "run_id": row["id"],
            "created_at": row["created_at"],
            "transcript_text": row["transcript_text"],
            "classification_scanner": _load_json(row["classification_scanner"], {}),
            "entities_predicted": _load_json(row["entities_predicted"], []),
            "triggered_flags_predicted": _load_json(row["triggered_flags_predicted"], []),
            "scam_type_gt": row["scam_type_gt"],
            "entities_gt": _load_json(row["entities_gt"], []),
            "triggered_flags_gt": _load_json(row["triggered_flags_gt"], []),
            "labeler": row["labeler"],
            "transcript_corrected_text": row["transcript_corrected_text"],
            "stt_quality": row["stt_quality"],
            "content_label": row["content_label"] or "",
            "sample_kind": row["sample_kind"] or "",
            "source_ref": row["source_ref"],
        }
        for row in rows
    ]


def get_dashboard_stats() -> dict[str, Any]:
    """대시보드용 집계 통계를 반환한다."""
    init_db()
    now = _now_iso()
    expire_threshold = _expire_iso(now)
    with _connect() as conn:
        total = conn.execute("SELECT COUNT(*) FROM analysis_runs").fetchone()[0]
        labeled = conn.execute("SELECT COUNT(*) FROM human_annotations").fetchone()[0]
        in_progress = conn.execute(
            "SELECT COUNT(*) FROM analysis_runs WHERE claimed_by IS NOT NULL AND claimed_at > ? AND id NOT IN (SELECT run_id FROM human_annotations)",
            (expire_threshold,),
        ).fetchone()[0]

        # 스캠 유형 분포 (예측 기준)
        type_rows = conn.execute(
            """
            SELECT
                json_extract(classification_scanner, '$.scam_type') AS scam_type,
                COUNT(*) AS cnt
            FROM analysis_runs
            GROUP BY scam_type
            ORDER BY cnt DESC
            """
        ).fetchall()

        # 위험도 분포
        risk_rows = conn.execute(
            """
            SELECT risk_level_predicted, COUNT(*) AS cnt
            FROM analysis_runs
            GROUP BY risk_level_predicted
            ORDER BY cnt DESC
            """
        ).fetchall()

        # 날짜별 run 수 (최근 30일)
        daily_rows = conn.execute(
            """
            SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS cnt
            FROM analysis_runs
            WHERE created_at >= date('now', '-30 days')
            GROUP BY day
            ORDER BY day ASC
            """
        ).fetchall()

        # 스캠 유형별 라벨 완료 수
        type_labeled_rows = conn.execute(
            """
            SELECT ha.scam_type_gt AS scam_type, COUNT(*) AS cnt
            FROM human_annotations ha
            GROUP BY scam_type_gt
            ORDER BY cnt DESC
            """
        ).fetchall()

    return {
        "total_runs": total,
        "labeled_runs": labeled,
        "unlabeled_runs": total - labeled - in_progress,
        "in_progress_runs": in_progress,
        "scam_type_distribution": [
            {"name": r["scam_type"] or "미분류", "count": r["cnt"]} for r in type_rows
        ],
        "risk_level_distribution": [
            {"name": r["risk_level_predicted"], "count": r["cnt"]} for r in risk_rows
        ],
        "daily_runs": [
            {"date": r["day"], "count": r["cnt"]} for r in daily_rows
        ],
        "labeled_by_type": [
            {"name": r["scam_type"], "count": r["cnt"]} for r in type_labeled_rows
        ],
    }


def search_runs(
    query: str | None = None,
    scam_type: str | None = None,
    risk_level: str | None = None,
    labeled: bool | None = None,
    limit: int = 30,
    offset: int = 0,
) -> dict[str, Any]:
    """DB 브라우저용 run 검색."""
    init_db()
    conditions = []
    params: list[Any] = []

    if query:
        conditions.append("ar.transcript_text LIKE ?")
        params.append(f"%{query}%")
    if scam_type:
        conditions.append("json_extract(ar.classification_scanner, '$.scam_type') = ?")
        params.append(scam_type)
    if risk_level:
        conditions.append("ar.risk_level_predicted = ?")
        params.append(risk_level)
    if labeled is True:
        conditions.append("ha.run_id IS NOT NULL")
    elif labeled is False:
        conditions.append("ha.run_id IS NULL")

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    with _connect() as conn:
        count_row = conn.execute(
            f"SELECT COUNT(*) FROM analysis_runs ar LEFT JOIN human_annotations ha ON ha.run_id = ar.id {where}",
            params,
        ).fetchone()
        total = count_row[0]

        rows = conn.execute(
            f"""
            SELECT
                ar.id,
                ar.created_at,
                ar.input_source,
                ar.classification_scanner,
                ar.total_score_predicted,
                ar.risk_level_predicted,
                ar.transcript_text,
                ar.use_llm,
                (ha.run_id IS NOT NULL) AS labeled,
                ha.scam_type_gt,
                ha.labeler
            FROM analysis_runs ar
            LEFT JOIN human_annotations ha ON ha.run_id = ar.id
            {where}
            ORDER BY ar.created_at DESC
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        ).fetchall()

    items = []
    for row in rows:
        clf = _load_json(row["classification_scanner"], {})
        transcript = row["transcript_text"] or ""
        items.append({
            "id": row["id"],
            "created_at": row["created_at"],
            "input_source": row["input_source"],
            "predicted_scam_type": clf.get("scam_type", ""),
            "predicted_confidence": clf.get("confidence", 0.0),
            "total_score_predicted": row["total_score_predicted"],
            "risk_level_predicted": row["risk_level_predicted"],
            "transcript_preview": transcript[:100] + ("..." if len(transcript) > 100 else ""),
            "use_llm": bool(row["use_llm"]),
            "labeled": bool(row["labeled"]),
            "scam_type_gt": row["scam_type_gt"],
            "labeler": row["labeler"],
        })

    return {"total": total, "items": items, "limit": limit, "offset": offset}


def _l2_distance(left: list[float], right: list[float]) -> float:
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)))


def search_similar_annotated_runs(
    query_embedding: list[float],
    *,
    limit: int = 3,
    scam_type: str | None = None,
) -> list[dict[str, Any]]:
    if not database_configured():
        return []

    init_db()
    query = """
        SELECT
            ar.id,
            ar.created_at,
            ar.transcript_text,
            ar.classification_scanner,
            ha.scam_type_gt,
            ha.entities_gt,
            ha.triggered_flags_gt,
            ha.transcript_corrected_text,
            te.model_name,
            te.embedding
        FROM transcript_embeddings te
        INNER JOIN analysis_runs ar ON ar.id = te.run_id
        INNER JOIN human_annotations ha ON ha.run_id = ar.id
        WHERE (? IS NULL OR ha.scam_type_gt = ?)
    """
    with _connect() as conn:
        rows = conn.execute(query, (scam_type, scam_type)).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        embedding = _load_json(row["embedding"], [])
        if len(embedding) != len(query_embedding):
            continue
        transcript = row["transcript_corrected_text"] or row["transcript_text"] or ""
        classification = _load_json(row["classification_scanner"], {})
        results.append(
            {
                "run_id": row["id"],
                "created_at": row["created_at"],
                "distance": _l2_distance(query_embedding, embedding),
                "model_name": row["model_name"],
                "predicted_scam_type": classification.get("scam_type", ""),
                "scam_type_gt": row["scam_type_gt"],
                "transcript_excerpt": transcript[:240] + ("..." if len(transcript) > 240 else ""),
                "entities_gt": _load_json(row["entities_gt"], []),
                "triggered_flags_gt": _load_json(row["triggered_flags_gt"], []),
            }
        )

    results.sort(key=lambda item: item["distance"])
    return results[:limit]


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

