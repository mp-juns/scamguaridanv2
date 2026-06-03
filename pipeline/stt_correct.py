"""LLM 기반 STT 후처리 교정.

CLOVA/Whisper 가 빠른 대화체에서 내는 오인식("이선호 수사관입니다"→"이선호 수작을 했다")
을 앞뒤 맥락으로 교정한다. **생성 금지** — 명백한 STT 오류만 고치고 내용 추가·삭제·요약·
의미변경 안 함. 가드(turn 개수·길이 비율) 실패 시 원본 turn 유지 → 회귀 없음.

화자 turn 단위로 교정해 speaker / start_sec / end_sec 는 그대로 보존하고 text 만 교체.

Identity Boundary: 판정·점수·등급 주입 절대 X — 순수 전사 텍스트 교정만.

env:
- STT_CORRECT — "1"(켜기) / "0"(기본 끄기)
- STT_CORRECT_MODEL — 교정 모델 (없으면 diarize 의 Haiku 기본)
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

LOG = logging.getLogger("pipeline.stt_correct")

# 교정된 turn 텍스트가 원본 길이 대비 이 비율 밖이면 의심 → 해당 turn 원본 유지.
_LEN_RATIO_MIN = 0.4
_LEN_RATIO_MAX = 2.5
# 전체 전사 길이 비율이 이 밖이면 통째로 교정 거부 (대규모 fabrication/누락 방어).
_TOTAL_RATIO_MIN = 0.6
_TOTAL_RATIO_MAX = 1.8

_SYSTEM_PROMPT = (
    "당신은 한국어 음성 통화 STT(자동 전사) 결과의 명백한 오인식을 교정합니다. "
    "입력은 화자별 turn 목록이며, 각 turn 텍스트에서 STT 가 잘못 알아들은 부분만 앞뒤 "
    "맥락으로 바로잡으세요.\n\n"
    "규칙(엄수):\n"
    "1. 명백한 STT 오류만 교정. 나머지는 한 글자도 바꾸지 마세요.\n"
    "2. 내용을 추가·삭제·요약·재배열하지 마세요. 없는 말을 지어내지 마세요.\n"
    "3. 확실하지 않으면 원문 그대로 두세요 (추측 금지).\n"
    "4. 이름·숫자·금액·기관명은 맥락상 명백할 때만 교정하고, 새로 지어내지 마세요.\n"
    "5. turn 개수와 순서를 그대로 유지하세요.\n\n"
    "예) '합수부에 이선호 수작을 했다' → '합수부에 이선호 수사관입니다' / "
    "'서화동 지점이 철산 통치성인데요' → '서화동 지점이고 철산동 지점인데요'\n\n"
    "출력: JSON 배열 하나. 각 원소는 해당 turn 의 교정된 텍스트(문자열), turn 과 동일 개수·"
    "순서. 설명·코드블록 없이 JSON 배열만."
)


def enabled() -> bool:
    return os.getenv("STT_CORRECT", "0").strip().lower() in {"1", "true", "yes", "on"}


def _parse_str_array(raw: str) -> list[str] | None:
    text = re.sub(r"```(?:json)?\s*", "", raw or "").strip().rstrip("`").strip()
    data: Any = None
    try:
        data = json.loads(text)
    except Exception:
        m = re.search(r"\[[\s\S]*\]", text)
        if m:
            try:
                data = json.loads(m.group(0))
            except Exception:
                data = None
    if not isinstance(data, list):
        return None
    return [str(x) for x in data]


def correct_turns(turns: list[dict], model: str | None = None) -> list[dict]:
    """turn 목록의 text 를 LLM 으로 교정해 반환. 실패·가드 위반 시 원본 그대로.

    speaker / start_sec / end_sec 는 보존하고 text 만 교체한다.
    """
    if not turns:
        return turns
    # 텍스트 있는 turn 만 대상
    indexed = [(i, (t.get("text", "") or "").strip()) for i, t in enumerate(turns)]
    nonempty = [(i, txt) for i, txt in indexed if txt]
    if not nonempty:
        return turns

    lines = []
    for n, (_, txt) in enumerate(nonempty, start=1):
        lines.append(f"{n}. {txt}")
    user_content = "turn 목록:\n" + "\n".join(lines) + "\n\n교정된 텍스트를 JSON 배열로:"

    try:
        from pipeline import diarize as _diarize
        client = _diarize._get_client()
        mdl = model or os.getenv("STT_CORRECT_MODEL") or _diarize._model_name(None)
        t0 = time.time()
        message = client.messages.create(
            model=mdl,
            max_tokens=4000,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        elapsed = time.time() - t0
        raw = message.content[0].text if message.content else ""
        try:
            from platform_layer import cost as _cost
            _cost.record_claude(
                mdl,
                int(getattr(message.usage, "input_tokens", 0) or 0),
                int(getattr(message.usage, "output_tokens", 0) or 0),
                action="stt.correct",
            )
        except Exception:
            pass
    except Exception as exc:
        LOG.warning("[STTCorrect] LLM 호출 실패 → 원본 유지: %s", exc)
        return turns

    corrected = _parse_str_array(raw)
    if corrected is None or len(corrected) != len(nonempty):
        LOG.warning(
            "[STTCorrect] 응답 무효 (개수 %s≠%d) → 원본 유지",
            None if corrected is None else len(corrected), len(nonempty),
        )
        return turns

    # 전체 길이 비율 가드 (대규모 fabrication/누락 방어)
    orig_total = sum(len(txt) for _, txt in nonempty) or 1
    new_total = sum(len(c) for c in corrected) or 1
    total_ratio = new_total / orig_total
    if not (_TOTAL_RATIO_MIN <= total_ratio <= _TOTAL_RATIO_MAX):
        LOG.warning(
            "[STTCorrect] 전체 길이 비율 %.2f 이탈 → 통째 거부 (원본 유지)", total_ratio,
        )
        return turns

    # turn 단위 적용 — 길이 비율 이탈한 개별 turn 은 원본 유지
    out = [dict(t) for t in turns]
    changed = 0
    kept = 0
    for (orig_idx, orig_txt), new_txt in zip(nonempty, corrected):
        new_txt = new_txt.strip()
        if not new_txt:
            kept += 1
            continue
        ratio = len(new_txt) / (len(orig_txt) or 1)
        if not (_LEN_RATIO_MIN <= ratio <= _LEN_RATIO_MAX):
            kept += 1
            continue  # 의심 turn → 원본 유지
        if new_txt != orig_txt:
            out[orig_idx]["text"] = new_txt
            changed += 1
    LOG.info(
        "[STTCorrect] %d turn 교정 (%d 유지, total_ratio=%.2f, %.2fs, model=%s)",
        changed, kept, total_ratio, elapsed, mdl,
    )
    return out


def corrected_full_text(turns: list[dict]) -> str:
    """교정된 turn 들로부터 전체 전사문 재구성."""
    return " ".join((t.get("text", "") or "").strip() for t in turns).strip()
