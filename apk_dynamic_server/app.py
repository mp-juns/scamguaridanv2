"""
ScamGuardian APK 동적 분석 서버 — production 호스트와 분리된 격리 VM 안에서 동작.

이 서버:
- POST /dynamic-analyze (multipart files=apk) 만 받음
  (production 의 pipeline.apk_analyzer._analyze_apk_dynamic_remote 가 호출)
- 받은 APK 를 redroid(Android-in-Docker) 에 설치 → Frida 후킹으로 런타임 행동 관찰
- { detected_flags: [...], observations: {...} } 반환
- DB 없음, API 키 없음, 사용자 데이터 없음 — 털려도 잃을 게 없는 ephemeral 노드

배포:
- 별도 Multipass VM / Hyper-V VM / 클라우드 VPS (production 호스트와 *다른 머신*)
- redroid 컨테이너 + frida-server 가 떠 있어야 함 (apk_dynamic_server/README.md 참고)

인증:
- Bearer token — production 과 사전 공유한 비밀. 환경변수 APK_DYNAMIC_SERVER_TOKEN.
  (production 측 APK_DYNAMIC_REMOTE_TOKEN 과 같은 값이어야 함)

네트워크 정책 (배포 시):
- inbound: production 서버 IP 에서만 허용 (firewall)
- outbound(REAL 단계): mitmproxy egress 통제 필수 (README)
"""

from __future__ import annotations

import logging
import os
import secrets
import shutil
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Header, HTTPException, UploadFile

try:
    from . import analyzer
except ImportError:  # `cd apk_dynamic_server && python3 app.py` 실행 호환
    import analyzer  # type: ignore

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s %(message)s")
log = logging.getLogger("apk_dynamic_server")

SERVER_TOKEN = os.getenv("APK_DYNAMIC_SERVER_TOKEN")
MAX_APK_BYTES = int(os.getenv("APK_DYNAMIC_MAX_BYTES", str(150 * 1024 * 1024)))  # 150MB

if not SERVER_TOKEN:
    log.warning("APK_DYNAMIC_SERVER_TOKEN 미설정 — 인증 비활성화. 운영에선 반드시 설정.")

app = FastAPI(title="ScamGuardian APK Dynamic Analyzer", version="0.1")


def _check_auth(authorization: str | None) -> None:
    if not SERVER_TOKEN:
        return  # dev 모드 — 인증 skip
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    presented = authorization.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(SERVER_TOKEN, presented):
        raise HTTPException(status_code=401, detail="invalid token")


@app.get("/health")
def health() -> dict[str, Any]:
    import subprocess
    booted = False
    try:
        r = subprocess.run(
            ["adb", "-s", analyzer.ADB_SERIAL, "shell", "getprop", "sys.boot_completed"],
            capture_output=True, text=True, timeout=10,
        )
        booted = r.stdout.strip() == "1"
    except Exception:
        pass
    return {
        "status": "ok",
        "adb_serial": analyzer.ADB_SERIAL,
        "redroid_booted": booted,
        "auth": bool(SERVER_TOKEN),
        "collect_seconds": analyzer.COLLECT_SECONDS,
    }


@app.post("/dynamic-analyze")
async def dynamic_analyze(
    apk: UploadFile = File(...),
    authorization: str | None = Header(default=None),
) -> dict[str, Any]:
    _check_auth(authorization)

    run_id = uuid.uuid4().hex[:12]
    workdir = Path(tempfile.mkdtemp(prefix=f"apkdyn-{run_id}-"))
    apk_path = workdir / "sample.apk"

    t0 = time.time()
    try:
        size = 0
        with apk_path.open("wb") as f:
            while chunk := await apk.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_APK_BYTES:
                    raise HTTPException(status_code=413, detail="apk too large")
                f.write(chunk)
        # APK(ZIP) 매직 확인 — 잘못된 입력 차단.
        with apk_path.open("rb") as f:
            if f.read(4) != b"PK\x03\x04":
                raise HTTPException(status_code=400, detail="not a valid apk (zip magic missing)")

        log.info("dynamic-analyze start: run_id=%s size=%dB", run_id, size)
        flags, observations = analyzer.analyze(apk_path)
        observations["run_id"] = run_id
        log.info("dynamic-analyze done: run_id=%s flags=%s %dms",
                 run_id, flags, int((time.time() - t0) * 1000))
        return {"detected_flags": flags, "observations": observations}

    except HTTPException:
        raise
    except analyzer.AnalyzerError as exc:
        log.warning("analyzer error: run_id=%s %s", run_id, exc)
        raise HTTPException(status_code=502, detail=f"analyzer: {exc}")
    except Exception as exc:
        log.exception("dynamic-analyze failed: run_id=%s", run_id)
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(workdir, ignore_errors=True)  # stateless — 분석 후 APK 즉시 삭제


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", "8002"))
    uvicorn.run(app, host="0.0.0.0", port=port)
