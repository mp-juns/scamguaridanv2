"""어드민 학습 모델 비교 helper."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel

class CompareAnalysisRequest(BaseModel):
    source: str | None = None
    text: str | None = None
    session_id: str | None = None
    classifier_session_id: str | None = None
    gliner_session_id: str | None = None
    whisper_model: str = "medium"
    compare_scope: str = "both"

_CLASSIFIER_COMPARE_SMOKE_SET: list[dict[str, str]] = [
    {
        "id": "agency_safe_account",
        "expected": "기관 사칭",
        "text": "서울중앙지검 수사관입니다. 본인 명의 계좌가 사건에 연루되어 안전계좌로 3000만원 검증 이체가 필요합니다.",
    },
    {
        "id": "smishing_delivery",
        "expected": "스미싱",
        "text": "[대한통운] 주소 오류로 배송이 보류되었습니다. 링크에서 앱을 설치하고 신분증 정보를 인증하세요.",
    },
    {
        "id": "investment_celebrity",
        "expected": "투자 사기",
        "text": "삼성 이재용 회장이 비공개 투자자를 모집합니다. 오늘 500만원만 넣으면 원금 보장과 40% 수익을 드립니다.",
    },
    {
        "id": "romance_customs",
        "expected": "로맨스 스캠",
        "text": "해외 파병 의사인 제가 당신에게 선물을 보냈는데 세관 수수료가 막혔어요. 80만원만 보내주면 바로 만날 수 있어요.",
    },
    {
        "id": "loan_pre_fee",
        "expected": "대출 사기",
        "text": "정부지원 저금리 대출 대상자입니다. 한도 5000만원 승인 가능하지만 보증보험료 30만원을 먼저 입금해야 실행됩니다.",
    },
    {
        "id": "messenger_child",
        "expected": "메신저 피싱",
        "text": "엄마 나 휴대폰 고장나서 카톡만 돼. 급히 결제해야 하니까 이 계좌로 120만원만 보내줘.",
    },
    {
        "id": "coin_listing",
        "expected": "코인 사기",
        "text": "신규 토큰이 바이낸스 상장을 앞두고 있습니다. 지금 사전 지갑에 입금하면 상장 당일 5배 수익이 확정입니다.",
    },
    {
        "id": "market_direct_payment",
        "expected": "중고거래 사기",
        "text": "중고나라에서 아이패드 판매합니다. 안전결제는 수수료가 커서 계좌로 예약금 먼저 보내주시면 바로 택배 발송합니다.",
    },
    {
        "id": "job_review_purchase",
        "expected": "취업·알바 사기",
        "text": "재택 리뷰 알바입니다. 상품을 먼저 구매하면 원금과 수당을 돌려드립니다. 첫 미션 결제금 20만원을 준비해주세요.",
    },
    {
        "id": "threat_family",
        "expected": "납치·협박형",
        "text": "네 가족을 데리고 있다. 경찰에 신고하면 다친다. 지금 2000만원을 보내면 조용히 끝내겠다.",
    },
    {
        "id": "realestate_down_payment",
        "expected": "부동산 사기",
        "text": "역세권 급매 물건이 나왔습니다. 계약금 500만원만 먼저 보내면 등기 전까지 단독 배정해드립니다.",
    },
    {
        "id": "health_cure_claim",
        "expected": "건강식품 사기",
        "text": "이 건강식품은 당뇨와 관절염을 2주 안에 개선하는 특허 제품입니다. 오늘 결제하면 병원 치료 없이 관리됩니다.",
    },
]
def _top_scores(scores: dict[str, float], limit: int = 3) -> list[dict[str, Any]]:
    return [
        {"label": label, "score": score}
        for label, score in sorted(scores.items(), key=lambda item: -item[1])[:limit]
    ]


def _classify_raw_for_compare(text: str) -> Any:
    from pipeline import classifier
    from pipeline.config import CLASSIFICATION_THRESHOLD, get_runtime_scam_taxonomy

    clf = classifier._get_classifier()
    taxonomy = get_runtime_scam_taxonomy()
    truncated = text[:2000]
    descriptive_labels = list(taxonomy["descriptions"].keys())
    result = clf(
        truncated,
        descriptive_labels,
        hypothesis_template="이 내용은 {}하는 것이다.",
        multi_label=False,
    )
    nli_scores: dict[str, float] = {}
    for label, score in zip(result["labels"], result["scores"]):
        short_name = taxonomy["descriptions"][label]
        nli_scores[short_name] = float(score)

    boosts = classifier._compute_keyword_boost(truncated)
    combined = {
        scam_type: score + boosts.get(scam_type, 0)
        for scam_type, score in nli_scores.items()
    }
    min_score = min(combined.values())
    shifted = {k: v - min_score for k, v in combined.items()}
    shifted_total = sum(shifted.values())
    if shifted_total == 0:
        uniform = 1.0 / len(shifted) if shifted else 0.0
        all_scores = {k: uniform for k in shifted}
    else:
        all_scores = {k: v / shifted_total for k, v in shifted.items()}
    top = max(all_scores.items(), key=lambda item: item[1])
    return classifier.ClassificationResult(
        scam_type=top[0],
        confidence=top[1],
        all_scores=all_scores,
        is_uncertain=top[1] < CLASSIFICATION_THRESHOLD,
    )


def _load_checkpoint_for_compare(output_dir: str) -> dict[str, Any]:
    from transformers import AutoTokenizer, pipeline as hf_pipeline
    from pipeline import classifier

    tokenizer = AutoTokenizer.from_pretrained(output_dir, local_files_only=True)
    model = classifier._load_finetuned_model(output_dir)
    pipe = hf_pipeline(
        "text-classification",
        model=model,
        tokenizer=tokenizer,
        device="cpu",
        top_k=None,
        truncation=True,
        max_length=512,
    )
    return {"pipe": pipe, "path": output_dir, "labels": {}}


def _classify_checkpoint_for_compare(text: str, finetuned: dict[str, Any]) -> Any:
    from pipeline import classifier

    return classifier._classify_finetuned(text, finetuned)


def _compare_classifier_session(session_id: str) -> dict[str, Any]:
    from training import sessions as tsess

    data = tsess.get_session(session_id)
    if data is None:
        raise FileNotFoundError("세션을 찾을 수 없습니다.")
    if data.get("model") != "classifier":
        raise ValueError("classifier 세션만 비교할 수 있습니다.")
    if data.get("status") != "completed":
        raise ValueError(f"완료된 classifier 세션만 비교할 수 있습니다 (현재 status={data.get('status')}).")
    output_dir = str(data.get("output_dir") or "")
    if not output_dir or not Path(output_dir).exists():
        raise FileNotFoundError("fine-tuned 체크포인트 디렉토리를 찾을 수 없습니다.")

    finetuned = _load_checkpoint_for_compare(output_dir)
    rows: list[dict[str, Any]] = []
    raw_correct = 0
    tuned_correct = 0
    changed = 0
    for sample in _CLASSIFIER_COMPARE_SMOKE_SET:
        raw = _classify_raw_for_compare(sample["text"])
        tuned = _classify_checkpoint_for_compare(sample["text"], finetuned)
        raw_hit = raw.scam_type == sample["expected"]
        tuned_hit = tuned.scam_type == sample["expected"]
        if raw_hit:
            raw_correct += 1
        if tuned_hit:
            tuned_correct += 1
        if raw.scam_type != tuned.scam_type:
            changed += 1
        rows.append({
            **sample,
            "raw": {
                "prediction": raw.scam_type,
                "confidence": raw.confidence,
                "is_correct": raw_hit,
                "top_scores": _top_scores(raw.all_scores),
            },
            "fine_tuned": {
                "prediction": tuned.scam_type,
                "confidence": tuned.confidence,
                "is_correct": tuned_hit,
                "top_scores": _top_scores(tuned.all_scores),
            },
            "delta": {
                "changed": raw.scam_type != tuned.scam_type,
                "confidence": tuned.confidence - raw.confidence,
            },
        })

    total = len(rows)
    return {
        "session_id": session_id,
        "output_dir": output_dir,
        "sample_count": total,
        "raw": {
            "correct": raw_correct,
            "accuracy": raw_correct / total if total else 0.0,
        },
        "fine_tuned": {
            "correct": tuned_correct,
            "accuracy": tuned_correct / total if total else 0.0,
        },
        "delta": {
            "correct": tuned_correct - raw_correct,
            "accuracy": (tuned_correct - raw_correct) / total if total else 0.0,
            "changed_predictions": changed,
        },
        "samples": rows,
    }


def _resolve_compare_session_id(session_id: str | None, *, model: str = "classifier") -> str:
    from training import sessions as tsess

    candidates = [
        item for item in tsess.list_sessions(100)
        if item.get("model") == model
    ]
    if session_id:
        candidates = [item for item in candidates if item.get("session_id") == session_id]
    for item in candidates:
        data = tsess.get_session(str(item.get("session_id")))
        if not data or data.get("status") != "completed":
            continue
        output_dir = Path(str(data.get("output_dir") or ""))
        if model == "classifier" and not (
            (output_dir / "label2id.json").exists() and (
                (output_dir / "adapter_model.safetensors").exists()
                or (output_dir / "model.safetensors").exists()
                or (output_dir / "pytorch_model.bin").exists()
            )
        ):
            continue
        if model == "gliner" and not (
            (output_dir / "gliner_config.json").exists()
            and (
                (output_dir / "model.safetensors").exists()
                or (output_dir / "pytorch_model.bin").exists()
            )
        ):
            continue
        if model in {"classifier", "gliner"}:
            return str(data["session_id"])
    raise ValueError(f"비교 가능한 완료 {model} 세션을 찾지 못했습니다.")


def _transcribe_for_compare(source: str, whisper_model: str) -> dict[str, Any]:
    from pipeline import stt

    result = stt.transcribe(source, model_size=whisper_model)
    return {
        "text": result.text or source,
        "source_type": result.source_type,
        "metadata": getattr(result, "metadata", {}),
    }


def _extract_compare_evidence(
    text: str,
    scam_type: str,
    *,
    model_path: str | None = None,
) -> dict[str, Any]:
    from pipeline import extractor, verifier

    entities = extractor.extract(text, scam_type, model_path=model_path)
    rule_results = verifier.detect_rule_signals(entities)
    triggered = [result for result in rule_results if result.triggered]
    return {
        "entities": [entity.to_dict() for entity in entities],
        "signals": [result.to_dict() for result in triggered],
        "signal_candidates": [result.to_dict() for result in rule_results],
    }


def _compare_analysis(payload: CompareAnalysisRequest) -> dict[str, Any]:
    source = (payload.text or payload.source or "").strip()
    if not source:
        raise ValueError("비교할 텍스트 또는 링크를 입력해주세요.")
    compare_scope = (payload.compare_scope or "both").strip()
    if compare_scope not in {"both", "classifier", "extractor"}:
        raise ValueError("compare_scope 는 both, classifier, extractor 중 하나여야 합니다.")

    classifier_session_id = _resolve_compare_session_id(
        payload.classifier_session_id or payload.session_id,
        model="classifier",
    )
    gliner_session_id: str | None = None
    from training import sessions as tsess
    classifier_session = tsess.get_session(classifier_session_id)
    classifier_output_dir = str(classifier_session.get("output_dir") if classifier_session else "")
    gliner_output_dir = ""
    if compare_scope in {"both", "extractor"} and payload.gliner_session_id:
        gliner_session_id = _resolve_compare_session_id(payload.gliner_session_id, model="gliner")
        gliner_session = tsess.get_session(gliner_session_id)
        gliner_output_dir = str(gliner_session.get("output_dir") if gliner_session else "")

    transcript = _transcribe_for_compare(source, payload.whisper_model)
    text = transcript["text"]
    raw = _classify_raw_for_compare(text)
    tuned = _classify_checkpoint_for_compare(text, _load_checkpoint_for_compare(classifier_output_dir))
    from pipeline.config import MODELS
    raw_evidence = _extract_compare_evidence(text, raw.scam_type, model_path=MODELS["gliner"])
    tuned_evidence = _extract_compare_evidence(
        text,
        tuned.scam_type,
        model_path=gliner_output_dir or None,
    )

    from pipeline import llm_assessor
    try:
        unified = llm_assessor.analyze_unified(text, raw.scam_type)
        llm_assessment = unified.assessment
        llm_type = unified.scam_type_suggestion.scam_type if unified.scam_type_suggestion else raw.scam_type
        llm_confidence = (
            unified.scam_type_suggestion.confidence
            if unified.scam_type_suggestion
            else None
        )
        llm_error = llm_assessment.error
    except Exception as exc:
        llm_assessment = llm_assessor.LLMAssessment(
            model=llm_assessor.default_model_name(),
            error=str(exc),
        )
        llm_type = ""
        llm_confidence = None
        llm_error = str(exc)

    return {
        "session_id": classifier_session_id,
        "classifier_session_id": classifier_session_id,
        "gliner_session_id": gliner_session_id,
        "output_dir": classifier_output_dir,
        "classifier_output_dir": classifier_output_dir,
        "gliner_output_dir": gliner_output_dir,
        "compare_scope": compare_scope,
        "input": {
            "source": source,
            "transcript_text": text,
            "source_type": transcript["source_type"],
            "metadata": transcript["metadata"],
        },
        "existing": {
            "label": "기존 분석",
            "method": "raw zero-shot classifier + keyword boost",
            "scam_type": raw.scam_type,
            "confidence": raw.confidence,
            "is_uncertain": raw.is_uncertain,
            "top_scores": _top_scores(raw.all_scores, 5),
            **raw_evidence,
        },
        "claude": {
            "label": "Claude 분석",
            "method": llm_assessor.default_model_name(),
            "scam_type": llm_type,
            "confidence": llm_confidence,
            "summary": llm_assessment.summary,
            "reasoning": llm_assessment.reasoning,
            "suggested_flags": [flag.to_dict() for flag in llm_assessment.suggested_flags],
            "suggested_entities": [entity.to_dict() for entity in llm_assessment.suggested_entities],
            "error": llm_error,
            "entities": [entity.to_dict() for entity in llm_assessment.suggested_entities],
            "signals": [flag.to_dict() for flag in llm_assessment.suggested_flags],
        },
        "fine_tuned": {
            "label": "파인튜닝 모델",
            "method": classifier_output_dir,
            "extractor_method": gliner_output_dir or "active/base GLiNER",
            "scam_type": tuned.scam_type,
            "confidence": tuned.confidence,
            "is_uncertain": tuned.is_uncertain,
            "top_scores": _top_scores(tuned.all_scores, 5),
            **tuned_evidence,
        },
        "agreement": {
            "existing_vs_fine_tuned": raw.scam_type == tuned.scam_type,
            "existing_vs_claude": bool(llm_type) and raw.scam_type == llm_type,
            "claude_vs_fine_tuned": bool(llm_type) and llm_type == tuned.scam_type,
        },
    }
