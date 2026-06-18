"""
pytest 공통 픽스처. 외부 API 호출 없이 단위 테스트 실행 가능하도록 SQLite 임시 DB
+ 환경변수 격리 + DB 스키마 초기화.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    """모든 테스트에 격리된 SQLite path. 외부 API key 는 비워서 실수 방지."""
    db_path = tmp_path / "test.sqlite3"
    monkeypatch.setenv("SCAMGUARDIAN_SQLITE_PATH", str(db_path))
    # 외부 호출 막기 — 테스트가 실수로 진짜 API 부르면 환경변수 빈 상태에서 일찍 죽음
    for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "SERPER_API_KEY", "VIRUSTOTAL_API_KEY"):
        if not os.getenv(f"_KEEP_{var}"):
            monkeypatch.delenv(var, raising=False)
    # active_models 격리 — 개발자가 레포에서 활성화해 둔 fine-tuned 모델(gate 등)이
    # 테스트의 base/fallback 경로 검증을 오염시키지 않도록 빈 포인터로 교체
    from pipeline import active_models
    monkeypatch.setattr(active_models, "ACTIVE_POINTER", tmp_path / "active_models.json")
    active_models.invalidate()
    yield
    active_models.invalidate()


@pytest.fixture
def sqlite_init():
    """DB 스키마 초기화 — 새 DB path 에 테이블 생성."""
    from db import sqlite_repository
    sqlite_repository.init_db()
    yield sqlite_repository
