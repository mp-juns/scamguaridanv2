"""
ScamGuardian APK 동적 분석기 — redroid(Android-in-Docker) + Frida.

격리 VM 안에서만 동작. 받은 APK 를:
  1. redroid 에 adb install (-g 런타임 권한 부여)
  2. Frida 로 spawn → frida_hooks.js 로드 → resume
  3. N초 동안 동작 관찰 (active fixture 는 launch 시 스스로 행동 실행)
  4. adb uninstall + (옵션) 스냅샷 복원
  5. 수집한 hook 이벤트를 5개 런타임 flag 로 매핑

production 계약: `{detected_flags: [...], observations: {...}}` 반환.
detected_flags 는 VALID_FLAGS(5종) 로 검증된 것만 — host 측이 한 번 더 DETECTED_FLAGS 로 거른다.

⚠️ 실행을 막지 않고 *관찰만* 한다 (Identity Boundary). 판정은 통합 기업.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

log = logging.getLogger("apk_dynamic.analyzer")

# 5개 런타임 candidate flag (pipeline/config.py 의 apk_runtime_* 과 동일해야 함).
VALID_FLAGS = {
    "apk_runtime_c2_network_call",
    "apk_runtime_sms_intercepted",
    "apk_runtime_overlay_attack",
    "apk_runtime_credential_exfiltration",
    "apk_runtime_persistence_install",
}

ADB_SERIAL = os.getenv("APK_DYNAMIC_ADB_SERIAL", "localhost:5555")
FRIDA_SERVER_PATH = os.getenv("APK_DYNAMIC_FRIDA_SERVER", "/data/local/tmp/frida-server")
COLLECT_SECONDS = int(os.getenv("APK_DYNAMIC_COLLECT_SECONDS", "12"))
HOOKS_JS = Path(__file__).parent / "frida_hooks.js"


class AnalyzerError(RuntimeError):
    pass


def _adb(*args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["adb", "-s", ADB_SERIAL, *args],
        capture_output=True, text=True, timeout=timeout,
    )


def _ensure_device() -> None:
    subprocess.run(["adb", "connect", ADB_SERIAL], capture_output=True, text=True, timeout=30)
    r = _adb("shell", "getprop", "sys.boot_completed")
    if r.stdout.strip() != "1":
        raise AnalyzerError(f"redroid({ADB_SERIAL}) not booted (sys.boot_completed={r.stdout.strip()!r})")


def _ensure_frida_server() -> None:
    """frida-server 가 안 떠 있으면 분리 실행으로 기동 (idempotent)."""
    r = _adb("shell", "pidof", "frida-server")
    if r.stdout.strip():
        return
    subprocess.run(["adb", "-s", ADB_SERIAL, "root"], capture_output=True, text=True, timeout=30)
    _adb("shell", f"setsid {FRIDA_SERVER_PATH} > /dev/null 2>&1 < /dev/null &")
    for _ in range(10):
        time.sleep(0.5)
        if _adb("shell", "pidof", "frida-server").stdout.strip():
            return
    raise AnalyzerError("frida-server 기동 실패 — VM 에서 frida-server push/실행 확인 필요")


def _wait_for_app_pid(package: str, timeout: int = 15) -> int | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        out = _adb("shell", "pidof", package).stdout.strip().split()
        if out:
            return int(out[0])
        time.sleep(0.4)
    return None


def _list_third_party() -> set[str]:
    r = _adb("shell", "pm", "list", "packages", "-3")
    return {
        line.split(":", 1)[1].strip()
        for line in r.stdout.splitlines()
        if ":" in line and line.strip()
    }


def _package_from_apk(apk_path: Path) -> str | None:
    """설치 diff 가 비었을 때 fallback — pyaxmlparser(있으면)로 패키지명 추출."""
    try:
        from pyaxmlparser import APK as _APK  # type: ignore
        return _APK(str(apk_path)).package
    except Exception:
        return None


def _run_frida(package: str, collect_seconds: int) -> list[dict]:
    import frida  # 지연 import — 모듈 없으면 명확한 에러

    hooks = HOOKS_JS.read_text(encoding="utf-8")
    device = frida.get_usb_device(timeout=10)
    messages: list[dict] = []
    errors: list[str] = []

    def on_message(message, _data):
        mtype = message.get("type")
        if mtype == "send":
            payload = message.get("payload")
            if isinstance(payload, dict):
                messages.append(payload)
        elif mtype == "error":
            err = message.get("description") or message.get("stack") or str(message)
            errors.append(err)
            log.warning("frida script error: %s", err)

    # 1순위: spawn (앱 시작 전부터 후킹 — 모든 행동 포착). Android 패키지는 *문자열*로 줘야 함
    # (리스트는 네이티브 argv 로 해석됨). redroid 에선 spawn 게이팅이 타임아웃날 수 있어
    # 2순위 fallback: am start 로 띄우고 attach (루프 fixture 라 늦게 붙어도 포착됨).
    spawned_pid = None
    try:
        pid = device.spawn(package)
        spawned_pid = pid
        mode = "spawn"
    except frida.TimedOutError:
        log.warning("spawn timed out — fallback to launch+attach (pkg=%s)", package)
        _adb("shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1", timeout=30)
        pid = _wait_for_app_pid(package)
        if not pid:
            raise AnalyzerError("앱 launch 실패 — spawn 타임아웃 + am start 후 pid 없음")
        mode = "attach"

    session = device.attach(pid)
    script = session.create_script(hooks)
    script.on("message", on_message)
    script.load()
    if spawned_pid is not None:
        device.resume(spawned_pid)
    log.info("frida %s: pkg=%s pid=%s collect=%ds", mode, package, pid, collect_seconds)
    time.sleep(collect_seconds)
    try:
        session.detach()
    except Exception:
        pass
    if spawned_pid is not None:
        try:
            device.kill(spawned_pid)
        except Exception:
            pass
    return messages, errors, mode


def analyze(apk_path: str | Path, collect_seconds: int | None = None) -> tuple[list[str], dict]:
    """APK 1개를 동적 분석. (detected_flags, observations) 반환."""
    apk_path = Path(apk_path)
    collect_seconds = collect_seconds or COLLECT_SECONDS
    t0 = time.time()

    _ensure_device()
    _ensure_frida_server()

    before = _list_third_party()
    inst = _adb("install", "-r", "-t", "-g", str(apk_path), timeout=120)
    out = (inst.stdout + inst.stderr)
    if inst.returncode != 0 or "Success" not in out:
        raise AnalyzerError(f"adb install 실패: {out.strip()[:300]}")

    after = _list_third_party()
    new_pkgs = after - before
    package = next(iter(new_pkgs), None) or _package_from_apk(apk_path)
    if not package:
        raise AnalyzerError("패키지명 식별 실패 (install diff 비었고 pyaxmlparser 없음)")

    try:
        # 오버레이는 런타임 권한이 아니라 appop — 명시 허용해야 fixture 가 addView 가능.
        _adb("shell", "appops", "set", package, "SYSTEM_ALERT_WINDOW", "allow")
        messages, script_errors, frida_mode = _run_frida(package, collect_seconds)
    finally:
        _adb("uninstall", package, timeout=60)

    flags = sorted({
        m["flag"] for m in messages
        if isinstance(m, dict) and m.get("flag") in VALID_FLAGS
    })
    script_loaded = next((m for m in messages if m.get("marker") == "script_loaded"), None)
    observations = {
        "package": package,
        "frida_mode": frida_mode,
        "collect_seconds": collect_seconds,
        "duration_ms": int((time.time() - t0) * 1000),
        "event_count": len(messages),
        "events": messages,
        "script_loaded": bool(script_loaded),
        "java_available": bool(script_loaded and script_loaded.get("java_available")),
        "hooks_installed": any(m.get("marker") == "hooks_installed" for m in messages),
        "script_errors": script_errors,
    }
    log.info("analyze done: pkg=%s flags=%s events=%d", package, flags, len(messages))
    return flags, observations
