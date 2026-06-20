#!/usr/bin/env python3
"""ScamGuardian 통합 스모크 테스트.

pytest 테스트셋은 세부 회귀를 담당하고, 이 스크립트는 README 에서 안내하는
수동 명령으로 현재 DetectionReport 스키마와 핵심 파이프라인이 살아있는지 확인한다.
외부 검색/LLM/RAG 호출은 끄고 로컬 경로만 검증한다.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

load_dotenv()

os.environ.setdefault("SCAMGUARDIAN_PERSIST_RUNS", "false")
os.environ.setdefault("SANDBOX_ENABLED", "0")
os.environ.setdefault("APK_DYNAMIC_ENABLED", "0")


SMOKE_CASES = [
    "저는 서울중앙지검 수사관입니다. 고객님 명의 계좌가 범죄에 사용되어 안전 계좌로 이체가 필요합니다.",
    "오늘 점심 뭐 먹을까요? 내일 팀 회의 자료도 같이 확인해 주세요.",
]


def test_detection_report_schema() -> bool:
    from pipeline.runner import ScamGuardianPipeline

    pipe = ScamGuardianPipeline(whisper_model="medium")
    ok = True

    for idx, text in enumerate(SMOKE_CASES, 1):
        report = pipe.analyze(
            text,
            skip_verification=True,
            use_llm=False,
            use_rag=False,
        )
        payload = report.to_dict()
        signals = payload.get("detected_signals")

        forbidden = {"total_score", "risk_level", "is_scam", "agent_verdict"}
        leaked = sorted(forbidden.intersection(payload))

        print(f"[{idx}] scam_type={payload.get('scam_type')} signals={len(signals or [])}")

        if leaked:
            print(f"  FAIL: 외부 응답 금지 필드 노출: {leaked}")
            ok = False
        if not isinstance(signals, list):
            print("  FAIL: detected_signals 가 list 가 아닙니다.")
            ok = False
        if not payload.get("summary"):
            print("  FAIL: summary 가 비어 있습니다.")
            ok = False

    return ok


def test_llm_signal_merge_contract() -> bool:
    from pipeline.classifier import ClassificationResult
    from pipeline.extractor import Entity
    from pipeline.llm_assessor import (
        LLMAssessment,
        SuggestedEntity,
        SuggestedFlag,
        merge_suggested_entities,
    )
    from pipeline.signal_detector import detect

    base_entities = [Entity(text="300만원", label="금액", score=1.0, start=0, end=4)]
    assessment = LLMAssessment(
        model="test-model",
        summary="추가 위험 신호가 보입니다.",
        suggested_entities=[
            SuggestedEntity(
                text="오늘만",
                label="날짜 또는 기간",
                reason="긴박감을 조성합니다.",
                confidence=0.91,
            )
        ],
        suggested_flags=[
            SuggestedFlag(
                flag="abnormal_return_rate",
                reason="과도한 수익 보장 문구입니다.",
                evidence="연 30% 수익 보장",
                confidence=0.92,
            )
        ],
    )

    merged = merge_suggested_entities(base_entities, assessment)
    report = detect(
        verification_results=[],
        classification=ClassificationResult(
            scam_type="투자 사기",
            confidence=0.8,
            is_uncertain=False,
            all_scores={"투자 사기": 0.8},
        ),
        entities=merged,
        source="smoke",
        transcript="오늘만 300만원 넣으면 연 30% 수익 보장",
        llm_assessment=assessment,
    )

    has_llm_entity = any(getattr(entity, "source", "") == "llm" for entity in merged)
    has_llm_signal = any(signal.detection_source == "llm" for signal in report.detected_signals)
    print(f"[llm-contract] entities={len(merged)} signals={len(report.detected_signals)}")

    if not has_llm_entity:
        print("  FAIL: LLM 제안 엔티티가 병합되지 않았습니다.")
        return False
    if not has_llm_signal:
        print("  FAIL: LLM 제안 신호가 DetectionReport 에 반영되지 않았습니다.")
        return False
    return True


def test_eval_metrics() -> bool:
    from pipeline import eval as pipeline_eval

    records = [
        {
            "run_id": "run-1",
            "classification_scanner": {"scam_type": "투자 사기"},
            "scam_type_gt": "투자 사기",
            "entities_predicted": [{"label": "금액", "text": "300만원"}],
            "entities_gt": [{"label": "금액", "text": "300만원"}],
            "triggered_flags_predicted": [{"flag": "abnormal_return_rate"}],
            "triggered_flags_gt": [{"flag": "abnormal_return_rate"}],
        }
    ]
    metrics = pipeline_eval.evaluate_annotated_runs(records)
    ok = metrics["sample_count"] == 1 and metrics["classification_accuracy"] == 1.0
    print(f"[eval] sample_count={metrics['sample_count']} accuracy={metrics['classification_accuracy']:.2f}")
    return ok


if __name__ == "__main__":
    print("\nScamGuardian — 통합 스모크 테스트\n")
    checks = {
        "DetectionReport schema": test_detection_report_schema(),
        "LLM signal contract": test_llm_signal_merge_contract(),
        "Eval metrics": test_eval_metrics(),
    }

    print("\n결과")
    failed = [name for name, passed in checks.items() if not passed]
    for name, passed in checks.items():
        print(f"- {name}: {'PASS' if passed else 'FAIL'}")

    if failed:
        sys.exit(1)
    print("\n모든 스모크 테스트 통과")
