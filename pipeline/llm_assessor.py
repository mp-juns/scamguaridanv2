"""
ScamGuardian v2 — Claude API 기반 LLM 보조 판정 모듈

기존 규칙 파이프라인을 대체하지 않고, 추가 엔티티/플래그 후보를 제안한다.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from pipeline.config import (
    DETECTED_FLAGS,
    LLM_ENTITY_MERGE_THRESHOLD,
    LLM_SCAM_TYPE_OVERRIDE_THRESHOLD,
    OLLAMA_MAX_ENTITY_COUNT as _MAX_ENTITY_COUNT,
    OLLAMA_MAX_TRANSCRIPT_CHARS as _MAX_TRANSCRIPT_CHARS,
    OLLAMA_MAX_TRIGGERED_FLAG_COUNT as _MAX_FLAG_COUNT,
    RAG_MAX_CASES_IN_PROMPT,
    get_runtime_scam_taxonomy,
)
from pipeline.extractor import Entity
from pipeline.verifier import VerificationResult

_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY가 설정되지 않았습니다.")
        # fast-fail: Anthropic overloaded 시 첫 응답이 26초까지 걸린 사례 (2026-05-22).
        # Phase 3 LLM 통합은 *2차 보조* 라 down 돼도 분류·신호 본체 (mDeBERTa/GLiNER/Serper/룰)는
        # 그대로 작동. 따라서 짧은 timeout + 1회 재시도로 fast-fail 해서 사용자 체감 latency 보호.
        _client = anthropic.Anthropic(api_key=api_key, timeout=8.0, max_retries=1)
    return _client


def default_model_name() -> str:
    # Phase 3 (analyze_unified) default: Haiku.
    # Sonnet 대비 ~3배 빠른 latency (10.7s → ~3-4s), LLM_FLAG_SCORE_RATIO=0.5 라
    # 정확도 손실은 점수 가중치에서 흡수됨. STT/labeler/vision 은 각자의 getenv default 유지.
    # 변경하려면 .env 에 ANTHROPIC_PHASE3_MODEL 또는 ANTHROPIC_MODEL 설정.
    return os.getenv("ANTHROPIC_PHASE3_MODEL", os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"))


@dataclass
class SuggestedEntity:
    text: str
    label: str
    reason: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "label": self.label,
            "reason": self.reason,
            "confidence": round(self.confidence, 4),
        }


@dataclass
class SuggestedFlag:
    flag: str
    reason: str
    evidence: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "flag": self.flag,
            "reason": self.reason,
            "evidence": self.evidence,
            "confidence": round(self.confidence, 4),
        }


@dataclass
class LLMAssessment:
    model: str
    summary: str = ""
    reasoning: list[str] = field(default_factory=list)
    suggested_entities: list[SuggestedEntity] = field(default_factory=list)
    suggested_flags: list[SuggestedFlag] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "summary": self.summary,
            "reasoning": self.reasoning,
            "suggested_entities": [e.to_dict() for e in self.suggested_entities],
            "suggested_flags": [f.to_dict() for f in self.suggested_flags],
            "error": self.error,
        }


@dataclass
class ScamTypeSuggestion:
    scam_type: str
    confidence: float
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "scam_type": self.scam_type,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
        }


def _clamp_confidence(value: Any, default: float = 0.6) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def _call_claude(prompt: str, max_tokens: int = 512) -> dict[str, Any]:
    import time as _time

    client = _get_client()
    model = default_model_name()
    prompt_len = len(prompt)
    print(
        f"    [Claude API] → 모델: {model}, "
        f"프롬프트: {prompt_len}자, max_tokens: {max_tokens}"
    )
    t0 = _time.time()
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system="당신은 한국어 스캠 탐지 보조 판정기입니다. JSON만 반환하세요. 마크다운 코드블록 없이 순수 JSON만 출력하세요.",
        messages=[{"role": "user", "content": prompt}],
    )
    elapsed = _time.time() - t0
    raw = message.content[0].text
    usage = getattr(message, "usage", None)
    try:
        from platform_layer import cost as _cost
        _cost.record_claude(
            model,
            int(getattr(usage, "input_tokens", 0) or 0),
            int(getattr(usage, "output_tokens", 0) or 0),
            action="llm_assessor.analyze_unified",
        )
    except Exception:
        pass
    usage_str = ""
    if usage:
        usage_str = f", 토큰: in={usage.input_tokens}/out={usage.output_tokens}"
    print(
        f"    [Claude API] ← 응답: {len(raw)}자 ({elapsed:.1f}s{usage_str})"
    )
    parsed = _parse_json(raw)
    summary = parsed.get("summary", "")
    if summary:
        print(f"    [Claude API] ← 요약: {summary[:80]}")
    return parsed


def _parse_json(raw: str) -> dict[str, Any]:
    text = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
        return {}


def _build_prompt(
    transcript: str,
    scam_type: str,
    entities: list[Entity],
    verification_results: list[VerificationResult],
    similar_cases: list[dict[str, Any]] | None = None,
) -> str:
    allowed_labels = get_runtime_scam_taxonomy()["label_sets"].get(scam_type, [])
    allowed_flags = list(DETECTED_FLAGS)

    entity_lines = [
        {
            "text": entity.text,
            "label": entity.label,
            "score": round(entity.score, 4),
            "source": entity.source,
        }
        for entity in entities[:_MAX_ENTITY_COUNT]
    ]
    triggered_flags = [
        {
            "flag": result.flag,
            "description": result.flag_description,
        }
        for result in verification_results[:_MAX_FLAG_COUNT]
        if result.triggered
    ]
    rag_cases = (similar_cases or [])[:RAG_MAX_CASES_IN_PROMPT]

    return f"""
역할: 한국어 스캠 탐지 보조 판정기
출력: JSON만

해야 할 일:
1. 기존 추출에서 빠졌을 수 있는 엔티티 최대 2개
2. 기존 검증과 별도로 점수 반영 후보 플래그 최대 2개
3. 짧은 한국어 요약 1문장
4. 왜 사기/비사기라고 보는지 핵심 근거 최대 3개

규칙:
- missing_entities[].label 은 허용 레이블 중 하나만 사용
- suggested_flags[].flag 는 허용 플래그 중 하나만 사용
- 확신이 낮으면 빈 배열
- confidence 는 0~1 숫자
- text 가 비어 있는 엔티티는 절대 반환하지 마라
- 이미 추출된 엔티티와 동일하면 다시 제안하지 마라

허용 레이블:
{json.dumps(allowed_labels, ensure_ascii=False)}

허용 플래그:
{json.dumps(allowed_flags, ensure_ascii=False)}

이미 추출된 엔티티:
{json.dumps(entity_lines, ensure_ascii=False)}

이미 발동된 플래그:
{json.dumps(triggered_flags, ensure_ascii=False)}

유사 과거 사례(사람이 정답 확정):
{json.dumps(rag_cases, ensure_ascii=False)}

전사 텍스트:
{transcript[:_MAX_TRANSCRIPT_CHARS]}

반환 JSON 스키마:
{{
  "summary": "짧은 한국어 요약",
  "reasoning": ["핵심 근거 1", "핵심 근거 2"],
  "missing_entities": [
    {{
      "text": "문자열",
      "label": "허용 레이블 중 하나",
      "reason": "왜 이 엔티티가 중요하다고 봤는지",
      "confidence": 0.0
    }}
  ],
  "suggested_flags": [
    {{
      "flag": "허용 플래그 중 하나",
      "reason": "왜 이 플래그를 제안하는지",
      "evidence": "전사에서 근거가 되는 짧은 문구",
      "confidence": 0.0
    }}
  ]
}}
""".strip()


def _build_scam_type_prompt(transcript: str) -> str:
    taxonomy = get_runtime_scam_taxonomy()
    scam_types = taxonomy["scam_types"]
    label_map = taxonomy["descriptions"]
    description_lines = [{"description": k, "scam_type": v} for k, v in label_map.items()]

    return f"""
역할: 한국어 스캠 유형 분류기 (문맥 기반)
출력: JSON만

해야 할 일:
- 전사 텍스트를 읽고 가장 적절한 스캠 유형 1개를 고른다.
- 확신도를 0~1로 반환한다.
- 근거를 전사에서 짧게 1~2문장으로 요약한다.

규칙:
- scam_type 은 허용 목록 중 하나만
- confidence 는 0~1 숫자

허용 스캠 유형:
{json.dumps(scam_types, ensure_ascii=False)}

유형 설명(참고):
{json.dumps(description_lines, ensure_ascii=False)}

전사 텍스트:
{transcript[:_MAX_TRANSCRIPT_CHARS]}

반환 JSON 스키마:
{{
  "scam_type": "허용 목록 중 하나",
  "confidence": 0.0,
  "reason": "근거 요약"
}}
""".strip()


def suggest_scam_type(transcript: str) -> ScamTypeSuggestion | None:
    """
    LLM이 전사 문맥을 보고 스캠 유형을 제안한다.
    confidence가 낮으면 None을 반환한다(기존 분류기 폴백용).
    """
    prompt = _build_scam_type_prompt(transcript)
    result = _call_claude(prompt, max_tokens=256)
    scam_type = str(result.get("scam_type", "")).strip()
    confidence = _clamp_confidence(result.get("confidence"), default=0.55)
    reason = str(result.get("reason", "")).strip()

    taxonomy = get_runtime_scam_taxonomy()
    if not scam_type or scam_type not in taxonomy["scam_types"]:
        return None
    if confidence < LLM_SCAM_TYPE_OVERRIDE_THRESHOLD:
        return None
    return ScamTypeSuggestion(scam_type=scam_type, confidence=confidence, reason=reason)


def assess(
    transcript: str,
    scam_type: str,
    entities: list[Entity],
    verification_results: list[VerificationResult],
    similar_cases: list[dict[str, Any]] | None = None,
) -> LLMAssessment:
    prompt = _build_prompt(
        transcript,
        scam_type,
        entities,
        verification_results,
        similar_cases=similar_cases,
    )
    raw = _call_claude(prompt, max_tokens=512)

    allowed_labels = set(get_runtime_scam_taxonomy()["label_sets"].get(scam_type, []))
    allowed_flags = set(DETECTED_FLAGS)
    existing_entity_pairs = {(entity.label, entity.text) for entity in entities}

    suggested_entities: list[SuggestedEntity] = []
    seen_entity_pairs: set[tuple[str, str]] = set()
    for item in raw.get("missing_entities", [])[:5]:
        label = str(item.get("label", "")).strip()
        text = str(item.get("text", "")).strip()
        if not label or not text or label not in allowed_labels:
            continue
        pair = (label, text)
        if pair in existing_entity_pairs or pair in seen_entity_pairs:
            continue
        seen_entity_pairs.add(pair)
        suggested_entities.append(
            SuggestedEntity(
                text=text,
                label=label,
                reason=str(item.get("reason", "")).strip(),
                confidence=_clamp_confidence(item.get("confidence")),
            )
        )

    suggested_flags: list[SuggestedFlag] = []
    seen_flags: set[str] = set()
    for item in raw.get("suggested_flags", [])[:3]:
        flag = str(item.get("flag", "")).strip()
        if not flag or flag not in allowed_flags or flag in seen_flags:
            continue
        seen_flags.add(flag)
        suggested_flags.append(
            SuggestedFlag(
                flag=flag,
                reason=str(item.get("reason", "")).strip(),
                evidence=str(item.get("evidence", "")).strip(),
                confidence=_clamp_confidence(item.get("confidence")),
            )
        )

    reasoning: list[str] = []
    for item in raw.get("reasoning", [])[:3]:
        text = str(item).strip()
        if text:
            reasoning.append(text)

    return LLMAssessment(
        model=default_model_name(),
        summary=str(raw.get("summary", "")).strip(),
        reasoning=reasoning,
        suggested_entities=suggested_entities,
        suggested_flags=suggested_flags,
    )


def merge_suggested_entities(
    entities: list[Entity],
    assessment: LLMAssessment | None,
) -> list[Entity]:
    if assessment is None or assessment.error:
        return list(entities)

    merged = list(entities)
    seen_pairs = {(entity.label, entity.text) for entity in merged}

    for suggested in assessment.suggested_entities:
        if suggested.confidence < LLM_ENTITY_MERGE_THRESHOLD:
            continue

        pair = (suggested.label, suggested.text)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        merged.append(
            Entity(
                text=suggested.text,
                label=suggested.label,
                score=suggested.confidence,
                start=-1,
                end=-1,
                source="llm",
            )
        )

    merged.sort(key=lambda entity: (entity.start < 0, entity.start, -entity.score))
    return merged


# ──────────────────────────────────────────────
# 통합 LLM 호출 (suggest_scam_type + assess를 1회로)
# ──────────────────────────────────────────────

@dataclass
class UnifiedLLMResult:
    """suggest_scam_type + assess 결과를 하나로 묶은 통합 결과."""
    scam_type_suggestion: ScamTypeSuggestion | None
    assessment: LLMAssessment


def _format_user_context_block(user_context: dict[str, Any] | None) -> str:
    """사용자 컨텍스트 대화 결과를 프롬프트용 블록으로 변환."""
    if not user_context:
        return "(사용자 컨텍스트 없음)"

    summary = str(user_context.get("summary_text", "")).strip()
    if not summary:
        qa_pairs = user_context.get("qa_pairs") or []
        lines = []
        for qa in qa_pairs:
            q = str(qa.get("question", "")).strip()
            a = str(qa.get("answer", "")).strip()
            if not a:
                continue
            if q:
                lines.append(f"Q: {q}")
            lines.append(f"A: {a}")
        summary = "\n".join(lines)

    if not summary:
        return "(사용자 컨텍스트 없음)"
    return summary[:1000]


def _build_unified_prompt(
    transcript: str,
    classifier_scam_type: str,
    user_context: dict[str, Any] | None = None,
) -> str:
    taxonomy = get_runtime_scam_taxonomy()
    scam_types = taxonomy["scam_types"]
    description_lines = [{"description": k, "scam_type": v} for k, v in taxonomy["descriptions"].items()]
    allowed_labels = taxonomy["label_sets"].get(classifier_scam_type, [])
    allowed_flags = list(DETECTED_FLAGS)
    user_context_block = _format_user_context_block(user_context)

    return f"""
역할: 한국어 스캠 탐지 통합 판정기
출력: JSON만

해야 할 일 (한 번에 모두 수행):
1. 스캠 유형을 직접 판정하라. 분류기가 "{classifier_scam_type}"(으)로 판단했지만, 문맥상 더 적절한 유형이 있으면 교체.
2. 전사에서 핵심 엔티티(이름, 금액, 기관 등) 최대 5개를 찾아라.
3. 스캠 징후 플래그 최대 3개를 제안하라.
4. 짧은 한국어 요약 1문장과 핵심 근거 최대 3개를 작성하라.

규칙:
- scam_type 은 허용 스캠 유형 중 하나만
- missing_entities[].label 은 허용 레이블 중 하나만
- suggested_flags[].flag 는 허용 플래그 중 하나만
- confidence 는 0~1 숫자
- text 가 비어 있는 엔티티는 절대 반환하지 마라
- 확신이 낮으면 빈 배열

사용자 제보(prior, 참고용):
- 사용자가 챗봇과 대화하며 직접 알려준 정보다. 출처·의심 포인트·권유받은 행동 등이 포함될 수 있다.
- 강한 prior 이지만 맹신하지 마라. 전사와 일치하지 않으면 전사를 우선한다.
- 사용자가 "수익 보장 받았다", "송금 요구받았다" 같은 구체적 행동 단서를 줬다면 관련 플래그 confidence 를 높여도 된다.
{user_context_block}

허용 스캠 유형:
{json.dumps(scam_types, ensure_ascii=False)}

유형 설명(참고):
{json.dumps(description_lines, ensure_ascii=False)}

허용 레이블 (분류기 기준 "{classifier_scam_type}" 유형):
{json.dumps(allowed_labels, ensure_ascii=False)}

허용 플래그:
{json.dumps(allowed_flags, ensure_ascii=False)}

전사 텍스트:
{transcript[:_MAX_TRANSCRIPT_CHARS]}

반환 JSON 스키마:
{{
  "scam_type": "허용 목록 중 하나",
  "scam_type_confidence": 0.0,
  "scam_type_reason": "근거 요약",
  "summary": "짧은 한국어 요약",
  "reasoning": ["핵심 근거 1", "핵심 근거 2"],
  "missing_entities": [
    {{
      "text": "문자열",
      "label": "허용 레이블 중 하나",
      "reason": "왜 중요한지",
      "confidence": 0.0
    }}
  ],
  "suggested_flags": [
    {{
      "flag": "허용 플래그 중 하나",
      "reason": "왜 제안하는지",
      "evidence": "전사에서 근거가 되는 짧은 문구",
      "confidence": 0.0
    }}
  ]
}}
""".strip()


def analyze_unified(
    transcript: str,
    classifier_scam_type: str,
    user_context: dict[str, Any] | None = None,
) -> UnifiedLLMResult:
    """
    LLM 스캠 유형 재판정 + 엔티티/플래그 제안을 1회 API 호출로 처리.
    verification_results 없이 동작하여 병렬 파이프라인에서 사용 가능.

    user_context: 챗봇 대화로 모은 사용자 제보. context_chat.summarize_for_pipeline() 결과.
    """
    prompt = _build_unified_prompt(transcript, classifier_scam_type, user_context=user_context)
    raw = _call_claude(prompt, max_tokens=512)

    # ── 스캠 유형 제안 파싱 ──
    scam_type_suggestion: ScamTypeSuggestion | None = None
    suggested_type = str(raw.get("scam_type", "")).strip()
    type_confidence = _clamp_confidence(raw.get("scam_type_confidence"), default=0.55)
    type_reason = str(raw.get("scam_type_reason", "")).strip()

    taxonomy = get_runtime_scam_taxonomy()
    if suggested_type and suggested_type in taxonomy["scam_types"]:
        if type_confidence >= LLM_SCAM_TYPE_OVERRIDE_THRESHOLD:
            scam_type_suggestion = ScamTypeSuggestion(
                scam_type=suggested_type,
                confidence=type_confidence,
                reason=type_reason,
            )

    # ── 엔티티/플래그 제안 파싱 (assess와 동일 로직) ──
    effective_type = suggested_type if scam_type_suggestion else classifier_scam_type
    allowed_labels = set(taxonomy["label_sets"].get(effective_type, []))
    allowed_flags = set(DETECTED_FLAGS)

    suggested_entities: list[SuggestedEntity] = []
    seen_entity_pairs: set[tuple[str, str]] = set()
    for item in raw.get("missing_entities", [])[:5]:
        label = str(item.get("label", "")).strip()
        text = str(item.get("text", "")).strip()
        if not label or not text or label not in allowed_labels:
            continue
        pair = (label, text)
        if pair in seen_entity_pairs:
            continue
        seen_entity_pairs.add(pair)
        suggested_entities.append(SuggestedEntity(
            text=text, label=label,
            reason=str(item.get("reason", "")).strip(),
            confidence=_clamp_confidence(item.get("confidence")),
        ))

    suggested_flags: list[SuggestedFlag] = []
    seen_flags: set[str] = set()
    for item in raw.get("suggested_flags", [])[:3]:
        flag = str(item.get("flag", "")).strip()
        if not flag or flag not in allowed_flags or flag in seen_flags:
            continue
        seen_flags.add(flag)
        suggested_flags.append(SuggestedFlag(
            flag=flag,
            reason=str(item.get("reason", "")).strip(),
            evidence=str(item.get("evidence", "")).strip(),
            confidence=_clamp_confidence(item.get("confidence")),
        ))

    reasoning: list[str] = []
    for item in raw.get("reasoning", [])[:3]:
        text = str(item).strip()
        if text:
            reasoning.append(text)

    assessment = LLMAssessment(
        model=default_model_name(),
        summary=str(raw.get("summary", "")).strip(),
        reasoning=reasoning,
        suggested_entities=suggested_entities,
        suggested_flags=suggested_flags,
    )

    return UnifiedLLMResult(
        scam_type_suggestion=scam_type_suggestion,
        assessment=assessment,
    )
