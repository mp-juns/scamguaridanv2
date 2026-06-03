"""어드민 — 학습 세션 관리 (mDeBERTa 분류기 / GLiNER 엔티티)."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .models import StartTrainingRequest

router = APIRouter()

_ADMIN_RESPONSES: dict[int | str, dict] = {
    401: {"description": "어드민 토큰 누락 또는 무효"},
    500: {"description": "서버 내부 오류"},
}


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


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _latest_checkpoint_state(output_dir: Path) -> dict[str, Any]:
    states: list[tuple[int, dict[str, Any]]] = []
    for state_path in output_dir.glob("checkpoint-*/trainer_state.json"):
        try:
            step = int(state_path.parent.name.rsplit("-", 1)[-1])
        except ValueError:
            step = 0
        state = _read_json(state_path)
        if state:
            states.append((step, state))
    if not states:
        return {}
    return max(states, key=lambda item: item[0])[1]


def _eval_snapshots(state: dict[str, Any]) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    for row in state.get("log_history", []):
        if not isinstance(row, dict) or "eval_macro_f1" not in row:
            continue
        snapshots.append({
            "step": row.get("step"),
            "epoch": row.get("epoch"),
            "eval_loss": row.get("eval_loss"),
            "eval_accuracy": row.get("eval_accuracy"),
            "eval_macro_f1": row.get("eval_macro_f1"),
            "eval_macro_precision": row.get("eval_macro_precision"),
            "eval_macro_recall": row.get("eval_macro_recall"),
        })
    return snapshots


def _synthetic_attempt_summary(session_dir: Path) -> dict[str, Any] | None:
    output_dir = session_dir / "output"
    if not output_dir.exists():
        return None
    label2id = _read_json(output_dir / "label2id.json")
    adapter_config = _read_json(output_dir / "adapter_config.json")
    state = _latest_checkpoint_state(output_dir)
    evals = _eval_snapshots(state)
    final_eval = evals[-1] if evals else {}
    return {
        "session_id": session_dir.name,
        "output_dir": str(output_dir),
        "has_adapter": (output_dir / "adapter_config.json").exists(),
        "saves_classifier_head": "classifier" in adapter_config.get("modules_to_save", []),
        "label_count": len(label2id),
        "global_step": state.get("global_step"),
        "epoch": state.get("epoch"),
        "best_metric": state.get("best_metric"),
        "evals": evals,
        "final_eval": final_eval,
    }


def _latest_synthetic_corpus() -> Path:
    default = Path("data/generated/scamguardian_synthetic_3000.jsonl")
    candidates = list(Path("data/generated").glob("scamguardian_synthetic_*.jsonl"))
    if not candidates:
        return default

    def corpus_size(path: Path) -> int:
        match = re.search(r"scamguardian_synthetic_(\d+)\.jsonl$", path.name)
        if not match:
            return -1
        return int(match.group(1))

    return max(candidates, key=lambda path: (corpus_size(path), path.stat().st_mtime))


def _synthetic_graph(path: Path) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    links: dict[tuple[str, str, str], dict[str, Any]] = {}

    def set_node(node_id: str, label: str, kind: str, group: str, weight: int = 0) -> None:
        nodes[node_id] = {"id": node_id, "label": label, "kind": kind, "group": group, "weight": weight}

    def add_weight(node_id: str, weight: int = 1) -> None:
        node = nodes.setdefault(
            node_id,
            {"id": node_id, "label": node_id, "kind": "unknown", "group": "unknown", "weight": 0},
        )
        node["weight"] = int(node.get("weight", 0)) + weight

    def add_link(source: str, target: str, kind: str, weight: int = 1) -> None:
        key = (source, target, kind)
        link = links.setdefault(
            key,
            {"source": source, "target": target, "kind": kind, "weight": 0},
        )
        link["weight"] = int(link.get("weight", 0)) + weight

    set_node("corpus", "학습 데이터", "corpus", "corpus")
    set_node("axis:classifier", "분류기", "axis", "classifier")
    set_node("axis:extractor", "추출기", "axis", "extractor")
    add_link("corpus", "axis:classifier", "feeds")
    add_link("corpus", "axis:extractor", "feeds")
    if not path.exists():
        return {"nodes": list(nodes.values()), "links": []}

    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue

        scam_type = str(row.get("scam_type") or "unknown")
        type_id = f"type:{scam_type}"
        if type_id not in nodes:
            set_node(type_id, scam_type, "scam_type", "classifier")
        add_weight(type_id)
        add_link("axis:classifier", type_id, "has_type")

        for ent in row.get("entities") or []:
            label = str(ent.get("label") or "").strip()
            if not label:
                continue
            ent_id = f"entity_label:{label}"
            if ent_id not in nodes:
                set_node(ent_id, label, "entity_label", "extractor")
            add_weight(ent_id)
            add_link("axis:extractor", ent_id, "has_entity_label")

    return {
        "nodes": sorted(nodes.values(), key=lambda node: (str(node["group"]), str(node["kind"]), -int(node.get("weight", 0)), str(node["id"]))),
        "links": sorted(links.values(), key=lambda link: (str(link["source"]), str(link["target"]))),
    }


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


@router.get(
    "/api/admin/training/data-stats",
    tags=["Admin — Training"],
    summary="학습 데이터 통계",
    description="현재 라벨링 데이터 라벨 분포 + 엔티티 수 — 학습 시작 전 충분성 판단용.",
    responses=_ADMIN_RESPONSES,
)
async def admin_training_data_stats() -> dict[str, Any]:
    """현재 라벨링 데이터 통계 — 라벨 분포, 학습 가능 여부."""
    try:
        from training import data as tdata
        cls = await asyncio.to_thread(tdata.load_classifier_dataset)
        extra_path = _latest_synthetic_corpus()
        gli_base = await asyncio.to_thread(tdata.load_gliner_dataset)
        gli = await asyncio.to_thread(tdata.load_gliner_dataset, extra_jsonl=extra_path)
        entity_labels: dict[str, int] = {}
        for example in gli:
            for _, _, label in example.ner:
                entity_labels[label] = entity_labels.get(label, 0) + 1
        return {
            "classifier": {
                "total": len(cls),
                "labels": tdata.label_distribution(cls),
            },
            "gliner": {
                "total": len(gli),
                "base_total": len(gli_base),
                "total_entities": sum(len(e.ner) for e in gli),
                "base_total_entities": sum(len(e.ner) for e in gli_base),
                "labels": dict(sorted(entity_labels.items(), key=lambda item: (-item[1], item[0]))),
                "label_count": len(entity_labels),
                "extra_jsonl": str(extra_path),
            },
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/api/admin/training/synthetic-summary",
    tags=["Admin — Training"],
    summary="synthetic classifier 학습 결과 요약",
    description=(
        "직접 실행한 synthetic classifier 학습 산출물을 스캔해 초심자용 시각화에 필요한 "
        "데이터셋 분포, 시도별 평가 지표, 활성화 보류 이유를 반환한다."
    ),
    responses=_ADMIN_RESPONSES,
)
async def admin_training_synthetic_summary() -> dict[str, Any]:
    try:
        from training import data as tdata
        from training.train_classifier import _ensure_min_per_class

        extra_path = _latest_synthetic_corpus()
        examples = _ensure_min_per_class(
            tdata.load_classifier_dataset(extra_jsonl=extra_path),
            5,
        )
        labels = tdata.label_distribution(examples)

        root = Path(".scamguardian") / "training_sessions"
        attempts: list[dict[str, Any]] = []
        if root.exists():
            for session_dir in sorted(root.glob("synthetic_classifier_*")):
                summary = _synthetic_attempt_summary(session_dir)
                if summary:
                    attempts.append(summary)

        attempts.sort(
            key=lambda item: float(
                (item.get("final_eval") or {}).get("eval_macro_f1") or -1
            ),
            reverse=True,
        )
        best = attempts[0] if attempts else None

        return {
            "dataset": {
                "path": str(extra_path),
                "total": len(examples),
                "labels": labels,
                "label_count": len(labels),
                "min_per_label": min(labels.values()) if labels else 0,
                "max_per_label": max(labels.values()) if labels else 0,
            },
            "graph": _synthetic_graph(extra_path),
            "attempts": attempts,
            "best_attempt": best,
            "status": {
                "headline": "학습과 재로드는 성공, 자동 적용은 보류",
                "activation_ready": False,
                "reason": (
                    "synthetic validation 은 높지만, 실제 운영 문장과 더 비슷한 hard smoke set "
                    "검증이 아직 없어서 active model 로 자동 swap 하지 않았다."
                ),
                "next_step": "실전형 smoke set 100-300개를 만들고 통과 기준을 정한 뒤 적용",
            },
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/api/admin/training/sessions",
    tags=["Admin — Training"],
    summary="fine-tune 세션 시작",
    description=(
        "subprocess 로 학습 세션 spawn — `.scamguardian/training_sessions/{id}/` 에 "
        "`status.json` / `metrics.jsonl` / `train.log` 출력.\n\n"
        "**Body** (`StartTrainingRequest`):\n"
        "- `model` — `classifier` (mDeBERTa) 또는 `gliner` (단일 세션, legacy)\n"
        "- `models` — `['classifier', 'gliner']` 처럼 보내면 선택된 모델을 각각 학습\n"
        "- `epochs` (기본 3), `batch_size` (기본 8), `lora` (LoRA 사용)\n"
        "- `extra_jsonl` — 추가 데이터셋 경로\n"
        "- `val_ratio` (기본 0.1), `seed` (기본 17), `base_model`"
    ),
    responses={**_ADMIN_RESPONSES, 400: {"description": "유효성 실패"}},
)
async def admin_training_start(payload: StartTrainingRequest) -> dict[str, Any]:
    try:
        from training import sessions as tsess
        requested_models = payload.models if payload.models is not None else [payload.model]
        models = []
        for model in requested_models:
            model_name = str(model or "").strip()
            if model_name and model_name not in models:
                models.append(model_name)
        if not models:
            raise ValueError("학습할 모델을 하나 이상 선택해야 합니다.")

        # 순차 학습 기본 순서: classifier 먼저, 그 다음 gliner.
        ordered_models = (
            ["classifier", "gliner"]
            if set(models) == {"classifier", "gliner"}
            else models
        )
        params_list: list[Any] = []
        for model_name in ordered_models:
            params_list.append(tsess.SessionParams(
                model=model_name,
                epochs=payload.epochs,
                batch_size=payload.batch_size,
                lora=payload.lora,
                extra_jsonl=payload.extra_jsonl,
                val_ratio=payload.val_ratio,
                seed=payload.seed,
                base_model=payload.base_model,
                early_stopping_patience=payload.early_stopping_patience,
                early_stopping_threshold=payload.early_stopping_threshold,
            ))

        if len(params_list) == 1:
            return await asyncio.to_thread(tsess.start_session, params_list[0])
        cooldown_seconds = int(__import__("os").getenv("SCAMGUARDIAN_TRAINING_COOLDOWN_SECONDS", "120"))
        return await asyncio.to_thread(
            tsess.start_sequential_sessions,
            params_list,
            cooldown_seconds=cooldown_seconds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/api/admin/training/sessions",
    tags=["Admin — Training"],
    summary="학습 세션 목록 + 활성 모델",
    description="모든 세션 메타 + 현재 파이프라인이 사용하는 active 모델 경로 (`active_models.json`).",
    responses=_ADMIN_RESPONSES,
)
async def admin_training_list(limit: int = 50) -> dict[str, Any]:
    try:
        from training import sessions as tsess
        items = await asyncio.to_thread(tsess.list_sessions, limit)
        return {"sessions": items, "active_models": tsess.get_active_models()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get(
    "/api/admin/training/sessions/{session_id}",
    tags=["Admin — Training"],
    summary="세션 상세 + metrics tail + log tail",
    description="`session` 메타 + 마지막 500 metric 이벤트 + 마지막 8KB 로그.",
    responses={**_ADMIN_RESPONSES, 404: {"description": "session not found"}},
)
async def admin_training_detail(session_id: str) -> dict[str, Any]:
    try:
        from training import sessions as tsess
        info = await asyncio.to_thread(tsess.get_session, session_id)
        if info is None:
            raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
        metrics = await asyncio.to_thread(tsess.read_metrics, session_id, 500)
        log_tail = await asyncio.to_thread(tsess.read_log_tail, session_id, 8000)
        loss_spikes = await asyncio.to_thread(tsess.read_loss_spikes, session_id, 80)
        return {"session": info, "metrics": metrics, "log_tail": log_tail, "loss_spikes": loss_spikes}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/api/admin/training/sessions/{session_id}/cancel",
    tags=["Admin — Training"],
    summary="학습 세션 취소",
    description="실행 중 subprocess 종료 + status `cancelled` 갱신.",
    responses={**_ADMIN_RESPONSES, 409: {"description": "취소할 수 없는 상태 (이미 끝남)"}},
)
async def admin_training_cancel(session_id: str) -> dict[str, Any]:
    try:
        from training import sessions as tsess
        ok = await asyncio.to_thread(tsess.cancel_session, session_id)
        if not ok:
            raise HTTPException(status_code=409, detail="취소할 수 없는 상태입니다.")
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/api/admin/training/sessions/{session_id}/activate",
    tags=["Admin — Training"],
    summary="학습 결과를 파이프라인에 적용",
    description=(
        "체크포인트 경로를 `.scamguardian/active_models.json` 에 기록 → "
        "`pipeline.active_models` 60s TTL 캐시가 무효화되어 즉시 swap.\n\n"
        "분류기 / GLiNER 각 1개씩 활성 가능. 경로 무효 시 base 모델로 fallback."
    ),
    responses={
        **_ADMIN_RESPONSES,
        400: {"description": "유효성 실패 (e.g. 체크포인트 경로 없음)"},
        404: {"description": "session not found 또는 모델 파일 없음"},
    },
)
async def admin_training_activate(session_id: str) -> dict[str, Any]:
    try:
        from training import sessions as tsess
        result = await asyncio.to_thread(tsess.activate_session, session_id)
        return {"ok": True, **result}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/api/admin/training/sessions/{session_id}/compare",
    tags=["Admin — Training"],
    summary="raw classifier 와 fine-tuned classifier 비교",
    description=(
        "완료된 classifier 세션의 output checkpoint 를 로드해, 같은 smoke 문장 세트에서 "
        "raw zero-shot classifier 와 fine-tuned classifier 의 예측을 비교한다."
    ),
    responses={**_ADMIN_RESPONSES, 400: {"description": "비교 불가 세션"}, 404: {"description": "session not found"}},
)
async def admin_training_compare_classifier(session_id: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_compare_classifier_session, session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/api/admin/training/compare-analysis",
    tags=["Admin — Training"],
    summary="입력 기반 모델 비교 분석",
    description=(
        "텍스트나 링크를 받아 같은 transcript 에 대해 기존 raw classifier, Claude/LLM 분석, "
        "fine-tuned classifier checkpoint 결과를 나란히 반환한다."
    ),
    responses={**_ADMIN_RESPONSES, 400: {"description": "비교 요청 오류"}},
)
async def admin_training_compare_analysis(payload: CompareAnalysisRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_compare_analysis, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EnvironmentError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
