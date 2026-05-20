"""content_label 중심 학습 데이터 로더 검증.

- scam_type 분류기 학습셋은 content_label == scam_attempt 만 포함
- content 게이트 학습셋은 normal/scam_attempt/scam_news_edu 포함
- suspicious_insufficient / undetermined 는 기본 학습셋에서 제외 (review queue)
- 뉴스 원문과 synthetic_scam_message 는 서로 다른 sample_kind
- content_label fallback / sample_kind 추정
- HumanAnnotationRequest 검증 (scam_news_edu 에 scam_type 강제 안 함)
- DB human_annotations content_label 컬럼 round-trip
"""

from __future__ import annotations

import json

import pytest

from pipeline.config import (
    GATE_NORMAL,
    GATE_SCAM_ATTEMPT,
    GATE_SCAM_NEWS_EDU,
    GATE_SUSPICIOUS_INSUFFICIENT,
    GATE_UNDETERMINED,
    SAMPLE_KIND_NORMAL,
    SAMPLE_KIND_REAL_SCAM,
    SAMPLE_KIND_REVIEW,
    SAMPLE_KIND_SCAM_NEWS_EDU,
    SAMPLE_KIND_SYNTHETIC_SCAM,
)
from training import data as tdata


_SAMPLES = [
    {"text": "원금 보장 월 30% 수익, 오늘 입금하세요", "content_label": "scam_attempt",
     "scam_type": "투자 사기", "sample_kind": "real_scam_message"},
    {"text": "보이스피싱 피해가 급증한다고 경찰이 경고했습니다", "content_label": "scam_news_edu",
     "sample_kind": "scam_news_education", "source_ref": "https://news.example/1"},
    {"text": "내일 회의 자료를 공유 드라이브에 올려두었습니다", "content_label": "normal",
     "sample_kind": "normal_content"},
    {"text": "음 그게 무슨 말인지 잘 모르겠는데요", "content_label": "undetermined"},
    {"text": "뭔가 좀 이상하긴 한데 확실하진 않아요", "content_label": "suspicious_insufficient"},
    {"text": "지금 바로 300만원 입금하면 월 30% 배당 지급합니다", "content_label": "scam_attempt",
     "scam_type": "투자 사기", "sample_kind": "synthetic_scam_message",
     "source_ref": "https://news.example/1"},
]


@pytest.fixture
def jsonl(tmp_path):
    p = tmp_path / "samples.jsonl"
    p.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in _SAMPLES),
        encoding="utf-8",
    )
    return p


# ── scam_type 분류기 학습셋 ──

def test_scam_type_dataset_only_scam_attempt(jsonl):
    examples = tdata.load_classifier_dataset(extra_jsonl=jsonl)
    assert len(examples) == 2  # scam_attempt 2개
    assert all(e.content_label == GATE_SCAM_ATTEMPT for e in examples)
    # label 은 content_label 이 아니라 scam_type
    assert all(e.label == "투자 사기" for e in examples)


def test_scam_news_edu_not_in_scam_type_dataset(jsonl):
    texts = [e.text for e in tdata.load_classifier_dataset(extra_jsonl=jsonl)]
    assert not any("경찰이 경고" in t for t in texts)


def test_normal_not_in_scam_type_dataset(jsonl):
    texts = [e.text for e in tdata.load_classifier_dataset(extra_jsonl=jsonl)]
    assert not any("회의 자료" in t for t in texts)


# ── content 게이트 학습셋 ──

def test_gate_dataset_includes_normal_attempt_news(jsonl):
    examples = tdata.load_content_gate_dataset(extra_jsonl=jsonl)
    labels = {e.label for e in examples}
    assert labels == {GATE_NORMAL, GATE_SCAM_ATTEMPT, GATE_SCAM_NEWS_EDU}
    # 게이트 학습셋의 label 은 content_label
    assert all(e.label == e.content_label for e in examples)


def test_normal_in_gate_dataset(jsonl):
    texts = [e.text for e in tdata.load_content_gate_dataset(extra_jsonl=jsonl)]
    assert any("회의 자료" in t for t in texts)


def test_suspicious_undetermined_excluded_from_training(jsonl):
    gate_texts = {e.text for e in tdata.load_content_gate_dataset(extra_jsonl=jsonl)}
    cls_texts = {e.text for e in tdata.load_classifier_dataset(extra_jsonl=jsonl)}
    assert not any("이상하긴 한데" in t for t in gate_texts | cls_texts)
    assert not any("모르겠는데요" in t for t in gate_texts | cls_texts)


# ── review queue ──

def test_review_queue_has_suspicious_and_undetermined(jsonl):
    examples = tdata.load_review_queue(extra_jsonl=jsonl)
    labels = {e.label for e in examples}
    assert labels == {GATE_SUSPICIOUS_INSUFFICIENT, GATE_UNDETERMINED}


# ── sample_kind 구분 ──

def test_news_and_synthetic_have_different_sample_kind(jsonl):
    by_text = {e.text: e for e in tdata.load_content_gate_dataset(extra_jsonl=jsonl)}
    news = next(e for t, e in by_text.items() if "경찰이 경고" in t)
    synth = next(
        e for e in tdata.load_classifier_dataset(extra_jsonl=jsonl)
        if "300만원" in e.text
    )
    assert news.sample_kind == SAMPLE_KIND_SCAM_NEWS_EDU
    assert synth.sample_kind == SAMPLE_KIND_SYNTHETIC_SCAM
    assert news.sample_kind != synth.sample_kind
    assert synth.source_ref == "https://news.example/1"


# ── fallback / 추정 ──

def test_resolve_content_label_explicit():
    assert tdata.resolve_content_label("scam_news_edu", None) == GATE_SCAM_NEWS_EDU


def test_resolve_content_label_fallback_scam_type_present():
    # content_label 없음 + scam_type 명확 → scam_attempt 추정
    assert tdata.resolve_content_label("", "투자 사기") == GATE_SCAM_ATTEMPT


def test_resolve_content_label_fallback_undetermined():
    assert tdata.resolve_content_label("", "") == GATE_UNDETERMINED
    assert tdata.resolve_content_label(None, tdata.NEGATIVE_LABEL) == GATE_UNDETERMINED


def test_resolve_content_label_invalid_value_falls_back():
    assert tdata.resolve_content_label("made_up", "투자 사기") == GATE_SCAM_ATTEMPT


def test_infer_sample_kind():
    assert tdata.infer_sample_kind(GATE_SCAM_ATTEMPT) == SAMPLE_KIND_REAL_SCAM
    assert tdata.infer_sample_kind(GATE_NORMAL) == SAMPLE_KIND_NORMAL
    assert tdata.infer_sample_kind(GATE_UNDETERMINED) == SAMPLE_KIND_REVIEW


def test_old_schema_jsonl_label_only(tmp_path):
    # 구 스키마 {text, label} — content_label 없음 → scam_type 명확하니 scam_attempt
    p = tmp_path / "old.jsonl"
    p.write_text(json.dumps({"text": "옛날 형식 샘플 투자 권유", "label": "투자 사기"},
                            ensure_ascii=False), encoding="utf-8")
    examples = tdata.load_classifier_dataset(extra_jsonl=p)
    assert len(examples) == 1
    assert examples[0].content_label == GATE_SCAM_ATTEMPT
    assert examples[0].label == "투자 사기"


# ── HumanAnnotationRequest 검증 ──

def test_annotation_request_scam_news_edu_no_scam_type():
    from api_server_pkg.models import HumanAnnotationRequest
    # scam_news_edu 는 scam_type 강제 안 함
    req = HumanAnnotationRequest(content_label="scam_news_edu")
    assert req.content_label == "scam_news_edu"
    assert req.scam_type_gt == ""


def test_annotation_request_scam_attempt_requires_scam_type():
    from api_server_pkg.models import HumanAnnotationRequest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        HumanAnnotationRequest(content_label="scam_attempt", scam_type_gt="")


def test_annotation_request_invalid_content_label():
    from api_server_pkg.models import HumanAnnotationRequest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        HumanAnnotationRequest(content_label="not_a_label")


# ── DB 스키마 + round-trip ──

def test_human_annotations_has_content_label_column(sqlite_init):
    from db import sqlite_repository
    with sqlite_repository._connect() as conn:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(human_annotations)").fetchall()}
    assert {"content_label", "sample_kind", "source_ref"} <= cols


def test_annotation_content_label_round_trip(sqlite_init):
    from db import repository
    run_id = repository.save_analysis_run(
        input_source="테스트 입력",
        whisper_model="medium",
        skip_verification=True,
        use_llm=False,
        use_rag=False,
        transcript_text="원금 보장 투자 권유 문자",
        classification_scanner={"scam_type": "투자 사기", "confidence": 0.8},
        entities_predicted=[],
        verification_results=[],
        triggered_flags_predicted=[],
        total_score_predicted=0,
        risk_level_predicted="",
        llm_assessment=None,
        metadata={},
    )
    repository.upsert_human_annotation(
        run_id=run_id,
        scam_type_gt="투자 사기",
        entities_gt=[],
        triggered_flags_gt=[],
        content_label="scam_attempt",
        sample_kind="real_scam_message",
        source_ref="https://news.example/42",
    )
    detail = repository.get_run_detail(run_id)
    ann = detail["annotation"]
    assert ann["content_label"] == "scam_attempt"
    assert ann["sample_kind"] == "real_scam_message"
    assert ann["source_ref"] == "https://news.example/42"
