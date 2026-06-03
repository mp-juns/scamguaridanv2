"""APK 동적 분석 — 다운로드 링크(url) 입력 경로.

파일 업로드 대신 URL 을 주면 Content-Type 으로 *먼저 판단* 후 받아서 동일 분석 잡으로 흐르는지.
실제 VM/네트워크 없이 materialize/probe/start_analysis 를 mock.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_AUTH_DISABLED", "true")
    from api_server_pkg.app import create_app
    return TestClient(create_app())


def _stub_start_analysis(monkeypatch):
    calls = {}

    def fake_start(path, *, force_dynamic, apk_name):
        calls["path"] = path
        calls["apk_name"] = apk_name
        calls["force_dynamic"] = force_dynamic
        return {"job_id": "job-test", "status": "running"}

    monkeypatch.setattr("api_server_pkg.apk_dynamic.ctl.start_analysis", fake_start)
    return calls


def test_url_apk_downloaded_and_analyzed(client, monkeypatch, tmp_path):
    calls = _stub_start_analysis(monkeypatch)
    # probe → APK 로 판단
    monkeypatch.setattr("api_server_pkg.common.probe_executable_url", lambda u, **k: True)
    # materialize → ZIP magic 가진 가짜 APK 저장
    fake_apk = tmp_path / "downloaded.bin"
    fake_apk.write_bytes(b"PK\x03\x04rest-of-zip")
    monkeypatch.setattr(
        "api_server_pkg.common.materialize_executable_url", lambda u, **k: str(fake_apk)
    )

    r = client.post(
        "/api/admin/apk-dynamic/analyze",
        data={"url": "https://host.example/api/apk-dummy/tok123", "force_dynamic": "true"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["job_id"] == "job-test"
    assert calls["path"] == str(fake_apk)
    assert calls["apk_name"].endswith(".apk")  # 확장자 없는 URL 도 .apk 라벨 보정


def test_url_not_executable_rejected(client, monkeypatch):
    _stub_start_analysis(monkeypatch)
    monkeypatch.setattr("api_server_pkg.common.probe_executable_url", lambda u, **k: False)
    r = client.post(
        "/api/admin/apk-dynamic/analyze",
        data={"url": "https://news.example/article/1"},
    )
    assert r.status_code == 400
    assert "APK" in r.json()["detail"]


def test_url_downloads_non_apk_rejected(client, monkeypatch, tmp_path):
    _stub_start_analysis(monkeypatch)
    monkeypatch.setattr("api_server_pkg.common.probe_executable_url", lambda u, **k: True)
    not_apk = tmp_path / "x.bin"
    not_apk.write_bytes(b"\x00\x00\x00\x00not-a-zip")
    monkeypatch.setattr(
        "api_server_pkg.common.materialize_executable_url", lambda u, **k: str(not_apk)
    )
    r = client.post(
        "/api/admin/apk-dynamic/analyze",
        data={"url": "https://host.example/d/blob"},
    )
    assert r.status_code == 400
    assert "ZIP" in r.json()["detail"]
    assert not not_apk.exists()  # 검증 실패 시 다운로드 파일 정리


def test_neither_file_nor_url_rejected(client, monkeypatch):
    _stub_start_analysis(monkeypatch)
    r = client.post("/api/admin/apk-dynamic/analyze", data={"force_dynamic": "false"})
    assert r.status_code == 400
    assert "파일 또는 다운로드 링크" in r.json()["detail"]
