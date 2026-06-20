"""/webhook/kakao 엔드포인트 — 어뷰즈 가드 → 특수 명령 → 진행 잡 → 신규 입력 디스패치.

구조 분기:
- 어뷰즈 차단 / 짧은 메시지 누적 우선
- 특수 명령(welcome/help/reset/결과확인/스킵)
- 진행 중 job: 답변 처리 / busy
- 신규 입력 + callbackUrl → 단발 callback
- 신규 무거운 입력 → 컨텍스트 수집
- 신규 텍스트 → 의도 분류 후 분기
"""

from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
import secrets
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Request

from pipeline import context_chat, kakao_formatter

from .. import state
from .commands import (
    _KAKAO_SKIP_PHRASES,
    _classify_error,
    _live_session_command,
    _is_result_request,
    _is_system_command,
    _mode_guide_command,
    _wrap_with_soft_warning,
)
from .context_flow import (
    _handle_done_state,
    _kakao_force_skip_context,
    _kakao_handle_context_answer,
    _kakao_start_context_collection,
)
from .detect import _EXECUTABLE_URL_RE, _kakao_detect_input, _kakao_materialize_url
from ..live_session_token import issue_live_session_token
from ..result_token import get_public_base_url
from .tasks import _cleanup_expired_jobs, _kakao_callback_task

router = APIRouter()

_KAKAO_RAW_LOG_PATH = Path(".scamguardian") / "logs" / "kakao_raw.jsonl"
_kakao_raw_logger: logging.Logger | None = None


def _get_kakao_raw_logger() -> logging.Logger:
    global _kakao_raw_logger
    if _kakao_raw_logger is not None:
        return _kakao_raw_logger
    logger = logging.getLogger("kakao_raw")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        _KAKAO_RAW_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            _KAKAO_RAW_LOG_PATH,
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
    _kakao_raw_logger = logger
    return logger


def _dump_kakao_in(
    request: Request,
    raw_bytes: bytes,
    body: dict | None,
    parse_error: bool,
    req_id: str,
) -> None:
    try:
        record: dict = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "req_id": req_id,
            "direction": "in",
            "client": request.client.host if request.client else None,
            "headers": {
                k: v
                for k, v in request.headers.items()
                if k.lower()
                in (
                    "user-agent",
                    "content-type",
                    "x-forwarded-for",
                    "x-forwarded-proto",
                    "x-real-ip",
                    "host",
                )
            },
            "parse_error": parse_error,
        }
        if parse_error or body is None:
            record["raw"] = raw_bytes.decode("utf-8", errors="replace")
        else:
            record["body"] = body
        _get_kakao_raw_logger().info(json.dumps(record, ensure_ascii=False))
    except Exception:
        logging.getLogger("kakao_webhook").exception("kakao_raw in 기록 실패")


def _dump_kakao_out(response: dict, req_id: str) -> None:
    try:
        record = {
            "ts": datetime.now().isoformat(timespec="milliseconds"),
            "req_id": req_id,
            "direction": "out",
            "body": response,
        }
        _get_kakao_raw_logger().info(json.dumps(record, ensure_ascii=False))
    except Exception:
        logging.getLogger("kakao_webhook").exception("kakao_raw out 기록 실패")


@router.post(
    "/webhook/kakao",
    tags=["Webhook"],
    summary="카카오 오픈빌더 Skill Webhook",
    description=(
        "카카오 챗봇 채널의 Skill 엔드포인트. 카카오 자체 인증을 사용하므로 "
        "ScamGuardian API key 검증은 skip 한다 (`PlatformMiddleware` 의 `_SKIP_PATTERNS`).\n\n"
        "**입력 분기**:\n"
        "- `utterance` 빈 값 → welcome\n"
        "- `사용법|도움말|help|?` → 도움말\n"
        "- `초기화|리셋|reset` → 진행 중 잡 삭제\n"
        "- `결과확인` 류 → 진행 잡의 1차 분석 결과 + refine 트리거\n"
        "- `action.params` 의 image/picture/photo/pdf/video/file → 멀티모달 분석 (Phase 1 vision/STT)\n"
        "- 일반 텍스트 → 의도 분류 (`context_chat.classify_intent`) → CONTENT 면 컨텍스트 수집 시작\n\n"
        "**컨텍스트 수집 모드**: 1차 분석을 백그라운드로 시작하면서 사용자에게 본문 단서 기반 "
        "추가 정보를 묻는다. 완료 시 사용자가 '결과확인' 누르면 LLM phase 만 user_context 와 "
        "재호출(refine) 후 결과 카드 발급.\n\n"
        "**카카오 오픈빌더 설정**: 스킬 블록에서 *콜백 사용* 체크 권장 — 영상 분석이 60초 한도를 "
        "넘을 때 callback 모드로 전환. 콜백은 카카오 관리자센터 별도 신청·승인 필요."
    ),
)
async def kakao_webhook(request: Request, background_tasks: BackgroundTasks) -> dict:
    """카카오 오픈빌더 Skill Webhook 엔드포인트.

    분기 흐름:
    - 도움말 / 결과확인 / 스킵 같은 특수 명령 우선 처리
    - 진행 중 job 이 있으면 답변 또는 busy 처리 (멀티턴 컨텍스트 수집)
    - 신규 입력:
      - callbackUrl 있음 → 단발 callback 모드 (컨텍스트 수집 없음)
      - URL/영상 + callback 없음 → 컨텍스트 수집 + 병렬 STT 시작
      - 텍스트 → 즉시 동기 분석
    """
    EC = kakao_formatter.ErrorCode

    req_id = secrets.token_hex(6)
    raw_bytes = await request.body()
    try:
        body = await request.json()
    except Exception:
        _dump_kakao_in(request, raw_bytes, body=None, parse_error=True, req_id=req_id)
        resp = kakao_formatter.format_error(EC.PARSE_ERROR)
        _dump_kakao_out(resp, req_id=req_id)
        return resp

    _dump_kakao_in(request, raw_bytes, body=body, parse_error=False, req_id=req_id)
    response = await _kakao_webhook_impl(body, background_tasks)
    _dump_kakao_out(response, req_id=req_id)
    return response


async def _kakao_webhook_impl(body: dict, background_tasks: BackgroundTasks) -> dict:
    log = logging.getLogger("kakao_webhook")
    EC = kakao_formatter.ErrorCode
    InputType = kakao_formatter.InputType

    log.info(
        "kakao webhook 수신:\n"
        "  utterance: %s\n"
        "  callbackUrl: %s\n"
        "  action.params: %s",
        (body.get("userRequest", {}).get("utterance") or "")[:100],
        (body.get("userRequest", {}).get("callbackUrl") or "")[:80],
        str(body.get("action", {}).get("params", {}))[:200],
    )

    user_request = body.get("userRequest", {})
    utterance: str = (user_request.get("utterance") or "").strip()
    callback_url: str = (user_request.get("callbackUrl") or "").strip()
    action_params: dict = body.get("action", {}).get("params", {})
    user_id: str = (user_request.get("user", {}).get("id") or "").strip()

    # ── 어뷰즈 누적 차단 우선 검사 ──
    soft_warn_info: dict | None = None
    if user_id:
        from platform_layer import abuse_guard as _ag
        blocked, remaining = _ag.block_status(user_id)
        if blocked:
            log.warning("→ blocked user %s (남은 %ds)", user_id[:12], remaining)
            with state.jobs_lock:
                state.pending_jobs.pop(user_id, None)
            return kakao_formatter.format_abuse_blocked(remaining)
        has_attachment = any(
            action_params.get(k)
            for k in (
                "image", "picture", "photo",
                "pdf", "document",
                "audio", "voice", "sound",
                "video", "video_url",
                "file", "attachment",
            )
        )
        if utterance and not has_attachment and not _is_system_command(utterance):
            soft_warn_info = _ag.track_short_message(user_id, utterance)
            if soft_warn_info and soft_warn_info.get("blocked"):
                log.warning("→ soft block triggered user %s", user_id[:12])
                with state.jobs_lock:
                    state.pending_jobs.pop(user_id, None)
                return kakao_formatter.format_abuse_blocked(
                    soft_warn_info.get("block_remaining_sec") or _ag.BLOCK_DURATION_SEC
                )

    # ── 특수 명령: 빈 메시지 = welcome (즉답) ──
    if not utterance:
        log.info("→ welcome 응답 반환 (빈 메시지)")
        return kakao_formatter.format_welcome()
    if utterance in ("사용법", "도움말", "help", "?"):
        log.info("→ 사용법 응답 반환 (특수 명령)")
        return kakao_formatter.format_help()
    mode_cmd = _mode_guide_command(utterance)
    if mode_cmd is not None:
        log.info("→ 모드 가이드 응답 반환: %s", mode_cmd)
        return kakao_formatter.format_mode_guide(mode_cmd)
    if _live_session_command(utterance):
        if not user_id:
            log.warning("→ 라이브 세션 요청 실패: user_id 없음")
            return kakao_formatter.format_error(
                kakao_formatter.ErrorCode.UNKNOWN,
                "라이브 세션 사용자 식별 정보가 없습니다. 다시 시도해 주세요.",
            )
        token, ttl = issue_live_session_token(user_id=user_id)
        base_url = get_public_base_url()
        if not base_url:
            log.warning("→ 라이브 세션 링크 발급 실패: public base URL 없음")
            return kakao_formatter.format_error(
                kakao_formatter.ErrorCode.SERVER_DOWN,
                "라이브 세션 링크를 만들 수 없습니다. 관리자에게 SCAMGUARDIAN_PUBLIC_URL 설정을 요청해 주세요.",
            )
        session_url = f"{base_url}/live/{token}"
        log.info(
            "→ 라이브 세션 링크 발급: user=%s token=%s",
            user_id[:12],
            token[:8],
        )
        return kakao_formatter.format_live_session_link(
            session_url=session_url,
            ttl_min=max(1, ttl // 60),
        )

    if utterance in ("분석 초기화", "초기화", "리셋", "reset"):
        had_job = False
        if user_id:
            with state.jobs_lock:
                had_job = user_id in state.pending_jobs
                state.pending_jobs.pop(user_id, None)
        log.info(
            "→ 분석 초기화: user=%s had_job=%s",
            user_id[:12] if user_id else "?", had_job,
        )
        return kakao_formatter.format_reset(had_active_job=had_job)

    if _is_result_request(utterance):
        _cleanup_expired_jobs()
        with state.jobs_lock:
            job = state.pending_jobs.get(user_id)
        log.info(
            "→ 결과확인 요청: user=%s status=%s phase=%s",
            user_id[:12] if user_id else "?",
            job and job.get("status"),
            job and job.get("phase"),
        )
        if job is None:
            return kakao_formatter.format_no_job()
        if job.get("status") == "error":
            with state.jobs_lock:
                state.pending_jobs.pop(user_id, None)
            error_code = _classify_error(job.get("error") or Exception())
            return kakao_formatter.format_error(error_code)
        if job.get("status") == "done":
            return await _handle_done_state(user_id, background_tasks)
        if job.get("phase") == "collecting_context":
            log.info("→ 결과확인 = 컨텍스트 강제 종료 신호로 해석")
            return await _kakao_force_skip_context(user_id)
        elapsed, poll_count, stt_done = state.record_poll(user_id)
        return kakao_formatter.format_still_running(
            elapsed_sec=elapsed, poll_count=poll_count, stt_done=stt_done,
        )

    if utterance in _KAKAO_SKIP_PHRASES and user_id:
        log.info("→ 스킵 신호 수신: user=%s", user_id[:12])
        with state.jobs_lock:
            has_job = user_id in state.pending_jobs
        if has_job:
            return await _kakao_force_skip_context(user_id)
        return kakao_formatter.format_no_job()

    source, input_type = _kakao_detect_input(utterance, action_params)
    is_heavy = input_type in (
        InputType.URL, InputType.VIDEO, InputType.AUDIO, InputType.FILE, InputType.IMAGE, InputType.PDF,
    )
    log.info(
        "입력 감지: type=%s, heavy=%s, source=%s",
        input_type.value, is_heavy, source[:80],
    )

    # ── v3 Phase 1: 이미지/PDF/실행파일 → 로컬 다운로드 ──
    if input_type in (InputType.IMAGE, InputType.PDF, InputType.AUDIO, InputType.FILE) and source.startswith("http"):
        try:
            if input_type == InputType.PDF:
                suffix_hint = ".pdf"
            elif input_type == InputType.AUDIO:
                suffix_hint = ""
            elif input_type == InputType.FILE:
                m = _EXECUTABLE_URL_RE.search(source)
                suffix_hint = f".{m.group(1).lower()}" if m else ""
            else:
                suffix_hint = ""
            local_path = await asyncio.to_thread(
                _kakao_materialize_url, source, suffix_hint,
            )
            log.info(
                "→ 카카오 미디어 로컬 저장: %s → %s",
                input_type.value, Path(local_path).name,
            )
            source = local_path
        except Exception as exc:
            log.error("카카오 미디어 다운로드 실패: %s", exc, exc_info=True)
            return kakao_formatter.format_error(
                kakao_formatter.ErrorCode.UNKNOWN,
                f"파일 다운로드 실패: {exc}",
            )

    # ── 진행 중 job 처리 ──
    if user_id and not callback_url:
        with state.jobs_lock:
            job = state.pending_jobs.get(user_id)
        if job is not None:
            phase = job.get("phase")
            status = job.get("status")
            if status == "error":
                with state.jobs_lock:
                    state.pending_jobs.pop(user_id, None)
                error_code = _classify_error(job.get("error") or Exception())
                return kakao_formatter.format_error(error_code)
            if status == "done":
                if phase == "collecting_context":
                    log.info(
                        "→ 분석 완료 후에도 채팅 계속: user=%s (사용자가 결과확인 안 함)",
                        user_id[:12],
                    )
                    return await _kakao_handle_context_answer(user_id, utterance)
                return await _handle_done_state(user_id, background_tasks, utterance=utterance)
            if is_heavy:
                log.info("→ busy: 진행 중 job 있음, 새 영상 거절")
                return kakao_formatter.format_busy()
            if phase == "collecting_context":
                log.info("→ 컨텍스트 답변 처리: user=%s", user_id[:12])
                return await _kakao_handle_context_answer(user_id, utterance)
            elapsed, poll_count, stt_done = state.record_poll(user_id)
            return kakao_formatter.format_still_running(
                elapsed_sec=elapsed, poll_count=poll_count, stt_done=stt_done,
            )

    # ── callbackUrl 있으면: 단발 callback 모드 ──
    if callback_url:
        log.info(
            "→ callback 모드: 백그라운드 분석 시작, callbackUrl=%s",
            callback_url[:80],
        )
        msg = kakao_formatter.format_analyzing(input_type)
        background_tasks.add_task(
            _kakao_callback_task, source, callback_url, input_type, True,
        )
        resp = {
            "version": "2.0",
            "useCallback": True,
            "data": {"text": msg},
        }
        log.info("→ 즉시 응답: %s", str(resp)[:200])
        return resp

    # ── callbackUrl 없음, 무거운 입력 → 컨텍스트 수집 시작 ──
    if is_heavy:
        if not user_id:
            log.warning("→ user_id 없음, 컨텍스트 수집 불가 → CALLBACK_REQUIRED")
            return kakao_formatter.format_error(EC.CALLBACK_REQUIRED)
        log.info(
            "→ 컨텍스트 수집 모드 시작: user=%s type=%s",
            user_id[:12], input_type.value,
        )
        return await _kakao_start_context_collection(
            user_id, source, input_type, background_tasks,
        )

    # ── 어뷰즈 가드 (TEXT) ──
    if user_id:
        from platform_layer import abuse_guard as _ag
        rej = _ag.guard(source, user_id=user_id)
        if rej is not None:
            log.warning(
                "→ abuse guard reject user=%s code=%s (%s)",
                user_id[:12], rej.code, rej.detail,
            )
            if rej.code == "BLOCKED":
                with state.jobs_lock:
                    state.pending_jobs.pop(user_id, None)
                remaining = 3600
                try:
                    remaining = int(rej.detail.split("=")[-1].split("s")[0])
                except Exception:
                    pass
                return kakao_formatter.format_abuse_blocked(remaining)
            warns_left = _ag.VIOLATION_WARN_LIMIT - _ag.violation_count(user_id)
            return kakao_formatter.format_abuse_warning(rej.message, max(0, warns_left))

    # ── 텍스트: 의도 분류 ──
    if soft_warn_info and soft_warn_info.get("count", 0) >= 2:
        log.info(
            "→ Haiku skip (soft warn count=%d) → welcome 직접 반환",
            soft_warn_info["count"],
        )
        return _wrap_with_soft_warning(kakao_formatter.format_welcome(), soft_warn_info)

    intent = await asyncio.to_thread(context_chat.classify_intent, source)
    log.info("→ TEXT intent: %s", intent)

    if intent == context_chat.INTENT_GREETING:
        return _wrap_with_soft_warning(kakao_formatter.format_welcome(), soft_warn_info)
    if intent == context_chat.INTENT_HELP:
        return _wrap_with_soft_warning(kakao_formatter.format_help(), soft_warn_info)
    if intent == context_chat.INTENT_ANALYZE_NO_CONTENT:
        return _wrap_with_soft_warning(
            kakao_formatter.format_ask_for_content(reason="analyze"), soft_warn_info,
        )
    if intent == context_chat.INTENT_CHAT:
        return _wrap_with_soft_warning(
            kakao_formatter.format_ask_for_content(reason="chat"), soft_warn_info,
        )

    # CONTENT (default) — 본문 들어왔다 → 컨텍스트 수집 모드 시작
    if not user_id:
        log.warning("→ TEXT user_id 없음, 컨텍스트 수집 불가 → CALLBACK_REQUIRED")
        return kakao_formatter.format_error(EC.CALLBACK_REQUIRED)
    log.info(
        "→ TEXT 컨텍스트 수집 모드 시작: user=%s len=%s",
        user_id[:12], len(source),
    )
    return await _kakao_start_context_collection(
        user_id, source, input_type, background_tasks,
    )
