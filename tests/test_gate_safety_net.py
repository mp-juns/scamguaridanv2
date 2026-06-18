"""게이트 안전 버킷 단정 방지 안전망 (_apply_gate_safety_net).

normal/scam_news_edu + (룰 신호 ≥1 또는 저신뢰 <0.70) → "추가 확인 필요" + 심층 권장.
"""

from __future__ import annotations

from api_server_pkg.common import _apply_gate_safety_net
from pipeline.gate import GateResult


def _report(signals: list[dict] | None = None, content_type: dict | None = None) -> dict:
    d: dict = {"detected_signals": signals or []}
    if content_type is not None:
        d["content_type"] = content_type
    return d


def test_news_edu_low_confidence_flagged():
    # 검찰 사칭 → scam_news_edu 0.51 오판 사례 (신호 0건이어도 단정 금지)
    report = _report(content_type={"bucket": "scam_news_edu", "label_ko": "사기 뉴스·교육"})
    gate = GateResult(bucket="scam_news_edu", confidence=0.51, source="finetuned")
    _apply_gate_safety_net(report, gate)
    assert report["content_type"]["bucket"] == "needs_review"
    assert report["deep_recommended"] is True
    assert "신뢰도가 낮아" in report["deep_recommended_reason"]


def test_news_edu_high_confidence_untouched():
    # 진짜 사기예방 뉴스 (고신뢰) — 기존 표시 유지
    ct = {"bucket": "scam_news_edu", "label_ko": "사기 뉴스·교육"}
    report = _report(content_type=dict(ct))
    gate = GateResult(bucket="scam_news_edu", confidence=0.97, source="finetuned")
    _apply_gate_safety_net(report, gate)
    assert report["content_type"] == ct
    assert "deep_recommended" not in report


def test_normal_with_signals_flagged():
    # 기존 동작 유지 — gate=normal + 텍스트 룰 신호
    report = _report(
        signals=[{"flag": "smishing_link_detected", "label_ko": "스미싱 의심 링크"}],
        content_type={"bucket": "normal", "label_ko": "정상"},
    )
    gate = GateResult(bucket="normal", confidence=0.97, source="finetuned")
    _apply_gate_safety_net(report, gate)
    assert report["content_type"]["bucket"] == "needs_review"
    assert report["deep_recommended"] is True
    assert "1차 게이트는 정상으로 판단했지만" in report["deep_recommended_reason"]
    assert "스미싱 의심 링크" in report["deep_recommended_reason"]


def test_news_edu_with_signals_flagged():
    # 신규 — news_edu 버킷도 신호 충돌 시 안전망 대상
    report = _report(signals=[{"flag": "courier_impersonation_pattern", "label_ko": "택배 사칭 의심 패턴"}])
    gate = GateResult(bucket="scam_news_edu", confidence=0.95, source="finetuned")
    _apply_gate_safety_net(report, gate)
    assert report["content_type"]["bucket"] == "needs_review"


def test_low_confidence_and_signals_combined_reason():
    report = _report(signals=[{"flag": "smishing_link_detected", "label_ko": "스미싱 의심 링크"}])
    gate = GateResult(bucket="normal", confidence=0.4, source="haiku")
    _apply_gate_safety_net(report, gate)
    reason = report["deep_recommended_reason"]
    assert "신뢰도가 낮고" in reason and "스미싱 의심 링크" in reason


def test_normal_clean_high_confidence_untouched():
    report = _report(content_type={"bucket": "normal", "label_ko": "정상"})
    gate = GateResult(bucket="normal", confidence=0.99, source="finetuned")
    _apply_gate_safety_net(report, gate)
    assert report["content_type"]["bucket"] == "normal"
    assert "deep_recommended" not in report


def test_news_heuristic_fast_path_boundary():
    # 뉴스 fast-path heuristic 은 confidence 0.7 고정 — 임계 미만 아님 (0.7 < 0.7 == False)
    report = _report()
    gate = GateResult(bucket="scam_news_edu", confidence=0.7, source="heuristic")
    _apply_gate_safety_net(report, gate)
    assert "deep_recommended" not in report


def test_scam_attempt_bucket_ignored():
    # 안전 버킷이 아니면 (이미 풀 강도 실행) 안전망 미적용
    report = _report(signals=[{"flag": "x", "label_ko": "y"}])
    gate = GateResult(bucket="scam_attempt", confidence=0.3, source="finetuned")
    _apply_gate_safety_net(report, gate)
    assert "deep_recommended" not in report
