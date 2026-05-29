"""한국어 전화 통화 STT 결과 화자 분리 (텍스트 기반).

Whisper API 는 화자 식별을 안 해주므로 — 전사된 텍스트를 Claude Haiku 로
후처리해 `상대방` / `본인` 두 화자로 분리한다. pyannote 같은 오디오 기반
diarization 보다 가볍고 (1-2초) Korean voice phishing 의 대화 패턴
(사기범=권위적/긴 발화, 피해자=짧은 응답) 에는 충분히 동작.

응답 형식: `[{speaker: "상대방"|"본인", text: str}, ...]`
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any

LOG = logging.getLogger("pipeline.diarize")

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-6"  # 정확도 우선 모드 (스트리밍 청크 등)
MAX_INPUT_CHARS = 8000  # Whisper 한 청크 정도. 너무 길면 잘라서 보냄.

_SYSTEM_PROMPT = """당신은 한국어 보이스피싱 의심 통화의 STT 전사문을 받아 두 화자로 분리하는 작업을 수행합니다.

═══════════════════════════════════════════════════════════
🚫 **가장 중요한 규칙 — 절대 위반 금지** 🚫
═══════════════════════════════════════════════════════════
**본문에 없는 단어·문장을 절대 추가하지 마세요.**

당신의 작업은 *나누는 것 (split)* 이고 *쓰는 것 (write)* 이 아닙니다.
당신이 출력한 모든 turn 의 text 를 순서대로 이어붙이면, 원본 전사문과
**단어 단위로 동일** 해야 합니다.

검증: 출력 단어 중 본문에 없는 단어 비율이 15% 넘으면 자동 reject 됩니다.

❌ 그럴듯한 본인 응답을 "추측" 으로 만들지 마세요 ("음...", "그래요?", "정말요?")
❌ 문맥상 자연스러워 보이는 추임새를 추가하지 마세요
❌ STT 오인식 같은 부분을 "교정" 하지 마세요 — 그대로 두세요
✅ 본문에 *실제로 등장하는* 문구만 화자별로 나누세요
✅ 본인 발화 못 찾겠으면 전부 "상대방" 으로 두세요
═══════════════════════════════════════════════════════════

**작업 전제 — 양방향 통화 패턴**
Whisper STT 는 화자 경계를 보존하지 못해 한 문단처럼 보일 수 있지만, 본문 안의
짧은 동의·질문·되묻기는 본인 발화일 가능성이 높습니다. 단, **본문에 실제로
존재하는 텍스트만** 분류 대상입니다.

두 화자:
- **상대방**: 전화를 건 사람 (사기범). 권위적·길고 정보 제공형·반복적 명령조.
  - 마커: "~입니다", "~하셔야 됩니다", "~하시면 돼요", "~드릴게요", "수사관/검찰청/금감원" 자칭, 사건 설명, 지시
- **본인**: 전화를 받은 사람 (피해자). 짧고 수동적, 의심이나 동의가 섞임.
  - 마커: "네", "아니요", "예", "맞습니다", "알겠습니다", "어?", "예?", "정말요?",
    "뭐요?", "그래요?", "누구요?", "잘 모르겠는데요", "왜요?", 짧은 질문, 되묻기

**핵심 휴리스틱**:
1. 상대방이 *"그러시면…", "그래서…", "그러니까…"* 로 시작하면, 직전에 본인 발화가 있었음 → 분리 필수
2. 상대방이 *질문 형태로 되묻기* ("…라고 하시니까 모르신다고요?", "…라구요?") 하면, 그 *직전에* 본인이 말한 것
3. *"네 맞습니다"* 류 짧은 동의 문장은 거의 본인 발화
4. *"네"* 하나만 있어도 본인 turn 으로 별도 분리
5. 토픽이 갑자기 바뀌면 화자 전환 의심

**규칙**:
- 양방향 통화 패턴이면 본인 turn 을 찾아내되, *본문 안 텍스트* 만 사용할 것
- **🚫 절대 금지: 본문에 없는 텍스트를 추가/생성/추측하지 마세요.**
  diarization 은 본문을 화자별로 *나누는 작업*이며, 새 발화를 *만들어내는 작업이 아닙니다*.
  모든 turn 의 `text` 를 순서대로 이어붙이면 입력 전사문과 **단어 단위로 동일** 해야 합니다.
- STT 오인식·반복은 그대로 두기 (수정 X). 어색해 보여도 손대지 마세요.
- 본인 turn 을 못 찾겠으면 그냥 전부 "상대방" 으로 두세요 — *없는 발화를 만들지 마세요*.
- 진짜로 한 화자뿐인 경우 (자동 음성 안내·녹취 메시지) 만 전부 "상대방"

**Few-shot 예시 1 — 올바른 분리 (✅)**:

입력:
"네, 검찰청 김민수 수사관입니다. 본인 명의로 개설된 계좌가 범죄에 사용됐는데요. 네? 모르신다고요? 그러시면 안전계좌로 자금을 옮기셔야 됩니다. 네 알겠습니다. 그러면 어떻게 해요? 지금 바로 송금하시면 됩니다."

✅ 올바른 출력:
[
  {"speaker": "상대방", "text": "네, 검찰청 김민수 수사관입니다. 본인 명의로 개설된 계좌가 범죄에 사용됐는데요."},
  {"speaker": "본인", "text": "네? 모르신다고요?"},
  {"speaker": "상대방", "text": "그러시면 안전계좌로 자금을 옮기셔야 됩니다."},
  {"speaker": "본인", "text": "네 알겠습니다. 그러면 어떻게 해요?"},
  {"speaker": "상대방", "text": "지금 바로 송금하시면 됩니다."}
]
→ 모든 text 를 이어붙이면 원본과 동일.

**Few-shot 예시 2 — 잘못된 분리 (❌ hallucination)**:

같은 입력에서 이렇게 출력하면 **REJECT 됩니다**:
❌ 잘못된 출력:
[
  {"speaker": "상대방", "text": "네, 검찰청 김민수 수사관입니다."},
  {"speaker": "본인", "text": "음... 무슨 일이세요?"},               ← 본문에 없는 단어 추가
  {"speaker": "상대방", "text": "계좌가 범죄에 사용됐는데요."},
  {"speaker": "본인", "text": "정말요? 어떻게 해야 하죠?"},          ← 본문에 없는 단어 추가
  {"speaker": "상대방", "text": "지금 바로 송금하시면 됩니다."}
]
→ "음", "무슨 일이세요", "정말요", "어떻게 해야 하죠" 가 본문에 없음 → reject.

**Few-shot 예시 3 — 본인 발화가 없는 경우 (✅ 안전한 선택)**:

입력:
"네, 중앙지검에서 연락 드렸습니다. 합숙비의 이선우 수사관입니다. 검찰청으로 나오셔야 됩니다."

✅ 올바른 출력 (본인 발화 흔적 없음 — 전부 상대방):
[
  {"speaker": "상대방", "text": "네, 중앙지검에서 연락 드렸습니다. 합숙비의 이선우 수사관입니다. 검찰청으로 나오셔야 됩니다."}
]
→ 가짜 본인 발화 만들지 않음. 안전.

**마지막 reminder — 출력 전 자가 검증**:
출력하기 전, 모든 turn 의 text 를 머릿속으로 이어붙여 원본과 비교하세요.
새 단어 / 추측한 문구 / 추가한 추임새가 하나라도 있으면 — 그것을 제거하고
*원본에 있는 텍스트만* 으로 다시 분류하세요.

**출력 형식 — JSON 배열만, 다른 설명/코드펜스 일절 금지**:
[{"speaker": "...", "text": "..."}, ...]"""


def _build_entity_types_block() -> str:
    """추출기 엔티티 schema 를 시스템 프롬프트용 텍스트로 변환."""
    from pipeline.config import BASE_LABELS, DEFAULT_LABEL_SETS

    union: list[str] = list(BASE_LABELS)
    for labels in DEFAULT_LABEL_SETS.values():
        for label in labels:
            if label not in union:
                union.append(label)
    return ", ".join(f'"{label}"' for label in union)


def _entities_system_prompt() -> str:
    """diarize + 엔티티 추출 통합 prompt — Sonnet 용 (라이브 스트리밍 청크)."""
    return f"""{_SYSTEM_PROMPT}

────────────────────────────────────────
**추가 작업: 각 turn 에서 엔티티 추출**

각 turn 의 `text` 에서 ScamGuardian 추출기 schema 에 정의된 엔티티를 식별해 `entities`
필드에 함께 반환합니다. label 은 **반드시 아래 schema 안의 한국어 라벨** 중에서만
선택하세요. 새 라벨을 만들지 마세요.

엔티티 라벨 목록 (정확히 이 표기 사용):
{_build_entity_types_block()}

규칙:
- 본문에 명시되지 않은 엔티티는 추측해 만들지 않음 (extract from text only)
- text 는 본문에서 등장한 표면 형태 그대로 (정규화 X)
- 엔티티가 없으면 빈 리스트 `[]` 로
- 중복은 제거 (같은 (label, text) 한 번만)

예시 (보이스피싱 청크):

입력 turn:
"네, 검찰청 김민수 수사관입니다. 본인 명의로 개설된 계좌가 범죄에 사용됐는데요."

추출:
[
  {{"label": "사칭 기관명", "text": "검찰청"}},
  {{"label": "사람 이름", "text": "김민수"}},
  {{"label": "직함 또는 직책", "text": "수사관"}}
]

**최종 출력 형식 — JSON 배열만**:
[
  {{
    "speaker": "상대방",
    "text": "...",
    "entities": [{{"label": "...", "text": "..."}}, ...]
  }},
  ...
]"""


@dataclass
class TurnEntity:
    label: str  # 추출기 엔티티 schema 의 한국어 라벨
    text: str   # 본문에서 등장한 그대로


@dataclass
class Turn:
    speaker: str  # "상대방" | "본인"
    text: str
    entities: list[TurnEntity] | None = None  # with_entities=True 일 때만 채워짐


_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise EnvironmentError("ANTHROPIC_API_KEY가 설정되지 않았습니다.")
        _client = anthropic.Anthropic(api_key=api_key)
    return _client


def _model_name(model: str | None = None) -> str:
    """model 인자 우선 → ANTHROPIC_DIARIZE_MODEL env → ANTHROPIC_HAIKU_MODEL env → DEFAULT_MODEL."""
    if model:
        return model
    return (
        os.getenv("ANTHROPIC_DIARIZE_MODEL")
        or os.getenv("ANTHROPIC_HAIKU_MODEL")
        or DEFAULT_MODEL
    )


def _parse_json_array(raw: str) -> list[dict[str, Any]]:
    text = re.sub(r"```(?:json)?\s*", "", raw).strip().rstrip("`").strip()
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    # fallback — 첫 [ ... ] 블록 추출
    match = re.search(r"\[[\s\S]*\]", text)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
    return []


def _normalize_entities(raw_entities: Any, allowed_labels: set[str] | None) -> list[TurnEntity]:
    if not isinstance(raw_entities, list):
        return []
    out: list[TurnEntity] = []
    seen: set[tuple[str, str]] = set()
    for e in raw_entities:
        if not isinstance(e, dict):
            continue
        label = str(e.get("label", "")).strip()
        text = str(e.get("text", "")).strip()
        if not label or not text:
            continue
        if allowed_labels is not None and label not in allowed_labels:
            continue  # schema 외 라벨 거름 — Sonnet 이 새 라벨 만든 경우
        key = (label, text)
        if key in seen:
            continue
        seen.add(key)
        out.append(TurnEntity(label=label, text=text))
    return out


def _is_hallucinated(input_text: str, turns: list[Turn], threshold: float = 0.85) -> bool:
    """Sonnet 이 본문에 없는 텍스트를 만들어냈는지 검출.

    diarization 은 본문을 화자별로 *나누기만* 해야 하고, 새 텍스트를 *생성하면 안 됨*.
    출력 turn 들의 모든 단어 (2자 이상) 중 입력에 등장하는 비율이 threshold 미만이면
    hallucination 으로 판정 → 단일 turn fallback.
    """
    def tokenize(s: str) -> list[str]:
        return [w for w in re.findall(r"\w+", s) if len(w) >= 2]

    input_words = set(tokenize(input_text))
    output_words: list[str] = []
    for t in turns:
        output_words.extend(tokenize(t.text))
    if not output_words:
        return False
    in_input = sum(1 for w in output_words if w in input_words)
    coverage = in_input / len(output_words)
    return coverage < threshold


def _allowed_entity_labels() -> set[str]:
    from pipeline.config import BASE_LABELS, DEFAULT_LABEL_SETS
    allowed: set[str] = set(BASE_LABELS)
    for labels in DEFAULT_LABEL_SETS.values():
        allowed.update(labels)
    return allowed


def _normalize_turns(raw_turns: list[dict[str, Any]], with_entities: bool = False) -> list[Turn]:
    out: list[Turn] = []
    allowed = _allowed_entity_labels() if with_entities else None
    for t in raw_turns:
        speaker = str(t.get("speaker", "")).strip()
        text = str(t.get("text", "")).strip()
        if not text:
            continue
        if speaker not in {"상대방", "본인"}:
            speaker = "상대방"  # 안전한 fallback
        entities = _normalize_entities(t.get("entities"), allowed) if with_entities else None
        out.append(Turn(speaker=speaker, text=text, entities=entities))
    return out


def diarize(
    text: str,
    model: str | None = None,
    with_entities: bool = False,
) -> list[Turn]:
    """전사문을 받아 상대방/본인 두 화자로 분리된 turn 리스트 반환.

    - text 가 빈 문자열이면 빈 리스트
    - text 가 30자 미만이면 짧으니까 그냥 상대방 한 turn 으로 처리 (LLM 호출 X)
    - 그 외 Claude (기본 Haiku, model 인자로 override 가능) 호출.
      실패 시 단일 turn fallback.
    - `with_entities=True` 면 각 turn 에 추출기 schema 기반 엔티티도 추출 (Sonnet 권장).
    """
    stripped = (text or "").strip()
    if not stripped:
        return []
    if len(stripped) < 30:
        return [Turn(speaker="상대방", text=stripped, entities=[] if with_entities else None)]

    body = stripped[:MAX_INPUT_CHARS]
    model = _model_name(model)
    system_prompt = _entities_system_prompt() if with_entities else _SYSTEM_PROMPT
    try:
        client = _get_client()
        t0 = time.time()
        message = client.messages.create(
            model=model,
            max_tokens=4000 if with_entities else 3000,
            system=system_prompt,
            messages=[{"role": "user", "content": body}],
        )
        elapsed = time.time() - t0
        raw = message.content[0].text if message.content else ""

        # 비용 ledger 기록
        try:
            from platform_layer import cost as _cost
            _cost.record_claude(
                model,
                int(getattr(message.usage, "input_tokens", 0) or 0),
                int(getattr(message.usage, "output_tokens", 0) or 0),
                action="diarize.split",
            )
        except Exception:
            pass

        turns = _normalize_turns(_parse_json_array(raw), with_entities=with_entities)
        LOG.info(
            "[Diarize] %d turns, %.2fs (chars=%d, model=%s, entities=%s)",
            len(turns), elapsed, len(body), model, with_entities,
        )

        if not turns:
            LOG.warning("[Diarize] 파싱 결과 0 turns — raw 응답: %r", raw[:300])
            return [Turn(speaker="상대방", text=stripped, entities=[] if with_entities else None)]

        # Hallucination 검출 — Sonnet 이 본문에 없는 발화를 만들었으면 reject
        if _is_hallucinated(stripped, turns):
            LOG.warning(
                "[Diarize] hallucination 검출 (출력이 본문 단어 coverage 미달) — 단일 turn fallback"
            )
            return [Turn(speaker="상대방", text=stripped, entities=[] if with_entities else None)]

        # 안전망: 본문 150자 이상인데 모든 turn 이 같은 화자면 양방향 통화 패턴
        # 인식 실패 가능성. retry 하되 fabrication 압박은 없는 약한 retry.
        unique_speakers = {t.speaker for t in turns}
        if len(stripped) > 150 and len(unique_speakers) == 1:
            LOG.info(
                "[Diarize] 단일 화자 결과 — soft retry (fabrication 금지)",
            )
            retry = _retry_with_emphasis(client, model, body, system_prompt, with_entities)
            # retry 결과도 hallucination 검증
            if retry and not _is_hallucinated(stripped, retry):
                LOG.info("[Diarize] retry → %d turns", len(retry))
                return retry
            elif retry:
                LOG.warning("[Diarize] retry 도 hallucinate — 원본 단일 turn 유지")

        return turns
    except Exception as exc:  # noqa: BLE001 — 화자 분리 실패해도 전사 자체는 살아야
        LOG.warning("[Diarize] 실패 → 단일 turn fallback: %s", exc)
        return [Turn(speaker="상대방", text=stripped, entities=[] if with_entities else None)]


def _retry_with_emphasis(
    client,
    model: str,
    body: str,
    system_prompt: str,
    with_entities: bool,
) -> list[Turn] | None:
    """단일 화자만 반환됐을 때 더 강한 압박으로 재시도."""
    retry_user = (
        "위 전사문이 두 사람의 통화로 보입니다. 다시 보면서 본인(받은 사람) 의 짧은 응답 "
        "(예: '네', '예?', '맞습니다', '모르겠는데요', 짧은 질문) 이 **본문 안에 있다면** "
        "찾아서 분리해주세요.\n\n"
        "⚠️ 그러나 **본문에 없는 발화는 절대 만들지 마세요**. 본인 turn 이 찾기 어려우면 "
        "그냥 전부 '상대방' 으로 두는 게 낫습니다 — 가짜 발화를 추가하지 마세요. "
        "이어붙이면 원본과 단어 단위로 동일해야 합니다.\n\n"
        f"전사문:\n{body}\n\n"
        "다시 JSON 배열로만 출력:"
    )
    try:
        message = client.messages.create(
            model=model,
            max_tokens=4000 if with_entities else 3000,
            system=system_prompt,
            messages=[{"role": "user", "content": retry_user}],
        )
        try:
            from platform_layer import cost as _cost
            _cost.record_claude(
                model,
                int(getattr(message.usage, "input_tokens", 0) or 0),
                int(getattr(message.usage, "output_tokens", 0) or 0),
                action="diarize.retry",
            )
        except Exception:
            pass
        raw = message.content[0].text if message.content else ""
        turns = _normalize_turns(_parse_json_array(raw), with_entities=with_entities)
        if turns and len({t.speaker for t in turns}) > 1:
            return turns
    except Exception as exc:  # noqa: BLE001
        LOG.warning("[Diarize] retry 실패: %s", exc)
    return None


def turns_to_dict(turns: list[Turn]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for t in turns:
        item: dict[str, Any] = {"speaker": t.speaker, "text": t.text}
        if t.entities is not None:
            item["entities"] = [{"label": e.label, "text": e.text} for e in t.entities]
        out.append(item)
    return out
