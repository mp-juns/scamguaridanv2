"""
입력 어뷰즈 방어 — Claude API 무임승차/과사용 차단.

ScamGuardian 의 분석 엔드포인트는 호출당 Claude(분석+요약) + Whisper/Vision +
Serper + VT 비용이 드는데, 정상 라벨 분석이 아닌 잡담·도배·악의적 긴 입력은
무료 LLM 통로로 악용될 수 있다. 외부 API 호출 *전* 단계에서 차단.

가드 단계:
1. 길이 cap — max 5000자 / min 10자 (한국어 기준 토큰 ~1500-2500)
2. 반복 detection — 단일 문자·짧은 패턴이 80% 이상이면 의미 없는 입력
3. gibberish — 한국어 음절·영문·숫자 비율이 너무 낮으면 거부
4. duplicate — 같은 텍스트 같은 키 5분 내 N번 반복 시 throttle (in-memory)

이 모듈은 *외부 API 호출 0회* 로 동작 — 가드 자체가 비용을 만들면 의미 없음.
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any


MAX_CHARS = int(os.getenv("ANALYZE_MAX_TEXT_LENGTH", "5000"))
MIN_CHARS = int(os.getenv("ANALYZE_MIN_TEXT_LENGTH", "2"))   # "안녕" 정도는 허용
REPETITION_MIN_LEN = 8         # 이 길이 이상에서만 다양성 체크 (짧은 인사 보호)
REPETITION_TOP3_RATIO = 0.80   # 상위 3 글자 비율
GIBBERISH_VALID_RATIO = 0.50   # 의미 있는 글자 비율 minimum
DUP_WINDOW_SEC = 300           # 5분
DUP_LIMIT = 5                  # 같은 입력 같은 키 5분에 5번 이상 → throttle

# 위반 누적 → 자동 블록 — user_id 가 식별 가능할 때만 적용 (카카오 user.id 등)
VIOLATION_WINDOW_SEC = int(os.getenv("ABUSE_VIOLATION_WINDOW", "3600"))   # 1시간
VIOLATION_WARN_LIMIT = int(os.getenv("ABUSE_WARN_LIMIT", "3"))             # 3회까지 경고
BLOCK_DURATION_SEC = int(os.getenv("ABUSE_BLOCK_DURATION", "3600"))        # 1시간 차단

# Soft 트래커 — "안녕" 같이 통과는 시키되 반복되면 위반으로 카운트하는 임계값.
# 분석 가치가 거의 없는 짧은 메시지(인사·잡담)가 Claude/Haiku 호출을 반복 유발하는 걸 막음.
SOFT_LEN_THRESHOLD = int(os.getenv("ABUSE_SOFT_THRESHOLD", "10"))


_HANGUL_RE = re.compile(r"[가-힣]")
_LATIN_DIGIT_RE = re.compile(r"[A-Za-z0-9]")

# ──────────────────────────────────
# 프롬프트 인젝션(우회) 탐지
# ──────────────────────────────────
# 분석 대상 텍스트가 *분석기 자신(LLM)* 을 조종하려는 메타-지시를 담고 있으면 차단.
# ⚠️ 실제 사기 문자도 "이전 안내는 무시하세요" 류 표현을 쓰므로, 일반 "무시"가 아니라
#    AI/시스템 프롬프트·역할을 겨냥한 패턴만 매칭 (오탐 최소화).
_INJECTION_PATTERNS = [
    # 한국어 — '프롬프트/지시/명령' 을 '무시/잊어/덮어써'
    r"(?:기존|이전|위(?:의)?|모든|시스템)?\s*(?:프롬프트|지시(?:사항)?|명령(?:어)?|규칙)\s*(?:을|를|은|는|들)?\s*(?:전부|모두|싹)?\s*(?:무시|잊어|잊고|덮어|초기화|리셋)",
    r"시스템\s*프롬프트",
    r"(?:지금|이제)\s*부터\s*(?:너|네|당신|챗봇|ai|assistant)\s*(?:는|은|를)?",   # "지금부터 너는 ~"
    r"(?:너|네|당신)\s*(?:는|은)\s*이제(?:부터)?",
    r"(?:역할|규칙|제약|설정)\s*(?:을|를)?\s*(?:잊|무시|벗어)",
    # English
    r"ignore\s+(?:all\s+|the\s+)?(?:previous|prior|above|earlier|preceding)\s+(?:instructions?|prompts?|messages?|rules?|context)",
    r"disregard\s+(?:all\s+|the\s+)?(?:previous|prior|above|system)",
    r"forget\s+(?:everything|all|your|the\s+previous)\b.*?(?:instruction|prompt|rule)?",
    r"(?:system\s*prompt|developer\s*mode|jailbreak|dan\s*mode)",
    r"you\s+are\s+now\s+(?:a|an|the)\b",
    r"(?:act|pretend|behave)\s+as\s+(?:if\s+)?(?:you|an|a)\b",
    r"override\s+(?:the\s+)?(?:system|previous|safety)",
]
_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)


def detect_prompt_injection(text: str | None) -> bool:
    """텍스트에 프롬프트 우회/주입 시도가 있으면 True."""
    if not text:
        return False
    return _INJECTION_RE.search(text) is not None


def force_block(user_id: str, *, duration_sec: int = BLOCK_DURATION_SEC) -> None:
    """user_id 를 즉시 차단(누적 무관). 프롬프트 인젝션 등 즉시 제한용."""
    if not user_id:
        return
    with _violation_lock:
        _blocks[user_id] = time.time() + duration_sec


@dataclass
class GuardReject:
    code: str           # MIN_LEN / MAX_LEN / REPETITIVE / GIBBERISH / DUPLICATE / EMPTY
    message: str
    detail: str = ""


_dup_lock = threading.Lock()
_dup_log: dict[str, list[float]] = defaultdict(list)

_violation_lock = threading.Lock()
_violations: dict[str, list[float]] = defaultdict(list)
_blocks: dict[str, float] = {}   # user_id → block_until_epoch


def _signature(text: str, key_id: str | None) -> str:
    h = hashlib.sha256()
    h.update((key_id or "anon").encode())
    h.update(b"::")
    h.update(text.strip().encode("utf-8"))
    return h.hexdigest()


def _check_duplicate(text: str, key_id: str | None) -> GuardReject | None:
    sig = _signature(text, key_id)
    now = time.time()
    cutoff = now - DUP_WINDOW_SEC
    with _dup_lock:
        log = _dup_log[sig]
        log[:] = [t for t in log if t > cutoff]
        if len(log) >= DUP_LIMIT:
            wait = max(1, int(DUP_WINDOW_SEC - (now - log[0]) + 0.5))
            return GuardReject(
                "DUPLICATE",
                "동일한 입력이 짧은 시간에 여러 번 반복됐어요. 잠시 후 다시 시도해 주세요.",
                detail=f"5분 내 {DUP_LIMIT}회 초과, 약 {wait}초 후 재시도 가능",
            )
        log.append(now)
    return None


def check(text: str, *, key_id: str | None = None, dedup: bool = True) -> GuardReject | None:
    """입력 분석 전에 호출. 거부 사유 있으면 GuardReject, 통과면 None."""
    if text is None:
        return GuardReject("EMPTY", "입력이 비어 있습니다.")
    stripped = text.strip()
    if not stripped:
        return GuardReject("EMPTY", "입력이 비어 있습니다.")

    n = len(stripped)
    if n < MIN_CHARS:
        return GuardReject(
            "MIN_LEN",
            f"입력이 너무 짧아요. 최소 {MIN_CHARS}자 이상 보내주세요.",
            detail=f"length={n}",
        )
    if n > MAX_CHARS:
        return GuardReject(
            "MAX_LEN",
            f"입력이 너무 길어요. 최대 {MAX_CHARS}자까지만 분석합니다 (현재 {n:,}자).",
            detail=f"length={n}",
        )

    # 반복 / 도배 검출 — 짧은 인사("안녕", "고마워" 등)는 길이 미달로 skip
    no_space = re.sub(r"\s", "", stripped)
    if len(no_space) >= REPETITION_MIN_LEN:
        counter = Counter(no_space)
        if len(counter) <= 3:
            # 거의 한 두 글자만 반복
            return GuardReject(
                "REPETITIVE",
                "의미 있는 분석 대상으로 보이지 않아요. 의심되는 메시지·URL·문서를 보내주세요.",
                detail=f"unique_chars={len(counter)}",
            )
        top3_sum = sum(c for _, c in counter.most_common(3))
        if top3_sum / len(no_space) > REPETITION_TOP3_RATIO:
            return GuardReject(
                "REPETITIVE",
                "반복 문자 비율이 너무 높아요. 분석할 내용을 다시 확인해 주세요.",
                detail=f"top3_ratio={top3_sum / len(no_space):.2f}",
            )

    # 의미 글자 비율 — 한국어/영어/숫자 비율이 너무 낮으면 (이모지/특수기호만) 거부
    valid = len(_HANGUL_RE.findall(stripped)) + len(_LATIN_DIGIT_RE.findall(stripped))
    if valid / max(1, len(stripped)) < GIBBERISH_VALID_RATIO:
        return GuardReject(
            "GIBBERISH",
            "분석 가능한 문자가 거의 없어요. 한국어·영문 텍스트로 다시 보내주세요.",
            detail=f"valid_ratio={valid / max(1, len(stripped)):.2f}",
        )

    # 동일 입력 도배
    if dedup:
        rej = _check_duplicate(stripped, key_id)
        if rej is not None:
            return rej

    return None


def reset_state() -> None:
    """테스트용 — duplicate / violation / block 모두 초기화."""
    with _dup_lock:
        _dup_log.clear()
    with _violation_lock:
        _violations.clear()
        _blocks.clear()


# ──────────────────────────────────
# 위반 누적 → 자동 블록
# ──────────────────────────────────
def block_status(user_id: str) -> tuple[bool, int]:
    """현재 user_id 가 블록 상태인지. 반환은 (blocked, remaining_seconds)."""
    if not user_id:
        return False, 0
    now = time.time()
    with _violation_lock:
        until = _blocks.get(user_id)
        if until is None:
            return False, 0
        if now >= until:
            _blocks.pop(user_id, None)
            return False, 0
        return True, int(until - now)


def violation_count(user_id: str) -> int:
    """현재 윈도우 내 위반 횟수."""
    if not user_id:
        return 0
    now = time.time()
    cutoff = now - VIOLATION_WINDOW_SEC
    with _violation_lock:
        log = _violations.get(user_id, [])
        return sum(1 for t in log if t > cutoff)


def record_violation(user_id: str) -> dict[str, Any]:
    """위반 기록. 임계값 초과 시 block 으로 전환.

    Returns:
        {"count": N, "warns_left": M, "blocked": bool, "block_remaining_sec": int}
    """
    if not user_id:
        return {"count": 0, "warns_left": VIOLATION_WARN_LIMIT, "blocked": False, "block_remaining_sec": 0}

    now = time.time()
    cutoff = now - VIOLATION_WINDOW_SEC
    with _violation_lock:
        log = _violations[user_id]
        log[:] = [t for t in log if t > cutoff]
        log.append(now)
        count = len(log)
        if count > VIOLATION_WARN_LIMIT:
            _blocks[user_id] = now + BLOCK_DURATION_SEC
            return {
                "count": count,
                "warns_left": 0,
                "blocked": True,
                "block_remaining_sec": BLOCK_DURATION_SEC,
            }
    return {
        "count": count,
        "warns_left": max(0, VIOLATION_WARN_LIMIT - count),
        "blocked": False,
        "block_remaining_sec": 0,
    }


def unblock(user_id: str) -> bool:
    """어드민 수동 해제."""
    with _violation_lock:
        was_blocked = user_id in _blocks
        _blocks.pop(user_id, None)
        _violations.pop(user_id, None)
    return was_blocked


def track_short_message(user_id: str, text: str) -> dict[str, Any] | None:
    """`SOFT_LEN_THRESHOLD` 미만 짧은 메시지 누적 트래커.

    - user_id 없거나 text 가 임계값 이상이면 None (no-op)
    - 짧은 메시지면 record_violation 호출 → 위반 +1
    - 임계 초과 시 자동 블록 (record_violation 내부에서 처리)

    호출자는 반환값으로 상태 판단:
      - None: 트래킹 안 됨 (충분히 긴 메시지 등)
      - {blocked: True}: 블록됨 → 채팅 종료
      - {blocked: False, count >= 1}: 응답에 경고 부착 권장
    """
    if not user_id or not text:
        return None
    if len(text.strip()) > SOFT_LEN_THRESHOLD:
        return None
    info = record_violation(user_id)
    info["soft"] = True
    return info


def list_blocks() -> list[dict[str, Any]]:
    now = time.time()
    out: list[dict[str, Any]] = []
    with _violation_lock:
        # 만료 정리
        expired = [uid for uid, until in _blocks.items() if until <= now]
        for uid in expired:
            _blocks.pop(uid, None)
        for uid, until in _blocks.items():
            out.append({
                "user_id": uid,
                "block_remaining_sec": int(until - now),
                "violations": len(_violations.get(uid, [])),
            })
    return out


# ──────────────────────────────────
# 종합 가드 — 블록 체크 + 위반 기록
# ──────────────────────────────────
def guard(text: str, *, key_id: str | None = None, user_id: str | None = None) -> GuardReject | None:
    """check() 위에 위반 누적·블록 적용.

    user_id 가 주어지면:
    - 이미 블록 상태면 BLOCKED reject (3회 위반 후 1시간)
    - check() 가 reject 하면 record_violation 호출
    """
    if user_id:
        blocked, remaining = block_status(user_id)
        if blocked:
            return GuardReject(
                "BLOCKED",
                "반복적인 어뷰즈로 일시 차단되었어요. 잠시 후 다시 시도해 주세요.",
                detail=f"remaining_sec={remaining}",
            )

    rej = check(text, key_id=key_id)
    if rej is None:
        return None

    if user_id:
        info = record_violation(user_id)
        if info["blocked"]:
            return GuardReject(
                "BLOCKED",
                "어뷰즈 횟수가 누적되어 일시 차단되었어요. 1시간 후 다시 시도해 주세요.",
                detail=f"count={info['count']} block={info['block_remaining_sec']}s",
            )
        # 일반 reject 메시지에 남은 경고 횟수 부착
        rej.message = (
            f"{rej.message}\n경고 {info['count']}/{VIOLATION_WARN_LIMIT} — 누적 시 일시 차단됩니다."
        )

    return rej
