"""
ScamGuardian — STT 백엔드: Naver CLOVA Speech

한국어 STT + audio-based 화자 분리 (STT_BACKEND=clova).
역할 배정(상대방/본인)은 내용 기반 LLM 1차 + 발화량 휴리스틱 fallback.
외부 소비자는 `pipeline.stt` facade 를 통해 import 한다.
"""

from __future__ import annotations

import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Callable

from pipeline.stt_common import _probe_audio_seconds


def _label_durations(segments: list[dict]) -> dict[str, float]:
    """speaker_label → 발화 시간 총합(초)."""
    durations: dict[str, float] = {}
    for seg in segments:
        label = str(seg.get("speaker_label", "")).strip()
        if not label:
            continue
        durations[label] = durations.get(label, 0.0) + float(
            seg.get("end", 0.0) - seg.get("start", 0.0)
        )
    return durations


def _label_texts(segments: list[dict]) -> dict[str, list[str]]:
    """speaker_label → 발화 텍스트 목록 (시간순)."""
    texts: dict[str, list[str]] = {}
    for seg in segments:
        label = str(seg.get("speaker_label", "")).strip()
        text = (seg.get("text", "") or "").strip()
        if not label or not text:
            continue
        texts.setdefault(label, []).append(text)
    return texts


def _duration_role_map(durations: dict[str, float]) -> dict[str, str]:
    """fallback 휴리스틱: 발화 시간 총합 가장 긴 화자 = 상대방, 나머지 = 본인."""
    if not durations:
        return {}
    longest = max(durations, key=lambda k: durations[k])
    return {label: ("상대방" if label == longest else "본인") for label in durations}


_CLOVA_ROLE_SYSTEM_PROMPT = (
    "당신은 한국어 통화 녹취의 두 화자에게 역할을 배정합니다. 각 화자의 발화 모음을 보고 "
    "누가 '전화를 건 사람(상대방)' 이고 누가 '전화를 받은 사람(본인)' 인지 판정하세요.\n\n"
    "**판정 기준 (우선순위 순)**:\n"
    "1. **통화 도입부를 가장 중시하세요.** 앞부분에서 먼저 용건을 꺼내고 기관"
    "(검찰/경찰/금감원/은행)을 사칭하며 정보를 길게 제공하고 지시하는 쪽이 '상대방' 입니다. "
    "이 역할은 통화 내내 고정입니다 — 이후 본인이 더 많이 말하거나 길게 답해도 역할은 "
    "**절대 바뀌지 않습니다**.\n"
    "2. 상대방(전화 건 사람): 권위적·명령조·기관 사칭·반복 지시·먼저 용건을 꺼냄.\n"
    "3. 본인(전화 받은 사람): 짧게 되묻기·의심·순응. 예: '네', '뭔데요?', "
    "'…말씀이신가요?', '아 네 알겠습니다'.\n\n"
    "발화량(초)은 동점일 때만 쓰는 약한 보조 단서입니다 — **항상 내용(도입부·권위·지시)을 "
    "우선**하세요. 발화량으로 역할을 뒤집지 마세요.\n\n"
    "반드시 JSON 객체 하나만 출력하세요. 키는 화자 번호만(예: \"1\", \"2\"), 값은 역할:\n"
    '{"1": "상대방", "2": "본인"}\n'
    "설명·코드블록 없이 JSON 만 출력."
)

_ROLE_TEXT_CAP = 2000  # 화자별 발화 prompt 길이 상한 (토큰 bound)


def _parse_role_map(raw: str, expected_labels: set[str]) -> dict[str, str] | None:
    """LLM 응답에서 {label: role} 객체 파싱 + 검증.

    유효 조건: expected_labels 전부 포함 + 역할 값이 정확히 {상대방, 본인} 1:1.
    하나라도 어긋나면 None (→ 호출부에서 duration fallback).
    """
    import json as _json

    text = re.sub(r"```(?:json)?\s*", "", raw or "").strip().rstrip("`").strip()
    data: Any = None
    try:
        data = _json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                data = _json.loads(m.group(0))
            except Exception:
                data = None
    if not isinstance(data, dict):
        return None

    def _norm_key(k: Any) -> str:
        # "화자 1" / "speaker 1" / "1" 모두 "1" 로 정규화
        s = re.sub(r"^\s*(화자|speaker)\s*", "", str(k).strip(), flags=re.IGNORECASE)
        return s.strip()

    mapping = {_norm_key(k): str(v).strip() for k, v in data.items()}
    if set(mapping.keys()) != expected_labels:
        return None
    roles = list(mapping.values())
    if sorted(roles) != ["본인", "상대방"]:  # 정확히 한 명씩
        return None
    return mapping


def _assign_clova_roles(segments: list[dict]) -> dict[str, str]:
    """CLOVA speaker_label → 상대방/본인 매핑.

    1차: 내용 기반 LLM(Haiku) — 권위·명령·정보제공 화자=상대방, 순응·되묻기=본인.
    CLOVA 의 segment 분리·텍스트는 그대로 두고 *역할 딱지만* 결정 (텍스트 생성 X → 환각 없음).
    실패·비활성·화자 수 != 2 시 duration 휴리스틱 fallback.
    `CLOVA_ROLE_ASSIGN=duration` 으로 LLM 끄기 가능.
    """
    durations = _label_durations(segments)
    if len(durations) <= 1:
        return {label: "상대방" for label in durations}  # 단일 화자 / 모놀로그

    fallback = _duration_role_map(durations)
    mode = os.getenv("CLOVA_ROLE_ASSIGN", "llm").strip().lower()
    if mode != "llm" or len(durations) != 2:
        return fallback

    clova_log = _get_clova_logger()
    texts = _label_texts(segments)
    labels = sorted(durations.keys())
    user_parts: list[str] = []
    for label in labels:
        joined = " ".join(texts.get(label, []))[:_ROLE_TEXT_CAP]
        user_parts.append(f"화자 {label} (발화량 {durations[label]:.0f}초):\n{joined}")
    user_content = "\n\n".join(user_parts) + "\n\n위 두 화자의 역할을 JSON 으로:"

    try:
        from pipeline import diarize as _diarize
        client = _diarize._get_client()
        model = _diarize._model_name(None)  # Haiku 기본
        t0 = time.time()
        message = client.messages.create(
            model=model,
            max_tokens=80,
            temperature=0.0,  # 결정적 — 같은 발화가 누적 윈도우마다 상대방/본인 뒤집히는 flip 제거
            system=_CLOVA_ROLE_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_content}],
        )
        elapsed = time.time() - t0
        raw = message.content[0].text if message.content else ""
        try:
            from platform_layer import cost as _cost
            _cost.record_claude(
                model,
                int(getattr(message.usage, "input_tokens", 0) or 0),
                int(getattr(message.usage, "output_tokens", 0) or 0),
                action="diarize.role_assign",
            )
        except Exception:
            pass
        role_map = _parse_role_map(raw, set(labels))
        if role_map is None:
            clova_log.info(
                "  역할배정: LLM 응답 무효 → duration fallback %s (raw=%r, %.2fs)",
                fallback, (raw or "")[:80], elapsed,
            )
            return fallback
        agree = role_map == fallback
        clova_log.info(
            "  역할배정: LLM %s (duration 휴리스틱 %s, %s, %.2fs)",
            role_map, "일치" if agree else "불일치→LLM 채택", fallback, elapsed,
        )
        return role_map
    except Exception as exc:
        clova_log.info("  역할배정: LLM 실패 → duration fallback %s (%s)", fallback, exc)
        return fallback


def _clova_to_turns(segments: list[dict]) -> list[dict]:
    """CLOVA Speech segments (speaker_label 포함) → 상대방/본인 turn 리스트.

    역할 배정: 내용 기반 LLM(`_assign_clova_roles`, 권위/순응 단서) — 실패 시 발화 시간
    총합 휴리스틱 fallback. 각 turn 에 start_sec / end_sec 도 함께 — frontend 재생용.
    """
    if not segments:
        return []
    role_map = _assign_clova_roles(segments)
    if not role_map:
        # speaker_label 자체가 없음 → 단일 상대방 turn
        joined = " ".join((s.get("text", "") or "").strip() for s in segments).strip()
        if not joined:
            return []
        first_start = float(segments[0].get("start", 0.0)) if segments else 0.0
        last_end = float(segments[-1].get("end", 0.0)) if segments else 0.0
        return [{"speaker": "상대방", "text": joined, "start_sec": first_start, "end_sec": last_end}]
    turns: list[dict] = []
    current_speaker: str | None = None
    current_parts: list[str] = []
    current_start: float = 0.0
    current_end: float = 0.0
    for seg in segments:
        label = str(seg.get("speaker_label", "")).strip()
        text = (seg.get("text", "") or "").strip()
        if not text:
            continue
        speaker = role_map.get(label, "상대방")
        seg_start = float(seg.get("start", 0.0))
        seg_end = float(seg.get("end", 0.0))
        if speaker == current_speaker:
            current_parts.append(text)
            current_end = seg_end
        else:
            if current_speaker is not None and current_parts:
                turns.append({
                    "speaker": current_speaker,
                    "text": " ".join(current_parts),
                    "start_sec": current_start,
                    "end_sec": current_end,
                })
            current_speaker = speaker
            current_parts = [text]
            current_start = seg_start
            current_end = seg_end
    if current_speaker is not None and current_parts:
        turns.append({
            "speaker": current_speaker,
            "text": " ".join(current_parts),
            "start_sec": current_start,
            "end_sec": current_end,
        })
    return turns


_DEFAULT_CLOVA_BOOSTING = (
    "소환장,소환,출석조사,출두,통보,발부,검찰청,경찰청,금융감독원,금감원,"
    "국정원,중앙지검,서울중앙지검,합동수사본부,수사관,검사,사건번호,"
    "대포통장,안전계좌,명의도용,개인정보,증거물,압수,범죄,피의자,참고인,"
    "송금,이체,입금,출금,계좌번호,주민등록번호,비밀번호,OTP,보안카드,인증번호,"
    "피해자,가해자,보이스피싱,사기"
)


_CLOVA_LOGGER: logging.Logger | None = None


def _get_clova_logger() -> logging.Logger:
    """CLOVA 전용 로그 파일 (.scamguardian/logs/clova-kyy.log) 설정."""
    global _CLOVA_LOGGER
    if _CLOVA_LOGGER is not None and _CLOVA_LOGGER.handlers:
        return _CLOVA_LOGGER
    logger = logging.getLogger("pipeline.stt.clova")
    log_path = Path(__file__).resolve().parent.parent / ".scamguardian" / "logs" / "clova-kyy.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(str(log_path), encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s [CLOVA] %(message)s", datefmt="%H:%M:%S"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False  # backend-kyy.log 에 중복 X
    _CLOVA_LOGGER = logger
    return logger


def _transcribe_with_clova(
    audio_path: str,
    logger: Callable[[str], None] | None = None,
    diarize: bool = True,
) -> dict:
    """Naver CLOVA Speech API 로 한국어 STT + audio-based 화자 분리.

    diarize=False 면 상대방/본인 역할 배정(_clova_to_turns → Claude 호출)을 건너뛰고
    전사 텍스트만 반환(turns=[]) — Live 즉시 검출 경로(화자 무관 시그널 스캔)용.

    한 번의 호출로 전사문 + segments + speaker_label 모두 받음 (LLM diarize 불필요).
    응답에 `segments` (각 segment 가 speaker_label 포함) + `turns` (상대방/본인 매핑됨) 포함.

    도메인 어휘 bias 는 `boostings` 파라미터로 적용 (Whisper prompt 와 달리
    hallucination 부작용 없음 — 단어 출력만 가중치, 새 텍스트 생성 X).
    환경변수 CLOVA_BOOSTING_WORDS 로 override.

    모든 호출이 .scamguardian/logs/clova-kyy.log 에 상세 기록 (진단용).
    """
    import json
    import traceback
    import requests

    clova_log = _get_clova_logger()

    invoke_url = os.environ.get("CLOVA_INVOKE_URL", "").strip().rstrip("/")
    secret_key = os.environ.get("CLOVA_SECRET_KEY", "").strip()
    if not invoke_url or not secret_key:
        clova_log.error("env 미설정 — CLOVA_INVOKE_URL/CLOVA_SECRET_KEY 둘 다 필요")
        raise RuntimeError(
            "CLOVA_INVOKE_URL / CLOVA_SECRET_KEY env 미설정 — NCP 콘솔에서 CLOVA Speech 도메인 생성 필요."
        )

    boosting_words = os.environ.get("CLOVA_BOOSTING_WORDS", _DEFAULT_CLOVA_BOOSTING).strip()

    # 요청 시작 로그
    try:
        audio_size = Path(audio_path).stat().st_size
    except Exception:
        audio_size = 0
    audio_duration = _probe_audio_seconds(audio_path)
    clova_log.info("=== 새 요청 ===")
    clova_log.info(
        "  audio: %s (%s bytes, %.1fs)",
        Path(audio_path).name, f"{audio_size:,}", audio_duration,
    )
    clova_log.info("  invoke_url: %s", invoke_url[:60] + "..." if len(invoke_url) > 60 else invoke_url)
    clova_log.info("  boosting: %d 단어", len(boosting_words.split(",")) if boosting_words else 0)

    params: dict = {
        "language": "ko-KR",
        "completion": "sync",
        "wordAlignment": False,
        "fullText": True,
        # 보이스피싱 통화 = 항상 2명 (사기범 + 피해자) 가정
        "diarization": {
            "enable": True,
            "speakerCountMin": 2,
            "speakerCountMax": 2,
        },
    }
    if boosting_words:
        # CLOVA boostings: 도메인 어휘 인식 우선순위 ↑.
        # "소환자" 대신 "소환장" 출력하도록 bias.
        params["boostings"] = [{"words": boosting_words}]

    t0 = time.time()
    try:
        with open(audio_path, "rb") as f:
            files = {
                "media": f,
                "params": (None, json.dumps(params).encode("utf-8"), "application/json"),
            }
            headers = {"X-CLOVASPEECH-API-KEY": secret_key}
            response = requests.post(
                f"{invoke_url}/recognizer/upload",
                files=files,
                headers=headers,
                timeout=300,
            )
        elapsed = time.time() - t0
        clova_log.info("  HTTP %d, elapsed=%.2fs", response.status_code, elapsed)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        elapsed = time.time() - t0
        clova_log.error("  ❌ 실패 (%.2fs): %s: %s", elapsed, type(exc).__name__, exc)
        clova_log.error("  traceback:\n%s", traceback.format_exc())
        raise

    if data.get("result") != "COMPLETED":
        clova_log.error(
            "  ❌ result != COMPLETED: result=%r message=%r",
            data.get("result"), data.get("message"),
        )
        raise RuntimeError(
            f"CLOVA Speech 실패: result={data.get('result')!r} message={data.get('message')!r}"
        )

    # 비용 ledger
    duration = _probe_audio_seconds(audio_path)
    if duration > 0:
        try:
            from platform_layer.cost import record_clova_speech
            record_clova_speech(duration)
        except Exception:
            pass

    full_text = (data.get("text") or "").strip()
    segments_raw = data.get("segments") or []
    segments: list[dict] = []
    for seg in segments_raw:
        speaker_label = ""
        speaker_obj = seg.get("speaker")
        if isinstance(speaker_obj, dict):
            speaker_label = str(speaker_obj.get("label", "")).strip()
        segments.append({
            "start": float(seg.get("start", 0)) / 1000.0,  # CLOVA 는 ms → 초
            "end": float(seg.get("end", 0)) / 1000.0,
            "text": (seg.get("text") or "").strip(),
            "speaker_label": speaker_label,
        })

    # diarize=False (Live 즉시 검출) 면 역할 배정(Claude 호출) 건너뜀 — 텍스트만 스캔.
    turns = _clova_to_turns(segments) if diarize else []

    # 결과 상세 기록
    preview = full_text[:200] + "…" if len(full_text) > 200 else full_text
    clova_log.info(
        "  ✅ 완료: text=%d자, segments=%d개, turns=%d개",
        len(full_text), len(segments), len(turns),
    )
    clova_log.info("  preview: %s", preview)
    # 첫 5 segments (speaker label 확인용)
    for i, seg in enumerate(segments[:5]):
        clova_log.info(
            "  seg[%d]: %.2f-%.2fs label=%s text=%r",
            i, seg["start"], seg["end"], seg.get("speaker_label", "?"),
            seg["text"][:60],
        )
    if len(segments) > 5:
        clova_log.info("  ... (%d more segments)", len(segments) - 5)
    # 전체 turns
    for i, t in enumerate(turns):
        clova_log.info(
            "  turn[%d] %s @ %.2f-%.2fs: %s",
            i, t["speaker"], t.get("start_sec", 0.0), t.get("end_sec", 0.0),
            t["text"][:80],
        )
    clova_log.info("")  # 빈 줄 — 다음 요청과 구분

    if logger:
        logger(
            f"[STT] CLOVA Speech 완료 ({elapsed:.1f}s)\n"
            f"       ← 전사 길이: {len(full_text)}자, segments: {len(segments)}개, turns: {len(turns)}개\n"
            f"       ← 미리보기: {preview}"
        )

    return {
        "text": full_text,
        "language": "ko",
        "segments": segments,
        "turns": turns,
    }
