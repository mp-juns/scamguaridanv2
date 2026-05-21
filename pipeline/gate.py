"""ScamGuardian — Stage 1 콘텐츠 게이트 (내부 라우팅 전용).

입력 콘텐츠를 5개 bucket 중 하나로 분류한다:
  normal / scam_attempt / scam_news_edu / suspicious_insufficient / undetermined

**Identity Boundary (CLAUDE.md)**: 게이트 결과는 *외부 API 응답에 노출하지 않는다*.
파이프라인 실행 강도 라우팅 + 라벨링 metadata 에만 쓴다. 검출(detection)이 아니라
내부 라우팅 신호다.

**검출 누락 방지**: 게이트는 룰 기반 신호검출을 *건너뛰게 하지 않는다*. 게이트가
normal 로 오판해도 룰 기반 검출은 항상 수행된다 (runner.py 라우팅 정책). 게이트는
비싼 단계(Serper·LLM)의 실행 강도만 조절한다.

구현: Claude Haiku 1회 호출. 빈/극단적으로 짧은 입력은 LLM 없이 fast-path,
호출 실패·파싱 실패는 GATE_FALLBACK_BUCKET 으로 안전하게 fallback.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

from pipeline.config import (
    GATE_BUCKETS,
    GATE_EXECUTION_PROFILE,
    GATE_FALLBACK_BUCKET,
    GATE_LABELS_KO,
    GATE_MIN_CHARS,
    GATE_UNDETERMINED,
)

_client = None

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
GATE_INPUT_MAX_CHARS = 4000  # 게이트 판단엔 충분 — 본문 앞부분만 본다


_SYSTEM_PROMPT = """당신은 한국어 콘텐츠를 5개 범주 중 하나로 분류하는 내부 라우팅 분류기입니다.
이 분류는 파이프라인 라우팅에만 쓰이며 최종 사용자에게 노출되지 않습니다.

입력 콘텐츠를 다음 중 정확히 하나로 분류하세요:

- "scam_attempt": 콘텐츠 자체가 수신자를 속이려는 사기 시도다. 송금·개인정보·앱
  설치 등을 유도하는 실제 미끼 메시지·통화·페이지.
- "scam_news_edu": 사기를 *소재로 다루는* 뉴스 기사·예방 교육·경고 안내·피해 후기.
  사기 키워드가 많아도 콘텐츠 자체는 누구를 속이려 하지 않는다.
- "normal": 사기와 무관한 일상적·정상적 콘텐츠.
- "suspicious_insufficient": 사기 쪽으로 의심되지만 단정할 신호가 부족하다.
- "undetermined": 입력이 너무 짧거나 깨져 방향조차 판단할 수 없다.

핵심 구분: 같은 "보이스피싱" 단어가 있어도 — 수신자를 속이려 하면 scam_attempt,
사기를 설명·경고하면 scam_news_edu 입니다.

예시:
- "[Web발신] 택배 미배송 안내, 주소 재확인: http://bit.ly/xxx" → scam_attempt
- "최근 택배 사칭 스미싱이 급증합니다. 출처 불명 링크는 누르지 마세요." → scam_news_edu
- "투자로 원금 보장, 연 30% 수익. 지금 입금하세요." → scam_attempt
- "보이스피싱 피해 사례: 검찰 사칭에 3천만원 송금" (기사 제목) → scam_news_edu
- "오늘 점심 뭐 먹을까?" → normal

사용자가 받은 메시지를 전달한 경우, 전달된 그 메시지 내용 자체를 기준으로 분류하세요.

JSON 한 줄로만 답하세요. 다른 텍스트 금지:
{"bucket": "<위 5개 영문 키 중 하나>", "confidence": <0.0~1.0 숫자>, "reason": "<한 줄 근거>"}"""


@dataclass
class GateResult:
    """Stage 1 게이트 분류 결과. 외부 응답 노출 금지 — 내부 라우팅·metadata 전용."""

    bucket: str                  # GATE_BUCKETS 멤버
    confidence: float = 0.0
    reason: str = ""
    source: str = "haiku"        # haiku | heuristic | fallback
    model: str = ""

    @property
    def label_ko(self) -> str:
        return GATE_LABELS_KO.get(self.bucket, self.bucket)

    def execution_profile(self) -> dict[str, Any]:
        """이 bucket 의 파이프라인 실행 강도 profile."""
        return execution_profile(self.bucket)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bucket": self.bucket,
            "label_ko": self.label_ko,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "source": self.source,
            "model": self.model,
        }


def execution_profile(bucket: str) -> dict[str, Any]:
    """bucket → 실행 강도 profile. 알 수 없는 bucket 은 fallback profile."""
    return dict(
        GATE_EXECUTION_PROFILE.get(
            bucket, GATE_EXECUTION_PROFILE[GATE_FALLBACK_BUCKET]
        )
    )


def _get_client():
    global _client
    if _client is None:
        import anthropic

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY가 설정되지 않았습니다.")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def _model_name() -> str:
    return os.getenv("ANTHROPIC_HAIKU_MODEL", DEFAULT_MODEL)


def _parse_gate_json(raw: str) -> dict[str, Any]:
    """Claude 응답에서 JSON 객체를 추출한다 (코드펜스 제거 + 중괄호 fallback)."""
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


def _result_from_payload(payload: dict[str, Any], model: str) -> GateResult:
    """파싱된 JSON payload → GateResult. bucket 무효 시 fallback."""
    bucket = str(payload.get("bucket", "")).strip()
    if bucket not in GATE_BUCKETS:
        return GateResult(
            bucket=GATE_FALLBACK_BUCKET,
            confidence=0.0,
            reason=f"게이트 응답의 bucket 무효({bucket!r}) — fallback",
            source="fallback",
            model=model,
        )
    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    return GateResult(
        bucket=bucket,
        confidence=confidence,
        reason=str(payload.get("reason", "")).strip(),
        source="haiku",
        model=model,
    )


def classify_gate(text: str) -> GateResult:
    """입력 콘텐츠를 Stage 1 게이트 bucket 으로 분류한다.

    fast-path: 빈/극단적으로 짧은 입력 → undetermined (LLM 호출 없음).
    그 외 → Claude Haiku 1회. 호출·파싱 실패는 GATE_FALLBACK_BUCKET 으로 fallback.
    어떤 경우에도 예외를 밖으로 던지지 않는다 — 게이트는 죽으면 안 된다.
    """
    stripped = (text or "").strip()

    # fast-path — 방향조차 못 정하는 입력
    if len(stripped) < GATE_MIN_CHARS:
        return GateResult(
            bucket=GATE_UNDETERMINED,
            confidence=1.0,
            reason=f"입력이 {GATE_MIN_CHARS}자 미만 — 판단 불가",
            source="heuristic",
        )

    model = _model_name()
    try:
        client = _get_client()
        body = stripped[:GATE_INPUT_MAX_CHARS]
        print(f"    [Gate] → {model}, len={len(body)}")
        t0 = time.time()
        message = client.messages.create(
            model=model,
            max_tokens=120,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": body}],
        )
        elapsed = time.time() - t0
        raw = message.content[0].text

        try:
            from platform_layer import cost as _cost

            _cost.record_claude(
                model,
                int(getattr(message.usage, "input_tokens", 0) or 0),
                int(getattr(message.usage, "output_tokens", 0) or 0),
                action="gate.classify",
            )
        except Exception:
            pass

        result = _result_from_payload(_parse_gate_json(raw), model)
        print(f"    [Gate] ← {result.bucket} ({result.confidence:.2f}, {elapsed:.1f}s)")
        return result
    except Exception as exc:  # noqa: BLE001 — 게이트는 죽으면 안 됨
        print(f"    [Gate] 분류 실패 → {GATE_FALLBACK_BUCKET} fallback: {exc}")
        return GateResult(
            bucket=GATE_FALLBACK_BUCKET,
            confidence=0.0,
            reason=f"게이트 호출 실패: {exc}",
            source="fallback",
            model=model,
        )
