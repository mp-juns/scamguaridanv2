"""
ScamGuardian — 파이프라인 오케스트레이터
전체 분석 흐름을 조율하며 각 단계를 순차 실행한다.

Identity (CLAUDE.md): 점수·등급 산정 안 함. signal_detector 가 검출 신호 list 만 만들고,
DetectionReport 로 통합 기업에 전달. 통합 기업이 자체 판정 logic 으로 결정.
"""

from __future__ import annotations

import concurrent.futures
import os
import time
from dataclasses import dataclass
from typing import Any

from pipeline import apk_analyzer, classifier, extractor, gate, llm_assessor, rag, safety, sandbox, signal_detector, stt, verifier
from pipeline.config import (
    CLASSIFICATION_THRESHOLD,
    COMMON_RISK_LABELS,
    RAG_TOP_K,
    get_runtime_scam_taxonomy,
)
from pipeline.signal_detector import DetectionReport


@dataclass
class StepLog:
    name: str
    duration_ms: float
    detail: Any = None


def _all_label_union() -> list[str]:
    """모든 scam_type LABEL_SET + 공통 위험 라벨의 합집합 (분류 skip 시 사용)."""
    runtime = get_runtime_scam_taxonomy()["label_sets"]
    union = {lbl for labels in runtime.values() for lbl in labels}
    union.update(COMMON_RISK_LABELS)
    return sorted(union)


def _extraction_label_set(candidates: list[str]) -> list[str]:
    """Stage 2 — 공통 위험 라벨 + candidate scam_type 들의 LABEL_SET 합집합.

    top-1 이 '투자 사기' 여도 개인정보 항목·악성 URL 같은 공통 위험 라벨이 항상
    추출 대상에 포함된다 (COMMON_RISK_LABELS).
    """
    runtime = get_runtime_scam_taxonomy()["label_sets"]
    labels: set[str] = set(COMMON_RISK_LABELS)
    for scam_type in candidates:
        labels.update(runtime.get(scam_type, []))
    return sorted(labels)


class ScamGuardianPipeline:
    """
    ScamGuardian v2 전체 파이프라인.

    사용법:
        pipe = ScamGuardianPipeline()
        report = pipe.analyze("https://youtube.com/watch?v=...")
        print(report.summary())
    """

    def __init__(self, whisper_model: str = "medium", debug: bool = False):
        self.whisper_model = whisper_model
        self.debug = debug
        self.steps: list[StepLog] = []
        self.last_transcript_result: stt.TranscriptResult | None = None
        self.last_classification: classifier.ClassificationResult | None = None
        self.last_entities: list[extractor.Entity] = []
        self.last_verification_results: list[verifier.VerificationResult] = []
        self.last_llm_assessment: llm_assessor.LLMAssessment | None = None
        self.last_similar_cases: list[dict[str, Any]] = []
        self.last_report: DetectionReport | None = None
        self.last_gate_result: gate.GateResult | None = None
        self.last_candidate_scam_types: list[str] = []

    def _debug(self, message: str):
        if self.debug:
            print(f"[DEBUG] {message}")

    def _log_step(self, name: str, start: float, detail: Any = None):
        elapsed = (time.time() - start) * 1000
        self.steps.append(StepLog(name=name, duration_ms=round(elapsed, 1), detail=detail))

    # ──────────────────────────────────
    # 개별 단계 (독립 호출 가능)
    # ──────────────────────────────────

    def transcribe(self, source: str) -> stt.TranscriptResult:
        t0 = time.time()
        self._debug(f"transcribe() 시작: model={self.whisper_model}, source={source[:80]}")
        result = stt.transcribe(
            source,
            model_size=self.whisper_model,
            debug=self.debug,
            logger=self._debug,
        )
        self._log_step("STT", t0, {"source_type": result.source_type, "text_length": len(result.text)})
        self.last_transcript_result = result
        return result

    def classify(self, text: str) -> classifier.ClassificationResult:
        t0 = time.time()
        self._debug(f"classify() 시작: text_length={len(text)}")
        result = classifier.classify(text)
        self._log_step("분류", t0, {"scam_type": result.scam_type, "confidence": result.confidence})
        self._debug(
            f"classify() 완료: scam_type={result.scam_type}, confidence={result.confidence:.3f}, "
            f"scores={result.all_scores}"
        )
        self.last_classification = result
        return result

    def extract(
        self, text: str, scam_type: str, labels: list[str] | None = None,
    ) -> list[extractor.Entity]:
        t0 = time.time()
        self._debug(f"extract() 시작: scam_type={scam_type}, labels={'union' if labels else 'by_type'}")
        entities = extractor.extract(text, scam_type, labels=labels)
        self._log_step("추출", t0, {"entity_count": len(entities)})
        self._debug(f"extract() 완료: entity_count={len(entities)}")
        self.last_entities = entities
        return entities

    def verify(
        self,
        entities: list[extractor.Entity],
        scam_type: str,
        transcript: str,
    ) -> list[verifier.VerificationResult]:
        t0 = time.time()
        self._debug(
            f"verify() 시작: entities={len(entities)}, scam_type={scam_type}, transcript_len={len(transcript)}"
        )
        results = verifier.verify(entities, scam_type, transcript=transcript)
        triggered = sum(1 for r in results if r.triggered)
        self._log_step("검증", t0, {"total_checks": len(results), "triggered": triggered})
        self._debug(f"verify() 완료: total_checks={len(results)}, triggered={triggered}")
        self.last_verification_results = results
        return results

    def retrieve_similar_cases(
        self,
        text: str,
        scam_type: str,
    ) -> list[dict[str, Any]]:
        t0 = time.time()
        self._debug(f"retrieve_similar_cases() 시작: scam_type={scam_type}, text_length={len(text)}")
        query_embedding = rag.compute_transcript_embedding(text)
        results = rag.retrieve_similar_runs(query_embedding, RAG_TOP_K, scam_type=scam_type)
        self._log_step("RAG", t0, {"similar_cases": len(results)})
        self._debug(f"retrieve_similar_cases() 완료: similar_cases={len(results)}")
        self.last_similar_cases = results
        return results

    def assess_with_llm(
        self,
        text: str,
        scam_type: str,
        entities: list[extractor.Entity],
        verification_results: list[verifier.VerificationResult],
        similar_cases: list[dict[str, Any]] | None = None,
    ) -> llm_assessor.LLMAssessment:
        t0 = time.time()
        self._debug(
            f"assess_with_llm() 시작: scam_type={scam_type}, entities={len(entities)}, "
            f"triggered={sum(1 for r in verification_results if r.triggered)}, "
            f"similar_cases={len(similar_cases or [])}"
        )
        result = llm_assessor.assess(
            text,
            scam_type,
            entities,
            verification_results,
            similar_cases=similar_cases,
        )
        self._log_step(
            "LLM",
            t0,
            {
                "model": result.model,
                "suggested_entities": len(result.suggested_entities),
                "suggested_flags": len(result.suggested_flags),
                "error": result.error,
            },
        )
        self._debug(
            f"assess_with_llm() 완료: entities={len(result.suggested_entities)}, "
            f"flags={len(result.suggested_flags)}, error={result.error!r}"
        )
        self.last_llm_assessment = result
        return result

    # ──────────────────────────────────
    # 전체 파이프라인
    # ──────────────────────────────────

    def analyze(
        self,
        source: str,
        skip_verification: bool = False,
        use_llm: bool = False,
        use_rag: bool = False,
        precomputed_transcript: stt.TranscriptResult | None = None,
        user_context: dict[str, Any] | None = None,
    ) -> DetectionReport:
        """
        전체 검출 파이프라인을 실행한다. 점수·등급 산정 없음 — 검출 신호만.

        Args:
            source: YouTube URL, 로컬 파일 경로, 또는 텍스트
            skip_verification: True이면 Serper API 검증 단계를 건너뜀 (테스트용)
            use_llm: True이면 Claude 기반 보조 검출을 추가 수행
            precomputed_transcript: 외부에서 미리 STT 한 결과. 있으면 Phase 1 스킵.
            user_context: 챗봇 대화로 모은 사용자 제보 dict (Phase 3 LLM 에 prior 로 주입)

        Returns:
            DetectionReport — detected_signals[] 형태로 검출 신호 list 만 보고.
            점수·등급·"사기다" 판정 없음. 통합 기업이 자체 판정 logic 구현.
        """
        self.steps = []
        self.last_transcript_result = None
        self.last_classification = None
        self.last_entities = []
        self.last_verification_results = []
        self.last_llm_assessment = None
        self.last_similar_cases = []
        self.last_report = None
        self.last_gate_result = None
        self.last_candidate_scam_types = []
        self.last_safety_result: safety.SafetyResult | None = None
        self.last_sandbox_result: sandbox.SandboxResult | None = None
        self.last_apk_static_result: apk_analyzer.APKStaticReport | None = None
        self.last_apk_bytecode_result: apk_analyzer.APKBytecodeReport | None = None
        self.last_apk_dynamic_result: apk_analyzer.APKDynamicReport | None = None
        pipeline_start = time.time()
        # effective_use_llm / effective_use_rag 는 Phase 1.5 게이트 후 확정된다.
        self._debug(
            "analyze() 시작: "
            f"skip_verification={skip_verification}, use_llm={use_llm}, use_rag={use_rag}"
        )

        # ════════════════════════════════
        # Phase 0 (v3): 안전성 필터 — URL/파일이면 VirusTotal 스캔
        # VT 는 source 자체(URL·바이너리)를 보는 것이지 transcript 와 무관하므로
        # precomputed_transcript 유무와 관계없이 URL/파일 입력이면 항상 돈다.
        # ════════════════════════════════
        safety_result: safety.SafetyResult | None = None
        phase0_start = time.time()
        try:
            if stt._is_youtube_url(source) or source.startswith(("http://", "https://")):
                print("[Phase 0] URL 안전성 검사 중 (VirusTotal)...")
                safety_result = safety.scan_url(source)
            else:
                src_path = source if source else None
                if src_path and len(src_path) < 1024 and "/" in src_path:
                    from pathlib import Path as _Path
                    if _Path(src_path).exists() and _Path(src_path).is_file():
                        print("[Phase 0] 파일 안전성 검사 중 (VirusTotal)...")
                        safety_result = safety.scan_file(src_path)
        except Exception as exc:  # noqa: BLE001 — 안전성은 죽으면 안 됨
            print(f"[Phase 0] 검사 실패(무시): {exc}")
            safety_result = None
        if safety_result is not None:
            self.last_safety_result = safety_result
            self._log_step(
                "Safety",
                phase0_start,
                {
                    "threat_level": safety_result.threat_level.value,
                    "detections": safety_result.detections,
                    "total_engines": safety_result.total_engines,
                },
            )
            level = safety_result.threat_level.value
            icon = "🚨" if level == "malicious" else ("⚠️" if level == "suspicious" else "✅")
            print(
                f"      ← {icon} {level} | 탐지 {safety_result.detections}/{safety_result.total_engines} | "
                f"카테고리: {', '.join(safety_result.threat_categories[:3]) or '없음'}"
            )

        # 악성 파일 확정 시 fast-path: STT/분류기가 바이너리에서 죽거나 노이즈 분류하지 않게
        # 즉시 safety 결과만으로 보고서 생성. policy (b) 의 "분석은 진행" 은 텍스트
        # 첨부가 같이 있을 때만 의미 있으므로 단독 악성 파일은 빠르게 막는다.
        if (
            safety_result is not None
            and safety_result.is_malicious
            and safety_result.target_kind == "file"
            and precomputed_transcript is None
        ):
            print("[fast-path] 악성 파일 확정 — STT/분류 skip, safety 결과만으로 보고")
            transcript = stt.TranscriptResult(text="", source_type="file")
            self.last_transcript_result = transcript
            empty_classification = classifier.ClassificationResult(
                scam_type="메신저 피싱",
                confidence=0.0,
                all_scores={},
                is_uncertain=True,
            )
            self.last_classification = empty_classification
            report = signal_detector.detect(
                verification_results=[],
                classification=empty_classification,
                entities=[],
                source=source,
                transcript="",
                safety_result=safety_result,
            )
            self.last_report = report
            self._log_step("전체", pipeline_start)
            return report

        # ════════════════════════════════
        # Phase 0.5 (v3.5): URL 디토네이션 — 격리 Chromium 으로 의심 URL 직접 navigate
        # 조건: 입력이 URL + Phase 0 fast-path 트리거 안 됨 + SANDBOX_ENABLED.
        # 디토네이션도 source 자체를 보는 작업이라 precomputed_transcript 와 무관.
        # ════════════════════════════════
        sandbox_result: sandbox.SandboxResult | None = None
        sandbox_enabled = (
            os.getenv("SANDBOX_ENABLED", "0") == "1"
            and source.startswith(("http://", "https://"))
        )
        if sandbox_enabled:
            phase05_start = time.time()
            try:
                print("[Phase 0.5] URL 디토네이션 (격리 Chromium)...")
                sandbox_result = sandbox.detonate_url(source)
            except Exception as exc:  # noqa: BLE001 — 샌드박스도 죽으면 안 됨
                print(f"[Phase 0.5] 디토네이션 실패(무시): {exc}")
                sandbox_result = None
            if sandbox_result is not None:
                self.last_sandbox_result = sandbox_result
                self._log_step(
                    "Sandbox",
                    phase05_start,
                    {
                        "status": sandbox_result.status.value,
                        "redirect_count": len(sandbox_result.redirect_chain),
                        "has_password_field": sandbox_result.has_password_field,
                        "downloads": len(sandbox_result.download_attempts),
                        "duration_ms": sandbox_result.duration_ms,
                    },
                )
                icon = "🚨" if sandbox_result.is_dangerous else "✅"
                print(
                    f"      ← {icon} status={sandbox_result.status.value} "
                    f"final={sandbox_result.final_url[:60] if sandbox_result.final_url else '-'} "
                    f"pwd_form={sandbox_result.has_password_field} "
                    f"downloads={len(sandbox_result.download_attempts)} "
                    f"cloaking={sandbox_result.cloaking_detected}"
                )

        # ════════════════════════════════
        # Phase 0.6 (Stage 2/3): APK 정적 분석 (Lv 1 + Lv 2)
        # 입력이 APK 파일일 때만. 코드 *읽기만*, 실행 X (정적 분석).
        # 진짜 동적 분석 (에뮬레이터 behavior 모니터링) 은 future work.
        # ════════════════════════════════
        apk_static_result: apk_analyzer.APKStaticReport | None = None
        apk_bytecode_result: apk_analyzer.APKBytecodeReport | None = None
        apk_dynamic_result: apk_analyzer.APKDynamicReport | None = None
        if precomputed_transcript is None and apk_analyzer.is_apk_file(source):
            phase06_start = time.time()
            print("[Phase 0.6] APK 정적 분석 (Lv 1 — manifest·권한·서명)...")
            try:
                apk_static_result = apk_analyzer.analyze_apk_static(source)
                self.last_apk_static_result = apk_static_result
                print(
                    f"      ← Lv 1: 검출 {len(apk_static_result.detected_flags)}개, "
                    f"package={apk_static_result.package_name[:40]}, "
                    f"perms={len(apk_static_result.permissions)}, "
                    f"self_signed={apk_static_result.is_self_signed}"
                )
            except Exception as exc:  # noqa: BLE001 — 분석은 죽으면 안 됨
                print(f"[Phase 0.6] Lv 1 실패 (무시): {exc}")

            print("[Phase 0.6] APK 심화 정적 분석 (Lv 2 — bytecode 패턴)...")
            try:
                apk_bytecode_result = apk_analyzer.analyze_apk_bytecode(source)
                self.last_apk_bytecode_result = apk_bytecode_result
                print(
                    f"      ← Lv 2: 검출 {len(apk_bytecode_result.detected_flags)}개"
                    + (f" — flags={apk_bytecode_result.detected_flags}"
                       if apk_bytecode_result.detected_flags else "")
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[Phase 0.6] Lv 2 실패 (무시): {exc}")

            # Lv 3 — 동적 분석 (기본 비활성, 격리 VM 만 허용)
            print("[Phase 0.6] APK 동적 분석 (Lv 3 — 격리 VM 에뮬레이터)...")
            try:
                apk_dynamic_result = apk_analyzer.analyze_apk_dynamic(source)
                self.last_apk_dynamic_result = apk_dynamic_result
                status_val = apk_dynamic_result.status.value
                print(
                    f"      ← Lv 3: status={status_val} "
                    f"backend={apk_dynamic_result.backend or '-'} "
                    f"flags={len(apk_dynamic_result.detected_flags)}"
                    + (f" — {apk_dynamic_result.error[:60]}" if apk_dynamic_result.error else "")
                )
            except Exception as exc:  # noqa: BLE001
                print(f"[Phase 0.6] Lv 3 실패 (무시): {exc}")

            self._log_step(
                "APK",
                phase06_start,
                {
                    "lv1_flags": len((apk_static_result.detected_flags if apk_static_result else []) or []),
                    "lv2_flags": len((apk_bytecode_result.detected_flags if apk_bytecode_result else []) or []),
                    "lv3_status": apk_dynamic_result.status.value if apk_dynamic_result else "-",
                    "lv3_flags": len((apk_dynamic_result.detected_flags if apk_dynamic_result else []) or []),
                },
            )

        # ════════════════════════════════
        # Phase 1: STT (precomputed_transcript 있으면 스킵)
        # ════════════════════════════════
        if precomputed_transcript is not None:
            print("[Phase 1] STT 스킵 (precomputed_transcript 사용)")
            transcript = precomputed_transcript
            self.last_transcript_result = transcript
            self._log_step(
                "STT",
                pipeline_start,  # 0 ms 로 기록되도 무방
                {"source_type": transcript.source_type, "text_length": len(transcript.text), "precomputed": True},
            )
        else:
            print("[Phase 1] STT 처리 중...")
            print(f"      → 입력: {source[:80]}{'…' if len(source) > 80 else ''}")
            transcript = self.transcribe(source)
        text = transcript.text
        preview = text[:100] + "…" if len(text) > 100 else text
        print(f"      ← 결과: {transcript.source_type} | {len(text)}자")
        if transcript.source_type != "text":
            print(f"      ← 전사: {preview}")

        # ════════════════════════════════
        # Phase 1.5: 콘텐츠 게이트 (Stage 1 — 내부 라우팅 전용)
        # 게이트 결과는 외부 응답에 노출하지 않는다 (Identity Boundary). 파이프라인
        # 실행 강도 라우팅 + 내부 metadata 에만 쓴다. self.last_gate_result 로 노출.
        # ════════════════════════════════
        print("[Phase 1.5] 콘텐츠 게이트 분류 중...")
        gate_start = time.time()
        gate_result = gate.classify_gate(text)
        self.last_gate_result = gate_result
        gate_profile = gate_result.execution_profile()
        self._log_step(
            "Gate",
            gate_start,
            {"bucket": gate_result.bucket, "source": gate_result.source},
        )
        print(
            f"      ← {gate_result.label_ko} ({gate_result.bucket}) | "
            f"scam_type={'O' if gate_profile['run_scam_type'] else 'skip'} "
            f"serper≤{gate_profile['serper_max_entities']} "
            f"llm={'O' if gate_profile['use_llm'] else 'skip'}"
        )

        # 게이트 profile 은 호출자 인자를 *상한선으로 줄이기만* 한다.
        effective_use_llm = use_llm and gate_profile["use_llm"]
        effective_use_rag = effective_use_llm and use_rag

        # ════════════════════════════════
        # Phase 2: 스캠 유형 분류 (mDeBERTa) — 게이트 profile 에 따라
        # ════════════════════════════════
        scam_type_source = "classifier"
        scam_type_reason = ""
        if gate_profile["run_scam_type"]:
            print("[Phase 2] 스캠 유형 분류 중...")
            print(f"      → mDeBERTa NLI 모델에 {len(text)}자 전송")
            classification = self.classify(text)
            top3 = sorted(classification.all_scores.items(), key=lambda x: x[1], reverse=True)[:3]
            top3_str = ", ".join(f"{k}({v:.1%})" for k, v in top3)
            print(f"      ← 판정: {classification.scam_type} (신뢰도: {classification.confidence:.1%})")
            print(f"      ← Top3: {top3_str}")
        else:
            print(f"[Phase 2] 스캠 유형 분류 skip (게이트: {gate_result.label_ko})")
            classification = classifier.ClassificationResult(
                scam_type="", confidence=0.0, all_scores={}, is_uncertain=True,
            )
            self.last_classification = classification
        classifier_original = classification

        # Stage 2: multi-label 추출 라우팅 후보 (all_scores 기반).
        # scam_type 필드는 top-1 문자열 그대로 유지 — 후보는 엔티티 추출 라우팅에만
        # 쓰이고 외부 응답에는 노출하지 않는다 (self.last_candidate_scam_types → 내부 metadata).
        candidate_scam_types = classifier.candidate_scam_types(classification.all_scores)
        self.last_candidate_scam_types = candidate_scam_types
        if candidate_scam_types:
            print(f"      ← Stage 2 추출 후보 유형: {', '.join(candidate_scam_types)}")

        # ════════════════════════════════
        # Phase 3: 병렬 실행 (LLM통합 + 엔티티추출 + RAG)
        # ════════════════════════════════
        print("[Phase 3] 병렬 실행 중 (LLM + 추출 + RAG)...")
        llm_result: llm_assessor.LLMAssessment | None = None
        unified_result: llm_assessor.UnifiedLLMResult | None = None
        entities: list[extractor.Entity] = []
        similar_cases: list[dict[str, Any]] = []

        def _task_extract():
            if not candidate_scam_types:
                # all_scores 없음 (게이트가 분류 skip 등) → 기존 top-1 라우팅 fallback.
                if classification.scam_type:
                    return self.extract(text, classification.scam_type)
                return self.extract(text, "", labels=_all_label_union())
            # Stage 2 multi-label: 공통 위험 라벨 + top-N 후보 LABEL_SET 합집합.
            labels = _extraction_label_set(candidate_scam_types)
            return self.extract(text, classification.scam_type, labels=labels)

        def _task_llm_unified():
            return llm_assessor.analyze_unified(
                text, classification.scam_type, user_context=user_context,
            )

        def _task_rag():
            return self.retrieve_similar_cases(text, classification.scam_type)

        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            # 항상 엔티티 추출
            future_extract = executor.submit(_task_extract)

            # LLM 통합 호출 (게이트 profile 로 게이팅된 effective_use_llm)
            future_llm = executor.submit(_task_llm_unified) if effective_use_llm else None

            # RAG (use_rag일 때만)
            future_rag = executor.submit(_task_rag) if effective_use_rag else None

            # 결과 수집
            entities = future_extract.result()
            print(f"      ← 엔티티 추출: {len(entities)}개")
            for e in entities:
                print(f"         [{e.label}] {e.text} ({e.score:.2f})")

            if future_llm is not None:
                try:
                    unified_result = future_llm.result()
                    llm_result = unified_result.assessment
                    suggestion = unified_result.scam_type_suggestion
                    print(
                        f"      ← LLM 통합: 엔티티 {len(llm_result.suggested_entities)}개, "
                        f"플래그 {len(llm_result.suggested_flags)}개"
                    )
                    # LLM 스캠 유형 재판정 적용
                    if suggestion is not None and suggestion.scam_type != classification.scam_type:
                        classification = classifier.ClassificationResult(
                            scam_type=suggestion.scam_type,
                            confidence=suggestion.confidence,
                            all_scores=classifier_original.all_scores,
                            is_uncertain=suggestion.confidence < CLASSIFICATION_THRESHOLD,
                        )
                        scam_type_source = "llm"
                        scam_type_reason = suggestion.reason
                        print(
                            f"      → [LLM 재판정] {classification.scam_type} "
                            f"(신뢰도: {classification.confidence:.1%})"
                        )
                except Exception as exc:
                    llm_result = llm_assessor.LLMAssessment(
                        model=llm_assessor.default_model_name(), error=str(exc),
                    )
                    self._debug(f"analyze_unified() 실패: {exc}")
                    print(f"      ← LLM 통합 실패: {exc}")

            if future_rag is not None:
                try:
                    similar_cases = future_rag.result()
                    print(f"      ← RAG: 참고 사례 {len(similar_cases)}개")
                except Exception as exc:
                    self._debug(f"retrieve_similar_cases() 실패: {exc}")
                    print(f"      ← RAG 실패: {exc}")

        # LLM 엔티티 병합
        merged_entities = llm_assessor.merge_suggested_entities(entities, llm_result)
        if len(merged_entities) != len(entities):
            print(f"      ← 엔티티 병합 후 총 {len(merged_entities)}개")

        # ════════════════════════════════
        # Phase 4: 신호 검출 — 룰 기반(항상) + Serper 교차검증(게이트 profile)
        # ════════════════════════════════
        # 룰 기반 신호검출은 게이트 bucket·skip_verification 과 무관하게 *항상* 수행.
        # 게이트가 normal 로 오판해도 검출 누락이 없도록.
        rule_results = verifier.detect_rule_signals(merged_entities)
        rule_triggered = sum(1 for r in rule_results if r.triggered)
        print(f"[Phase 4] 룰 기반 신호검출: {len(rule_results)}건 중 {rule_triggered}건 검출")

        serper_results: list[verifier.VerificationResult] = []
        serper_cap = gate_profile["serper_max_entities"]
        if skip_verification:
            print("[Phase 4] Serper 교차검증 건너뜀 (skip_verification=True)")
        elif serper_cap <= 0:
            print(f"[Phase 4] Serper 교차검증 건너뜀 (게이트: {gate_result.label_ko})")
        else:
            # 검증 대상 엔티티를 스코어 상위 serper_cap 개로 제한 (라벨당 최대 2개)
            seen_labels: dict[str, int] = {}
            verify_entities: list[extractor.Entity] = []
            for e in sorted(merged_entities, key=lambda x: -x.score):
                count = seen_labels.get(e.label, 0)
                if count >= 2:
                    continue
                seen_labels[e.label] = count + 1
                verify_entities.append(e)
                if len(verify_entities) >= serper_cap:
                    break

            print("[Phase 4] Serper 교차검증 중 (병렬)...")
            print(
                f"      → 엔티티 {len(verify_entities)}개 (전체 {len(merged_entities)}개 중, "
                f"상한 {serper_cap}), scam_type={classification.scam_type}"
            )
            serper_results = self.verify(
                verify_entities,
                classification.scam_type,
                transcript=text,
            )
            print(f"      ← Serper 검증 {len(serper_results)}건")

        verification_results = rule_results + serper_results
        triggered = sum(1 for r in verification_results if r.triggered)
        print(f"      ← 총 {len(verification_results)}건 검증, {triggered}건 신호 검출")
        for r in verification_results:
            if r.triggered:
                reason = r.evidence_snippets[0][:60] if r.evidence_snippets else ""
                print(f"         🚩 {r.flag} {reason}")

        # ════════════════════════════════
        # Phase 5: 검출 신호 종합 (점수·등급 산정 X)
        # ════════════════════════════════
        print("[Phase 5] 검출 신호 종합 중...")
        print(
            f"      → 입력: 검증신호 {len(verification_results)}개, "
            f"엔티티 {len(merged_entities)}개, 분류={classification.scam_type}"
        )
        report = signal_detector.detect(
            verification_results=verification_results,
            classification=classification,
            entities=merged_entities,
            source=source,
            transcript=text,
            llm_assessment=llm_result,
            rag_context={
                "enabled": effective_use_rag,
                "similar_cases": similar_cases,
            }
            if effective_use_rag
            else None,
            scam_type_source=scam_type_source,
            scam_type_reason=scam_type_reason,
            classifier_original=classifier_original,
            safety_result=safety_result,
            sandbox_result=sandbox_result,
            apk_static_result=apk_static_result,
            apk_bytecode_result=apk_bytecode_result,
            apk_dynamic_result=apk_dynamic_result,
        )

        total_ms = (time.time() - pipeline_start) * 1000
        self._log_step("전체", pipeline_start)
        print(f"      ← 검출 신호: {len(report.detected_signals)}개")
        print(f"\n{'='*50}")
        print(f"✅ 검출 완료! (소요시간: {total_ms:.0f}ms)")
        print(f"   유형: {report.scam_type} | 검출 신호: {len(report.detected_signals)}개")
        print(f"{'='*50}")

        self.last_report = report
        return report

    def print_step_log(self):
        """각 단계별 소요 시간을 출력한다."""
        print("\n[단계별 소요 시간]")
        for step in self.steps:
            print(f"  {step.name}: {step.duration_ms:.0f}ms")
