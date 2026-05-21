"""scripts/export_runs_to_jsonl_draft.py — pure 헬퍼 + DB 통합 export 검증."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.export_runs_to_jsonl_draft import (
    _clean_entities,
    _clean_flags,
    _infer_content_label,
    _source_ref,
    build_draft,
    export_drafts,
)


# ── _infer_content_label ──

def test_content_label_scam_news_edu_when_gate_says_so():
    assert _infer_content_label({"gate": {"bucket": "scam_news_edu"}}) == "scam_news_edu"


def test_content_label_undetermined_for_scam_attempt_gate():
    # 초안 단계에선 scam_attempt 도 사람이 확인해야 하므로 undetermined 로
    assert _infer_content_label({"gate": {"bucket": "scam_attempt"}}) == "undetermined"


def test_content_label_undetermined_for_normal_gate():
    assert _infer_content_label({"gate": {"bucket": "normal"}}) == "undetermined"


def test_content_label_undetermined_when_no_gate():
    assert _infer_content_label({}) == "undetermined"
    assert _infer_content_label(None) == "undetermined"


# ── _source_ref ──

def test_source_ref_extracts_http_url():
    assert _source_ref("https://youtube.com/watch?v=xx") == "https://youtube.com/watch?v=xx"
    assert _source_ref("  http://example.com/news/1  ") == "http://example.com/news/1"


def test_source_ref_none_for_text_or_file_path():
    assert _source_ref("그냥 텍스트 입력") is None
    assert _source_ref("/uploads/file.mp4") is None
    assert _source_ref(None) is None
    assert _source_ref("") is None


# ── _clean_entities ──

def test_clean_entities_keeps_text_and_label_only():
    out = _clean_entities([
        {"text": "이유리", "label": "사람 이름", "score": 0.9, "source": "gliner"},
        {"text": "  ", "label": "X"},        # 공백 → drop
        {"text": "x", "label": ""},          # label 없음 → drop
        "not a dict",                         # 무시
    ])
    assert out == [{"text": "이유리", "label": "사람 이름"}]


# ── _clean_flags ──

def test_clean_flags_only_keeps_whitelisted():
    out = _clean_flags([
        {"flag": "personal_info_request"},   # OK (DETECTED_FLAGS 안)
        {"flag": "made_up_flag"},            # 화이트리스트 밖 → drop
        {"flag": "personal_info_request"},   # 중복 → dedup
        "abnormal_return_rate",              # 문자열도 허용
    ])
    flag_ids = [f["flag"] for f in out]
    assert flag_ids == ["personal_info_request", "abnormal_return_rate"]


def test_clean_flags_handles_none_and_empty():
    assert _clean_flags(None) == []
    assert _clean_flags([]) == []
    assert _clean_flags([{"flag": ""}, {"no_flag_key": "x"}]) == []


# ── build_draft ──

def _sample_run(**overrides):
    base = {
        "transcript_text": "여보세요? NH농협은행 대출 상담사 이유리예요...",
        "classification_scanner": {"scam_type": "대출 사기", "confidence": 0.22},
        "entities_predicted": [
            {"text": "이유리", "label": "사람 이름", "score": 0.65},
            {"text": "주민번호", "label": "개인정보 항목", "score": 0.95},
        ],
        "triggered_flags_predicted": [
            {"flag": "personal_info_request", "label_ko": "개인정보 요구"},
            {"flag": "_typo_not_a_real_flag"},
        ],
        "input_source": "https://youtube.com/watch?v=abc",
        "metadata": {"gate": {"bucket": "scam_attempt"}},
    }
    base.update(overrides)
    return base


def test_build_draft_full_schema():
    draft = build_draft("run-001", _sample_run())
    assert draft is not None
    assert draft["run_id"] == "run-001"
    assert "NH농협은행" in draft["text"]
    assert draft["content_label"] == "undetermined"
    assert draft["sample_kind"] == "review_needed"
    assert draft["scam_type"] == "대출 사기"
    assert {"text": "주민번호", "label": "개인정보 항목"} in draft["entities"]
    assert [f["flag"] for f in draft["risk_flags"]] == ["personal_info_request"]
    assert draft["source_ref"] == "https://youtube.com/watch?v=abc"
    assert draft["notes"] == "needs_human_review"


def test_build_draft_prefers_corrected_transcript():
    run = _sample_run(transcript_text="원본", transcript_corrected_text="교정된 본문 텍스트")
    draft = build_draft("r", run)
    assert draft is not None
    assert draft["text"] == "교정된 본문 텍스트"


def test_build_draft_returns_none_when_text_empty():
    run = _sample_run(transcript_text="", transcript_corrected_text=None)
    assert build_draft("r", run) is None


def test_build_draft_scam_news_edu_gate_sets_content_label():
    run = _sample_run(metadata={"gate": {"bucket": "scam_news_edu"}})
    draft = build_draft("r", run)
    assert draft is not None
    assert draft["content_label"] == "scam_news_edu"


def test_build_draft_text_input_no_source_ref():
    run = _sample_run(input_source="그냥 텍스트 입력입니다")
    draft = build_draft("r", run)
    assert draft is not None
    assert draft["source_ref"] is None


# ── DB 통합 export ──

def test_export_drafts_writes_jsonl(sqlite_init, tmp_path):
    from db import repository
    run_id = repository.save_analysis_run(
        input_source="https://news.example.com/voice-phishing",
        whisper_model="medium",
        skip_verification=True,
        use_llm=False,
        use_rag=False,
        transcript_text="여보세요 NH농협은행 대출 상담사입니다 주민번호 알려주세요",
        classification_scanner={"scam_type": "대출 사기", "confidence": 0.22, "is_uncertain": True},
        entities_predicted=[
            {"text": "주민번호", "label": "개인정보 항목", "score": 0.95},
        ],
        verification_results=[],
        triggered_flags_predicted=[
            {"flag": "personal_info_request"},
            {"flag": "garbage_flag_not_in_whitelist"},
        ],
        total_score_predicted=1,
        risk_level_predicted="",
        llm_assessment=None,
        metadata={"gate": {"bucket": "scam_attempt"}},
    )

    out = tmp_path / "drafts.jsonl"
    stats = export_drafts(output_path=out, limit=None, only_unlabeled=False)
    assert stats["written"] == 1
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    draft = json.loads(lines[0])
    assert draft["run_id"] == run_id
    assert "NH농협은행" in draft["text"]
    assert draft["scam_type"] == "대출 사기"
    assert draft["content_label"] == "undetermined"
    assert draft["sample_kind"] == "review_needed"
    assert draft["source_ref"] == "https://news.example.com/voice-phishing"
    assert [f["flag"] for f in draft["risk_flags"]] == ["personal_info_request"]
    assert draft["notes"] == "needs_human_review"


def test_export_drafts_only_unlabeled_filter(sqlite_init, tmp_path):
    from db import repository

    run_id_labeled = repository.save_analysis_run(
        input_source="텍스트1",
        whisper_model="medium",
        skip_verification=True, use_llm=False, use_rag=False,
        transcript_text="이미 라벨링된 run",
        classification_scanner={"scam_type": "투자 사기", "confidence": 0.4},
        entities_predicted=[], verification_results=[], triggered_flags_predicted=[],
        total_score_predicted=0, risk_level_predicted="", llm_assessment=None,
        metadata={},
    )
    repository.upsert_human_annotation(
        run_id=run_id_labeled,
        scam_type_gt="투자 사기",
        entities_gt=[],
        triggered_flags_gt=[],
        content_label="scam_attempt",
    )
    repository.save_analysis_run(
        input_source="텍스트2",
        whisper_model="medium",
        skip_verification=True, use_llm=False, use_rag=False,
        transcript_text="아직 라벨링 안 된 run",
        classification_scanner={"scam_type": "대출 사기", "confidence": 0.3},
        entities_predicted=[], verification_results=[], triggered_flags_predicted=[],
        total_score_predicted=0, risk_level_predicted="", llm_assessment=None,
        metadata={},
    )

    out = tmp_path / "drafts.jsonl"
    stats = export_drafts(output_path=out, only_unlabeled=True)
    # 라벨링된 run 은 제외 → 1건만 export
    assert stats["written"] == 1
    line = out.read_text(encoding="utf-8").strip()
    assert "아직 라벨링" in line


def test_export_drafts_scam_type_filter(sqlite_init, tmp_path):
    from db import repository
    for name, st in [("a", "대출 사기"), ("b", "투자 사기"), ("c", "대출 사기")]:
        repository.save_analysis_run(
            input_source=name,
            whisper_model="medium",
            skip_verification=True, use_llm=False, use_rag=False,
            transcript_text=f"transcript {name}",
            classification_scanner={"scam_type": st, "confidence": 0.3},
            entities_predicted=[], verification_results=[], triggered_flags_predicted=[],
            total_score_predicted=0, risk_level_predicted="", llm_assessment=None,
            metadata={},
        )

    out = tmp_path / "drafts.jsonl"
    stats = export_drafts(output_path=out, scam_type_filter="대출 사기")
    assert stats["written"] == 2
    assert stats["skipped_filter"] == 1


def test_export_drafts_limit(sqlite_init, tmp_path):
    from db import repository
    for i in range(5):
        repository.save_analysis_run(
            input_source=f"run-{i}",
            whisper_model="medium",
            skip_verification=True, use_llm=False, use_rag=False,
            transcript_text=f"text {i}",
            classification_scanner={"scam_type": "대출 사기", "confidence": 0.3},
            entities_predicted=[], verification_results=[], triggered_flags_predicted=[],
            total_score_predicted=0, risk_level_predicted="", llm_assessment=None,
            metadata={},
        )

    out = tmp_path / "drafts.jsonl"
    stats = export_drafts(output_path=out, limit=3)
    assert stats["written"] == 3
