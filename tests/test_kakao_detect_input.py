"""카카오 webhook input 분류 — text/url/video/image/pdf/file 정확한 라우팅."""

from __future__ import annotations


def _detect(utterance, params):
    from api_server import _kakao_detect_input
    return _kakao_detect_input(utterance, params)


def test_pure_text_routes_to_text():
    src, kind = _detect("안녕 투자 9배 보장", {})
    assert kind.value == "text"
    assert "투자" in src


def test_youtube_url_in_action_param_routes_to_video():
    src, kind = _detect("", {"video_url": "https://youtube.com/watch?v=abc"})
    assert kind.value == "video"


def test_image_action_param_routes_to_image():
    src, kind = _detect("", {"image": "https://k.kakaocdn.net/abc.jpg"})
    assert kind.value == "image"
    assert src.endswith(".jpg")


def test_picture_dict_with_url_routes_to_image():
    src, kind = _detect("", {"picture": {"url": "https://x.example/y.png"}})
    assert kind.value == "image"


def test_pdf_routes_to_pdf():
    src, kind = _detect("", {"pdf": "https://example.com/x.pdf"})
    assert kind.value == "pdf"


def test_file_with_image_extension_routes_to_image():
    src, kind = _detect("", {"file": "https://cdn.example/poster.jpeg"})
    assert kind.value == "image"


def test_file_with_video_extension_falls_back_to_file():
    src, kind = _detect("", {"file": "https://cdn.example/x.mp4"})
    assert kind.value == "file"


def test_url_in_utterance_extracts_only_url():
    src, kind = _detect("이거 봐줘 https://example.com/scam.jpg 부탁해", {})
    assert kind.value == "image"
    assert src == "https://example.com/scam.jpg"


def test_pure_url_pdf_in_utterance_routes_to_pdf():
    src, kind = _detect("https://example.com/x.pdf", {})
    assert kind.value == "pdf"


def test_custom_param_name_pdf_url_routes_to_pdf():
    """카카오 오픈빌더에서 표준 키 외 커스텀 이름(예: 'doc1', 'secureimage') 으로 들어와도 인식되어야 한다."""
    src, kind = _detect("", {"doc1": "https://k.kakaocdn.net/abc.pdf"})
    assert kind.value == "pdf"


def test_custom_param_name_image_url_routes_to_image():
    src, kind = _detect("", {"secureimage": "https://k.kakaocdn.net/abc.png"})
    assert kind.value == "image"


def test_custom_param_dict_with_pdf_url_routes_to_pdf():
    src, kind = _detect(
        "", {"첨부": {"url": "https://k.kakaocdn.net/x.pdf"}}
    )
    assert kind.value == "pdf"


def test_custom_param_video_extension_routes_to_video():
    src, kind = _detect("", {"clip": "https://k.kakaocdn.net/x.mp4"})
    assert kind.value == "video"


def test_custom_param_unknown_extension_falls_back_to_file():
    src, kind = _detect("", {"misc": "https://example.com/something.bin"})
    assert kind.value == "file"


def test_apk_url_routes_to_file_for_vt_scan():
    """사기범이 텍스트로 보낸 APK 다운로드 링크 — VT 파일 스캔 강제 라우팅."""
    src, kind = _detect("이거 깔아줘 https://evil.com/court.apk 부탁해", {})
    assert kind.value == "file"
    assert src == "https://evil.com/court.apk"


def test_exe_url_routes_to_file():
    src, kind = _detect("https://evil.com/setup.exe", {})
    assert kind.value == "file"


def test_dmg_url_routes_to_file():
    src, kind = _detect("https://example.com/installer.dmg", {})
    assert kind.value == "file"


def test_audio_url_in_utterance_routes_to_audio():
    src, kind = _detect("이거 들어봐 https://example.com/call_record.m4a", {})
    assert kind.value == "audio"
    assert src == "https://example.com/call_record.m4a"


def test_audio_action_param_routes_to_audio():
    src, kind = _detect("", {"audio": "https://k.kakaocdn.net/voice_001.mp3"})
    assert kind.value == "audio"
