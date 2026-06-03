#!/usr/bin/env python3
"""WSL-local HTTP bridge to the Multipass APK dynamic-analysis VM.

The main ScamGuardian server can call this bridge at http://127.0.0.1:18002.
The bridge uses multipass transfer/exec to reach the VM-local dynamic server,
so it does not depend on WSL routing to the Multipass NAT subnet.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse

ROOT = Path(__file__).resolve().parents[1]
VM_NAME = os.getenv("APK_DYNAMIC_VM_NAME", "sg-sandbox")
VM_WORKDIR = os.getenv("APK_DYNAMIC_VM_WORKDIR", "/home/ubuntu/sg-apkdyn")
SERVER_PORT = os.getenv("APK_DYNAMIC_SERVER_PORT", "8002")
SERVER_TOKEN = os.getenv("APK_DYNAMIC_SERVER_TOKEN") or os.getenv("APK_DYNAMIC_REMOTE_TOKEN", "dev-secret-123")
MULTIPASS_EXE = os.getenv("MULTIPASS_EXE", "/mnt/c/Program Files/Multipass/bin/multipass.exe")
MAX_APK_BYTES = int(os.getenv("APK_DYNAMIC_MAX_BYTES", str(150 * 1024 * 1024)))

app = FastAPI(title="ScamGuardian APK Dynamic WSL Bridge", version="0.1")


def _check_auth(authorization: str | None) -> None:
    if not SERVER_TOKEN:
        return
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(SERVER_TOKEN, token):
        raise HTTPException(status_code=401, detail="invalid token")


def _run(args: list[str], timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def _mp(*args: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    return _run([MULTIPASS_EXE, *args], timeout=timeout)


def _vm_curl(path: str, timeout: int = 30) -> tuple[int, Any, str]:
    cmd = f"curl -sS -w '\\n%{{http_code}}' http://127.0.0.1:{SERVER_PORT}{path}"
    r = _mp("exec", VM_NAME, "--", "bash", "-lc", cmd, timeout=timeout)
    if r.returncode != 0:
        return 502, {"error": r.stderr.strip() or r.stdout.strip()}, r.stderr
    body, _, code_s = r.stdout.rpartition("\n")
    try:
        code = int(code_s.strip())
    except ValueError:
        code = 502
    try:
        parsed = json.loads(body) if body.strip() else {}
    except json.JSONDecodeError:
        parsed = {"raw": body}
    return code, parsed, r.stderr


@app.get("/health")
def health() -> JSONResponse:
    code, body, stderr = _vm_curl("/health", timeout=20)
    if isinstance(body, dict):
        body = dict(body)
        body["bridge"] = "wsl-multipass"
        if stderr.strip():
            body["bridge_stderr"] = stderr.strip()[:500]
    return JSONResponse(status_code=code, content=body)


@app.post("/dynamic-analyze")
async def dynamic_analyze(
    apk: UploadFile = File(...),
    authorization: str | None = Header(default=None),
) -> JSONResponse:
    _check_auth(authorization)

    run_id = uuid.uuid4().hex[:12]
    local_dir = Path(tempfile.mkdtemp(prefix=f"apkbridge-{run_id}-"))
    local_apk = local_dir / "sample.apk"
    vm_dir = f"{VM_WORKDIR}/bridge-inbox/{run_id}"
    vm_apk = f"{vm_dir}/sample.apk"

    try:
        size = 0
        with local_apk.open("wb") as f:
            while chunk := await apk.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_APK_BYTES:
                    raise HTTPException(status_code=413, detail="apk too large")
                f.write(chunk)

        with local_apk.open("rb") as f:
            if f.read(4) != b"PK\x03\x04":
                raise HTTPException(status_code=400, detail="not a valid apk (zip magic missing)")

        mk = _mp("exec", VM_NAME, "--", "bash", "-lc", f"mkdir -p {vm_dir!r}", timeout=30)
        if mk.returncode != 0:
            raise HTTPException(status_code=502, detail=f"bridge mkdir failed: {mk.stderr[:300]}")

        win_local = _run(["wslpath", "-w", str(local_apk)], timeout=10).stdout.strip()
        tr = _mp("transfer", win_local, f"{VM_NAME}:{vm_apk}", timeout=120)
        if tr.returncode != 0:
            raise HTTPException(status_code=502, detail=f"bridge transfer failed: {tr.stderr[:300]}")

        curl_cmd = (
            f"curl -sS -w '\\n%{{http_code}}' -X POST "
            f"http://127.0.0.1:{SERVER_PORT}/dynamic-analyze "
            f"-H 'Authorization: Bearer {SERVER_TOKEN}' "
            f"-F apk=@{vm_apk!r}"
        )
        r = _mp("exec", VM_NAME, "--", "bash", "-lc", curl_cmd, timeout=int(os.getenv("APK_DYNAMIC_TIMEOUT", "180")) + 60)
        if r.returncode != 0:
            raise HTTPException(status_code=502, detail=f"bridge remote curl failed: {r.stderr[:500]}")
        raw, _, code_s = r.stdout.rpartition("\n")
        try:
            code = int(code_s.strip())
        except ValueError:
            code = 502
        try:
            body: Any = json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            body = {"raw": raw}
        if isinstance(body, dict):
            body.setdefault("observations", {})
            if isinstance(body["observations"], dict):
                body["observations"]["bridge"] = "wsl-multipass"
        return JSONResponse(status_code=code, content=body)
    finally:
        shutil.rmtree(local_dir, ignore_errors=True)
        _mp("exec", VM_NAME, "--", "bash", "-lc", f"rm -rf {vm_dir!r}", timeout=30)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("APK_DYNAMIC_BRIDGE_PORT", "18002"))
    uvicorn.run(app, host="127.0.0.1", port=port)
