"""verifier — 룰 기반 신호검출(detect_rule_signals)이 Serper 기반과 분리되어
네트워크 호출 없이 동작하는지 검증.

룰 기반은 모든 gate bucket 에서 항상 실행되므로 외부 API 없이 결정적이어야 한다.
"""

from __future__ import annotations

from pipeline.extractor import Entity
from pipeline import verifier


def _entity(text: str, label: str) -> Entity:
    return Entity(text=text, label=label, score=0.9, start=0, end=len(text))


def test_high_return_rate_triggers_rule_signal():
    results = verifier.detect_rule_signals([_entity("연 30%", "수익 퍼센트")])
    assert len(results) == 1
    assert results[0].flag == "abnormal_return_rate"
    assert results[0].triggered is True


def test_low_return_rate_not_triggered():
    results = verifier.detect_rule_signals([_entity("연 10%", "수익 퍼센트")])
    assert len(results) == 1
    assert results[0].flag == "abnormal_return_rate"
    assert results[0].triggered is False


def test_personal_info_request_triggers():
    results = verifier.detect_rule_signals([_entity("주민번호", "개인정보 항목")])
    assert len(results) == 1
    assert results[0].flag == "personal_info_request"
    assert results[0].triggered is True


def test_serper_labels_produce_no_rule_signal():
    # 전화번호·계좌번호 등은 Serper 기반 — detect_rule_signals 는 건드리지 않는다.
    results = verifier.detect_rule_signals([
        _entity("010-1234-5678", "전화번호"),
        _entity("110-222-333333", "계좌번호"),
        _entity("https://evil.example", "웹사이트 주소"),
    ])
    assert results == []


def test_empty_entities_returns_empty():
    assert verifier.detect_rule_signals([]) == []


def test_rule_and_serper_dispatch_are_disjoint():
    rule_labels = set(verifier._RULE_VERIFY_DISPATCH)
    serper_labels = set(verifier._SERPER_VERIFY_DISPATCH)
    assert rule_labels.isdisjoint(serper_labels)
    # 회사명은 Serper 기반 별도 처리 — 룰 dispatch 에 없어야 함
    assert verifier._COMPANY_LABELS.isdisjoint(rule_labels)
