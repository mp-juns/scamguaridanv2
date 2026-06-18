"""각 flag 가 정확한 조건에서 검출되는지 검증 (점수·등급 X — Identity Boundary).

Stage 3 신설. signal_detector.detect() 의 입력 → 출력 contract 만 검증.
"""

from __future__ import annotations


def _empty_classification():
    from pipeline.classifier import ClassificationResult
    return ClassificationResult(scam_type="기타", confidence=0.5, all_scores={}, is_uncertain=False)


def _vr(flag: str, *, triggered: bool = True, evidence: list[str] | None = None):
    from pipeline.extractor import Entity
    from pipeline.verifier import VerificationResult
    return VerificationResult(
        entity=Entity(text="x", label="회사명 또는 기관명", score=0.5, start=0, end=1, source="test"),
        query="test",
        flag=flag,
        flag_description=f"{flag} 검출",
        triggered=triggered,
        evidence_snippets=evidence or [f"{flag} 근거"],
    )


def test_verification_triggered_signal_carries_rationale():
    """Phase 4 검증 단계에서 발동된 신호는 FLAG_RATIONALE 의 학술 근거를 함께 운반한다."""
    from pipeline import signal_detector
    report = signal_detector.detect(
        verification_results=[_vr("urgent_transfer_demand")],
        classification=_empty_classification(),
        entities=[],
    )
    flags = [s.flag for s in report.detected_signals]
    assert "urgent_transfer_demand" in flags
    sig = next(s for s in report.detected_signals if s.flag == "urgent_transfer_demand")
    assert sig.rationale, "검출 신호는 FLAG_RATIONALE 의 학술 근거 필수 동반"
    assert sig.source, "검출 신호는 출처 기관·논문 필수 동반"
    assert sig.label_ko == "즉각 송금·이체 요구"
    assert sig.detection_source == "rule"


def test_verification_not_triggered_no_signal():
    """triggered=False 면 검출 신호로 만들지 않는다."""
    from pipeline import signal_detector
    report = signal_detector.detect(
        verification_results=[_vr("urgent_transfer_demand", triggered=False)],
        classification=_empty_classification(),
        entities=[],
    )
    flags = [s.flag for s in report.detected_signals]
    assert "urgent_transfer_demand" not in flags


def test_duplicate_flags_deduplicated():
    """같은 flag 가 여러 source 에서 들어와도 1번만 검출."""
    from pipeline import signal_detector
    report = signal_detector.detect(
        verification_results=[_vr("phone_scam_reported"), _vr("phone_scam_reported")],
        classification=_empty_classification(),
        entities=[],
    )
    flags = [s.flag for s in report.detected_signals]
    assert flags.count("phone_scam_reported") == 1


def test_unknown_flag_from_llm_ignored():
    """LLM 이 환각으로 알 수 없는 flag 를 제안하면 무시 (DETECTED_FLAGS 외)."""
    from pipeline import llm_assessor, signal_detector
    asmt = llm_assessor.LLMAssessment(
        model="test",
        suggested_flags=[
            llm_assessor.SuggestedFlag(
                flag="this_flag_does_not_exist",
                reason="hallucinated",
                evidence="x",
                confidence=0.99,
            ),
        ],
    )
    report = signal_detector.detect(
        verification_results=[],
        classification=_empty_classification(),
        entities=[],
        llm_assessment=asmt,
    )
    flags = [s.flag for s in report.detected_signals]
    assert "this_flag_does_not_exist" not in flags


def test_llm_low_confidence_flag_filtered():
    """LLM confidence < LLM_FLAG_DETECTION_CONFIDENCE_THRESHOLD 면 검출 신호로 채택 안 함."""
    from pipeline import llm_assessor, signal_detector
    asmt = llm_assessor.LLMAssessment(
        model="test",
        suggested_flags=[
            llm_assessor.SuggestedFlag(
                flag="urgent_transfer_demand",
                reason="weak signal",
                evidence="…",
                confidence=0.3,  # 임계 (0.75) 미만
            ),
        ],
    )
    report = signal_detector.detect(
        verification_results=[],
        classification=_empty_classification(),
        entities=[],
        llm_assessment=asmt,
    )
    assert "urgent_transfer_demand" not in [s.flag for s in report.detected_signals]


def test_llm_high_confidence_flag_kept():
    """LLM confidence ≥ 임계 면 detection_source='llm' 으로 검출."""
    from pipeline import llm_assessor, signal_detector
    asmt = llm_assessor.LLMAssessment(
        model="test",
        suggested_flags=[
            llm_assessor.SuggestedFlag(
                flag="fake_government_agency",
                reason="strong signal",
                evidence="…",
                confidence=0.9,
            ),
        ],
    )
    report = signal_detector.detect(
        verification_results=[],
        classification=_empty_classification(),
        entities=[],
        llm_assessment=asmt,
    )
    sig = next(s for s in report.detected_signals if s.flag == "fake_government_agency")
    assert sig.detection_source == "llm"


def test_summary_text_zero_signals():
    """검출 0 일 때 summary 가 일관된 한국어 문장."""
    from pipeline import signal_detector
    report = signal_detector.detect(
        verification_results=[],
        classification=_empty_classification(),
        entities=[],
    )
    assert "위험 신호가 검출되지 않았습니다" in report.summary
    assert len(report.detected_signals) == 0


def test_summary_text_with_signals_includes_count():
    """검출 N>0 일 때 summary 에 개수와 사용자 안내 포함."""
    from pipeline import signal_detector
    report = signal_detector.detect(
        verification_results=[_vr("urgent_transfer_demand"), _vr("fake_government_agency")],
        classification=_empty_classification(),
        entities=[],
    )
    assert "위험 신호 2개" in report.summary
    assert "탐지된 위험 신호 목록" in report.summary
