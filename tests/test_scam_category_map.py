"""scam_type → scam_category 결정적 매핑 (표시 전용 레이어)."""

from __future__ import annotations

from pipeline.config import (
    DEFAULT_SCAM_TYPES,
    SCAM_CATEGORY_FALLBACK,
    SCAM_CATEGORY_MAP,
    scam_category_for,
)


def test_mapping_expectations():
    cases = {
        "코인 사기": "투자·가상자산형",
        "투자 사기": "투자·가상자산형",
        "스미싱": "링크·문자 유도형",
        "기관 사칭": "기관·금융 사칭형",
        "대출 사기": "기관·금융 사칭형",
        "로맨스 스캠": "관계·지인 사칭형",
        "메신저 피싱": "관계·지인 사칭형",
        "중고거래 사기": "거래·취업형",
        "취업·알바 사기": "거래·취업형",
        "건강식품 사기": "기타·특수형",
        "부동산 사기": "기타·특수형",
        "납치·협박형": "기타·특수형",
    }
    for scam_type, expected in cases.items():
        assert scam_category_for(scam_type) == expected, scam_type


def test_all_default_scam_types_covered():
    # 12종 전부 매핑돼 있어야 — 새 유형 추가 시 매핑 누락 방지 가드
    assert set(DEFAULT_SCAM_TYPES) == set(SCAM_CATEGORY_MAP.keys())


def test_empty_scam_type_yields_empty_category():
    # 게이트 normal/scam_news_edu 로 분류가 skip 되면 scam_type="" → 카테고리 미표시
    assert scam_category_for("") == ""
    assert scam_category_for("   ") == ""


def test_unknown_custom_type_falls_back():
    assert scam_category_for("신종 사기 유형") == SCAM_CATEGORY_FALLBACK


def test_detection_report_carries_category():
    from pipeline.classifier import ClassificationResult
    from pipeline import signal_detector

    report = signal_detector.detect(
        verification_results=[],
        classification=ClassificationResult(
            scam_type="코인 사기", confidence=0.9, all_scores={}, is_uncertain=False,
        ),
        entities=[],
        transcript="테스트",
    )
    d = report.to_dict()
    assert d["scam_category"] == "투자·가상자산형"
    assert d["scam_category_source"] == "mapping"
    assert d["scam_type"] == "코인 사기"  # 기존 필드 유지


def test_detection_report_empty_category_when_classification_skipped():
    from pipeline.classifier import ClassificationResult
    from pipeline import signal_detector

    report = signal_detector.detect(
        verification_results=[],
        classification=ClassificationResult(
            scam_type="", confidence=0.0, all_scores={}, is_uncertain=True,
        ),
        entities=[],
        transcript="테스트",
    )
    d = report.to_dict()
    assert d["scam_category"] == ""
    assert d["scam_category_source"] == ""
