"""
요청별 비용 추적 — context-local 로 현재 요청의 api_key_id / request_id 를 들고
다니며, 외부 API 호출 시점에 record() 호출.

ScamReport 내부 통합 지점:
- llm_assessor.py / claude_labeler.py / context_chat.py / vision.py → claude
- stt.py (OpenAI 백엔드) → openai
- verifier.py → serper
- safety.py → virustotal

호출 실패해도 분석은 계속 — DB 미설정 시 silent skip.
"""

from __future__ import annotations

import contextvars
import logging
from typing import Any

from db import repository
from platform_layer import pricing

log = logging.getLogger("cost")

_REQUEST_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
_API_KEY_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("api_key_id", default=None)


def set_context(*, request_id: str | None, api_key_id: str | None) -> None:
    _REQUEST_ID.set(request_id)
    _API_KEY_ID.set(api_key_id)


def clear_context() -> None:
    _REQUEST_ID.set(None)
    _API_KEY_ID.set(None)


def _record(provider: str, action: str, units: float, usd: float, **metadata: Any) -> None:
    try:
        repository.insert_cost_event(
            request_id=_REQUEST_ID.get(),
            api_key_id=_API_KEY_ID.get(),
            provider=provider,
            action=action,
            units=units,
            usd_amount=usd,
            metadata=metadata or None,
        )
    except Exception as exc:  # noqa: BLE001 — cost 기록 실패가 분석을 죽이면 안 됨
        log.warning("cost record 실패 (%s/%s): %s", provider, action, exc)


def record_claude(model: str, input_tokens: int, output_tokens: int, *, action: str = "messages.create") -> None:
    usd = pricing.claude_cost(model, input_tokens, output_tokens)
    _record(
        "claude",
        action,
        units=input_tokens + output_tokens,
        usd=usd,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def record_openai_whisper(audio_seconds: float, *, action: str = "transcribe") -> None:
    usd = pricing.whisper_cost(audio_seconds)
    _record("openai", action, units=audio_seconds, usd=usd, audio_seconds=audio_seconds)


def record_clova_speech(audio_seconds: float, *, action: str = "transcribe") -> None:
    """Naver CLOVA Speech 비용 ledger 기록."""
    usd = pricing.clova_speech_cost(audio_seconds)
    _record("clova", action, units=audio_seconds, usd=usd, audio_seconds=audio_seconds)


def record_serper(queries: int = 1, *, action: str = "search") -> None:
    _record("serper", action, units=queries, usd=pricing.serper_cost(queries))


def record_virustotal(requests: int = 1, *, action: str = "scan") -> None:
    _record("virustotal", action, units=requests, usd=pricing.vt_cost(requests))
