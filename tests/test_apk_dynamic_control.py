"""APK 동적 분석 VM 컨트롤러 단위 테스트.

subprocess / VM / analyze_apk_dynamic 를 모두 mock 해서 실제 VM 없이 디스패치·파싱·잡 흐름을 검증.
"""

from __future__ import annotations

import time
import types

import pytest

from api_server_pkg import apk_dynamic_control as ctl
from pipeline import apk_analyzer


def _wait(fn, timeout: float = 5.0):
    end = time.time() + timeout
    while time.time() < end:
        v = fn()
        if v and v.get("status") != "running":
            return v
        time.sleep(0.03)
    raise AssertionError("timeout waiting for completion")


# ──────────────── status-json 파싱 ────────────────
def test_probe_status_parses_json(monkeypatch):
    line = '{"vm_running":true,"redroid_booted":true,"frida_running":true,"server_up":false,"remote_url":"http://127.0.0.1:18002"}'
    monkeypatch.setattr(
        ctl.subprocess, "run",
        lambda *a, **k: types.SimpleNamespace(stdout=line + "\n", stderr="", returncode=0),
    )
    out = ctl._probe_status()
    assert out["ok"] is True
    assert out["vm_running"] is True
    assert out["redroid_booted"] is True
    assert out["server_up"] is False
    assert out["remote_url"] == "http://127.0.0.1:18002"


def test_probe_status_unparseable_is_safe(monkeypatch):
    monkeypatch.setattr(
        ctl.subprocess, "run",
        lambda *a, **k: types.SimpleNamespace(stdout="multipass not found\n", stderr="boom", returncode=2),
    )
    out = ctl._probe_status()
    assert out["ok"] is False
    assert out["vm_running"] is False and out["server_up"] is False
    assert "error" in out


def test_probe_status_timeout_is_safe(monkeypatch):
    def _raise(*a, **k):
        raise ctl.subprocess.TimeoutExpired(cmd="status-json", timeout=30)

    monkeypatch.setattr(ctl.subprocess, "run", _raise)
    out = ctl._probe_status()
    assert out["ok"] is False
    assert out["vm_running"] is False


def test_vm_status_caches(monkeypatch):
    calls = {"n": 0}

    def _run(*a, **k):
        calls["n"] += 1
        return types.SimpleNamespace(
            stdout='{"vm_running":false,"redroid_booted":false,"frida_running":false,"server_up":false,"remote_url":"x"}',
            stderr="", returncode=0,
        )

    monkeypatch.setattr(ctl.subprocess, "run", _run)
    ctl.vm_status(force=True)        # 강제 1회
    n_after_force = calls["n"]
    ctl.vm_status()                  # 캐시 히트 — subprocess 추가 호출 없어야
    assert calls["n"] == n_after_force


# ──────────────── VM op 디스패치 ────────────────
class _FakePopen:
    def __init__(self, *a, **k):
        pass

    def wait(self):
        return 0


def test_start_vm_op_injects_remote_config(monkeypatch, tmp_path):
    monkeypatch.setattr(ctl, "OPS_DIR", tmp_path / "ops")
    monkeypatch.setattr(ctl.subprocess, "Popen", _FakePopen)

    recorded = {}
    monkeypatch.setattr(
        apk_analyzer, "configure_remote",
        lambda url, token, **kw: recorded.update({"url": url, "token": token, **kw}),
    )

    op = ctl.start_vm()
    assert op["op"] == "start"
    done = _wait(lambda: ctl.get_op(op["op_id"]))
    assert done["status"] == "done"
    assert done["exit_code"] == 0
    assert recorded.get("enabled") is True   # start 성공 → remote 활성 주입


def test_concurrent_vm_op_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(ctl, "OPS_DIR", tmp_path / "ops")

    class _SlowPopen:
        def __init__(self, *a, **k):
            pass

        def wait(self):
            time.sleep(0.3)
            return 0

    monkeypatch.setattr(ctl.subprocess, "Popen", _SlowPopen)
    monkeypatch.setattr(apk_analyzer, "configure_remote", lambda *a, **k: None)

    op = ctl.start_vm()
    with pytest.raises(RuntimeError):
        ctl.stop_vm()            # 진행 중이라 거절
    _wait(lambda: ctl.get_op(op["op_id"]))  # 정리 대기 (lock 해제)


# ──────────────── 분석 잡 ────────────────
def test_force_dynamic_job(monkeypatch, tmp_path):
    apk = tmp_path / "x.apk"
    apk.write_bytes(b"PK\x03\x04stub")

    fake = apk_analyzer.APKDynamicReport(
        status=apk_analyzer.APKDynamicStatus.COMPLETED,
        backend="remote",
        detected_flags=["apk_runtime_sms_intercepted"],
        raw_observations={"hooks": ["sms"]},
    )
    monkeypatch.setattr(apk_analyzer, "analyze_apk_dynamic", lambda p: fake)

    started = ctl.start_analysis(str(apk), force_dynamic=True, apk_name="x.apk")
    done = _wait(lambda: ctl.get_job(started["job_id"]))
    assert done["status"] == "done"
    assert done["result"]["mode"] == "force_dynamic"
    assert done["result"]["apk_dynamic_check"]["detected_flags"] == ["apk_runtime_sms_intercepted"]
    assert not apk.exists()      # 분석 후 임시 파일 삭제 확인
