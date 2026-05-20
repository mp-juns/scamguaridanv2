"""결과 페이지 content_type 노출 — 안전 버킷만 통과하는지 검증.

Identity Boundary: Stage 1 게이트 결과 중 *비-판정* 버킷(normal / scam_news_edu /
undetermined)만 결과 페이지에 노출. scam_attempt / suspicious_insufficient 는
"사기 시도다"라는 판정성 정보라서 결과 페이지에 절대 보내지 않는다.
"""

from __future__ import annotations

from api_server_pkg.result_token import SAFE_CONTENT_TYPE_BUCKETS, _safe_content_type


def test_scam_news_edu_passes_through():
    out = _safe_content_type({"bucket": "scam_news_edu", "label_ko": "사기 뉴스·교육"})
    assert out == {"bucket": "scam_news_edu", "label_ko": "사기 뉴스·교육"}


def test_normal_passes_through():
    out = _safe_content_type({"bucket": "normal", "label_ko": "정상"})
    assert out == {"bucket": "normal", "label_ko": "정상"}


def test_undetermined_passes_through():
    out = _safe_content_type({"bucket": "undetermined", "label_ko": "판단 불가"})
    assert out == {"bucket": "undetermined", "label_ko": "판단 불가"}


def test_scam_attempt_blocked():
    # 판정성 버킷 — 결과 페이지에 노출 X
    assert _safe_content_type({"bucket": "scam_attempt", "label_ko": "사기 시도"}) is None


def test_suspicious_insufficient_blocked():
    assert _safe_content_type({"bucket": "suspicious_insufficient", "label_ko": "의심·불충분"}) is None


def test_none_gate_returns_none():
    assert _safe_content_type(None) is None


def test_empty_gate_returns_none():
    assert _safe_content_type({}) is None


def test_unknown_bucket_blocked():
    # 미래에 새 bucket 추가돼도 화이트리스트 안 통과하면 노출 X (안전 기본값)
    assert _safe_content_type({"bucket": "made_up_bucket"}) is None


def test_missing_label_ko_falls_back_to_bucket():
    out = _safe_content_type({"bucket": "scam_news_edu"})
    assert out is not None
    assert out["bucket"] == "scam_news_edu"
    assert out["label_ko"] == "scam_news_edu"


def test_safe_buckets_set_is_exactly_three():
    # 화이트리스트 boundary 가 의도 외로 늘어나지 않게 잠금
    assert SAFE_CONTENT_TYPE_BUCKETS == frozenset({"normal", "scam_news_edu", "undetermined"})
