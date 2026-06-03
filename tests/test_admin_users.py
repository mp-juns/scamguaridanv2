"""admin 사용자 승인 시스템 — access/check 상태 전이 + master-only 가드."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("SCAMGUARDIAN_ADMIN_TOKEN", "tok123")
    monkeypatch.setenv("ADMIN_AUTH_DISABLED", "false")
    monkeypatch.setenv("SCAMGUARDIAN_MASTER_EMAILS", "master@x.com")
    from api_server_pkg.app import create_app
    return TestClient(create_app())


TOK = {"X-Admin-Token": "tok123"}
MASTER = {**TOK, "X-Admin-Email": "master@x.com"}
NONMASTER = {**TOK, "X-Admin-Email": "approved@x.com"}


def test_access_check_master(client):
    r = client.post("/api/admin/access/check", json={"email": "master@x.com"})
    assert r.status_code == 200
    assert r.json() == {"allowed": True, "status": "approved", "role": "master"}


def test_access_check_is_public(client):
    # 토큰 없이도 호출 가능 (로그인 전 signIn 콜백)
    r = client.post("/api/admin/access/check", json={"email": "anyone@x.com"})
    assert r.status_code == 200


def test_unknown_becomes_pending_then_approve_flow(client):
    # 1) unknown → pending
    r = client.post("/api/admin/access/check", json={"email": "new@x.com"})
    assert r.json() == {"allowed": False, "status": "pending"}
    # 2) 마스터가 승인
    r = client.post("/api/admin/users/approve", json={"email": "new@x.com"}, headers=MASTER)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    # 3) 이제 allowed
    r = client.post("/api/admin/access/check", json={"email": "new@x.com"})
    assert r.json()["allowed"] is True


def test_denied_stays_denied(client):
    client.post("/api/admin/access/check", json={"email": "bad@x.com"})
    client.post("/api/admin/users/deny", json={"email": "bad@x.com"}, headers=MASTER)
    r = client.post("/api/admin/access/check", json={"email": "bad@x.com"})
    assert r.json() == {"allowed": False, "status": "denied"}


def test_approve_requires_master(client):
    client.post("/api/admin/access/check", json={"email": "x@x.com"})
    # 비마스터(승인된 일반 admin)는 403
    r = client.post("/api/admin/users/approve", json={"email": "x@x.com"}, headers=NONMASTER)
    assert r.status_code == 403


def test_users_list_requires_admin_token(client):
    assert client.get("/api/admin/users").status_code == 401
    assert client.get("/api/admin/users", headers=MASTER).status_code == 200


def test_master_cannot_be_revoked(client):
    r = client.post("/api/admin/users/revoke", json={"email": "master@x.com"}, headers=MASTER)
    assert r.status_code == 400
