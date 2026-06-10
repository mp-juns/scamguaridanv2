"""
ScamGuardian — SQLite: 분석 run·라벨링·임베딩·검색·대시보드

analysis_runs / human_annotations / transcript_embeddings / scam_type_catalog.
연결·스키마는 db.sqlite_core, platform(API key·비용) 은 db.sqlite_platform.
외부 소비자는 `db.sqlite_repository` facade 를 통해 import 한다.
"""

from __future__ import annotations

import math
import sqlite3
import uuid
from datetime import datetime
from typing import Any

from db.sqlite_core import (
    _VECTOR_DIMENSION,
    _connect,
    _dump_json,
    _load_json,
    _now_iso,
    database_configured,
    init_db,
)


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
