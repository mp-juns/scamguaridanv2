"""사용자용 APK 분석 — 정적(Lv1 manifest + Lv2 bytecode) + VirusTotal 파일 스캔.

웹 허브의 `/apk` 화면이 호출하는 공개 엔드포인트. admin 의 `apk_dynamic` 와 달리
비동기 잡 없이 **동기 분석** 한다 — 정적 분석은 짧고 host-safe (androguard 가 코드를
*읽기만* 함, 실행 0). 동적(Lv3)은 격리 VM 이 필요하므로 기본 비활성으로 보고한다.

응답은 웹 `ApkClient` 의 `ApkReport` 형태(티어별 그룹 + VT 배지)로 직접 매핑된다.
"""

from __future__ import annotations

import asyncio
import os
import random
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

router = APIRouter()

_TAG = "Public"
_APK_ZIP_MAGIC = b"PK\x03\x04"
_MAX_APK_BYTES = 100 * 1024 * 1024  # 100MB

_ROOT = Path(__file__).resolve().parent.parent
# 사용자가 바로 테스트할 실제 APK 샘플 풀 — AndroZoo 실제 악성앱 + 큐레이트 패밀리 샘플.
_SAMPLE_DIRS = [
    _ROOT / "data" / "androzoo" / "malware",
    _ROOT / "data_examples" / "apk",
]
# 친숙한 패밀리 샘플 표시 이름.
_SAMPLE_NAMES = {
    "moqhao.apk": "MoqHao (택배 스미싱)",
    "krbanker.apk": "KrBanker (은행 앱 사칭)",
    "secretcalls.apk": "SecretCalls (보안앱 위장)",
    "fake_phishing.apk": "피싱 샘플",
    "dynamic_active.apk": "동적 행위 샘플",
}

# 🎬 시연용 데모 샘플 — Lv1·Lv2·Lv3 3 단계가 *항상* 검출되게 큐레이트.
# 실제 동적(Lv3)은 런타임 행위가 안 나오면 비어서 라이브 시연에 불안정 → 발표용 고정 결과.
# is_demo=True 로 표시해 실제 분석과 명확히 구분한다 (검출 보고만 — 판정 X).
_DEMO_SAMPLE_ID = "__demo_full__"
_DEMO_SAMPLE_LABEL = "🎬 시연용 샘플 (전체 단계 검출)"
_DEMO_REPORT: dict[str, Any] = {
    "apk_name": "voice_phishing_demo.apk",
    "apk_size": "4.7 MB",
    "package": "kr.gov.police.secure",
    "signal_count": 9,
    "tiers": [
        {
            "key": "static",
            "title": "Lv1 정적 · manifest",
            "verdict": "fail",
            "note": "AndroidManifest 권한·서명·패키지명 검사",
            "flags": [
                {"labelKo": "APK: 위험 권한 조합 (4종 이상)", "code": "apk_dangerous_permissions_combo"},
                {"labelKo": "APK: 자체 서명 인증서", "code": "apk_self_signed"},
                {"labelKo": "APK: 패키지명 위장 의심", "code": "apk_suspicious_package_name"},
            ],
        },
        {
            "key": "bytecode",
            "title": "Lv2 · bytecode",
            "verdict": "fail",
            "note": "DEX 정적 분석 (xref · string pool 패턴)",
            "flags": [
                {"labelKo": "APK: SMS 자동 발송 코드", "code": "apk_sms_auto_send_code"},
                {"labelKo": "APK: 접근성 서비스 악용", "code": "apk_accessibility_abuse"},
                {"labelKo": "APK: 사칭 키워드 string", "code": "apk_impersonation_keywords"},
            ],
        },
        {
            "key": "dynamic",
            "title": "Lv3 동적 · 격리 VM",
            "verdict": "fail",
            "note": "redroid + Frida 런타임 관찰",
            "flags": [
                {"labelKo": "APK: SMS 가로채기 (런타임)", "code": "apk_runtime_sms_intercepted"},
                {"labelKo": "APK: 화면 오버레이 공격 (런타임)", "code": "apk_runtime_overlay_attack"},
                {"labelKo": "APK: 자격증명 탈취 (런타임)", "code": "apk_runtime_credential_exfiltration"},
            ],
        },
    ],
    "vt": {
        "detected": 41,
        "total": 68,
        "permalink": "https://www.virustotal.com/gui/file/0000a6d452d58424a8b7613f175af5937f590033616b808bf8c0445695f82541",
        "categories": ["Android.Banker", "Trojan-Banker.AndroidOS.Agent", "apk.troj.banker"],
    },
    "summary": (
        "검찰·경찰 사칭 보이스피싱 악성앱 패턴이 3 단계 모두에서 검출되었습니다 — "
        "정적(자체 서명+위험 권한 조합), bytecode(SMS 자동발송+접근성 악용+사칭 키워드), "
        "동적(런타임 SMS 가로채기+오버레이+자격증명 탈취). 계좌 탈취형 악성앱의 전형입니다."
    ),
    "sample_label": _DEMO_SAMPLE_LABEL,
    "is_demo": True,
}


def _all_samples() -> dict[str, Path]:
    """sample_id(basename) → 실제 경로. 허용 디렉터리 안의 .apk 만."""
    out: dict[str, Path] = {}
    for d in _SAMPLE_DIRS:
        if not d.is_dir():
            continue
        for p in d.glob("*.apk"):
            if p.is_file():
                out[p.name] = p.resolve()
    return out


def _sample_label(name: str) -> str:
    if name in _SAMPLE_NAMES:
        return _SAMPLE_NAMES[name]
    stem = name[:-4] if name.endswith(".apk") else name
    if len(stem) >= 32:  # AndroZoo SHA256 파일명 — 앞 10자만
        return f"AndroZoo 악성앱 · {stem[:10]}…"
    return stem


def _label(code: str) -> str:
    from pipeline.config import FLAG_LABELS_KO

    return FLAG_LABELS_KO.get(code, code)


def _human_size(num: int) -> str:
    size = float(num)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"


def _flags_payload(codes: list[str]) -> list[dict[str, str]]:
    return [{"labelKo": _label(c), "code": c} for c in codes]


def _build_report(apk_path: str, apk_name: str, apk_size: int) -> dict[str, Any]:
    """정적 Lv1/Lv2 + 동적(보통 비활성) + VT 를 동기 실행해 티어 구조로 합친다."""
    from pipeline import apk_analyzer

    static = apk_analyzer.analyze_apk_static(apk_path)
    bytecode = apk_analyzer.analyze_apk_bytecode(apk_path)
    dynamic = apk_analyzer.analyze_apk_dynamic(apk_path)

    # androguard parse 자체가 실패하면(=APK 깨짐/형식 오류) 신호 0 이 아니라 '분석 실패'.
    if static.error and bytecode.error:
        raise HTTPException(
            status_code=400,
            detail="APK 를 해석하지 못했습니다 (손상되었거나 APK 형식이 아닙니다).",
        )

    static_flags = list(static.detected_flags)
    bytecode_flags = list(bytecode.detected_flags)
    dynamic_status = dynamic.status.value
    dynamic_completed = dynamic_status == "completed"
    dynamic_flags = list(dynamic.detected_flags) if dynamic_completed else []

    # 동적 상태를 정직하게 구분 — '실행 안 함'을 '이상 없음'으로 표기하면 안전 오인.
    #   completed → pass/fail (실제 결과)
    #   error     → 연결 실패 (VM 부팅됐어도 브릿지 끊김 등) — '미가동'과 다름
    #   blocked_local → 로컬 실행 차단
    #   disabled/not_configured → 비활성(미실행)
    if dynamic_completed:
        dynamic_verdict = "fail" if dynamic_flags else "pass"
        dynamic_note = "redroid + Frida 런타임 관찰"
    elif dynamic_status == "error":
        err = dynamic.error or ""
        # "remote http {5xx}" = VM 은 요청을 받았지만 *분석 자체*가 실패 (앱이 에뮬레이터에서
        # 실행 안 됨 등) → 연결 문제 아님. "remote call failed" = 진짜 연결/네트워크 실패.
        if err.startswith("remote http"):
            dynamic_verdict = "incomplete"
            dynamic_note = (
                "동적 분석 미완료 — 이 앱이 격리 VM 에서 실행되지 않았어요 "
                "(packing·anti-emulator 가능). 연결은 정상, 정적 Lv1·Lv2 는 수행됨."
            )
        else:
            dynamic_verdict = "error"
            dynamic_note = "동적 분석 연결 실패 — 격리 VM/네트워크 확인 필요 (정적 Lv1·Lv2 는 수행됨)"
    elif dynamic_status == "blocked_local":
        dynamic_verdict = "skipped"
        dynamic_note = "로컬 실행 차단 — 동적 분석은 격리 VM 에서만 허용"
    else:  # disabled / not_configured
        dynamic_verdict = "skipped"
        dynamic_note = "동적 분석 비활성 — 어드민에서 VM 가동 시 실행 (정적 Lv1·Lv2 만 수행)"

    tiers = [
        {
            "key": "static",
            "title": "Lv1 정적 · manifest",
            "verdict": "fail" if static_flags else "pass",
            "note": "AndroidManifest 권한·서명·패키지명 검사",
            "flags": _flags_payload(static_flags),
        },
        {
            "key": "bytecode",
            "title": "Lv2 · bytecode",
            "verdict": "fail" if bytecode_flags else "pass",
            "note": "DEX 정적 분석 (xref · string pool 패턴)",
            "flags": _flags_payload(bytecode_flags),
        },
        {
            "key": "dynamic",
            "title": "Lv3 동적 · 격리 VM",
            "verdict": dynamic_verdict,
            "note": dynamic_note,
            "flags": _flags_payload(dynamic_flags),
        },
    ]

    signal_count = len(static_flags) + len(bytecode_flags) + len(dynamic_flags)

    # VirusTotal — 키 있을 때만. 실패해도 분석은 계속.
    # permalink = VT GUI 상세 리포트(엔진별 탐지·행위·앱 정보), categories = "뭐가 위험한지".
    vt: dict[str, Any] | None = None
    if os.environ.get("VIRUSTOTAL_API_KEY"):
        try:
            from pipeline import safety

            sr = safety.scan_file(apk_path)
            if sr and sr.total_engines:
                vt = {
                    "detected": sr.detections,
                    "total": sr.total_engines,
                    "permalink": sr.permalink,
                    "categories": list(sr.threat_categories),
                }
        except Exception:  # noqa: BLE001 — VT 실패는 치명적이지 않음
            vt = None

    # 검출 사실만 요약 (판정 X — Identity Boundary).
    if signal_count == 0:
        summary = (
            "정적 분석(Lv1·Lv2)에서 알려진 악성 APK 신호가 검출되지 않았습니다. "
            "단, 정적 분석은 난독화·packing 된 변형을 놓칠 수 있어 '안전'을 보장하지 않습니다."
        )
    else:
        top = [_label(c) for c in (static_flags + bytecode_flags + dynamic_flags)][:3]
        summary = (
            f"정적 분석에서 위험 신호 {signal_count}개가 검출되었습니다 — {', '.join(top)} 등. "
            "ScamGuardian 은 검출 신호만 보고하며, 설치·실행은 격리 VM 에 위임합니다."
        )

    return {
        "apk_name": apk_name,
        "apk_size": _human_size(apk_size),
        "package": static.package_name or "(알 수 없음)",
        "signal_count": signal_count,
        "tiers": tiers,
        "vt": vt,
        "summary": summary,
        "is_demo": False,
    }


@router.post(
    "/api/analyze-apk",
    tags=[_TAG],
    summary="APK 정적 분석 (Lv1 manifest + Lv2 bytecode + VT)",
    description=(
        "안드로이드 설치 파일(.apk)을 업로드하면 정적 분석으로 위험 신호를 검출한다.\n\n"
        "- Lv1 정적(manifest 권한·서명·패키지명) + Lv2 bytecode(DEX xref·string) — host-safe, *읽기만*.\n"
        "- VirusTotal 파일 스캔 (VIRUSTOTAL_API_KEY 있을 때).\n"
        "- Lv3 동적(격리 VM 실행)은 기본 비활성 — 검출 사실만 보고, 판정은 통합 기업.\n\n"
        "최대 100MB. 로컬에서 APK 를 *실행하지 않는다*."
    ),
    responses={400: {"description": "APK 아님 / 빈 파일 / 크기 초과 / 해석 실패"}},
)
async def analyze_apk(
    file: UploadFile | None = File(None),
    sample: str | None = Form(None),
) -> dict[str, Any]:
    # 경로 0 — 시연용 데모 샘플: 3 단계 전체 검출 고정 결과 (실제 분석 X, is_demo 표시).
    if sample and sample.strip() == _DEMO_SAMPLE_ID:
        return dict(_DEMO_REPORT)

    # 경로 1 — 서버 측 샘플 APK(예시 앱) 분석. 업로드 없이 id 로 지정.
    if sample and sample.strip():
        samples = _all_samples()
        path = samples.get(Path(sample).name)  # basename 만 — traversal 차단
        if path is None or not str(path).startswith(str(_ROOT)):
            raise HTTPException(status_code=404, detail="알 수 없는 샘플 APK 입니다.")
        report = await asyncio.to_thread(
            _build_report, str(path), path.name, path.stat().st_size
        )
        report["sample_label"] = _sample_label(path.name)
        return report  # 샘플은 repo 파일 — 삭제 금지

    if file is None or not file.filename:
        raise HTTPException(status_code=400, detail="APK 파일이 필요합니다.")

    upload_dir = Path(".scamguardian") / "apk_public" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename).suffix or ".apk"
    tmp = tempfile.NamedTemporaryFile(
        mode="wb", delete=False, dir=str(upload_dir), prefix="apk_", suffix=suffix
    )
    tmp_path = Path(tmp.name)
    total = 0
    first = b""
    try:
        with tmp:
            while chunk := await file.read(1024 * 1024):
                if not first:
                    first = chunk[:4]
                total += len(chunk)
                if total > _MAX_APK_BYTES:
                    raise HTTPException(status_code=400, detail="APK 가 100MB 를 초과합니다.")
                tmp.write(chunk)
        if total == 0:
            raise HTTPException(status_code=400, detail="업로드된 파일이 비어 있습니다.")
        if first != _APK_ZIP_MAGIC:
            raise HTTPException(status_code=400, detail="APK(ZIP) 형식이 아닙니다.")

        report = await asyncio.to_thread(
            _build_report, str(tmp_path), file.filename, total
        )
        return report
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"APK 분석 실패: {exc}") from exc
    finally:
        tmp_path.unlink(missing_ok=True)


@router.get(
    "/api/apk-samples",
    tags=[_TAG],
    summary="테스트용 실제 APK 샘플 (무작위 10개)",
    description="AndroZoo 실제 악성앱 + 패밀리 샘플 풀에서 무작위 10개를 반환. 업로드 없이 바로 분석할 수 있다.",
)
async def apk_samples() -> dict[str, Any]:
    items = [{"id": name, "name": _sample_label(name)} for name in _all_samples()]
    random.shuffle(items)
    # 시연용 데모 샘플은 항상 맨 앞 (발표 시 3 단계 전체 검출 보장).
    demo = {"id": _DEMO_SAMPLE_ID, "name": _DEMO_SAMPLE_LABEL}
    return {"samples": [demo, *items[:9]], "total": len(items) + 1}


def _dynamic_ready() -> bool:
    """api_server 가 *실제로* 동적 분석 백엔드(격리 VM/브릿지)에 닿는지 ping.

    LED 가 단순 'VM 부팅됨'이 아니라 'Lv3 가 실제로 실행 가능'을 뜻하도록 —
    REMOTE_URL/health 를 짧은 timeout 으로 직접 확인 (analyze_apk_dynamic 가 쓰는 경로와 동일).
    """
    from pipeline import apk_analyzer

    if not apk_analyzer.APK_DYNAMIC_ENABLED:
        return False
    url = (apk_analyzer.APK_DYNAMIC_REMOTE_URL or "").strip().rstrip("/")
    token = (apk_analyzer.APK_DYNAMIC_REMOTE_TOKEN or "").strip()
    if not url:
        return False
    try:
        import requests

        headers = {"Authorization": f"Bearer {token}"} if token else {}
        resp = requests.get(f"{url}/health", headers=headers, timeout=3)
        return resp.status_code == 200
    except Exception:  # noqa: BLE001
        return False


@router.get(
    "/api/apk-dynamic-status",
    tags=[_TAG],
    summary="동적 분석 VM 가동 상태 (읽기 전용 LED)",
    description=(
        "사용자 화면 LED 용 — 동적(Lv3) 분석을 *실제로 실행 가능한지* 만 노출 (제어 X).\n\n"
        "`enabled`(APK_DYNAMIC_ENABLED) + `ready`(격리 VM/브릿지 /health 도달). "
        "VM 이 부팅돼도 브릿지가 끊겨 api_server 가 못 닿으면 ready=false 로 정직하게 표시."
    ),
)
async def apk_dynamic_status() -> dict[str, Any]:
    from pipeline import apk_analyzer

    enabled = bool(apk_analyzer.APK_DYNAMIC_ENABLED)
    ready = await asyncio.to_thread(_dynamic_ready) if enabled else False
    return {"enabled": enabled, "ready": ready}
