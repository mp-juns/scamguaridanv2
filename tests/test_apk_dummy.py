"""더미 피싱앱 다운로드 링크 — 카탈로그 / 발급 / 공개 다운로드 / 만료·보안."""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("ADMIN_AUTH_DISABLED", "true")
    from api_server_pkg.app import create_app
    from api_server_pkg import state
    state.apk_dummy_tokens.clear()
    return TestClient(create_app())


def test_catalog_lists_prebuilt_variants(client):
    r = client.get("/api/admin/apk-dynamic/dummy/catalog")
    assert r.status_code == 200
    variants = r.json()["variants"]
    ids = {v["id"] for v in variants}
    # 최소 2종 (fake_phishing 정적 + dynamic_active 동적)
    assert {"fake_phishing", "dynamic_active"} <= ids
    fp = next(v for v in variants if v["id"] == "fake_phishing")
    assert "apk_suspicious_package_name" in fp["expected_signals"]
    assert fp["tier"] == "static"


def test_issue_link_and_public_download(client):
    from api_server_pkg import state

    r = client.post("/api/admin/apk-dynamic/dummy/link", json={"variant_id": "fake_phishing"})
    assert r.status_code == 200
    data = r.json()
    token = data["token"]
    assert token in state.apk_dummy_tokens
    assert data["download_path"] == f"/api/apk-dummy/{token}"

    # 공개 다운로드 — APK(ZIP) 매직 바이트 + 안드로이드 패키지 media type
    d = client.get(data["download_path"])
    assert d.status_code == 200
    assert d.content[:4] == b"PK\x03\x04"
    assert d.headers["content-type"] == "application/vnd.android.package-archive"


def test_invalid_token_404(client):
    assert client.get("/api/apk-dummy/nope-not-a-token").status_code == 404


def test_expired_token_410(client):
    from api_server_pkg import state

    token = client.post(
        "/api/admin/apk-dynamic/dummy/link", json={"variant_id": "fake_phishing"}
    ).json()["token"]
    # 만료 시각을 과거로
    state.apk_dummy_tokens[token]["expires_at"] = time.time() - 1
    assert client.get(f"/api/apk-dummy/{token}").status_code == 410


def test_unknown_variant_404(client):
    r = client.post("/api/admin/apk-dynamic/dummy/link", json={"variant_id": "../../etc/passwd"})
    assert r.status_code == 404


def test_links_list(client):
    client.post("/api/admin/apk-dynamic/dummy/link", json={"variant_id": "fake_phishing"})
    r = client.get("/api/admin/apk-dynamic/dummy/links")
    assert r.status_code == 200
    assert len(r.json()["links"]) >= 1
