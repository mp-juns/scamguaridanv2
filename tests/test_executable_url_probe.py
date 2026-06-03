"""api_server_pkg.common.probe_executable_url — 확장자 없는 APK 다운로드 URL 판단.

핵심 회귀: `/api/apk-dummy/{token}` 처럼 확장자 없는 링크를 메인 분석창에 넣었을 때,
STT/웹 분석으로 새지 않고 Content-Type 으로 실행파일 다운로드임을 *먼저 판단* 해야 한다.
"""
from __future__ import annotations

import pytest

from api_server_pkg import common


class _FakeResp:
    def __init__(self, headers: dict, status_code: int = 200):
        self.headers = headers
        self.status_code = status_code

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_head(monkeypatch, headers, status_code=200, fail=False):
    def fake_head(url, **kw):
        if fail:
            raise RuntimeError("HEAD 실패")
        return _FakeResp(headers, status_code)
    monkeypatch.setattr("requests.head", fake_head)
    monkeypatch.setattr("requests.get", lambda url, **kw: _FakeResp(headers, status_code))


def test_apk_content_type_detected(monkeypatch):
    # 더미 APK 엔드포인트와 동일한 응답 (확장자 없는 토큰 URL)
    _patch_head(monkeypatch, {"Content-Type": "application/vnd.android.package-archive"})
    assert common.probe_executable_url("https://host.example/api/apk-dummy/abc123") is True


def test_apk_filename_in_disposition(monkeypatch):
    _patch_head(monkeypatch, {
        "Content-Type": "application/octet-stream",
        "Content-Disposition": 'attachment; filename="KakaoTalk_보안.apk"',
    })
    assert common.probe_executable_url("https://cdn.example/d/xyz") is True


def test_plain_html_page_not_executable(monkeypatch):
    _patch_head(monkeypatch, {"Content-Type": "text/html; charset=utf-8"})
    assert common.probe_executable_url("https://news.example/article/1") is False


def test_generic_octet_stream_alone_is_not_executable(monkeypatch):
    # octet-stream 단독은 오탐 위험 → False (실행파일 파일명/타입 없으면 URL 로 유지)
    _patch_head(monkeypatch, {"Content-Type": "application/octet-stream"})
    assert common.probe_executable_url("https://host.example/download/blob") is False


def test_extension_url_shortcircuits(monkeypatch):
    # 확장자가 이미 .apk 면 네트워크 probe 없이 True (head 호출 시 실패해도 무관)
    _patch_head(monkeypatch, {}, fail=True)
    assert common.probe_executable_url("https://evil.example/app.apk") is True


def test_non_url_is_false(monkeypatch):
    _patch_head(monkeypatch, {}, fail=True)
    assert common.probe_executable_url("그냥 텍스트 메시지") is False


def test_network_failure_is_false(monkeypatch):
    _patch_head(monkeypatch, {}, fail=True)
    assert common.probe_executable_url("https://unreachable.example/api/apk-dummy/t") is False


# ──────────────── 자기 서버 더미 링크 — 루프백 fetch 없이 토큰으로 로컬 해석 ────────────────
def _seed_dummy_token(monkeypatch, tmp_path, token="tok_abc-1"):
    """data_examples/apk 하위에 실제 .apk 가 있어야 DATA_DIR 검증 통과."""
    from api_server_pkg import apk_dummy, state
    apks = list(apk_dummy.DATA_DIR.glob("*.apk")) if apk_dummy.DATA_DIR.exists() else []
    if not apks:
        pytest.skip("data_examples/apk 에 .apk 없음 (빌드 필요)")
    import time
    monkeypatch.setitem(
        state.apk_dummy_tokens, token,
        {"variant_id": "fake_phishing", "file_path": str(apks[0]),
         "filename": apks[0].name, "expires_at": time.time() + 3600, "created_at": time.time()},
    )
    return token, apks[0]


def test_self_dummy_link_probed_without_network(monkeypatch, tmp_path):
    token, _ = _seed_dummy_token(monkeypatch, tmp_path)
    # 네트워크가 호출되면 실패하도록 막아둠 — 그래도 True 여야(로컬 해석)
    _patch_head(monkeypatch, {}, fail=True)
    cf_url = f"https://sao-foo.trycloudflare.com/api/apk-dummy/{token}"
    assert common.probe_executable_url(cf_url) is True


def test_self_dummy_link_materializes_local_copy(monkeypatch, tmp_path):
    token, apk = _seed_dummy_token(monkeypatch, tmp_path)
    cf_url = f"https://sao-foo.trycloudflare.com/api/apk-dummy/{token}"
    path = common.materialize_executable_url(cf_url)
    try:
        with open(path, "rb") as fp:
            assert fp.read(4) == b"PK\x03\x04"  # APK(ZIP) magic
    finally:
        import os
        os.unlink(path)


def test_expired_dummy_token_not_resolved(monkeypatch):
    from api_server_pkg import apk_dummy, state
    import time
    monkeypatch.setitem(state.apk_dummy_tokens, "expired",
                        {"file_path": "/nonexistent.apk", "expires_at": time.time() - 1})
    assert apk_dummy.resolve_dummy_url_to_path("https://x/api/apk-dummy/expired") is None
