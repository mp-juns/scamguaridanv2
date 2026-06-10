"""
ScamGuardian — SQLite repository (facade)

구현은 세 모듈로 분리됨:
- db.sqlite_core     — 경로·커넥션·init_db(스키마+마이그레이션)·JSON 헬퍼
- db.sqlite_runs     — 분석 run·라벨링·임베딩·검색·대시보드
- db.sqlite_platform — API key·admin 승인·비용 ledger·요청 로그

외부 소비자(db.repository facade·테스트)는 기존처럼 `db.sqlite_repository`
경로로 모든 심볼에 접근한다.
"""

from __future__ import annotations

from db.sqlite_core import (  # noqa: F401
    _VECTOR_DIMENSION,
    _connect,
    _dump_json,
    _load_json,
    _now_iso,
    database_configured,
    get_sqlite_path,
    init_db,
)
from db.sqlite_runs import (  # noqa: F401
    claim_run,
    fetch_annotated_pairs,
    get_dashboard_stats,
    get_next_unannotated_run,
    get_run_detail,
    list_custom_scam_types,
    list_runs_for_labeling,
    merge_run_metadata,
    save_analysis_run,
    save_transcript_embedding,
    search_runs,
    search_similar_annotated_runs,
    upsert_custom_scam_type,
    upsert_human_annotation,
)
from db.sqlite_platform import (  # noqa: F401
    aggregate_costs,
    create_api_key,
    get_admin_user,
    get_api_key_by_hash,
    get_monthly_usd_for_key,
    insert_cost_event,
    insert_request_log,
    list_admin_users,
    list_api_keys,
    request_log_recent,
    request_log_summary,
    revoke_api_key,
    set_admin_user_status,
    touch_api_key_usage,
    upsert_access_request,
)
