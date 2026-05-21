"""Stage 2 — multi-label 추출 라우팅 검증.

- candidate_scam_types: all_scores → top-N 후보 (우세 시 top-1 단독)
- _extraction_label_set: 공통 위험 라벨 + 후보 LABEL_SET 합집합
- "투자 사기 top-1 + 주민번호 요구" → 개인정보 항목 라벨이 추출 대상에 포함
- all_scores 없으면 [] → 기존 top-1 라우팅 fallback
- candidate_scam_types 가 외부 응답(to_dict)에 노출되지 않음 / scam_type 은 문자열 유지
"""

from __future__ import annotations

from pipeline.classifier import candidate_scam_types
from pipeline.config import COMMON_RISK_LABELS
from pipeline import runner
from pipeline.signal_detector import DetectionReport


# ── candidate_scam_types ──

def test_empty_all_scores_returns_empty():
    # all_scores 없음 → [] → 호출부가 기존 top-1 라우팅으로 fallback
    assert candidate_scam_types({}) == []


def test_single_score_returns_single():
    assert candidate_scam_types({"투자 사기": 1.0}) == ["투자 사기"]


def test_dominant_top1_returns_only_top1():
    # top1 - top2 차이가 dominance_gap(0.30) 이상 → top-1 단독
    scores = {"투자 사기": 0.62, "코인 사기": 0.20, "대출 사기": 0.10, "스미싱": 0.08}
    assert candidate_scam_types(scores) == ["투자 사기"]


def test_ambiguous_returns_top_n():
    # top1 - top2 차이가 작음 → 상위 top-3
    scores = {
        "투자 사기": 0.30,
        "코인 사기": 0.26,
        "로맨스 스캠": 0.22,
        "대출 사기": 0.12,
        "스미싱": 0.10,
    }
    result = candidate_scam_types(scores)
    assert result == ["투자 사기", "코인 사기", "로맨스 스캠"]


def test_top_n_caps_at_three():
    scores = {f"유형{i}": 0.2 - i * 0.01 for i in range(8)}
    assert len(candidate_scam_types(scores)) == 3


def test_custom_top_n_and_gap():
    scores = {"a": 0.3, "b": 0.28, "c": 0.22, "d": 0.2}
    assert candidate_scam_types(scores, top_n=2, dominance_gap=0.5) == ["a", "b"]


# ── _extraction_label_set — 공통 위험 라벨 항상 포함 ──

def test_investment_scam_top1_includes_personal_info_label():
    # "투자 사기 top-1 + 주민번호 요구" — 투자 사기 라벨셋엔 개인정보 항목이 없지만
    # COMMON_RISK_LABELS 로 항상 추출 대상에 포함된다.
    labels = runner._extraction_label_set(["투자 사기"])
    assert "개인정보 항목" in labels
    assert "악성 URL" in labels
    assert "계좌번호" in labels
    # 투자 사기 고유 라벨도 포함
    assert "투자 상품명" in labels


def test_extraction_label_set_always_has_common_risk_labels():
    for candidates in ([], ["로맨스 스캠"], ["중고거래 사기", "대출 사기"]):
        labels = runner._extraction_label_set(candidates)
        for common in COMMON_RISK_LABELS:
            assert common in labels


def test_extraction_label_set_unions_multiple_types():
    single = set(runner._extraction_label_set(["투자 사기"]))
    multi = set(runner._extraction_label_set(["투자 사기", "코인 사기"]))
    # 코인 사기 추가 → 코인 고유 라벨이 더 들어와 합집합이 더 커진다
    assert "코인 또는 토큰명" in multi
    assert single <= multi


def test_all_label_union_includes_common_risk_labels():
    union = runner._all_label_union()
    for common in COMMON_RISK_LABELS:
        assert common in union


# ── 외부 응답 schema 불변 ──

def test_candidate_scam_types_not_in_external_response():
    report = DetectionReport(scam_type="투자 사기")
    payload = report.to_dict()
    assert "candidate_scam_types" not in payload


def test_scam_type_stays_top1_string_in_response():
    report = DetectionReport(scam_type="투자 사기")
    payload = report.to_dict()
    assert "scam_type" in payload
    assert isinstance(payload["scam_type"], str)
    assert payload["scam_type"] == "투자 사기"
