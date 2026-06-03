from __future__ import annotations

import os
import threading
import uuid
from typing import Any

from pgvector.psycopg import register_vector
from psycopg import Connection, connect
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from db import sqlite_repository

_TRUE_VALUES = {"1", "true", "yes", "on"}
_VECTOR_DIMENSION = 384
_SCHEMA_READY = False
_SCHEMA_LOCK = threading.Lock()


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def get_database_url(required: bool = False) -> str:
    value = os.getenv("SCAMGUARDIAN_DATABASE_URL", "").strip()
    if required and not value:
        raise EnvironmentError("SCAMGUARDIAN_DATABASE_URL이 설정되지 않았습니다.")
    return value


def get_db_backend() -> str:
    if sqlite_repository.database_configured():
        return "sqlite"
    if get_database_url(required=False):
        return "postgres"
    return ""


def database_configured() -> bool:
    return bool(get_db_backend())


def persistence_enabled() -> bool:
    return database_configured() and _env_flag("SCAMGUARDIAN_PERSIST_RUNS", default=False)


def _connect() -> Connection[Any]:
    conn = connect(get_database_url(required=True), row_factory=dict_row, autocommit=True)
    register_vector(conn)
    return conn


def _ensure_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return

        statements = [
            "CREATE EXTENSION IF NOT EXISTS vector",
            """
            CREATE TABLE IF NOT EXISTS analysis_runs (
                id UUID PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                input_source TEXT NOT NULL,
                whisper_model TEXT NOT NULL,
                skip_verification BOOLEAN NOT NULL,
                use_llm BOOLEAN NOT NULL,
                use_rag BOOLEAN NOT NULL DEFAULT FALSE,
                transcript_text TEXT NOT NULL,
                transcript_corrected_text TEXT,
                classification_scanner JSONB NOT NULL,
                entities_predicted JSONB NOT NULL,
                verification_results JSONB NOT NULL,
                triggered_flags_predicted JSONB NOT NULL,
                total_score_predicted INTEGER NOT NULL,
                risk_level_predicted TEXT NOT NULL,
                llm_assessment JSONB,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS human_annotations (
                run_id UUID PRIMARY KEY REFERENCES analysis_runs(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                labeler TEXT,
                scam_type_gt TEXT NOT NULL,
                entities_gt JSONB NOT NULL,
                triggered_flags_gt JSONB NOT NULL,
                transcript_corrected_text TEXT,
                stt_quality INTEGER,
                notes TEXT NOT NULL DEFAULT '',
                content_label TEXT,
                sample_kind TEXT,
                source_ref TEXT
            )
            """,
            # content_label 재설계 마이그레이션 — 기존 테이블에 컬럼 추가 (idempotent)
            "ALTER TABLE human_annotations ADD COLUMN IF NOT EXISTS content_label TEXT",
            "ALTER TABLE human_annotations ADD COLUMN IF NOT EXISTS sample_kind TEXT",
            "ALTER TABLE human_annotations ADD COLUMN IF NOT EXISTS source_ref TEXT",
            f"""
            CREATE TABLE IF NOT EXISTS transcript_embeddings (
                run_id UUID PRIMARY KEY REFERENCES analysis_runs(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                model_name TEXT NOT NULL,
                embedding VECTOR({_VECTOR_DIMENSION}) NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS scam_type_catalog (
                name TEXT PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                description TEXT NOT NULL DEFAULT '',
                labels JSONB NOT NULL DEFAULT '[]'::jsonb
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_analysis_runs_created_at ON analysis_runs(created_at DESC)",
            """
            CREATE INDEX IF NOT EXISTS idx_transcript_embeddings_embedding
            ON transcript_embeddings USING ivfflat (embedding vector_l2_ops)
            """,
        ]

        try:
            with _connect() as conn:
                for statement in statements:
                    conn.execute(statement)
        except Exception as exc:
            raise EnvironmentError(
                "Postgres 초기화에 실패했습니다. pgvector 확장 설치와 "
                "SCAMGUARDIAN_DATABASE_URL 설정을 확인해주세요."
            ) from exc

        _SCHEMA_READY = True


def init_db() -> None:
    backend = get_db_backend()
    if not backend:
        return
    if backend == "sqlite":
        sqlite_repository.init_db()
        return
    _ensure_schema()


def _require_sqlite_for_admin_users() -> None:
    if get_db_backend() != "sqlite":
        raise NotImplementedError("admin_users(마스터 승인)는 현재 SQLite 백엔드만 지원합니다.")


def upsert_access_request(email: str) -> dict[str, Any]:
    _require_sqlite_for_admin_users()
    return sqlite_repository.upsert_access_request(email)


def get_admin_user(email: str) -> dict[str, Any] | None:
    _require_sqlite_for_admin_users()
    return sqlite_repository.get_admin_user(email)


def list_admin_users() -> list[dict[str, Any]]:
    _require_sqlite_for_admin_users()
    return sqlite_repository.list_admin_users()


def set_admin_user_status(email: str, status: str, decided_by: str | None = None) -> dict[str, Any] | None:
    _require_sqlite_for_admin_users()
    return sqlite_repository.set_admin_user_status(email, status, decided_by)


def list_custom_scam_types() -> list[dict[str, Any]]:
    if get_db_backend() == "sqlite":
        return sqlite_repository.list_custom_scam_types()

    _ensure_schema()
    query = """
        SELECT name, created_at, updated_at, description, labels
        FROM scam_type_catalog
        ORDER BY created_at ASC, name ASC
    """
    with _connect() as conn:
        rows = conn.execute(query).fetchall()

    return [
        {
            "name": row["name"],
            "created_at": row["created_at"].isoformat(),
            "updated_at": row["updated_at"].isoformat(),
            "description": row["description"] or "",
            "labels": row["labels"] or [],
        }
        for row in rows
    ]


def upsert_custom_scam_type(
    *,
    name: str,
    description: str = "",
    labels: list[str] | None = None,
) -> dict[str, Any]:
    if get_db_backend() == "sqlite":
        return sqlite_repository.upsert_custom_scam_type(
            name=name,
            description=description,
            labels=labels,
        )

    _ensure_schema()
    normalized_labels = [str(label).strip() for label in (labels or []) if str(label).strip()]
    query = """
        INSERT INTO scam_type_catalog (name, description, labels)
        VALUES (%s, %s, %s)
        ON CONFLICT (name)
        DO UPDATE SET
            updated_at = NOW(),
            description = EXCLUDED.description,
            labels = EXCLUDED.labels
        RETURNING name, created_at, updated_at, description, labels
    """
    with _connect() as conn:
        row = conn.execute(
            query,
            (name, description.strip(), Jsonb(normalized_labels)),
        ).fetchone()

    return {
        "name": row["name"],
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "description": row["description"] or "",
        "labels": row["labels"] or [],
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
    if get_db_backend() == "sqlite":
        return sqlite_repository.save_analysis_run(
            input_source=input_source,
            whisper_model=whisper_model,
            skip_verification=skip_verification,
            use_llm=use_llm,
            use_rag=use_rag,
            transcript_text=transcript_text,
            classification_scanner=classification_scanner,
            entities_predicted=entities_predicted,
            verification_results=verification_results,
            triggered_flags_predicted=triggered_flags_predicted,
            total_score_predicted=total_score_predicted,
            risk_level_predicted=risk_level_predicted,
            llm_assessment=llm_assessment,
            metadata=metadata,
        )
    _ensure_schema()
    run_id = str(uuid.uuid4())
    payload = {
        "id": run_id,
        "input_source": input_source,
        "whisper_model": whisper_model,
        "skip_verification": skip_verification,
        "use_llm": use_llm,
        "use_rag": use_rag,
        "transcript_text": transcript_text,
        "classification_scanner": Jsonb(classification_scanner),
        "entities_predicted": Jsonb(entities_predicted),
        "verification_results": Jsonb(verification_results),
        "triggered_flags_predicted": Jsonb(triggered_flags_predicted),
        "total_score_predicted": total_score_predicted,
        "risk_level_predicted": risk_level_predicted,
        "llm_assessment": Jsonb(llm_assessment) if llm_assessment is not None else None,
        "metadata": Jsonb(metadata or {}),
    }

    query = """
        INSERT INTO analysis_runs (
            id,
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
        ) VALUES (
            %(id)s,
            %(input_source)s,
            %(whisper_model)s,
            %(skip_verification)s,
            %(use_llm)s,
            %(use_rag)s,
            %(transcript_text)s,
            %(classification_scanner)s,
            %(entities_predicted)s,
            %(verification_results)s,
            %(triggered_flags_predicted)s,
            %(total_score_predicted)s,
            %(risk_level_predicted)s,
            %(llm_assessment)s,
            %(metadata)s
        )
    """
    with _connect() as conn:
        conn.execute(query, payload)
    return run_id


def merge_run_metadata(run_id: str, partial: dict[str, Any]) -> None:
    """기존 metadata 와 partial 을 머지. SQLite/Postgres 라우팅."""
    if not partial:
        return
    if get_db_backend() == "sqlite":
        sqlite_repository.merge_run_metadata(run_id, partial)
        return
    _ensure_schema()
    with _connect() as conn:
        row = conn.execute(
            "SELECT metadata FROM analysis_runs WHERE id = %s",
            (run_id,),
        ).fetchone()
        if row is None:
            return
        current = row["metadata"] or {}
        if not isinstance(current, dict):
            current = {}
        current.update(partial)
        conn.execute(
            "UPDATE analysis_runs SET metadata = %s WHERE id = %s",
            (Jsonb(current), run_id),
        )


def save_transcript_embedding(run_id: str, embedding: list[float], model_name: str) -> None:
    if get_db_backend() == "sqlite":
        sqlite_repository.save_transcript_embedding(run_id, embedding, model_name)
        return
    if len(embedding) != _VECTOR_DIMENSION:
        raise ValueError(
            f"임베딩 차원이 {_VECTOR_DIMENSION}이 아닙니다. 실제 차원: {len(embedding)}"
        )
    _ensure_schema()
    query = """
        INSERT INTO transcript_embeddings (run_id, model_name, embedding)
        VALUES (%s, %s, %s)
        ON CONFLICT (run_id)
        DO UPDATE SET
            model_name = EXCLUDED.model_name,
            embedding = EXCLUDED.embedding
    """
    with _connect() as conn:
        conn.execute(query, (run_id, model_name, embedding))


def list_runs_for_labeling(
    limit: int = 50,
    offset: int = 0,
    status_filter: str | None = None,
) -> list[dict[str, Any]]:
    if get_db_backend() == "sqlite":
        return sqlite_repository.list_runs_for_labeling(limit=limit, offset=offset, status_filter=status_filter)
    # Postgres 미구현 — SQLite와 동일한 인터페이스 제공 예정
    raise NotImplementedError("Postgres list_runs_for_labeling 미구현")


def claim_run(run_id: str, labeler: str) -> bool:
    if get_db_backend() == "sqlite":
        return sqlite_repository.claim_run(run_id, labeler)
    raise NotImplementedError("Postgres claim_run 미구현")


def get_dashboard_stats() -> dict[str, Any]:
    if get_db_backend() == "sqlite":
        return sqlite_repository.get_dashboard_stats()
    raise NotImplementedError("Postgres get_dashboard_stats 미구현")


def search_runs(
    query: str | None = None,
    scam_type: str | None = None,
    risk_level: str | None = None,
    labeled: bool | None = None,
    limit: int = 30,
    offset: int = 0,
) -> dict[str, Any]:
    if get_db_backend() == "sqlite":
        return sqlite_repository.search_runs(
            query=query,
            scam_type=scam_type,
            risk_level=risk_level,
            labeled=labeled,
            limit=limit,
            offset=offset,
        )
    raise NotImplementedError("Postgres search_runs 미구현")


def get_next_unannotated_run() -> dict[str, Any] | None:
    if get_db_backend() == "sqlite":
        return sqlite_repository.get_next_unannotated_run()
    _ensure_schema()
    query = """
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
    with _connect() as conn:
        row = conn.execute(query).fetchone()

    if row is None:
        return None

    transcript = row["transcript_text"] or ""
    classification = row["classification_scanner"] or {}
    return {
        "id": str(row["id"]),
        "created_at": row["created_at"].isoformat(),
        "transcript_preview": transcript[:200] + ("..." if len(transcript) > 200 else ""),
        "predicted_scam_type": classification.get("scam_type", ""),
        "predicted_confidence": classification.get("confidence", 0.0),
        "total_score_predicted": row["total_score_predicted"],
        "risk_level_predicted": row["risk_level_predicted"],
    }


def get_run_detail(run_id: str) -> dict[str, Any] | None:
    if get_db_backend() == "sqlite":
        return sqlite_repository.get_run_detail(run_id)
    _ensure_schema()
    run_query = """
        SELECT
            id,
            created_at,
            input_source,
            whisper_model,
            skip_verification,
            use_llm,
            use_rag,
            transcript_text,
            transcript_corrected_text,
            classification_scanner,
            entities_predicted,
            verification_results,
            triggered_flags_predicted,
            total_score_predicted,
            risk_level_predicted,
            llm_assessment,
            metadata
        FROM analysis_runs
        WHERE id = %s
    """
    annotation_query = """
        SELECT
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
        FROM human_annotations
        WHERE run_id = %s
    """

    with _connect() as conn:
        run_row = conn.execute(run_query, (run_id,)).fetchone()
        if run_row is None:
            return None
        annotation_row = conn.execute(annotation_query, (run_id,)).fetchone()

    run = {
        "id": str(run_row["id"]),
        "created_at": run_row["created_at"].isoformat(),
        "input_source": run_row["input_source"],
        "whisper_model": run_row["whisper_model"],
        "skip_verification": run_row["skip_verification"],
        "use_llm": run_row["use_llm"],
        "use_rag": run_row["use_rag"],
        "transcript_text": run_row["transcript_text"],
        "transcript_corrected_text": run_row["transcript_corrected_text"],
        "classification_scanner": run_row["classification_scanner"] or {},
        "entities_predicted": run_row["entities_predicted"] or [],
        "verification_results": run_row["verification_results"] or [],
        "triggered_flags_predicted": run_row["triggered_flags_predicted"] or [],
        "total_score_predicted": run_row["total_score_predicted"],
        "risk_level_predicted": run_row["risk_level_predicted"],
        "llm_assessment": run_row["llm_assessment"],
        "metadata": run_row["metadata"] or {},
    }

    annotation = None
    if annotation_row is not None:
        annotation = {
            "run_id": str(annotation_row["run_id"]),
            "created_at": annotation_row["created_at"].isoformat(),
            "updated_at": annotation_row["updated_at"].isoformat(),
            "labeler": annotation_row["labeler"],
            "scam_type_gt": annotation_row["scam_type_gt"],
            "entities_gt": annotation_row["entities_gt"] or [],
            "triggered_flags_gt": annotation_row["triggered_flags_gt"] or [],
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
    if get_db_backend() == "sqlite":
        return sqlite_repository.upsert_human_annotation(
            run_id=run_id,
            scam_type_gt=scam_type_gt,
            entities_gt=entities_gt,
            triggered_flags_gt=triggered_flags_gt,
            labeler=labeler,
            transcript_corrected_text=transcript_corrected_text,
            stt_quality=stt_quality,
            notes=notes,
            content_label=content_label,
            sample_kind=sample_kind,
            source_ref=source_ref,
        )
    _ensure_schema()
    query = """
        INSERT INTO human_annotations (
            run_id,
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
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (run_id)
        DO UPDATE SET
            updated_at = NOW(),
            labeler = EXCLUDED.labeler,
            scam_type_gt = EXCLUDED.scam_type_gt,
            entities_gt = EXCLUDED.entities_gt,
            triggered_flags_gt = EXCLUDED.triggered_flags_gt,
            transcript_corrected_text = EXCLUDED.transcript_corrected_text,
            stt_quality = EXCLUDED.stt_quality,
            notes = EXCLUDED.notes,
            content_label = EXCLUDED.content_label,
            sample_kind = EXCLUDED.sample_kind,
            source_ref = EXCLUDED.source_ref
        RETURNING
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
    """
    params = (
        run_id,
        labeler,
        scam_type_gt,
        Jsonb(entities_gt),
        Jsonb(triggered_flags_gt),
        transcript_corrected_text,
        stt_quality,
        notes,
        content_label,
        sample_kind,
        source_ref,
    )
    with _connect() as conn:
        row = conn.execute(query, params).fetchone()

    return {
        "run_id": str(row["run_id"]),
        "created_at": row["created_at"].isoformat(),
        "updated_at": row["updated_at"].isoformat(),
        "labeler": row["labeler"],
        "scam_type_gt": row["scam_type_gt"],
        "entities_gt": row["entities_gt"] or [],
        "triggered_flags_gt": row["triggered_flags_gt"] or [],
        "transcript_corrected_text": row["transcript_corrected_text"],
        "stt_quality": row["stt_quality"],
        "notes": row["notes"] or "",
        "content_label": row["content_label"] or "",
        "sample_kind": row["sample_kind"] or "",
        "source_ref": row["source_ref"],
    }


def fetch_annotated_pairs(scam_type: str | None = None) -> list[dict[str, Any]]:
    if get_db_backend() == "sqlite":
        return sqlite_repository.fetch_annotated_pairs(scam_type)
    _ensure_schema()
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
            ha.transcript_corrected_text,
            ha.stt_quality,
            ha.content_label,
            ha.sample_kind,
            ha.source_ref
        FROM analysis_runs ar
        INNER JOIN human_annotations ha ON ha.run_id = ar.id
        WHERE (%s IS NULL OR ha.scam_type_gt = %s)
        ORDER BY ar.created_at DESC
    """
    with _connect() as conn:
        rows = conn.execute(query, (scam_type, scam_type)).fetchall()

    return [
        {
            "run_id": str(row["id"]),
            "created_at": row["created_at"].isoformat(),
            "transcript_text": row["transcript_text"],
            "classification_scanner": row["classification_scanner"] or {},
            "entities_predicted": row["entities_predicted"] or [],
            "triggered_flags_predicted": row["triggered_flags_predicted"] or [],
            "scam_type_gt": row["scam_type_gt"],
            "entities_gt": row["entities_gt"] or [],
            "triggered_flags_gt": row["triggered_flags_gt"] or [],
            "transcript_corrected_text": row["transcript_corrected_text"],
            "stt_quality": row["stt_quality"],
            "content_label": row["content_label"] or "",
            "sample_kind": row["sample_kind"] or "",
            "source_ref": row["source_ref"],
        }
        for row in rows
    ]


def search_similar_annotated_runs(
    query_embedding: list[float],
    *,
    limit: int = 3,
    scam_type: str | None = None,
) -> list[dict[str, Any]]:
    if get_db_backend() == "sqlite":
        return sqlite_repository.search_similar_annotated_runs(
            query_embedding,
            limit=limit,
            scam_type=scam_type,
        )
    if not database_configured():
        return []

    _ensure_schema()
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
            te.embedding <-> %s AS distance
        FROM transcript_embeddings te
        INNER JOIN analysis_runs ar ON ar.id = te.run_id
        INNER JOIN human_annotations ha ON ha.run_id = ar.id
        WHERE (%s IS NULL OR ha.scam_type_gt = %s)
        ORDER BY te.embedding <-> %s
        LIMIT %s
    """
    params = (query_embedding, scam_type, scam_type, query_embedding, limit)
    with _connect() as conn:
        rows = conn.execute(query, params).fetchall()

    results: list[dict[str, Any]] = []
    for row in rows:
        transcript = row["transcript_corrected_text"] or row["transcript_text"] or ""
        classification = row["classification_scanner"] or {}
        results.append(
            {
                "run_id": str(row["id"]),
                "created_at": row["created_at"].isoformat(),
                "distance": float(row["distance"]),
                "model_name": row["model_name"],
                "predicted_scam_type": classification.get("scam_type", ""),
                "scam_type_gt": row["scam_type_gt"],
                "transcript_excerpt": transcript[:240] + ("..." if len(transcript) > 240 else ""),
                "entities_gt": row["entities_gt"] or [],
                "triggered_flags_gt": row["triggered_flags_gt"] or [],
            }
        )
    return results



# ──────────────────────────────────
# v3 platform facade — 현재 SQLite 만 지원 (Postgres 미지원 시 NotImplementedError)
# ──────────────────────────────────
def _require_sqlite(name: str) -> None:
    if get_db_backend() != "sqlite":
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
    if get_db_backend() != "sqlite":
        return  # 비용 추적은 사일런트 (Postgres 환경 운영용)
    sqlite_repository.insert_cost_event(**kwargs)


def aggregate_costs(*, days: int = 30):
    _require_sqlite("aggregate_costs")
    return sqlite_repository.aggregate_costs(days=days)


def insert_request_log(**kwargs) -> None:
    if get_db_backend() != "sqlite":
        return
    sqlite_repository.insert_request_log(**kwargs)


def request_log_recent(limit: int = 100):
    _require_sqlite("request_log_recent")
    return sqlite_repository.request_log_recent(limit)


def request_log_summary(*, hours: int = 24):
    _require_sqlite("request_log_summary")
    return sqlite_repository.request_log_summary(hours=hours)
