"""Stage 1 콘텐츠 게이트 — 파서·heuristic fast-path·fallback 단위 테스트.

Claude Haiku 호출 자체는 단위 테스트 대상이 아니다 (conftest 가 ANTHROPIC_API_KEY 를
비우므로 classify_gate 의 LLM 경로는 항상 fallback 으로 떨어진다 — 그 경로를 검증).
"""

from __future__ import annotations

from pipeline.config import (
    GATE_BUCKETS,
    GATE_EXECUTION_PROFILE,
    GATE_FALLBACK_BUCKET,
    GATE_NORMAL,
    GATE_SCAM_ATTEMPT,
    GATE_UNDETERMINED,
)
from pipeline import gate


# ── heuristic fast-path ──

def test_empty_input_is_undetermined():
    result = gate.classify_gate("")
    assert result.bucket == GATE_UNDETERMINED
    assert result.source == "heuristic"


def test_short_input_fast_path_undetermined():
    result = gate.classify_gate("ㅋㅋ")
    assert result.bucket == GATE_UNDETERMINED
    assert result.source == "heuristic"
    # fast-path 는 LLM 을 부르지 않으므로 model 미설정
    assert result.model == ""


# ── classify_gate fallback (API key 없음 → conftest) ──

def test_long_input_without_api_key_falls_back():
    long_text = "안녕하세요 " * 50  # GATE_MIN_CHARS 훌쩍 넘김
    result = gate.classify_gate(long_text)
    assert result.bucket == GATE_FALLBACK_BUCKET
    assert result.source == "fallback"


# ── JSON 파서 ──

def test_parse_plain_json():
    out = gate._parse_gate_json('{"bucket": "normal", "confidence": 0.9}')
    assert out["bucket"] == "normal"


def test_parse_code_fenced_json():
    raw = '```json\n{"bucket": "scam_attempt", "confidence": 0.8}\n```'
    out = gate._parse_gate_json(raw)
    assert out["bucket"] == "scam_attempt"


def test_parse_json_embedded_in_text():
    raw = '분류 결과는 다음과 같습니다: {"bucket": "normal", "confidence": 0.7} 입니다.'
    out = gate._parse_gate_json(raw)
    assert out["bucket"] == "normal"


def test_parse_garbage_returns_empty():
    assert gate._parse_gate_json("이건 JSON 이 아닙니다") == {}


# ── payload → GateResult ──

def test_result_from_valid_payload():
    r = gate._result_from_payload(
        {"bucket": "scam_attempt", "confidence": 0.85, "reason": "송금 유도"}, "m"
    )
    assert r.bucket == GATE_SCAM_ATTEMPT
    assert r.confidence == 0.85
    assert r.source == "haiku"


def test_result_from_invalid_bucket_falls_back():
    r = gate._result_from_payload({"bucket": "made_up", "confidence": 0.9}, "m")
    assert r.bucket == GATE_FALLBACK_BUCKET
    assert r.source == "fallback"


def test_result_confidence_clamped():
    assert gate._result_from_payload({"bucket": "normal", "confidence": 5.0}, "m").confidence == 1.0
    assert gate._result_from_payload({"bucket": "normal", "confidence": -2.0}, "m").confidence == 0.0


def test_result_missing_confidence_defaults_zero():
    r = gate._result_from_payload({"bucket": "normal"}, "m")
    assert r.confidence == 0.0


def test_result_non_numeric_confidence_defaults_zero():
    r = gate._result_from_payload({"bucket": "normal", "confidence": "높음"}, "m")
    assert r.confidence == 0.0


# ── 실행 강도 profile ──

def test_every_bucket_has_execution_profile():
    for bucket in GATE_BUCKETS:
        assert bucket in GATE_EXECUTION_PROFILE
        prof = GATE_EXECUTION_PROFILE[bucket]
        assert set(prof) == {"run_scam_type", "serper_max_entities", "use_llm"}


def test_normal_bucket_disables_expensive_steps():
    prof = gate.execution_profile(GATE_NORMAL)
    assert prof["run_scam_type"] is False
    assert prof["serper_max_entities"] == 0
    assert prof["use_llm"] is False


def test_scam_attempt_runs_full_pipeline():
    prof = gate.execution_profile(GATE_SCAM_ATTEMPT)
    assert prof["run_scam_type"] is True
    assert prof["serper_max_entities"] > 0
    assert prof["use_llm"] is True


def test_unknown_bucket_uses_fallback_profile():
    assert gate.execution_profile("nonexistent") == GATE_EXECUTION_PROFILE[GATE_FALLBACK_BUCKET]


# ── GateResult 헬퍼 ──

def test_gate_result_label_ko_and_to_dict():
    r = gate.GateResult(bucket=GATE_NORMAL, confidence=0.9, reason="일상 대화")
    assert r.label_ko == "정상"
    d = r.to_dict()
    assert d["bucket"] == GATE_NORMAL
    assert d["label_ko"] == "정상"
    assert d["confidence"] == 0.9


def test_gate_result_execution_profile_method():
    r = gate.GateResult(bucket=GATE_SCAM_ATTEMPT)
    assert r.execution_profile() == GATE_EXECUTION_PROFILE[GATE_SCAM_ATTEMPT]
