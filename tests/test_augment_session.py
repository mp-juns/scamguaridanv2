"""증강 세션 라이프사이클 — FAKE 모드(API 비용 0)로 플럼빙 검증."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest


def _write_seeds(path: Path) -> None:
    seeds = [
        {"text": "취업 보증금 50만원 입금하면 채용", "content_label": "scam_attempt", "scam_type": "취업·알바 사기"},
        {"text": "코인 상장 전 선점 기회 지금 입금", "content_label": "scam_attempt", "scam_type": "코인 사기"},
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fp:
        for s in seeds:
            fp.write(json.dumps(s, ensure_ascii=False) + "\n")


def test_runner_fake_generates_output(tmp_path, monkeypatch):
    """FAKE 러너가 씨앗 2개 × 변형 2개 = 4행을 생성하고 done 메트릭을 남긴다."""
    from training import augment_sessions as asess

    seed_file = tmp_path / "seeds.jsonl"
    out_file = tmp_path / "out.jsonl"
    metrics_file = tmp_path / "metrics.jsonl"
    _write_seeds(seed_file)

    monkeypatch.setenv("SCAMGUARDIAN_AUGMENT_FAKE", "1")
    monkeypatch.setenv("SCAMGUARDIAN_AUGMENT_METRICS", str(metrics_file))

    import scripts.run_augment_session as runner

    monkeypatch.setattr(
        "sys.argv",
        ["run_augment_session", "--seed-file", str(seed_file), "--output", str(out_file),
         "--variants", "2", "--concurrency", "2"],
    )
    rc = runner.main()
    assert rc == 0

    rows = [json.loads(l) for l in out_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rows) == 4
    assert all(r["sample_kind"] == "augmented_llm" for r in rows)
    assert {r["scam_type"] for r in rows} == {"취업·알바 사기", "코인 사기"}

    metrics = [json.loads(l) for l in metrics_file.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert metrics[-1]["kind"] == "done"
    assert metrics[-1]["total_generated"] == 4


def test_session_lifecycle_and_promote(tmp_path, monkeypatch):
    """start_session → 완료 폴링 → promote_output 까지 동작."""
    from training import augment_sessions as asess

    # 세션 루트 + generated 디렉토리를 tmp 로 격리
    import sys

    monkeypatch.setattr(asess, "ROOT", tmp_path / "aug_sessions")
    monkeypatch.setattr(asess, "GENERATED_DIR", tmp_path / "generated")
    monkeypatch.setenv("SCAMGUARDIAN_AUGMENT_FAKE", "1")
    # subprocess 가 pytest 와 동일 인터프리터 사용 (conda 오버헤드·환경 불일치 회피)
    monkeypatch.setenv("SCAMGUARDIAN_TRAIN_PYTHON", sys.executable)

    seed_file = tmp_path / "seeds.jsonl"
    _write_seeds(seed_file)

    params = asess.AugmentParams(seed_file=str(seed_file), variants=3, concurrency=2)
    info = asess.start_session(params)
    sid = info["session_id"]
    assert info["status"] == "running"

    # 완료 대기 (FAKE 라 수 초 내)
    deadline = time.time() + 30
    status = "running"
    while time.time() < deadline:
        cur = asess.get_session(sid)
        status = cur["status"]
        if status in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.3)
    assert status == "completed", f"세션이 완료되지 않음: {status}"

    metrics = asess.read_metrics(sid)
    assert metrics and metrics[-1]["kind"] == "done"

    promoted = asess.promote_output(sid, "test_promote")
    assert promoted["added"] == 6  # 씨앗 2 × 변형 3
    dest = Path(promoted["path"])
    assert dest.exists()
    promoted_rows = [json.loads(l) for l in dest.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(promoted_rows) == 6


def test_start_session_missing_seed_file(tmp_path, monkeypatch):
    from training import augment_sessions as asess

    monkeypatch.setattr(asess, "ROOT", tmp_path / "aug_sessions")
    params = asess.AugmentParams(seed_file=str(tmp_path / "nope.jsonl"))
    with pytest.raises(FileNotFoundError):
        asess.start_session(params)
