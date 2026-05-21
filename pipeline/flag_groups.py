"""Stage 3 — 검출 신호 그룹핑 레이어 (UI/보고서 표시용).

기존 세부 flag (`DETECTED_FLAGS` / `FLAG_RATIONALE` / `FLAG_LABELS_KO`)는
*절대 변경하지 않는다*. Stage 3 는 내부 flag 를 대체하지 않고, 사용자·관리자
화면에서 관련 flag 들을 ~11개 그룹으로 묶어 보여주기 위한 **표시 레이어**다.

세부 flag 는 감사 가능성, 학술·법적 rationale 매핑, 학습/평가용으로 그대로 유지.

사용:
    from pipeline.flag_groups import group_detected_flags
    groups = group_detected_flags(detected_signals)
    # → [{"group_id": "impersonation", "label_ko": "사칭·신원위조",
    #     "count": 2, "flags": [...], "summary": "...", "description": "..."}]

새 flag 가 추가됐는데 그룹 매핑에 없으면 "other_signals" 그룹으로 누락 없이
보존된다 — 매핑 누락이 검출 누락으로 이어지지 않게.
"""

from __future__ import annotations

from typing import Any, Iterable

OTHER_GROUP_ID = "other_signals"


# 그룹 정의. 정의 순서가 출력 순서. 각 flag id 는 한 그룹에만 속한다.
FLAG_GROUPS: list[dict[str, Any]] = [
    {
        "group_id": "impersonation",
        "label_ko": "사칭·신원위조",
        "description": "정부기관·기업·가족·인증기관 사칭 또는 사업자·금융 등록 위조",
        "summary": "공공기관·기업·지인을 사칭하거나 신원·등록 정보가 위조된 신호",
        "flags": [
            "fake_government_agency",
            "impersonation_family",
            "romance_foreign_identity",
            "fake_certification",
            "fake_exchange",
            "business_not_registered",
            "ceo_name_mismatch",
            "fss_not_registered",
        ],
    },
    {
        "group_id": "personal_sensitive_request",
        "label_ko": "개인정보·민감정보 요구",
        "description": "주민번호·비밀번호·OTP·자격증명 등 민감 정보 요구",
        "summary": "개인정보 또는 자격증명 제공을 요구하는 신호",
        "flags": [
            "personal_info_request",
            "sandbox_password_form_detected",
            "sandbox_sensitive_form_detected",
            "apk_runtime_credential_exfiltration",
        ],
    },
    {
        "group_id": "financial_demand",
        "label_ko": "금전·이체 요구",
        "description": "송금·선납금·수수료·에스크로 회피 등 금전 이동 요구",
        "summary": "긴급 송금·선납·에스크로 회피 등 금전 제공을 유도하는 신호",
        "flags": [
            "urgent_transfer_demand",
            "prepayment_requested",
            "job_deposit_requested",
            "fake_escrow_bypass",
        ],
    },
    {
        "group_id": "unrealistic_promise",
        "label_ko": "비현실적 보장·주장",
        "description": "고수익·완치 등 검증되지 않은 보장",
        "summary": "비현실적 고수익이나 의학적 효능 등 검증되지 않은 보장 신호",
        "flags": [
            "abnormal_return_rate",
            "medical_claim_unverified",
        ],
    },
    {
        "group_id": "coercion_threat",
        "label_ko": "협박·강요",
        "description": "협박·공포 조성·강요성 발화",
        "summary": "협박·강요로 즉각적 행동을 압박하는 신호",
        "flags": ["threat_or_coercion"],
    },
    {
        "group_id": "malicious_link_url",
        "label_ko": "악성·피싱 URL",
        "description": "피싱 URL, 스미싱 링크, 도메인 위장, 자동 다운로드 등 웹 기반 위협",
        "summary": "외부 링크·웹 행위 기반 위협 신호 (피싱·스미싱·클로킹 등)",
        "flags": [
            "smishing_link_detected",
            "phishing_url_confirmed",
            "suspicious_url_signal",
            "website_scam_reported",
            "sandbox_cloaking_detected",
            "sandbox_excessive_redirects",
            "sandbox_auto_download_attempt",
        ],
    },
    {
        "group_id": "malware_file",
        "label_ko": "악성 파일·코드",
        "description": "다중 백신 엔진 또는 파일 시그니처에서 악성으로 확인된 신호",
        "summary": "VirusTotal 등에서 악성으로 확인된 파일·코드 신호",
        "flags": [
            "malware_detected",
            "suspicious_file_signal",
        ],
    },
    {
        "group_id": "malicious_apk",
        "label_ko": "악성 APK 행위",
        "description": "안드로이드 APK 의 위험 권한·악성 코드·런타임 행위",
        "summary": "APK manifest·bytecode·런타임 행위에서 발견된 악성 신호",
        "flags": [
            "apk_dangerous_permissions_combo",
            "apk_self_signed",
            "apk_suspicious_package_name",
            "apk_sms_auto_send_code",
            "apk_call_state_listener",
            "apk_accessibility_abuse",
            "apk_impersonation_keywords",
            "apk_hardcoded_c2_url",
            "apk_string_obfuscation",
            "apk_device_admin_lock",
            "apk_runtime_c2_network_call",
            "apk_runtime_sms_intercepted",
            "apk_runtime_overlay_attack",
            "apk_runtime_persistence_install",
        ],
    },
    {
        "group_id": "scam_history_report",
        "label_ko": "스캠 신고 이력",
        "description": "전화번호·계좌가 스캠으로 신고된 이력",
        "summary": "공개된 스캠 신고 데이터에서 매칭된 신호",
        "flags": [
            "account_scam_reported",
            "phone_scam_reported",
        ],
    },
    {
        "group_id": "context_mismatch",
        "label_ko": "발화 맥락 불일치",
        "description": "화자 프로파일과 발화 내용의 의미 불일치",
        "summary": "화자의 알려진 활동·전문성과 발화 맥락이 어긋나는 신호",
        "flags": [
            "authority_context_mismatch",
            "authority_context_uncertain",
        ],
    },
    {
        "group_id": "external_verification",
        "label_ko": "외부 교차검증·팩트체크",
        "description": "신뢰 언론·팩트체크에서의 검증 결과",
        "summary": "외부 검색·팩트체크에서 확인되거나 스캠 패턴이 발견된 신호",
        "flags": [
            "query_a_confirmed",
            "query_a_unconfirmed",
            "query_b_factcheck_found",
            "query_b_confirmed",
            "query_c_scam_pattern_found",
        ],
    },
]


# flag id → group_id 역매핑 (조회 빠르게)
_FLAG_TO_GROUP: dict[str, str] = {
    flag: group["group_id"]
    for group in FLAG_GROUPS
    for flag in group["flags"]
}


_OTHER_GROUP_META: dict[str, str] = {
    "group_id": OTHER_GROUP_ID,
    "label_ko": "기타 신호",
    "description": "정의된 그룹에 매핑되지 않은 검출 신호",
    "summary": "그룹 정의에 매핑되지 않은 신호 — 그룹 정의를 업데이트하세요",
}


def _flag_id_of(item: Any) -> str:
    """입력이 str / dict / DetectedSignal 무엇이든 flag id 문자열로 정규화."""
    if isinstance(item, str):
        return item.strip()
    if isinstance(item, dict):
        return str(item.get("flag", "")).strip()
    flag_attr = getattr(item, "flag", None)
    return str(flag_attr).strip() if flag_attr else ""


def group_of(flag_id: str) -> str:
    """단일 flag id 의 group_id (없으면 OTHER_GROUP_ID)."""
    return _FLAG_TO_GROUP.get(flag_id, OTHER_GROUP_ID)


def group_detected_flags(flags: Iterable[Any]) -> list[dict[str, Any]]:
    """검출된 flag 리스트를 표시용 그룹으로 묶어 반환.

    Args:
        flags: flag id 문자열, `DetectedSignal` 객체, 또는 그 to_dict() dict 의 iterable.

    Returns:
        그룹 list — 정의 순서 유지, 빈 그룹은 제외. 알 수 없는 flag 는
        "other_signals" 그룹으로 *누락 없이* 보존. 각 그룹은:
            {group_id, label_ko, description, summary, count, flags: [flag_ids]}

    동일 flag 가 중복으로 들어와도 한 번만 카운트된다.
    """
    buckets: dict[str, list[str]] = {g["group_id"]: [] for g in FLAG_GROUPS}
    other: list[str] = []
    seen: set[str] = set()

    for raw in flags:
        flag_id = _flag_id_of(raw)
        if not flag_id or flag_id in seen:
            continue
        seen.add(flag_id)
        group_id = _FLAG_TO_GROUP.get(flag_id)
        if group_id is None:
            other.append(flag_id)
        else:
            buckets[group_id].append(flag_id)

    out: list[dict[str, Any]] = []
    for group in FLAG_GROUPS:
        gid = group["group_id"]
        items = buckets[gid]
        if not items:
            continue
        out.append({
            "group_id": gid,
            "label_ko": group["label_ko"],
            "description": group["description"],
            "summary": group["summary"],
            "count": len(items),
            "flags": items,
        })
    if other:
        out.append({
            **_OTHER_GROUP_META,
            "count": len(other),
            "flags": other,
        })
    return out
