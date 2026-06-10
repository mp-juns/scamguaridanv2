"""
ScamGuardian — 카카오 오픈빌더 응답 포맷터 (facade)

구현은 두 모듈로 분리됨:
- pipeline.kakao_result — 검출 결과 카드 + 에러 (Identity Boundary: 점수·등급 X)
- pipeline.kakao_dialog — 대화 흐름 / 폴링 / 시스템 메시지

외부 소비자(api_server_pkg/kakao/*, result_token, 테스트)는 기존처럼
`pipeline.kakao_formatter` 경로로 모든 심볼에 접근한다.
https://i.kakao.com/docs/skill-response-format
"""

from __future__ import annotations

from pipeline.kakao_result import (  # noqa: F401
    InputType,
    ErrorCode,
    quick_replies,
    format_result,
    format_error,
    _ERROR_MESSAGES,
    _DISCLAIMER_TEXT,
    _PHASES_WITH_RESULT_CHECK,
    _detection_icon,
    _truncate,
    _entity_lines,
    _signal_lines,
    _build_result_card,
    _build_uncertain_text,
    _build_user_context_block,
    _build_safety_warning_block,
)
from pipeline.kakao_dialog import (  # noqa: F401
    format_analyzing,
    format_queued,
    format_still_running,
    format_no_job,
    format_ask_for_content,
    format_reset,
    format_welcome,
    format_help,
    format_question,
    format_context_done_waiting,
    format_result_ready_announce,
    format_refining_in_progress,
    format_abuse_warning,
    format_abuse_blocked,
    format_busy,
    _humanize_duration,
    _polling_progress_lines,
)
