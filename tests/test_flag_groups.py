"""Stage 3 — 검출 신호 그룹핑 레이어 검증.

- group_detected_flags: 같은 그룹 flag 들이 한 그룹으로 묶임
- 매핑 안 된 flag → "other_signals" 로 누락 없이 보존
- 동일 flag 중복 입력 → 1회만 카운트
- str / dict / DetectedSignal 입력 모두 허용
- 기존 FLAG_RATIONALE / FLAG_LABELS_KO / DETECTED_FLAGS 변경되지 않음
- DetectionReport.to_dict() 기존 필드 보존 + signal_groups 추가
- FLAG_GROUPS 의 모든 flag 가 DETECTED_FLAGS 에 존재 (오타·매핑 누락 방지)
"""

from __future__ import annotations

from pipeline.config import DETECTED_FLAGS, FLAG_LABELS_KO, FLAG_RATIONALE
from pipeline.flag_groups import (
    FLAG_GROUPS,
    OTHER_GROUP_ID,
    group_detected_flags,
    group_of,
)
from pipeline.signal_detector import DetectedSignal, DetectionReport


# ── 그룹핑 기본 ──

def test_multiple_flags_in_same_group_are_grouped():
    groups = group_detected_flags([
        "personal_info_request",
        "sandbox_password_form_detected",
    ])
    # 둘 다 personal_sensitive_request 에 속함 → 한 그룹 entry
    personal = [g for g in groups if g["group_id"] == "personal_sensitive_request"]
    assert len(personal) == 1
    assert personal[0]["count"] == 2
    assert set(personal[0]["flags"]) == {
        "personal_info_request", "sandbox_password_form_detected",
    }
    assert personal[0]["label_ko"] == "개인정보·민감정보 요구"
    assert personal[0]["summary"]  # 비어 있지 않음


def test_flags_from_different_groups_split():
    groups = group_detected_flags([
        "fake_government_agency",       # impersonation
        "urgent_transfer_demand",       # financial_demand
        "abnormal_return_rate",         # unrealistic_promise
    ])
    ids = {g["group_id"] for g in groups}
    assert ids == {"impersonation", "financial_demand", "unrealistic_promise"}
    for g in groups:
        assert g["count"] == 1


def test_unknown_flag_goes_to_other_group():
    groups = group_detected_flags(["personal_info_request", "_brand_new_unmapped_flag"])
    other = [g for g in groups if g["group_id"] == OTHER_GROUP_ID]
    assert len(other) == 1
    assert other[0]["flags"] == ["_brand_new_unmapped_flag"]
    assert other[0]["count"] == 1
    # 원본 flag 가 결과에서 누락되지 않음
    all_flags = [f for g in groups for f in g["flags"]]
    assert "_brand_new_unmapped_flag" in all_flags
    assert "personal_info_request" in all_flags


def test_empty_input_returns_empty_list():
    assert group_detected_flags([]) == []


def test_duplicate_flag_counted_once():
    groups = group_detected_flags([
        "personal_info_request",
        "personal_info_request",
        {"flag": "personal_info_request"},
    ])
    assert sum(g["count"] for g in groups) == 1


def test_output_order_follows_group_definition():
    # impersonation 먼저, financial_demand 나중에 들어와도 정의 순서 유지
    groups = group_detected_flags(["urgent_transfer_demand", "fake_government_agency"])
    ids_in_order = [g["group_id"] for g in groups]
    assert ids_in_order.index("impersonation") < ids_in_order.index("financial_demand")


def test_empty_groups_excluded():
    # 한 그룹만 있는 입력 → 출력에 한 그룹만
    groups = group_detected_flags(["threat_or_coercion"])
    assert len(groups) == 1
    assert groups[0]["group_id"] == "coercion_threat"


# ── 다양한 입력 형식 ──

def test_accepts_string_input():
    groups = group_detected_flags(["personal_info_request"])
    assert groups[0]["flags"] == ["personal_info_request"]


def test_accepts_dict_input():
    groups = group_detected_flags([{"flag": "personal_info_request", "label_ko": "X"}])
    assert groups[0]["flags"] == ["personal_info_request"]


def test_accepts_detected_signal_object():
    sig = DetectedSignal(flag="personal_info_request", label_ko="개인정보 요구",
                         rationale="", source="")
    groups = group_detected_flags([sig])
    assert groups[0]["flags"] == ["personal_info_request"]


def test_mixed_input_types():
    sig = DetectedSignal(flag="threat_or_coercion", label_ko="협박·강요",
                         rationale="", source="")
    groups = group_detected_flags([
        "personal_info_request",
        {"flag": "fake_government_agency"},
        sig,
    ])
    ids = {g["group_id"] for g in groups}
    assert ids == {"personal_sensitive_request", "impersonation", "coercion_threat"}


# ── group_of 단일 조회 ──

def test_group_of_known_flag():
    assert group_of("personal_info_request") == "personal_sensitive_request"
    assert group_of("threat_or_coercion") == "coercion_threat"


def test_group_of_unknown_flag_returns_other():
    assert group_of("does_not_exist") == OTHER_GROUP_ID


# ── 기존 schema 보존 ──

def test_existing_flag_rationale_unchanged():
    # 27+ 세부 flag 의 rationale 매핑은 절대 변경되지 않아야 함
    assert "abnormal_return_rate" in FLAG_RATIONALE
    assert "personal_info_request" in FLAG_RATIONALE
    assert "fake_government_agency" in FLAG_RATIONALE
    # 각 rationale 은 'rationale' 과 'source' 키를 가져야 함 (기존 schema)
    sample = FLAG_RATIONALE["abnormal_return_rate"]
    assert "rationale" in sample
    assert "source" in sample


def test_existing_flag_labels_ko_unchanged():
    assert FLAG_LABELS_KO["personal_info_request"] == "개인정보 요구"
    assert FLAG_LABELS_KO["abnormal_return_rate"] == "비정상적 고수익 주장"
    # 51개 라벨이 그대로
    assert len(FLAG_LABELS_KO) >= 51


def test_detected_flags_unchanged():
    # Stage 3 가 DETECTED_FLAGS 를 줄이지 않았다 (절대 11개로 교체 X)
    assert len(DETECTED_FLAGS) >= 51


# ── FLAG_GROUPS 무결성 ──

def test_all_grouped_flags_exist_in_detected_flags():
    """그룹 정의의 모든 flag 가 DETECTED_FLAGS 에 실재 — 오타·매핑 누락 방지."""
    detected_set = set(DETECTED_FLAGS)
    for group in FLAG_GROUPS:
        for flag in group["flags"]:
            assert flag in detected_set, f"unknown flag in FLAG_GROUPS: {flag}"


def test_no_flag_assigned_to_multiple_groups():
    seen: dict[str, str] = {}
    for group in FLAG_GROUPS:
        for flag in group["flags"]:
            assert flag not in seen, (
                f"flag {flag} assigned to both {seen[flag]} and {group['group_id']}"
            )
            seen[flag] = group["group_id"]


def test_group_count_is_around_eleven():
    # 사용자 요구: 11개 내외
    assert 8 <= len(FLAG_GROUPS) <= 13


# ── DetectionReport schema 보존 ──

def test_detection_report_keeps_existing_fields():
    report = DetectionReport(scam_type="투자 사기")
    payload = report.to_dict()
    # 기존 외부 schema 필드 유지
    for key in [
        "source", "scam_type", "classification_confidence", "is_uncertain",
        "entities", "detected_signals", "summary", "disclaimer",
    ]:
        assert key in payload, f"missing existing field: {key}"
    # scam_type 은 문자열 그대로 (list 로 안 바뀜)
    assert isinstance(payload["scam_type"], str)


def test_detection_report_to_dict_has_signal_groups():
    # Stage 3 추가 필드 — 기본값은 빈 list
    report = DetectionReport()
    payload = report.to_dict()
    assert "signal_groups" in payload
    assert payload["signal_groups"] == []


def test_detection_report_signal_groups_optional_consumer_safe():
    # 기존 소비자가 signal_groups 를 무시해도 깨지지 않아야 함 — list 타입 + 기본 빈 list
    report = DetectionReport(scam_type="투자 사기")
    payload = report.to_dict()
    assert isinstance(payload["signal_groups"], list)
