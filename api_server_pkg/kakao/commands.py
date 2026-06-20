"""카카오 webhook 의 시스템 명령 / 결과 요청 / 어뷰즈 안내 / 에러 분류 헬퍼.

테스트 호환을 위해 `_is_system_command`, `_wrap_with_soft_warning` 이름은 유지.
"""

from __future__ import annotations

from pipeline import kakao_formatter

# 사용자 발화 중 "그냥 분석 결과만 보내줘" 류로 컨텍스트 수집을 강제 종료할 신호
_KAKAO_SKIP_PHRASES = {
    "그냥 분석결과 보내줘",
    "그냥 분석",
    "그만 묻고 분석",
    "건너뛰기",
    "스킵",
    "skip",
}

_RESULT_REQUEST_EXACT = {
    "결과확인", "결과 확인", "결과", "확인",
}
_RESULT_REQUEST_SUBSTRINGS = (
    "결과확인", "결과 확인",
    "결과 알려", "결과알려", "결과 좀", "결과좀",
    "결과 보여", "결과보여", "결과 받", "결과받",
    "결과 봐", "결과봐", "결과 줘", "결과줘",
    "분석 다됐", "분석다됐", "분석 됐어", "분석됐어",
    "분석 끝", "분석끝", "분석 결과", "분석결과",
    "다 됐어", "다됐어", "다 끝났",
)


def _is_result_request(text: str) -> bool:
    """사용자 발화가 결과 요청인지 판별. '결과확인' 외에 자연 표현도 폭넓게 인식."""
    s = (text or "").strip()
    if not s:
        return False
    if s in _RESULT_REQUEST_EXACT:
        return True
    return any(p in s for p in _RESULT_REQUEST_SUBSTRINGS)


# 시스템 명령어 — 짧지만 분석 의도가 분명하므로 어뷰즈 소프트 트래커에서 제외해야 한다.
# (결과확인 4자, 사용법 3자 등이 SOFT_LEN_THRESHOLD=10 미만이라 위반으로 잘못 카운트되던 버그 방지)
_SYSTEM_COMMAND_EXACT = {
    "사용법", "도움말", "help", "?",
    "분석 초기화", "초기화", "리셋", "reset",
    "apk 분석", "apk분석", "앱 분석", "앱분석",
    "보이스 분석", "보이스분석", "음성 분석", "음성분석",
    "콘텐츠 분석", "콘텐츠분석", "컨텐츠 분석", "컨텐츠분석",
}

_MODE_GUIDE_COMMANDS: dict[str, tuple[str, ...]] = {
    "apk": (
        "apk분석", "apk 분석", "앱분석", "앱 분석",
    ),
    "voice": (
        "보이스분석", "보이스 분석", "음성분석", "음성 분석",
    ),
    "content": (
        "콘텐츠분석", "콘텐츠 분석", "컨텐츠분석", "컨텐츠 분석",
    ),
}

_LIVE_SESSION_COMMANDS: tuple[str, ...] = (
    "라이브보이스피싱",
    "라이브 보이스피싱",
    "실시간보이스피싱",
    "실시간 보이스피싱",
    "라이브피싱",
    "라이브 피싱",
)


def _mode_guide_command(text: str) -> str | None:
    """모드별 빠른 가이드 명령어인지 판별.

    Returns:
        "apk" | "voice" | "content" | None
    """
    s = (text or "").strip().lower().replace(" ", "")
    if not s:
        return None
    for mode, variants in _MODE_GUIDE_COMMANDS.items():
        if s in {v.lower().replace(" ", "") for v in variants}:
            return mode
    return None


def _live_session_command(text: str) -> bool:
    """라이브 보이스피싱 전용 세션 진입 명령인지 판별."""
    s = (text or "").strip().lower().replace(" ", "")
    if not s:
        return False
    return s in {v.lower().replace(" ", "") for v in _LIVE_SESSION_COMMANDS}


def _is_system_command(text: str) -> bool:
    """결과확인/사용법/초기화/스킵 같은 시스템 명령어인지 — 어뷰즈 트래커 우회용."""
    s = (text or "").strip()
    if not s:
        return False
    if s in _SYSTEM_COMMAND_EXACT:
        return True
    if s in _KAKAO_SKIP_PHRASES:
        return True
    if _mode_guide_command(s) is not None:
        return True
    if _live_session_command(s):
        return True
    return _is_result_request(s)


def _wrap_with_soft_warning(response: dict, info: dict | None) -> dict:
    """짧은 메시지 누적 위반 시 응답 최상단에 경고 simpleText 부착.

    첫 번째(count=1) 는 무시 — 정상 인사로 통과시킴.
    두 번째(count>=2) 부터 경고 prepend.
    """
    if not info or info.get("count", 0) < 2 or info.get("blocked"):
        return response
    from platform_layer import abuse_guard as _ag
    count = info["count"]
    limit = _ag.VIOLATION_WARN_LIMIT
    warn = {
        "simpleText": {
            "text": (
                f"⚠️ 짧은 메시지가 반복되고 있어요 ({count}/{limit}).\n"
                "분석할 의심 메시지·URL·문서를 보내주세요. 누적 시 일시 차단됩니다."
            )
        }
    }
    response.setdefault("template", {}).setdefault("outputs", []).insert(0, warn)
    return response


def _classify_error(exc: Exception) -> kakao_formatter.ErrorCode:
    """예외 종류에 따라 적절한 ErrorCode를 반환한다."""
    EC = kakao_formatter.ErrorCode
    msg = str(exc).lower()
    if "api" in msg and ("credit" in msg or "quota" in msg or "limit" in msg):
        return EC.API_CREDIT
    if "connection" in msg or "connect" in msg or "unreachable" in msg:
        return EC.SERVER_DOWN
    if "stt" in msg or "whisper" in msg or "audio" in msg or "transcri" in msg:
        return EC.STT_FAIL
    if "timeout" in msg or "timed out" in msg:
        return EC.TIMEOUT
    if "memory" in msg or "llm" in msg or "anthropic" in msg:
        return EC.LLM_UNAVAILABLE
    if "empty" in msg or "비어" in msg:
        return EC.EMPTY_INPUT
    return EC.UNKNOWN
