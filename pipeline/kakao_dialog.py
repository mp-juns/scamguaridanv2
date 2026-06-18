"""
ScamGuardian — 카카오 응답: 대화 흐름 / 폴링 / 시스템 메시지

분석 시작·폴링 진행·컨텍스트 질문·환영/사용법·어뷰즈 안내 등
결과 카드 이외의 모든 대화 응답. 결과 카드와 에러는 kakao_result 참고.
외부 소비자는 `pipeline.kakao_formatter` facade 를 통해 import 한다.
"""

from __future__ import annotations

from typing import Any

from pipeline.kakao_result import InputType, quick_replies


def format_analyzing(input_type: InputType = InputType.TEXT) -> dict[str, Any]:
    """분석 시작 안내 (callback 초기 응답 텍스트)."""
    msgs = {
        InputType.TEXT: "🔍 텍스트를 분석 중입니다...",
        InputType.URL: "🔗 링크 안전성 검사 중입니다...\nVirusTotal 조회 후 페이지 내용을 분석합니다.",
        InputType.VIDEO: "🎬 영상을 분석 중입니다...\n음성 인식(STT) 후 사기 여부를 판별합니다.",
        InputType.FILE: "📎 파일을 분석 중입니다...",
        InputType.IMAGE: "🖼 이미지를 분석 중입니다...\nOCR + 시각 단서를 같이 봅니다.",
        InputType.PDF: "📄 PDF를 분석 중입니다...\n페이지별로 OCR + 시각 단서를 추출합니다.",
    }
    return msgs.get(input_type, msgs[InputType.TEXT])


def format_queued(input_type: InputType = InputType.URL) -> dict[str, Any]:
    """폴링 모드: 분석 시작 안내 (콜백 없을 때 즉시 응답)."""
    msgs = {
        InputType.URL: "🔗 링크 분석을 시작했습니다.\nVirusTotal 검사 + 페이지 내용 분석.\n완료되면 '결과확인'을 입력해 주세요.",
        InputType.VIDEO: "🎬 영상 분석을 시작했습니다.\n완료되면 '결과확인'을 입력해 주세요.",
        InputType.FILE: "📎 파일 분석을 시작했습니다.\n완료되면 '결과확인'을 입력해 주세요.",
        InputType.TEXT: "🔍 분석을 시작했습니다.\n완료되면 '결과확인'을 입력해 주세요.",
        InputType.IMAGE: "🖼 이미지 분석을 시작했습니다.\nOCR 후 사기 여부를 판별합니다.\n완료되면 '결과확인'을 입력해 주세요.",
        InputType.PDF: "📄 PDF 분석을 시작했습니다.\n페이지 OCR 후 사기 여부를 판별합니다.\n완료되면 '결과확인'을 입력해 주세요.",
    }
    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {"simpleText": {"text": msgs.get(input_type, msgs[InputType.TEXT])}}
            ],
            "quickReplies": quick_replies("polling"),
        },
    }


def _humanize_duration(sec: int) -> str:
    """경과 초 → 사용자에게 보여줄 한국어 표현."""
    if sec < 10:
        return "방금 시작"
    if sec < 60:
        return f"{sec}초째"
    minutes = sec // 60
    rem = sec % 60
    if rem < 10:
        return f"{minutes}분째"
    return f"{minutes}분 {rem}초째"


def _polling_progress_lines(stage: str, elapsed_sec: int, poll_count: int) -> str:
    """polling 진행 상황을 사용자가 헷갈리지 않게 단계별 텍스트로 변환.

    stage:
        "stt"        — 음성 인식 중
        "analyzing"  — 분석 중 (STT 끝났고 본 분석 진행)
        "refining"   — 사용자 답변 반영 최종 정리 중
    """
    elapsed_label = _humanize_duration(elapsed_sec)
    if stage == "stt":
        head = "⏳ 음성 인식 진행 중이에요"
        if poll_count <= 1:
            tail = "유튜브 영상은 보통 1~3분 걸려요. 끝나면 결과를 정리해드릴게요."
        else:
            tail = (
                f"({elapsed_label}) — 유튜브는 다운로드 + 받아쓰기까지 1~3분 걸려요.\n"
                "곧 끝납니다, 30초만 더 기다려주세요."
            )
    elif stage == "refining":
        head = "📊 알려주신 정보 반영해서 마지막 정리 중이에요"
        if poll_count <= 1:
            tail = "5~10초 정도면 끝나요. 잠시 후 다시 '결과확인' 눌러주세요."
        else:
            tail = (
                f"({elapsed_label}) — 거의 다 됐어요. 한 번만 더 기다려주세요."
            )
    else:  # "analyzing"
        head = "🔍 받아쓰기는 끝났고 본 분석을 마무리하는 중이에요"
        if poll_count <= 1:
            tail = "보통 10~20초 걸려요. 끝나면 결과 카드 보여드릴게요."
        else:
            tail = (
                f"({elapsed_label}) — 곧 끝나요. 30초만 더 기다려주세요."
            )
    return f"{head}\n{tail}"


def format_still_running(
    elapsed_sec: int = 0,
    poll_count: int = 1,
    stt_done: bool = True,
) -> dict[str, Any]:
    """폴링 모드: 아직 분석 중일 때 응답. 매 호출마다 경과 시간 다르게 표시."""
    stage = "analyzing" if stt_done else "stt"
    text = _polling_progress_lines(stage, elapsed_sec, poll_count)
    return {
        "version": "2.0",
        "template": {
            "outputs": [{"simpleText": {"text": text}}],
            "quickReplies": quick_replies("polling"),
        },
    }


def format_no_job() -> dict[str, Any]:
    """폴링 모드: 진행 중인 분석이 없을 때 응답."""
    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": "📭 현재 진행 중인 분석이 없습니다.\n의심 텍스트, URL, 또는 영상을 보내주세요."
                    }
                }
            ],
            "quickReplies": quick_replies("idle"),
        },
    }


def format_ask_for_content(reason: str = "analyze") -> dict[str, Any]:
    """사용자가 분석 요청만 했거나 상황만 묘사했을 때 — 본문을 보여달라 부탁."""
    if reason == "chat":
        text = (
            "어떤 일이 있으셨어요? 함께 살펴볼게요. 🙂\n"
            "받으신 메시지·캡처·영상·URL 그대로 보내주시면 바로 분석할게요.\n"
            "(텍스트라면 통째로 붙여넣어 주세요)"
        )
    else:  # analyze
        text = (
            "그럼요! 분석할 내용을 보여주세요. 🔍\n"
            "받으신 메시지·캡처·영상·URL 그대로 보내주시면 됩니다.\n"
            "(텍스트라면 통째로 붙여넣어 주세요)"
        )
    return {
        "version": "2.0",
        "template": {
            "outputs": [{"simpleText": {"text": text}}],
            "quickReplies": quick_replies("idle"),
        },
    }


def format_reset(had_active_job: bool = False) -> dict[str, Any]:
    """진행 중 분석 잡 정리 후 안내 — '분석 초기화' 버튼 응답."""
    if had_active_job:
        text = (
            "🔄 진행 중이던 분석을 초기화했어요.\n"
            "새 의심 메시지/영상/URL을 보내주시면 처음부터 시작할게요."
        )
    else:
        text = (
            "🔄 초기화 완료. 진행 중인 분석은 없었어요.\n"
            "의심되는 메시지/영상/URL을 보내주시면 분석 시작할게요."
        )
    return {
        "version": "2.0",
        "template": {
            "outputs": [{"simpleText": {"text": text}}],
            "quickReplies": quick_replies(),
        },
    }


def format_welcome() -> dict[str, Any]:
    """첫 인사 / 새 세션 진입용 — 대화체 오프닝."""
    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": (
                            "안녕하세요! 저는 ScamGuardian이에요. 🛡️\n"
                            "어떤 일로 오셨어요?\n\n"
                            "의심되는 메시지·영상·URL이 있으면 그대로 보내주세요.\n"
                            "받자마자 함께 살펴보고 위험 신호를 알려드릴게요.\n\n"
                            "(자세한 사용법은 '사용법'을 입력하세요)"
                        )
                    }
                }
            ],
            "quickReplies": quick_replies("idle"),
        },
    }


def format_help() -> dict[str, Any]:
    """명시적 사용법 요청 시 — 무엇을 보낼 수 있고 어떻게 동작하는지 안내."""
    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": (
                            "📌 ScamGuardian 사용법\n\n"
                            "이렇게 보내주시면 돼요:\n\n"
                            "1️⃣  의심 문자/통화 내용을 텍스트로 붙여넣기\n"
                            "2️⃣  YouTube · 영상 URL 보내기\n"
                            "3️⃣  의심 영상·음성 파일 직접 전송\n\n"
                            "💬 받자마자 분석 정확도를 높일 정보를 몇 가지\n"
                            "    여쭤볼게요 (어디서 받으셨는지, 어떤 게 의심됐는지 등).\n"
                            "    답변하기 어려우시면 언제든 '결과확인'을 눌러주세요.\n\n"
                            "✅ 투자·건강식품·기관 사칭·로맨스·스미싱 등\n"
                            "    다양한 유형을 자동 분류하고 검출된 위험 신호를 알려드려요."
                        )
                    }
                }
            ],
            "quickReplies": quick_replies("help"),
        },
    }


# ──────────────────────────────────
# 컨텍스트 대화 / 멀티턴 응답
# ──────────────────────────────────
def format_question(
    question_text: str,
    *,
    is_first_turn: bool = False,
    input_type: InputType = InputType.URL,
) -> dict[str, Any]:
    """챗봇이 사용자에게 컨텍스트 질문을 던질 때 사용.

    is_first_turn 이면 영상 접수 안내 + 첫 질문을 함께 보낸다.
    """
    outputs: list[dict[str, Any]] = []
    if is_first_turn:
        if input_type in (InputType.URL, InputType.VIDEO, InputType.FILE, InputType.IMAGE, InputType.PDF):
            # 영상/URL/이미지/PDF: vision/STT + 1차 분석이 백그라운드로 돌고 있고, 채팅으로 정보 수집
            kind = {
                InputType.URL: "🔗 링크",
                InputType.VIDEO: "🎬 영상",
                InputType.FILE: "📎 파일",
                InputType.IMAGE: "🖼 이미지",
                InputType.PDF: "📄 PDF",
            }.get(input_type, "콘텐츠")
            # 이미지/PDF/URL 은 다운로드/OCR/VT 만 — 더 빠름
            duration = (
                "10초 정도"
                if input_type in (InputType.IMAGE, InputType.PDF, InputType.URL)
                else "1~3분"
            )
            intro = (
                f"{kind} 받았어요! 🔍 분석을 시작했어요 ({duration} 걸려요).\n"
                "그 동안 분석 정확도를 높일 정보 몇 가지 여쭤볼게요.\n"
                "분석이 끝나면 다음 메시지에서 '🎉 완료' 알림과 함께 정리해드릴게요."
            )
        else:
            # TEXT: 분석도 백그라운드로 돌고 있음 (1분 정도)
            intro = (
                "📩 받았어요! 🔍 분석을 시작했어요 (약 1분 걸려요).\n"
                "그 동안 분석 정확도를 높일 정보 몇 가지 여쭤볼게요.\n"
                "분석이 끝나면 다음 메시지에서 '🎉 완료' 알림과 함께 정리해드릴게요."
            )
        outputs.append({"simpleText": {"text": intro}})
    outputs.append({"simpleText": {"text": f"💬 {question_text}"}})

    return {
        "version": "2.0",
        "template": {
            "outputs": outputs,
            "quickReplies": quick_replies("collecting_context"),
        },
    }


def format_context_done_waiting(
    stt_done: bool,
    elapsed_sec: int = 0,
    poll_count: int = 1,
) -> dict[str, Any]:
    """컨텍스트 수집이 끝났고 분석을 기다리는 중일 때 안내.

    poll_count 가 2 이상이면 ack 인사 빼고 진행 단계만 표시 — 같은 메시지 도배 방지.
    """
    stage = "analyzing" if stt_done else "stt"
    progress = _polling_progress_lines(stage, elapsed_sec, poll_count)
    if poll_count <= 1:
        text = f"📝 알려주신 내용 잘 받았어요.\n\n{progress}"
    else:
        text = progress
    return {
        "version": "2.0",
        "template": {
            "outputs": [{"simpleText": {"text": text}}],
            "quickReplies": quick_replies("analyzing"),
        },
    }


def format_result_ready_announce(has_refine: bool) -> dict[str, Any]:
    """1차 분석 완료를 사용자에게 처음 알릴 때 — 결과 준비됐다는 announce.

    has_refine=True 면 "최종 정리 중" 안내, False 면 결과 받기 안내.
    """
    if has_refine:
        text = (
            "🎉 분석이 완료됐어요!\n"
            "알려주신 정보를 더해 최종 결과를 정리 중이에요. (5~10초)\n"
            "잠시 후 '결과확인'을 눌러주시면 최종 결과를 보여드릴게요."
        )
    else:
        text = (
            "🎉 분석이 완료됐어요!\n"
            "'결과확인'을 눌러 결과를 받아보세요."
        )
    return {
        "version": "2.0",
        "template": {
            "outputs": [{"simpleText": {"text": text}}],
            "quickReplies": quick_replies("polling"),
        },
    }


def format_refining_in_progress(
    elapsed_sec: int = 0,
    poll_count: int = 1,
) -> dict[str, Any]:
    """최종 합본 분석 진행 중 폴링 응답."""
    text = _polling_progress_lines("refining", elapsed_sec, poll_count)
    return {
        "version": "2.0",
        "template": {
            "outputs": [{"simpleText": {"text": text}}],
            "quickReplies": quick_replies("polling"),
        },
    }


def format_abuse_warning(message: str, warns_left: int) -> dict[str, Any]:
    """어뷰즈 가드 경고 — 짧은/도배/gibberish 등. warns_left 표시."""
    return {
        "version": "2.0",
        "template": {
            "outputs": [{"simpleText": {"text": f"⚠️ {message}"}}],
            "quickReplies": quick_replies("idle"),
        },
    }


def format_abuse_blocked(remaining_sec: int) -> dict[str, Any]:
    """반복 어뷰즈로 일시 차단됐을 때. 채팅 종료."""
    minutes = max(1, remaining_sec // 60)
    text = (
        "🚫 반복적인 어뷰즈로 일시 차단되었어요.\n"
        f"약 {minutes}분 후 다시 시도해 주세요.\n"
        "정상적인 사기 의심 메시지는 길고 구체적일수록 분석 정확도가 높아져요."
    )
    return {
        "version": "2.0",
        "template": {
            "outputs": [{"simpleText": {"text": text}}],
            "quickReplies": [],   # 차단 상태에선 quick reply 도 제거
        },
    }


def format_busy() -> dict[str, Any]:
    """이전 분석이 아직 진행 중인데 사용자가 새 영상/URL 을 보냈을 때."""
    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {
                    "simpleText": {
                        "text": (
                            "⏳ 이전 분석이 아직 진행 중이에요.\n"
                            "끝나면 '결과확인'으로 결과를 받으신 뒤 다시 보내주세요."
                        )
                    }
                }
            ],
            "quickReplies": quick_replies("busy"),
        },
    }
