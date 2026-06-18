"""
ScamGuardian — 카카오 응답: 검출 결과 카드 + 에러

DetectionReport.to_dict() 결과를 카카오 챗봇 응답 JSON 으로 변환.
Identity (CLAUDE.md): 점수·등급 표시 안 함 — 검출 신호 list + 학술/법적 근거만.
대화 흐름(질문/폴링/시스템 메시지)은 kakao_dialog 참고. 외부 소비자는
`pipeline.kakao_formatter` facade 를 통해 import 한다.
https://i.kakao.com/docs/skill-response-format
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pipeline.config import flag_label_ko


# ──────────────────────────────────
# 입력 유형
# ──────────────────────────────────
class InputType(str, Enum):
    TEXT = "text"
    URL = "url"
    VIDEO = "video"
    FILE = "file"
    IMAGE = "image"   # v3 — 사진·캡쳐
    PDF = "pdf"       # v3 — PDF 문서


# ──────────────────────────────────
# 에러 코드 → 사용자 친화적 메시지
# ──────────────────────────────────
class ErrorCode(str, Enum):
    UNKNOWN = "unknown"
    API_CREDIT = "api_credit"
    SERVER_DOWN = "server_down"
    STT_FAIL = "stt_fail"
    TIMEOUT = "timeout"
    EMPTY_INPUT = "empty_input"
    INVALID_URL = "invalid_url"
    FILE_TOO_LARGE = "file_too_large"
    LLM_UNAVAILABLE = "llm_unavailable"
    CALLBACK_REQUIRED = "callback_required"
    PARSE_ERROR = "parse_error"


_ERROR_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.UNKNOWN: "알 수 없는 오류가 발생했습니다.",
    ErrorCode.API_CREDIT: (
        "🔑 서버의 API 크레딧이 부족합니다!\n"
        "챗봇 관리자에게 알려주세요."
    ),
    ErrorCode.SERVER_DOWN: (
        "🔧 분석 서버에 연결할 수 없습니다.\n"
        "서버가 점검 중이거나 일시적 장애입니다.\n"
        "관리자에게 문의해 주세요."
    ),
    ErrorCode.STT_FAIL: (
        "🎤 음성 인식(STT)에 실패했습니다.\n"
        "영상/음성 파일이 손상되었거나\n"
        "오디오가 포함되지 않은 파일일 수 있습니다."
    ),
    ErrorCode.TIMEOUT: (
        "⏱️ 처리 시간이 초과되었습니다.\n"
        "다시 시도해 주세요."
    ),
    ErrorCode.EMPTY_INPUT: (
        "📝 분석할 내용이 비어 있습니다.\n"
        "의심되는 텍스트, URL, 또는 영상을 보내주세요."
    ),
    ErrorCode.INVALID_URL: (
        "🔗 유효하지 않은 URL입니다.\n"
        "YouTube 링크 또는 영상 URL을 확인해 주세요."
    ),
    ErrorCode.FILE_TOO_LARGE: (
        "📦 파일 크기가 너무 큽니다.\n"
        "100MB 이하의 파일을 보내주세요."
    ),
    ErrorCode.LLM_UNAVAILABLE: (
        "🤖 AI 보조 분석 서비스를 사용할 수 없습니다.\n"
        "기본 분석으로 진행합니다."
    ),
    ErrorCode.CALLBACK_REQUIRED: (
        "⏳ 영상/URL 분석은 시간이 걸립니다.\n"
        "챗봇 관리자가 '콜백 사용' 설정을 켜야 합니다."
    ),
    ErrorCode.PARSE_ERROR: "요청을 파싱할 수 없습니다.",
}


# ──────────────────────────────────
# 검출 신호 개수별 아이콘 (점수·등급 X — Identity Boundary)
# 단순히 "신호 있음/없음" 만 시각화. 판정은 통합 기업 몫.
# ──────────────────────────────────


def _detection_icon(signal_count: int) -> str:
    """검출 신호 개수에 따른 표시 아이콘. 점수·등급 매기기 X."""
    if signal_count <= 0:
        return "✅"
    if signal_count <= 2:
        return "⚠️"
    return "🚨"


_DISCLAIMER_TEXT = (
    "ⓘ ScamGuardian 은 사기 판정을 내리지 않습니다. "
    "위 검출 신호와 근거를 참고하여 신중히 판단해주세요."
)

_QUICK_REPLY_HELP = {
    "label": "사용법",
    "action": "message",
    "messageText": "사용법",
}

_QUICK_REPLY_RESET = {
    "label": "분석 초기화",
    "action": "message",
    "messageText": "분석 초기화",
}

_QUICK_REPLY_RESULT_CHECK = {
    "label": "결과확인",
    "action": "message",
    "messageText": "결과확인",
}

# 결과확인 버튼이 우선 노출돼야 하는 phase — 사용자가 결과를 기다리는 상황
_PHASES_WITH_RESULT_CHECK = frozenset({
    "polling",
    "analyzing",
    "busy",
    "collecting_context",
})


def quick_replies(phase: str = "default") -> list[dict[str, str]]:
    """phase 별 퀵 리플라이 반환.

    분석 결과를 기다리는 phase(폴링/refining/대기 등)에서는 결과확인 버튼을 우선 노출한다.
    그 외 phase 에서는 [사용법, 분석 초기화] 두 개만 반환한다.
    """
    if phase in _PHASES_WITH_RESULT_CHECK:
        return [_QUICK_REPLY_RESULT_CHECK, _QUICK_REPLY_HELP, _QUICK_REPLY_RESET]
    return [_QUICK_REPLY_HELP, _QUICK_REPLY_RESET]


def _entity_lines(entities: list[dict[str, Any]], max_count: int = 6) -> str:
    if not entities:
        return "없음"
    lines = []
    for e in entities[:max_count]:
        lines.append(f"• {e.get('label', '')}: {e.get('text', '')}")
    if len(entities) > max_count:
        lines.append(f"… 외 {len(entities) - max_count}개")
    return "\n".join(lines)


def _signal_lines(signals: list[dict[str, Any]], max_count: int = 4) -> str:
    """검출 신호를 한국어 라벨 + (요약된) 학술/법적 근거로 표시. 점수 표기 없음."""
    if not signals:
        return "검출된 위험 신호 없음"
    lines = []
    for s in signals[:max_count]:
        flag_key = s.get("flag", "")
        label = s.get("label_ko") or (flag_label_ko(flag_key) if flag_key else "(이름 없음)")
        rationale = (s.get("rationale") or "").strip()
        # 카드 본문이 너무 길어지지 않도록 근거는 1문장 또는 80자까지만 노출
        if rationale:
            short = rationale.split(".", 1)[0].strip()
            short = (short[:80] + "…") if len(short) > 80 else short
            lines.append(f"• {label}\n   └ 근거: {short}")
        else:
            lines.append(f"• {label}")
    if len(signals) > max_count:
        lines.append(f"… 외 {len(signals) - max_count}개")
    return "\n".join(lines)


def _truncate(text: str, max_len: int = 200) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"


# ──────────────────────────────────
# 결과 카드 빌더 (입력 유형별)
# ──────────────────────────────────
def _build_result_card(
    report: dict[str, Any],
    input_type: InputType = InputType.TEXT,
    result_url: str | None = None,
) -> dict[str, Any]:
    """검출 결과 카드 — 점수·등급 X, 검출 신호 list 만 표시."""
    scam_type = report.get("scam_type", "미분류")
    confidence = report.get("classification_confidence", 0)
    entities = report.get("entities", [])
    signals = report.get("detected_signals", [])
    signal_count = len(signals)

    icon = _detection_icon(signal_count)
    confidence_pct = f"{confidence * 100:.0f}%"

    # 입력 유형 표시
    type_labels = {
        InputType.TEXT: "💬 텍스트 검출",
        InputType.URL: "🔗 링크 검출",
        InputType.VIDEO: "🎬 영상 검출",
        InputType.FILE: "📎 파일 검출",
        InputType.IMAGE: "🖼 이미지 검출",
        InputType.PDF: "📄 PDF 검출",
    }
    type_label = type_labels.get(input_type, "검출")

    if signal_count == 0:
        title = f"{icon} 검출된 위험 신호 없음"
    else:
        title = f"{icon} 위험 신호 {signal_count}개 검출"

    body_parts = [f"[검출 방식] {type_label}"]

    # 입력 본문/전사 미리보기 — TEXT 도 포함하여 일관 표시
    transcript = report.get("transcript_text", "")
    if transcript:
        # VIDEO/FILE 만 음성 전사. URL 은 링크 자체 또는 페이지 텍스트라 "입력 본문" 으로 통일.
        label = "음성 전사" if input_type in (InputType.VIDEO, InputType.FILE) else "입력 본문"
        body_parts.append(f"[{label}]\n{_truncate(transcript, 150)}")

    # LLM 한 줄 요약이 있으면 우선 노출 — 사용자가 핵심 빠르게 파악 가능
    llm = report.get("llm_assessment") or {}
    summary = str(llm.get("summary", "")).strip()
    if summary:
        body_parts.append(f"[AI 요약]\n{_truncate(summary, 200)}")

    body_parts.extend([
        f"[추정 유형]\n{scam_type} (분류 신뢰도 {confidence_pct})",
        f"[검출된 위험 신호 — {signal_count}개]\n{_signal_lines(signals)}",
        f"[추출 엔티티]\n{_entity_lines(entities)}",
    ])

    body = "\n\n".join(body_parts)

    card: dict[str, Any] = {
        "basicCard": {
            "title": title,
            "description": body,
        }
    }
    if result_url:
        card["basicCard"]["buttons"] = [
            {
                "label": "자세한 결과 보기",
                "action": "webLink",
                "webLinkUrl": result_url,
            }
        ]
    return card


def _build_uncertain_text() -> dict[str, Any]:
    return {
        "simpleText": {
            "text": (
                "⚠️ 분류 신뢰도가 낮아 정확도가 떨어질 수 있습니다.\n"
                "더 자세한 내용을 포함한 텍스트를 다시 입력해 주세요."
            )
        }
    }


# ──────────────────────────────────
# 공개 API
# ──────────────────────────────────
def _build_user_context_block(user_context: dict[str, Any] | None) -> dict[str, Any] | None:
    """결과 카드 뒤에 붙는 '사용자 제공 정보' 블록 — 컨텍스트 있을 때만."""
    if not user_context:
        return None
    qa_pairs = user_context.get("qa_pairs") or []
    if not qa_pairs:
        return None
    lines = ["📝 사용자 제공 정보"]
    for qa in qa_pairs[:4]:
        a = str(qa.get("answer", "")).strip()
        if not a:
            continue
        q = str(qa.get("question", "")).strip()
        if q:
            lines.append(f"• Q: {_truncate(q, 60)}")
            lines.append(f"  A: {_truncate(a, 100)}")
        else:
            lines.append(f"• {_truncate(a, 100)}")
    return {"simpleText": {"text": "\n".join(lines)}}


def _build_safety_warning_block(report: dict[str, Any]) -> dict[str, Any] | None:
    """v3 Phase 0 안전성 결과 — malicious/suspicious 일 때만 최상단 경고 블록 생성."""
    safety = report.get("safety_check") or {}
    level = (safety.get("threat_level") or "").lower()
    if level not in ("malicious", "suspicious"):
        return None
    detections = int(safety.get("detections") or 0)
    total = int(safety.get("total_engines") or 0)
    cats = safety.get("threat_categories") or []
    target_kind = safety.get("target_kind", "")
    kind_label = "URL" if target_kind == "url" else "파일"
    icon = "🚨" if level == "malicious" else "⚠️"
    if level == "malicious":
        head = f"{icon} 이 {kind_label}에서 악성 신호가 검출됐어요."
    else:
        head = f"{icon} 주의: 이 {kind_label}에 일부 의심 신호가 있어요."
    lines = [head]
    if total:
        lines.append(f"VirusTotal {detections}/{total} 엔진 탐지")
    if cats:
        lines.append("탐지 카테고리: " + ", ".join(map(str, cats[:3])))
    lines.append("절대 클릭·실행하지 마시고 발신자에게 답하지 마세요.")
    return {"simpleText": {"text": "\n".join(lines)}}


def format_result(
    report: dict[str, Any],
    input_type: InputType = InputType.TEXT,
    user_context: dict[str, Any] | None = None,
    result_url: str | None = None,
) -> dict[str, Any]:
    """검출 결과를 카카오 응답 JSON 으로 변환.

    Identity (CLAUDE.md): 점수·등급 X, 검출 신호 list 만. 끝에 disclaimer 부착.
    result_url 이 주어지면 카드에 '자세한 결과 보기' webLink 버튼 + 안내 텍스트 추가.
    """
    outputs: list[dict[str, Any]] = []

    safety_block = _build_safety_warning_block(report)
    if safety_block:
        # VT 다중 엔진 합의 신호는 카드보다 먼저 — 사용자 눈에 가장 먼저 들어오도록
        outputs.append(safety_block)

    outputs.append(_build_result_card(report, input_type, result_url=result_url))

    user_block = _build_user_context_block(user_context)
    if user_block:
        outputs.append(user_block)

    if result_url:
        outputs.append({
            "simpleText": {
                "text": f"📊 자세한 결과는 1시간 동안 다음 링크에서 보실 수 있어요.\n{result_url}"
            }
        })

    if report.get("is_uncertain"):
        outputs.append(_build_uncertain_text())

    # Identity Boundary disclaimer — 모든 결과 카드 마지막에
    outputs.append({"simpleText": {"text": _DISCLAIMER_TEXT}})

    return {
        "version": "2.0",
        "template": {
            "outputs": outputs,
            "quickReplies": quick_replies("result"),
        },
    }


def format_error(
    code: ErrorCode = ErrorCode.UNKNOWN,
    detail: str | None = None,
) -> dict[str, Any]:
    """에러 상황별 카카오 응답을 반환한다."""
    message = _ERROR_MESSAGES.get(code, _ERROR_MESSAGES[ErrorCode.UNKNOWN])
    if detail:
        message += f"\n\n상세: {_truncate(detail, 100)}"

    return {
        "version": "2.0",
        "template": {
            "outputs": [
                {"simpleText": {"text": f"❌ {message}"}}
            ],
            "quickReplies": quick_replies("error"),
        },
    }
