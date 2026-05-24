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
    GATE_SCAM_NEWS_EDU,
    GATE_UNDETERMINED,
)


# 뉴스 narration 마커 — 3인칭 보도·인용·사례 표현. 2개 이상 + 명령 부재면 scam_news_edu fast-path
_NEWS_MARKERS = re.compile(
    r"라고\s*(밝혔|전했|말했|덧붙였|설명했)"
    r"|\[(기자|특파원|취재|앵커)|(기자|특파원)\]"
    r"|(검찰|경찰|금감원|방통위|KISA)에\s*따르면"
    r"|(피해자|피의자|용의자)(는|가|의)"
    r"|수사\s*(중|결과|에\s*착수)"
    r"|급증하(고|는|며)"
    r"|주의(가\s*필요|하셔야|해야)"
    r"|예방\s*(안내|수칙|법)"
    r"|피해\s*사례"
    r"|(보도|기사|뉴스|방송)(에서|에\s*따르면|입니다|이다)"
)
# 직접 명령형 금전·인증 요구 — 한 개라도 있으면 fast-path 금지 (LLM 으로 위임)
_DIRECT_DEMAND = re.compile(
    r"지금\s*(송금|입금|이체|전화)"
    r"|(OTP|인증번호|비밀번호)\s*(입력|알려|보내)"
    r"|계좌(번호)?\s*(입력|알려|로\s*(보내|이체|송금))"
    r"|클릭(하세요|해\s*주세요)"
    r"|(설치|다운로드)\s*(하세요|해\s*주세요)"
)
_NEWS_FAST_PATH_MIN_MARKERS = 2

_client = None

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
GATE_INPUT_MAX_CHARS = 4000  # 게이트 판단엔 충분 — 본문 앞부분만 본다


_SYSTEM_PROMPT = """한국어 콘텐츠를 내부 라우팅용으로 5개 중 하나로 분류하세요.

- scam_attempt: 콘텐츠 자체가 수신자를 속이려 함 (송금·개인정보·앱설치 유도).
- scam_news_edu: 사기를 *소재로 다루는* 뉴스·교육·경고·피해 후기·사례 영상. 사기 키워드·금액이 많아도 콘텐츠 자체는 누구도 안 속임.
- normal: 사기와 무관한 일상.
- suspicious_insufficient: 의심되지만 단정 부족.
- undetermined: 너무 짧거나 깨져 방향조차 모름.

핵심: 같은 "보이스피싱" 단어라도 수신자 속이면 scam_attempt, 설명·경고·사례 narration 이면 scam_news_edu.
사용자가 받은 메시지를 전달했으면 *전달된 그 메시지* 를 기준으로.

예:
- "택배 미배송, 주소 재확인 http://bit.ly/xxx" → scam_attempt
- "택배 사칭 스미싱이 급증, 링크 누르지 마세요" → scam_news_edu
- "보이스피싱 피해 사례: 검찰 사칭에 3천만원 송금" (기사·영상) → scam_news_edu
- "서울 한 남성이 현금 5,400만원을 ... 사기 피해" (사건 narration) → scam_news_edu
- "오늘 점심 뭐 먹지?" → normal

JSON 한 줄만 출력 (reason 은 20자 이내). 다른 텍스트 금지:
{"bucket":"<영문 키>","confidence":<0.0~1.0>,"reason":"<≤20자>"}"""


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


def _news_edu_fast_path(text: str) -> GateResult | None:
    """뉴스/교육 narration 마커가 충분하고 직접 명령형 요구가 없으면 LLM skip.

    매우 보수적 — fast-path 가 false positive 면 Phase 2/LLM/Serper 까지 skip 됨.
    그래서 (1) 뉴스 마커 2개 이상 (2) 명령형 금전·인증 요구 0개 둘 다 만족해야 함.
    """
    if _DIRECT_DEMAND.search(text):
        return None
    matches = _NEWS_MARKERS.findall(text)
    if len(matches) < _NEWS_FAST_PATH_MIN_MARKERS:
        return None
    return GateResult(
        bucket=GATE_SCAM_NEWS_EDU,
        confidence=0.7,
        reason=f"뉴스 narration 마커 {len(matches)}개 + 직접 명령형 요구 0건 (heuristic)",
        source="heuristic",
    )


def classify_gate(text: str) -> GateResult:
    """입력 콘텐츠를 Stage 1 게이트 bucket 으로 분류한다.

    fast-path 우선순위:
      1. 빈/극단적으로 짧은 입력 → undetermined
      2. 뉴스 narration 마커 충분 + 직접 명령 없음 → scam_news_edu
    위 둘에 안 걸리면 → Claude Haiku 1회. 호출·파싱 실패는 fallback.
    어떤 경우에도 예외를 밖으로 던지지 않는다 — 게이트는 죽으면 안 된다.
    """
    stripped = (text or "").strip()

    # fast-path 1 — 방향조차 못 정하는 입력
    if len(stripped) < GATE_MIN_CHARS:
        return GateResult(
            bucket=GATE_UNDETERMINED,
            confidence=1.0,
            reason=f"입력이 {GATE_MIN_CHARS}자 미만 — 판단 불가",
            source="heuristic",
        )

    # fast-path 2 — 뉴스/교육 narration 패턴 (LLM 비용 + latency 절약)
    news_hit = _news_edu_fast_path(stripped[:GATE_INPUT_MAX_CHARS])
    if news_hit is not None:
        print(f"    [Gate] ← {news_hit.bucket} (heuristic, LLM skip)")
        return news_hit

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
