"""시스템 명령어("결과확인", "사용법", "초기화" 등)는 어뷰즈 소프트 트래커에서 제외돼야 한다.

배경: 결과확인(4자), 사용법(3자) 모두 SOFT_LEN_THRESHOLD(10) 미만이라
track_short_message 가 위반으로 잘못 카운트하던 버그가 있었다. 팀원이 결과확인을
3~4회 누르자 자동 차단된 케이스 발생 → _is_system_command 화이트리스트 도입.
"""

from __future__ import annotations

import importlib

from fastapi.testclient import TestClient

from api_server import app


def test_result_confirm_recognized_as_system_command():
    from api_server import _is_system_command
    # 정확 매칭
    assert _is_system_command("결과확인")
    assert _is_system_command("결과 확인")
    # 부분 매칭 (자연 표현)
    assert _is_system_command("결과 알려줘")
    assert _is_system_command("분석 다됐어?")
    assert _is_system_command("결과 보여줘")


def test_help_and_reset_recognized():
    from api_server import _is_system_command
    assert _is_system_command("사용법")
    assert _is_system_command("도움말")
    assert _is_system_command("help")
    assert _is_system_command("?")
    assert _is_system_command("분석 초기화")
    assert _is_system_command("초기화")
    assert _is_system_command("리셋")
    assert _is_system_command("reset")


def test_skip_phrases_recognized():
    from api_server import _is_system_command
    assert _is_system_command("스킵")
    assert _is_system_command("skip")
    assert _is_system_command("그냥 분석")


def test_mode_shortcuts_recognized_as_system_command():
    from api_server import _is_system_command
    assert _is_system_command("apk 분석")
    assert _is_system_command("보이스분석")
    assert _is_system_command("음성 분석")
    assert _is_system_command("콘텐츠분석")


def test_live_shortcuts_recognized_as_system_command():
    from api_server import _is_system_command
    assert _is_system_command("라이브 보이스피싱")
    assert _is_system_command("실시간 보이스피싱")
    assert _is_system_command("라이브피싱")


def test_quick_replies_always_include_live_button():
    from pipeline.kakao_formatter import quick_replies

    default_labels = [item.get("label") for item in quick_replies("default")]
    polling_labels = [item.get("label") for item in quick_replies("polling")]

    assert "라이브 보이스피싱" in default_labels
    assert "라이브 보이스피싱" in polling_labels


def test_normal_input_not_system_command():
    from api_server import _is_system_command
    assert not _is_system_command("안녕")
    assert not _is_system_command("ㅋㅋㅋ")
    assert not _is_system_command("이거 사기인가요")
    assert not _is_system_command("https://example.com 의심돼요")
    assert not _is_system_command("")
    assert not _is_system_command("   ")


def test_kakao_live_command_returns_live_link(monkeypatch):
    client = TestClient(app)
    router_module = importlib.import_module("api_server_pkg.kakao.router")
    monkeypatch.setattr(
        router_module,
        "get_public_base_url",
        lambda: "https://example.com",
    )
    payload = {
        "userRequest": {
            "utterance": "라이브 보이스피싱",
            "user": {"id": "kakao-test-user"},
        },
        "action": {"params": {}},
    }
    resp = client.post("/webhook/kakao", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    outputs = body.get("template", {}).get("outputs", [])
    card = next(
        (
            x.get("basicCard")
            for x in outputs
            if isinstance(x, dict) and "basicCard" in x
        ),
        None,
    )
    assert card is not None
    buttons = card.get("buttons") or []
    assert buttons
    assert "/live/" in (buttons[0].get("webLinkUrl") or "")
