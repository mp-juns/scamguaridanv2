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

from pipeline import apk_analyzer, classifier, extractor, gate, llm_assessor, rag, safety, sandbox, signal_detector, stt, text_rules, verifier
from pipeline.config import (
    CLASSIFICATION_THRESHOLD,
    COMMON_RISK_LABELS,
    GATE_NORMAL,
    GATE_SCAM_ATTEMPT,
    GATE_SCAM_NEWS_EDU,
    RAG_TOP_K,
    get_runtime_scam_taxonomy,
)
from pipeline.runner_input_phases import (
    resolve_transcript_phase,
    run_apk_phase,
    run_safety_phase,
    run_sandbox_phase,
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
        deep: bool = False,
    ) -> DetectionReport:
        """
        전체 검출 파이프라인을 실행한다. 점수·등급 산정 없음 — 검출 신호만.

        Args:
            source: YouTube URL, 로컬 파일 경로, 또는 텍스트
            skip_verification: True이면 Serper API 검증 단계를 건너뜀 (테스트용)
            use_llm: True이면 Claude 기반 보조 검출을 추가 수행
            precomputed_transcript: 외부에서 미리 STT 한 결과. 있으면 Phase 1 스킵.
            user_context: 챗봇 대화로 모은 사용자 제보 dict (Phase 3 LLM 에 prior 로 주입)
            deep: True이면 심층 분석 — 게이트는 metadata 용으로만 돌리고 실행 강도
                  라우팅을 무시, 풀 파이프라인(분류·추출·LLM·Serper) 무조건 실행.
                  게이트 오판(예: 주석 붙은 스미싱 → normal)으로 검출이 0개로 끝나는
                  케이스의 사용자 주도 escape hatch.

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
        # 글로벌 kill switch — SCAMGUARDIAN_LLM_ENABLED=0 이면 어떤 진입점(웹/카카오/CLI)에서도
        # LLM 보조 검출 비활성. 진입점 코드가 use_llm=True 를 강제하더라도 여기서 끈다.
        if use_llm and os.environ.get("SCAMGUARDIAN_LLM_ENABLED", "1") == "0":
            self._debug("LLM 보조 검출 비활성: SCAMGUARDIAN_LLM_ENABLED=0")
            use_llm = False
        # 심층 분석 — Serper 교차검증까지 무조건 수행
        if deep and skip_verification:
            skip_verification = False
        # effective_use_llm / effective_use_rag 는 Phase 1.5 게이트 후 확정된다.
        self._debug(
            "analyze() 시작: "
            f"skip_verification={skip_verification}, use_llm={use_llm}, use_rag={use_rag}, "
            f"deep={deep}"
        )

        safety_result, safety_fast_path = run_safety_phase(
            self,
            source,
            precomputed_transcript,
            pipeline_start,
        )
        if safety_fast_path is not None:
            return safety_fast_path

        sandbox_result = run_sandbox_phase(self, source)
        apk_input, apk_static_result, apk_bytecode_result, apk_dynamic_result = run_apk_phase(
            self,
            source,
            precomputed_transcript,
        )
        transcript = resolve_transcript_phase(
            self,
            source,
            precomputed_transcript,
            apk_input,
            apk_static_result,
            apk_bytecode_result,
            pipeline_start,
        )
        text = transcript.text
        preview = text[:100] + "…" if len(text) > 100 else text
        print(f"      ← 결과: {transcript.source_type} | {len(text)}자")
        if transcript.source_type != "text":
            print(f"      ← 전사: {preview}")

        # ════════════════════════════════
        # Phase 1.5+2+3 통합 병렬 — STT 후 게이트·분류·추출·RAG 동시 실행
        # latency 단축 (이전: Gate 1s → Phase 2 1s → Phase 3 1-2s = 3-4s)
        # (지금: max(Gate, Classify, Extract, RAG) ≈ 1s + LLM if 필요)
        #
        # Trade-off: 게이트 결과 보기 전 Classify/Extract/RAG 를 eager 실행 →
        # 게이트가 skip 결정 시 CPU 낭비. wall time 은 모두 overlap 되어 단축.
        # LLM 만 sequential (사전 시작 시 $ cost 낭비 회피).
        # ════════════════════════════════
        print("[Phase 1.5+2+3] 통합 병렬 실행 (게이트 || 분류 || 추출 || RAG)...")
        parallel_start = time.time()

        llm_result: llm_assessor.LLMAssessment | None = None
        unified_result: llm_assessor.UnifiedLLMResult | None = None
        entities: list[extractor.Entity] = []
        similar_cases: list[dict[str, Any]] = []
        scam_type_source = "classifier"
        scam_type_reason = ""

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)
        try:
            future_gate = executor.submit(gate.classify_gate, text)
            future_classify = executor.submit(self.classify, text)
            # 추출은 union 모드 — Phase 2 결과 기다리지 않고 eager 실행.
            # 라벨이 더 넓어 약간 더 무겁지만 wall time 단축이 더 큼.
            future_extract = executor.submit(
                self.extract, text, "", labels=_all_label_union(),
            )
            future_rag = (
                executor.submit(self.retrieve_similar_cases, text, "")
                if use_rag else None
            )

            # 게이트 먼저 (라우팅 결정에 필요)
            gate_result = future_gate.result()
            self.last_gate_result = gate_result
            gate_profile = gate_result.execution_profile()
            if deep:
                # 심층 분석 — 게이트 결과는 metadata 로만 보존, 라우팅은 풀 강도 고정
                gate_profile = gate.execution_profile(GATE_SCAM_ATTEMPT)
            self._log_step(
                "Gate", parallel_start,
                {"bucket": gate_result.bucket, "source": gate_result.source, "deep": deep},
            )
            print(
                f"      ← [Gate] {gate_result.label_ko} ({gate_result.bucket}) | "
                + ("심층 분석 — 게이트 라우팅 무시, 풀 파이프라인 강제 | " if deep else "")
                + f"scam_type={'O' if gate_profile['run_scam_type'] else 'skip'} "
                f"serper≤{gate_profile['serper_max_entities']} "
                f"llm={'O' if gate_profile['use_llm'] else 'skip'}"
            )

            effective_use_llm = use_llm and gate_profile["use_llm"]
            effective_use_rag = effective_use_llm and use_rag

            # 분류 결과 — 게이트가 run_scam_type=True 일 때만 사용
            if gate_profile["run_scam_type"]:
                classification = future_classify.result()
                top3 = sorted(
                    classification.all_scores.items(), key=lambda x: x[1], reverse=True,
                )[:3]
                top3_str = ", ".join(f"{k}({v:.1%})" for k, v in top3)
                print(
                    f"      ← [분류] {classification.scam_type} "
                    f"({classification.confidence:.1%}) | Top3: {top3_str}"
                )
            else:
                classification = classifier.ClassificationResult(
                    scam_type="", confidence=0.0, all_scores={}, is_uncertain=True,
                )
                self.last_classification = classification
                print(f"      ← [분류] skip (게이트: {gate_result.label_ko})")
            classifier_original = classification

            candidate_scam_types = classifier.candidate_scam_types(classification.all_scores)
            self.last_candidate_scam_types = candidate_scam_types
            if candidate_scam_types:
                print(f"      ← Stage 2 추출 후보 유형: {', '.join(candidate_scam_types)}")

            # 추출 — B 최적화: 게이트=normal 이면 엔티티 무의미 → skip (심층 분석은 예외)
            if gate_result.bucket == GATE_NORMAL and not deep:
                entities = []
                print(f"      ← [추출] skip (게이트: normal, 사기 무관 콘텐츠)")
            else:
                entities = future_extract.result()
                print(f"      ← [추출] 엔티티 {len(entities)}개")
                for e in entities:
                    print(f"         [{e.label}] {e.text} ({e.score:.2f})")

            # RAG
            if future_rag is not None and effective_use_rag:
                try:
                    similar_cases = future_rag.result()
                    print(f"      ← [RAG] 참고 사례 {len(similar_cases)}개")
                except Exception as exc:
                    self._debug(f"retrieve_similar_cases() 실패: {exc}")
                    print(f"      ← [RAG] 실패: {exc}")

            # LLM — 게이트 결과 받은 후 conditionally 시작 ($ cost 낭비 회피).
            # 같은 executor 에 submit 해서 RAG/Extract 잔여 작업과 overlap.
            if effective_use_llm:
                future_llm = executor.submit(
                    llm_assessor.analyze_unified,
                    text, classification.scam_type, user_context=user_context,
                )
                try:
                    unified_result = future_llm.result()
                    llm_result = unified_result.assessment
                    suggestion = unified_result.scam_type_suggestion
                    print(
                        f"      ← [LLM] 엔티티 {len(llm_result.suggested_entities)}개, "
                        f"플래그 {len(llm_result.suggested_flags)}개"
                    )
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
                    print(f"      ← [LLM] 실패: {exc}")
        finally:
            # eager 실행한 잔여 future 는 background 에서 알아서 끝나고 thread 종료.
            executor.shutdown(wait=False)

        parallel_ms = (time.time() - parallel_start) * 1000
        print(f"      ← Phase 1.5+2+3 통합 병렬 완료: {parallel_ms:.0f}ms")

        # LLM 엔티티 병합
        merged_entities = llm_assessor.merge_suggested_entities(entities, llm_result)
        if len(merged_entities) != len(entities):
            print(f"      ← 엔티티 병합 후 총 {len(merged_entities)}개")

        # ════════════════════════════════
        # Phase 4: 신호 검출 — 룰 기반(항상) + Serper 교차검증(게이트 profile)
        # ════════════════════════════════
        # 룰 기반 신호검출은 게이트 bucket·skip_verification 과 무관하게 *항상* 수행.
        # 게이트가 normal 로 오판해도 검출 누락이 없도록.
        # (1) 텍스트 패턴 룰 — 원문만 보므로 추출 skip(게이트 normal)에도 영향받지 않음
        text_rule_results = text_rules.detect_text_risk_signals(text)
        print(f"[Phase 4] 텍스트 룰 고위험 신호: {len(text_rule_results)}건 검출 (게이트 무관 상시)")

        # 요구 1 안전장치: 게이트 고신뢰 정상 판정 + 텍스트 룰 0건 → 분류기 스캠 확정 차단
        # deep 모드에서 gate=normal/scam_news_edu 70%+ 이고 텍스트 룰 신호가 전혀 없는데
        # 분류기만 스캠 유형을 반환한 경우 — NLI 키워드 혼동으로 간주하고 scam_type 제거.
        # LLM 이 명시적으로 스캠이라 판정했으면 유지 (scam_type_source == "llm" 예외).
        # LLM 도 스미싱 지시자 없으면 같은 안전장치 적용 (요구 5)
        _llm_also_no_signal = (
            scam_type_source == "llm"
            and classification.scam_type == "스미싱"
            and not classifier._has_smishing_indicators(text)
        )
        if (
            deep
            and gate_result.bucket in {GATE_NORMAL, GATE_SCAM_NEWS_EDU}
            and gate_result.confidence >= 0.70
            and not text_rule_results
            and classification.scam_type
            and (scam_type_source != "llm" or _llm_also_no_signal)
        ):
            print(
                f"      [안전장치] 게이트 고신뢰({gate_result.confidence:.0%}) "
                f"{gate_result.label_ko} 판정 + 텍스트 룰 0건 — "
                f"분류기 '{classification.scam_type}' 채택 보류"
            )
            classification = classifier.ClassificationResult(
                scam_type="",
                confidence=classification.confidence,
                all_scores=classification.all_scores,
                is_uncertain=True,
            )

        # (2) 엔티티 기반 룰
        rule_results = text_rule_results + verifier.detect_rule_signals(merged_entities)
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
