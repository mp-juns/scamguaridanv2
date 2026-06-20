"""사기 *신호 검출* — 점수·등급 산정 없음, 검출 사실만 보고.

ScamGuardian 의 정체성: 사기 판정 시스템이 아니라 사기 신호 검출 reference implementation.
VirusTotal 모델과 동일 — 70개 백신의 검출 결과를 *보고만* 한다. 판정은 통합한 기업의
risk tolerance 에 맡긴다.

이전 `pipeline/scorer.py` 의 *검출 조건 판정* 로직만 보존하고, 다음 항목은 모두 제거:
- 점수 합산 (`total_score`)
- 임계값 등급 산정 (`risk_level` / `RISK_LEVELS`)
- LLM 점수 보정 비율 (`LLM_FLAG_SCORE_RATIO`)
- "사기/비사기" 판정 (`is_scam`, `agent_verdict`)

응답에는 다음만 노출:
- `detected_signals`: 검출된 신호 list (각 신호의 학술/법적 근거 포함)
- `summary`: "위험 신호 N개 검출되었습니다."
- `disclaimer`: 통합 기업이 자체 판정 logic 구현하라는 안내
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pipeline.classifier import ClassificationResult
from pipeline.config import (
    DETECTED_FLAGS,
    FLAG_LABELS_KO,
    FLAG_RATIONALE,
    LLM_FLAG_DETECTION_CONFIDENCE_THRESHOLD,
    scam_category_for,
)
from pipeline.extractor import Entity
from pipeline.flag_groups import group_detected_flags
from pipeline.llm_assessor import LLMAssessment
from pipeline.verifier import VerificationResult


# ──────────────────────────────────
# 새 응답 schema
# ──────────────────────────────────


@dataclass
class DetectedSignal:
    """검출된 위험 신호 1개. 점수 없음 — 검출 사실 + 학술/법적 근거만."""
    flag: str                              # 영문 키 (DETECTED_FLAGS 멤버)
    label_ko: str                          # 한국어 라벨 (FLAG_LABELS_KO)
    rationale: str                         # 학술·법적 근거 (FLAG_RATIONALE)
    source: str                            # 출처 기관·논문 (FLAG_RATIONALE)
    detection_source: str = "rule"         # rule | llm | safety | sandbox — 누가 검출했는지
    evidence: list[str] = field(default_factory=list)
    description: str = ""                  # 검출 시점 컨텍스트 (e.g. "VT 다중 엔진 malicious 판정")

    def to_dict(self) -> dict[str, Any]:
        return {
            "flag": self.flag,
            "label_ko": self.label_ko,
            "rationale": self.rationale,
            "source": self.source,
            "detection_source": self.detection_source,
            "evidence": self.evidence,
            "description": self.description,
        }


_DEFAULT_DISCLAIMER = (
    "ScamGuardian 은 사기 판정을 내리지 않습니다. "
    "위 검출 신호의 학술·법적 근거를 참고해 통합 기업의 자체 판정 logic 으로 결정하세요."
)


@dataclass
class DetectionReport:
    """검출 보고서. **score / risk_level / is_scam / agent_verdict 필드 절대 추가 금지.**"""
    # 입력 정보
    source: str = ""
    transcript_preview: str = ""

    # 분류 결과 (검출의 컨텍스트 — 어떤 종류의 사기로 추정되는지만)
    scam_type: str = ""
    classification_confidence: float = 0.0
    is_uncertain: bool = False
    scam_type_source: str = "classifier"
    scam_type_reason: str = ""
    scam_type_classifier: str = ""
    scam_type_classifier_confidence: float = 0.0
    # 대표 카테고리 — scam_type 의 SCAM_CATEGORY_MAP 결정적 매핑 (표시 전용).
    # 내부 라우팅은 계속 scam_type 기준. scam_type 비면(게이트 normal 등) 빈 값.
    scam_category: str = ""
    scam_category_source: str = ""     # "mapping" | "" — 모델 기반 도입 시 구분용

    # 추출 결과
    entities: list[dict[str, Any]] = field(default_factory=list)

    # ── 핵심: 검출 신호 (점수 X, 등급 X) ──
    detected_signals: list[DetectedSignal] = field(default_factory=list)
    summary: str = ""
    disclaimer: str = _DEFAULT_DISCLAIMER
    # Stage 3 — UI/보고서 표시용 그룹핑 레이어 (기존 detected_signals 와 무관, 보조 필드).
    # 세부 flag 와 학술/법적 rationale 매핑은 detected_signals 에 그대로 보존.
    signal_groups: list[dict[str, Any]] = field(default_factory=list)

    # 검증 상세 (디버깅/감사용)
    all_verifications: list[dict[str, Any]] = field(default_factory=list)
    llm_assessment: dict[str, Any] | None = None
    rag_context: dict[str, Any] | None = None
    safety_check: dict[str, Any] | None = None
    sandbox_check: dict[str, Any] | None = None
    apk_static_check: dict[str, Any] | None = None
    apk_bytecode_check: dict[str, Any] | None = None
    apk_dynamic_check: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "transcript_preview": self.transcript_preview,
            "scam_type": self.scam_type,
            "classification_confidence": round(self.classification_confidence, 4),
            "is_uncertain": self.is_uncertain,
            "scam_type_source": self.scam_type_source,
            "scam_type_reason": self.scam_type_reason,
            "scam_type_classifier": self.scam_type_classifier,
            "scam_type_classifier_confidence": round(self.scam_type_classifier_confidence, 4),
            "scam_category": self.scam_category,
            "scam_category_source": self.scam_category_source,
            "entities": self.entities,
            "detected_signals": [s.to_dict() for s in self.detected_signals],
            "summary": self.summary,
            "disclaimer": self.disclaimer,
            "signal_groups": self.signal_groups,
            "verification_count": len(self.all_verifications),
            "llm_assessment": self.llm_assessment,
            "rag_context": self.rag_context,
            "safety_check": self.safety_check,
            "sandbox_check": self.sandbox_check,
            "apk_static_check": self.apk_static_check,
            "apk_bytecode_check": self.apk_bytecode_check,
            "apk_dynamic_check": self.apk_dynamic_check,
        }


# ──────────────────────────────────
# 검출 헬퍼
# ──────────────────────────────────


def _make_signal(
    *,
    flag: str,
    description: str,
    detection_source: str,
    evidence: list[str],
) -> DetectedSignal:
    info = FLAG_RATIONALE.get(flag, {})
    return DetectedSignal(
        flag=flag,
        label_ko=FLAG_LABELS_KO.get(flag, flag),
        rationale=info.get("rationale", ""),
        source=info.get("source", ""),
        detection_source=detection_source,
        evidence=evidence,
        description=description,
    )


def _add_sandbox_signal(
    detected: list[DetectedSignal],
    seen: set[str],
    flag: str,
    description: str,
    evidence: list[str],
) -> None:
    """샌드박스 신호 추가 (중복 방지)."""
    if flag in seen:
        return
    seen.add(flag)
    detected.append(_make_signal(
        flag=flag,
        description=description,
        detection_source="sandbox",
        evidence=evidence,
    ))


# ──────────────────────────────────
# 메인 검출 함수
# ──────────────────────────────────


def detect(
    verification_results: list[VerificationResult],
    classification: ClassificationResult,
    entities: list[Entity],
    source: str = "",
    transcript: str = "",
    llm_assessment: LLMAssessment | None = None,
    rag_context: dict[str, Any] | None = None,
    scam_type_source: str = "classifier",
    scam_type_reason: str = "",
    classifier_original: ClassificationResult | None = None,
    safety_result: Any = None,
    sandbox_result: Any = None,
    apk_static_result: Any = None,
    apk_bytecode_result: Any = None,
    apk_dynamic_result: Any = None,
) -> DetectionReport:
    """
    검증·LLM·safety·sandbox 결과를 종합해 *검출 신호* list 를 만든다.
    점수 합산·등급 산정·"사기다" 판정 모두 안 함.
    """
    detected: list[DetectedSignal] = []
    seen_flags: set[str] = set()

    # ─── Phase 0 안전성: VirusTotal 자동 신호 ───
    if safety_result is not None and getattr(safety_result, "threat_level", None) is not None:
        kind = getattr(safety_result, "target_kind", "")
        level = getattr(safety_result, "threat_level").value if hasattr(getattr(safety_result, "threat_level"), "value") else str(safety_result.threat_level)
        if level == "malicious":
            flag = "malware_detected" if kind == "file" else "phishing_url_confirmed"
        elif level == "suspicious":
            flag = "suspicious_file_signal" if kind == "file" else "suspicious_url_signal"
        else:
            flag = None
        if flag:
            seen_flags.add(flag)
            cats = getattr(safety_result, "threat_categories", []) or []
            evidence = [
                f"VirusTotal: {safety_result.detections}/{safety_result.total_engines} 엔진 악성 탐지",
                *cats[:2],
            ]
            detected.append(_make_signal(
                flag=flag,
                description=f"[Phase 0 안전성] VT 다중 엔진 {level} 판정",
                detection_source="safety",
                evidence=evidence,
            ))

    # ─── Phase 0.5 샌드박스 디토네이션 ───
    if sandbox_result is not None and getattr(sandbox_result, "status", None) is not None:
        sb_status = getattr(sandbox_result, "status")
        sb_status_val = sb_status.value if hasattr(sb_status, "value") else str(sb_status)
        if sb_status_val == "completed":
            sb_evidence_base = [
                f"target: {getattr(sandbox_result, 'target_url', '')[:120]}",
            ]
            final_url = getattr(sandbox_result, "final_url", None)
            if final_url and final_url != getattr(sandbox_result, "target_url", None):
                sb_evidence_base.append(f"final: {final_url[:120]}")

            if getattr(sandbox_result, "has_password_field", False):
                _add_sandbox_signal(
                    detected, seen_flags, "sandbox_password_form_detected",
                    "[Phase 0.5 샌드박스] 격리 환경에서 비밀번호 입력 필드 감지",
                    sb_evidence_base + [f"민감 필드: {', '.join(getattr(sandbox_result, 'sensitive_form_fields', []))}"],
                )
            elif getattr(sandbox_result, "sensitive_form_fields", []):
                _add_sandbox_signal(
                    detected, seen_flags, "sandbox_sensitive_form_detected",
                    "[Phase 0.5 샌드박스] 민감 정보 입력 필드 감지",
                    sb_evidence_base + [f"필드: {', '.join(getattr(sandbox_result, 'sensitive_form_fields', []))}"],
                )

            downloads = getattr(sandbox_result, "download_attempts", []) or []
            if downloads:
                _add_sandbox_signal(
                    detected, seen_flags, "sandbox_auto_download_attempt",
                    "[Phase 0.5 샌드박스] 자동 다운로드 시도 감지",
                    sb_evidence_base + [
                        f"다운로드: {d.get('suggested_filename') or d.get('url', '')[:80]}"
                        for d in downloads[:3]
                    ],
                )

            if getattr(sandbox_result, "cloaking_detected", False):
                _add_sandbox_signal(
                    detected, seen_flags, "sandbox_cloaking_detected",
                    "[Phase 0.5 샌드박스] 도메인 위장 (클로킹) 감지",
                    sb_evidence_base,
                )

            if getattr(sandbox_result, "excessive_redirects", False):
                redirect_count = len(getattr(sandbox_result, "redirect_chain", []) or [])
                _add_sandbox_signal(
                    detected, seen_flags, "sandbox_excessive_redirects",
                    "[Phase 0.5 샌드박스] 과도한 리디렉션",
                    sb_evidence_base + [f"리디렉션 횟수: {redirect_count}"],
                )

    # ─── Stage 2 APK 정적 분석 Lv 1 (manifest·권한·서명) ───
    if apk_static_result is not None:
        for flag in getattr(apk_static_result, "detected_flags", []) or []:
            if flag in seen_flags:
                continue
            if flag not in DETECTED_FLAGS:
                continue  # 알 수 없는 flag 차단
            seen_flags.add(flag)
            pkg = getattr(apk_static_result, "package_name", "") or ""
            evidence = [f"package: {pkg}"] if pkg else []
            detected.append(_make_signal(
                flag=flag,
                description="[Stage 2 APK 정적 분석] manifest·권한·서명 Lv 1",
                detection_source="static_lv1",
                evidence=evidence,
            ))

    # ─── Stage 3 APK 심화 정적 분석 Lv 2 (dex bytecode 패턴) ───
    if apk_bytecode_result is not None:
        for flag in getattr(apk_bytecode_result, "detected_flags", []) or []:
            if flag in seen_flags:
                continue
            if flag not in DETECTED_FLAGS:
                continue
            seen_flags.add(flag)
            detected.append(_make_signal(
                flag=flag,
                description="[Stage 3 APK 심화 정적 분석] dex bytecode 패턴 매칭 Lv 2",
                detection_source="static_lv2",
                evidence=[],
            ))

    # ─── Stage 4 APK 동적 분석 Lv 3 (격리 VM 에뮬레이터) ───
    # 기본 비활성. status=COMPLETED 일 때만 detected_flags 신호화.
    if apk_dynamic_result is not None:
        if getattr(apk_dynamic_result, "status", None) is not None:
            status_val = apk_dynamic_result.status.value if hasattr(apk_dynamic_result.status, "value") else str(apk_dynamic_result.status)
            if status_val == "completed":
                for flag in getattr(apk_dynamic_result, "detected_flags", []) or []:
                    if flag in seen_flags:
                        continue
                    if flag not in DETECTED_FLAGS:
                        continue
                    seen_flags.add(flag)
                    detected.append(_make_signal(
                        flag=flag,
                        description="[Stage 4 APK 동적 분석] 격리 VM 에뮬레이터 behavior 관찰 Lv 3",
                        detection_source="dynamic_lv3",
                        evidence=[f"backend: {apk_dynamic_result.backend}"],
                    ))

    # ─── Phase 4 검증 신호 ───
    for vr in verification_results:
        if not vr.triggered:
            continue
        if vr.flag in seen_flags:
            continue
        seen_flags.add(vr.flag)
        detected.append(_make_signal(
            flag=vr.flag,
            description=vr.flag_description,
            detection_source="rule",
            evidence=vr.evidence_snippets,
        ))

    # ─── LLM 보조 신호 (confidence 임계 통과한 것만) ───
    if llm_assessment is not None and not llm_assessment.error:
        for suggested in llm_assessment.suggested_flags:
            if suggested.confidence < LLM_FLAG_DETECTION_CONFIDENCE_THRESHOLD:
                continue
            if suggested.flag in seen_flags:
                continue
            if suggested.flag not in DETECTED_FLAGS:
                # 알 수 없는 flag 는 무시 (LLM 환각 차단)
                continue
            seen_flags.add(suggested.flag)
            detected.append(_make_signal(
                flag=suggested.flag,
                description=f"[LLM 보조] {suggested.reason}",
                detection_source="llm",
                evidence=[suggested.evidence] if suggested.evidence else [],
            ))

    summary = (
        f"위험 신호 {len(detected)}개 검출되었습니다. 자세한 근거는 탐지된 위험 신호 목록에서 확인할 수 있습니다."
        if detected
        else "위험 신호가 검출되지 않았습니다."
    )

    # 대표 카테고리 — 결정적 매핑. scam_type 비면(게이트 normal/news_edu 로 분류 skip) 빈 값.
    scam_category = scam_category_for(classification.scam_type)

    return DetectionReport(
        source=source,
        transcript_preview=transcript[:200] + ("..." if len(transcript) > 200 else ""),
        scam_type=classification.scam_type,
        classification_confidence=classification.confidence,
        is_uncertain=classification.is_uncertain,
        scam_category=scam_category,
        scam_category_source="mapping" if scam_category else "",
        scam_type_source=scam_type_source,
        scam_type_reason=scam_type_reason,
        scam_type_classifier=(classifier_original.scam_type if classifier_original else classification.scam_type),
        scam_type_classifier_confidence=(
            classifier_original.confidence if classifier_original else classification.confidence
        ),
        entities=[e.to_dict() for e in entities],
        detected_signals=detected,
        summary=summary,
        signal_groups=group_detected_flags(detected),
        all_verifications=[vr.to_dict() for vr in verification_results],
        llm_assessment=llm_assessment.to_dict() if llm_assessment is not None else None,
        rag_context=rag_context,
        safety_check=safety_result.to_dict() if safety_result is not None and hasattr(safety_result, "to_dict") else None,
        sandbox_check=sandbox_result.to_dict() if sandbox_result is not None and hasattr(sandbox_result, "to_dict") else None,
        apk_static_check=apk_static_result.to_dict() if apk_static_result is not None and hasattr(apk_static_result, "to_dict") else None,
        apk_bytecode_check=apk_bytecode_result.to_dict() if apk_bytecode_result is not None and hasattr(apk_bytecode_result, "to_dict") else None,
        apk_dynamic_check=apk_dynamic_result.to_dict() if apk_dynamic_result is not None and hasattr(apk_dynamic_result, "to_dict") else None,
    )
