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
    GATE_SCAM_NEWS_EDU,
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


# ── 뉴스/교육 heuristic fast-path (LLM skip) ──

def test_news_fast_path_strong_markers_triggers():
    """뉴스 마커 2개 이상 + 직접 명령 없음 → LLM 호출 없이 scam_news_edu."""
    text = (
        "검찰에 따르면 보이스피싱 피해자는 지난해 대비 30% 급증하고 있다. "
        "경찰청 사이버수사대 관계자는 \"OTP 노출 사례가 늘었다\"라고 밝혔다."
    )
    result = gate.classify_gate(text)
    assert result.bucket == GATE_SCAM_NEWS_EDU
    assert result.source == "heuristic"
    assert result.model == ""  # LLM 호출 없음 (fast-path)


def test_news_fast_path_blocked_by_direct_demand():
    """뉴스 마커 충분해도 직접 명령형 요구 있으면 LLM 으로 위임 (false positive 방지)."""
    text = (
        "검찰에 따르면 보이스피싱이 급증하고 있다고 밝혔다. "
        "지금 송금 안 하시면 큰일납니다. 계좌번호 입력하세요."
    )
    # conftest 가 ANTHROPIC_API_KEY 비움 → LLM 경로는 fallback. heuristic skip 안 됨이 핵심
    result = gate.classify_gate(text)
    assert result.source == "fallback"  # heuristic 통과 못하고 LLM 시도 → fallback
    assert result.bucket == GATE_FALLBACK_BUCKET


def test_news_fast_path_insufficient_markers_falls_through():
    """뉴스 마커 1개만 있으면 fast-path skip → LLM 위임."""
    text = "보이스피싱 사건이 발생했습니다. 추가 정보는 곧 공유됩니다." * 2
    result = gate.classify_gate(text)
    # 마커 부족 → heuristic 안 걸림 → LLM 시도 → API key 없음 → fallback
    assert result.source == "fallback"


def test_news_fast_path_helper_direct():
    """_news_edu_fast_path 헬퍼 단독 테스트 — 마커 매칭 로직 확인."""
    # 마커 2개 (검찰에 따르면 + 라고 밝혔다)
    hit = gate._news_edu_fast_path(
        "검찰에 따르면 사기 사건이 30% 증가했다고 관계자가 밝혔다고 한다. "
        "라고 전했다."
    )
    assert hit is not None
    assert hit.bucket == GATE_SCAM_NEWS_EDU
    assert "뉴스 narration 마커" in hit.reason


def test_news_fast_path_helper_zero_markers():
    """뉴스 마커 0개면 None 반환."""
    assert gate._news_edu_fast_path("오늘 점심 뭐 먹을까요? 짜장면 어때요?") is None


def test_news_fast_path_helper_one_marker():
    """뉴스 마커 1개만 있으면 (임계 미달) None 반환."""
    text = "이 사건은 검찰에 따르면 진행 중이다. 자세한 내용은 추후 공개된다."
    assert gate._news_edu_fast_path(text) is None
