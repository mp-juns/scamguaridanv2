"""
외부 API 가격표 — USD 단위.

운영자가 실제 청구서랑 맞추도록 한 곳에 모음. 가격은 변동될 수 있으니 정기 점검.
출처:
- Anthropic: https://www.anthropic.com/pricing#api
- OpenAI Whisper: $0.006/min (audio)
- Serper: ~$0.001 per query (basic plan)
- VirusTotal Public: 무료 (4 req/min)
"""

from __future__ import annotations

# Claude (per 1M tokens) — sonnet-4-6 기준. opus·haiku 는 별도 분기.
CLAUDE_PRICING = {
    "claude-sonnet-4-6": {"input": 3.0 / 1_000_000, "output": 15.0 / 1_000_000},
    "claude-opus-4-7": {"input": 15.0 / 1_000_000, "output": 75.0 / 1_000_000},
    "claude-haiku-4-5-20251001": {"input": 0.80 / 1_000_000, "output": 4.0 / 1_000_000},
}
DEFAULT_CLAUDE = CLAUDE_PRICING["claude-sonnet-4-6"]


def claude_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    p = CLAUDE_PRICING.get(model, DEFAULT_CLAUDE)
    return input_tokens * p["input"] + output_tokens * p["output"]


# OpenAI Whisper (per minute)
OPENAI_WHISPER_PER_MIN = 0.006


def whisper_cost(audio_seconds: float) -> float:
    return (audio_seconds / 60.0) * OPENAI_WHISPER_PER_MIN


# Naver CLOVA Speech (per minute) — NCP 표 기준 대략 ₩4/분 ≈ $0.003.
# 정확한 단가는 NCP 콘솔에서 확인. CLOVA_SPEECH_PER_MIN_USD env 로 override.
import os as _os_pricing
CLOVA_SPEECH_PER_MIN_USD = float(_os_pricing.getenv("CLOVA_SPEECH_PER_MIN_USD", "0.003"))


def clova_speech_cost(audio_seconds: float) -> float:
    return (audio_seconds / 60.0) * CLOVA_SPEECH_PER_MIN_USD


# Serper (per query) — 무료 티어 후 $0.001 가정. 정확한 단가는 플랜에 따라 다름.
SERPER_PER_QUERY = 0.001


def serper_cost(queries: int) -> float:
    return queries * SERPER_PER_QUERY


# VirusTotal Public — 무료. Premium 사용 시 별도 계산.
VT_PER_REQUEST = 0.0


def vt_cost(requests: int) -> float:
    return requests * VT_PER_REQUEST
