"""APK 정적 분석 — Lv 1 (manifest·권한·서명) + Lv 2 (dex bytecode 패턴 매칭).

Identity (CLAUDE.md): 검출 시스템. 점수·등급 산정 안 함. 검출된 flag list 만 반환.

⚠️ 정확한 학술 용어:
- **정적 분석 (static analysis)** — APK 의 manifest·권한·서명·bytecode 를 *읽기만* 함
- **심화 정적 분석 (bytecode pattern matching)** — Lv 2. 코드는 읽지만 *실행 안 함*
- **동적 분석 (dynamic analysis)** — APK 를 에뮬레이터 안에서 *실제 실행* 후 behavior 모니터링
  → ScamGuardian 은 동적 분석 하지 않음. future work (호스트 위험 + 5-7 주 작업).

⚠️ False positive 한계 (CLAUDE.md `검출률에 대한 정직한 표현` 참조):
- 정상 메신저 앱도 SmsManager 사용 (인증 코드 발송)
- 정상 앱도 AccessibilityService 사용 (장애인 보조)
- 뉴스 앱도 "검찰" / "경찰" 같은 키워드 가질 수 있음
→ **단일 신호만으로 사기 판정 X**. 권한 조합·서명·패턴 *누적* 시점에서만 강한 신호.
   판정은 통합 기업의 자체 logic 에 위임 (Identity Boundary).

학술 기준 정적 분석 검출률은 60-80%. 정교히 난독화·packing·reflection 다 쓴 APK 는
정적 분석 영역 밖이며, 그건 진짜 동적 분석 자리.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

log = logging.getLogger("apk_analyzer")


# ──────────────────────────────────────────────
# Lv 1 — manifest·권한·서명 분석에 사용되는 list
# ──────────────────────────────────────────────

# 한국 보이스피싱 패밀리에서 자주 보이는 위험 권한 조합 (S2W TALON 보고서 기반).
# 단독으로는 정상 앱도 일부 가질 수 있음 — 4개 이상 동시는 매우 의심.
_DANGEROUS_PERMISSION_COMBO: frozenset[str] = frozenset({
    "android.permission.SEND_SMS",
    "android.permission.READ_SMS",
    "android.permission.RECEIVE_SMS",
    "android.permission.READ_CALL_LOG",
    "android.permission.PROCESS_OUTGOING_CALLS",
    "android.permission.BIND_ACCESSIBILITY_SERVICE",
    "android.permission.SYSTEM_ALERT_WINDOW",
})

# Lv 1 임계 — 위험 권한 4 종 이상 동시 보유 시 의심 패턴
_DANGEROUS_PERMISSION_THRESHOLD = 4

# 정상 한국 앱 패키지명 — typo-squatting 위장 탐지용
_LEGITIMATE_PACKAGE_PATTERNS: tuple[str, ...] = (
    "com.kakao.talk",                    # 카카오톡
    "com.kakao.story",
    "com.kakao.taxi",
    "com.nhn.android.search",            # 네이버
    "com.nhn.android.naverlogin",
    "com.nhn.android.band",
    "net.daum.android.daum",             # 다음
    "kr.co.shinhan",                     # 신한은행
    "com.shinhan.sbanking",
    "com.kbstar.kbbank",                 # 국민은행
    "com.kbstar.minibank",
    "nh.smart",                          # 농협
    "com.wooribank.smart.npib",          # 우리은행
    "com.ibk.spdmb",                     # 기업은행
    "com.hanabank.ebk.channel.android.hananbank",  # 하나은행
    "com.coocaa.market.smartstore",
)

# 패키지명 위장 의심 suffix
_SUSPICIOUS_PACKAGE_SUFFIXES: tuple[str, ...] = (
    "fake", "test", "_v2", "_new", "official", "_2024", "_2025",
)


# ──────────────────────────────────────────────
# Lv 2 — bytecode 패턴 매칭에 사용되는 list
# ──────────────────────────────────────────────

# bytecode string pool 에서 찾을 사칭 시나리오 키워드.
# 정상 뉴스·보안 앱도 일부 가질 수 있어 *단독* 신호로는 약함 — 다른 신호와 누적 평가.
_IMPERSONATION_KEYWORDS: frozenset[str] = frozenset({
    "검찰", "경찰", "금감원", "금융감독원",
    "수사", "구속", "체포", "고소",
    "안전계좌", "보안승급", "보안카드",
    "사칭", "피해자", "압수수색",
})

# C&C URL 패턴 — IP 직접·무료 도메인·비표준 포트
_SUSPICIOUS_URL_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r"https?://\d+\.\d+\.\d+\.\d+(?::\d+)?/"),  # IP 주소 직접
    re.compile(r"\.(tk|ml|ga|cf|gq)/", re.IGNORECASE),     # 무료 도메인
    re.compile(r":\d{4,5}/"),                              # 비표준 포트 (1024~65535)
)

# 난독화 휴리스틱 임계 — 1-2 글자 클래스명 비율 > 30% + 클래스 50개 초과
_OBFUSCATION_SHORT_NAME_LIMIT = 2
_OBFUSCATION_RATIO_THRESHOLD = 0.30
_OBFUSCATION_MIN_CLASSES = 50


# ──────────────────────────────────────────────
# 입력 감지
# ──────────────────────────────────────────────


def is_apk_file(path: str | Path) -> bool:
    """경로가 APK 파일인지 확인. 확장자 + ZIP magic bytes 둘 다."""
    try:
        p = Path(path)
        if not p.is_file():
            return False
        if p.suffix.lower() == ".apk":
            return True
        # APK 는 ZIP container — PK\x03\x04 magic
        with p.open("rb") as f:
            head = f.read(4)
        return head == b"PK\x03\x04"
    except Exception:  # noqa: BLE001 — 분석 입력 감지가 죽으면 안 됨
        return False


# ──────────────────────────────────────────────
# Lv 1 — manifest·권한·서명 분석
# ──────────────────────────────────────────────


@dataclass
class APKStaticReport:
    """Lv 1 정적 분석 결과 — 검출된 flag + 메타데이터."""
    detected_flags: list[str] = field(default_factory=list)
    package_name: str = ""
    permissions: list[str] = field(default_factory=list)
    is_self_signed: bool = False
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "detected_flags": list(self.detected_flags),
            "package_name": self.package_name,
            "permissions": self.permissions,
            "is_self_signed": self.is_self_signed,
            "error": self.error,
        }


def analyze_apk_static(apk_path: str | Path) -> APKStaticReport:
    """APK 정적 분석 — manifest 권한 / 서명 / 패키지명 검사.

    분석은 *읽기만* 함 (코드 실행 0). 검출된 flag list + 메타 반환.
    실패 시 빈 result 에 error 메시지 기록 (분석은 죽으면 안 됨).
    """
    try:
        from androguard.core.apk import APK
        apk = APK(str(apk_path))
    except Exception as exc:  # noqa: BLE001
        log.warning("apk parse 실패: %s", exc)
        return APKStaticReport(error=f"parse_failed: {exc}")

    detected: list[str] = []

    # 1) 위험 권한 조합 — 4 종 이상 동시 보유
    perms = sorted(set(apk.get_permissions()))
    dangerous_count = len(set(perms) & _DANGEROUS_PERMISSION_COMBO)
    if dangerous_count >= _DANGEROUS_PERMISSION_THRESHOLD:
        detected.append("apk_dangerous_permissions_combo")

    # 2) 자체 서명 vs 공인 인증
    self_signed = _check_self_signed(apk)
    if self_signed:
        detected.append("apk_self_signed")

    # 3) 패키지명 위장 — 정상 앱 typo-squatting
    package = (apk.get_package() or "").strip()
    if _is_suspicious_impersonation(package):
        detected.append("apk_suspicious_package_name")

    return APKStaticReport(
        detected_flags=detected,
        package_name=package,
        permissions=perms,
        is_self_signed=self_signed,
    )


def _check_self_signed(apk) -> bool:
    """공인 keystore vs 자체 서명 휴리스틱.

    Google Play 등록 앱은 보통 회사 verified keystore (subject ≠ issuer 또는 다른 CA).
    사이드로딩 APK 는 거의 자체 서명 (subject == issuer).
    """
    try:
        certs = apk.get_certificates_v3() or apk.get_certificates_v2() or apk.get_certificates_v1()
        if not certs:
            return True
        for cert in certs:
            try:
                # asn1crypto.x509.Certificate.subject / .issuer 는 Name 객체
                subject = cert.subject.human_friendly
                issuer = cert.issuer.human_friendly
            except AttributeError:
                # 구버전 또는 다른 type — str() 비교
                subject = str(cert.subject)
                issuer = str(cert.issuer)
            if subject == issuer:
                return True
        return False
    except Exception as exc:  # noqa: BLE001
        log.warning("certificate check 실패 (보수적으로 self-signed 간주): %s", exc)
        return True


def _is_suspicious_impersonation(package: str) -> bool:
    """정상 앱 패키지명 위장 패턴."""
    if not package:
        return False
    pkg = package.lower()
    # typo-squatting — 정상 패키지명 prefix 포함하지만 정확 일치 X
    for legit in _LEGITIMATE_PACKAGE_PATTERNS:
        if pkg.startswith(legit) and pkg != legit:
            return True
    # 의심 suffix
    if any(sfx in pkg for sfx in _SUSPICIOUS_PACKAGE_SUFFIXES):
        return True
    return False


# ──────────────────────────────────────────────
# Lv 2 — dex bytecode 패턴 매칭
# ──────────────────────────────────────────────


@dataclass
class APKBytecodeReport:
    """Lv 2 심화 정적 분석 결과 — 검출된 flag list."""
    detected_flags: list[str] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "detected_flags": list(self.detected_flags),
            "error": self.error,
        }


def analyze_apk_bytecode(apk_path: str | Path) -> APKBytecodeReport:
    """dex bytecode 패턴 매칭. 검출된 flag list 반환.

    이건 *심화 정적 분석* (static analysis) — 코드는 읽지만 실행하지 않음.
    실제 동적 behavior (네트워크 트래픽, 파일 시스템, runtime API) 모니터링은
    future work — Android 에뮬레이터 통합 영역.
    """
    try:
        from androguard.misc import AnalyzeAPK
        apk_obj, dex_objs, analysis = AnalyzeAPK(str(apk_path))
    except Exception as exc:  # noqa: BLE001
        log.warning("AnalyzeAPK 실패: %s", exc)
        return APKBytecodeReport(error=f"analyze_failed: {exc}")

    detected: list[str] = []

    # 1) SMS 자동 발송 — SmsManager.sendTextMessage
    if _has_method_xref(analysis, "Landroid/telephony/SmsManager;", "sendTextMessage"):
        detected.append("apk_sms_auto_send_code")

    # 2) 통화 상태 감시 — TelephonyManager.listen
    if _has_method_xref(analysis, "Landroid/telephony/TelephonyManager;", "listen"):
        detected.append("apk_call_state_listener")

    # 3) AccessibilityService 악용 — 클래스 상속 또는 관련 import
    if _references_accessibility_service(analysis):
        detected.append("apk_accessibility_abuse")

    # 4) 사칭 키워드 — dex string pool
    if _contains_string_keywords(dex_objs, _IMPERSONATION_KEYWORDS):
        detected.append("apk_impersonation_keywords")

    # 5) Hard-coded C&C URL 패턴 — IP 직접 / 무료 도메인 / 비표준 포트
    if _has_suspicious_url_constants(dex_objs):
        detected.append("apk_hardcoded_c2_url")

    # 6) 난독화 흔적 — 짧은 random 클래스명 비율
    if _looks_obfuscated(analysis):
        detected.append("apk_string_obfuscation")

    # 7) Device admin 화면 잠금 — DevicePolicyManager.lockNow
    if _has_method_xref(analysis, "Landroid/app/admin/DevicePolicyManager;", "lockNow"):
        detected.append("apk_device_admin_lock")

    return APKBytecodeReport(detected_flags=detected)


def _has_method_xref(analysis, class_descriptor: str, method_name: str) -> bool:
    """bytecode 안에서 특정 method 호출 (xref) 발견 여부.

    `class_descriptor` 는 dalvik 형식 (`Landroid/...;`).
    """
    try:
        for method in analysis.get_methods():
            try:
                xrefs = list(method.get_xref_to())
            except Exception:
                continue
            for entry in xrefs:
                # androguard 4.x: (cls, call, offset) 또는 (cls, call) 가능 — 변동
                call = entry[1] if len(entry) >= 2 else None
                if call is None:
                    continue
                cls_name = getattr(call, "class_name", "")
                m_name = getattr(call, "name", "")
                if cls_name == class_descriptor and m_name == method_name:
                    return True
    except Exception as exc:  # noqa: BLE001
        log.debug("method xref 탐색 실패 (무시): %s", exc)
    return False


def _contains_string_keywords(dex_objs, keywords: frozenset[str]) -> bool:
    """dex string pool 에서 키워드 등장 여부."""
    try:
        for dex in dex_objs:
            try:
                strings = dex.get_strings()
            except Exception:
                continue
            for s in strings:
                try:
                    s_str = str(s)
                except Exception:
                    continue
                if any(kw in s_str for kw in keywords):
                    return True
    except Exception as exc:  # noqa: BLE001
        log.debug("string pool 탐색 실패: %s", exc)
    return False


def _has_suspicious_url_constants(dex_objs) -> bool:
    """dex string pool 에서 의심 URL 패턴 (IP 직접 / 무료 도메인 / 비표준 포트)."""
    try:
        for dex in dex_objs:
            try:
                strings = dex.get_strings()
            except Exception:
                continue
            for s in strings:
                try:
                    s_str = str(s)
                except Exception:
                    continue
                if any(p.search(s_str) for p in _SUSPICIOUS_URL_PATTERNS):
                    return True
    except Exception as exc:  # noqa: BLE001
        log.debug("URL pattern 탐색 실패: %s", exc)
    return False


def _looks_obfuscated(analysis) -> bool:
    """난독화 휴리스틱 — 1-2 글자 클래스명 비율 + 클래스 수 임계.

    ProGuard/DexGuard 사용 흔적. 정상 라이브러리 (kotlin/coroutines 등) 도
    일부 짧은 이름 가지므로 *비율 임계 + 최소 클래스 수* 둘 다 만족 시에만 True.
    """
    try:
        short = 0
        total = 0
        for cls in analysis.get_classes():
            total += 1
            cls_name = getattr(cls, "name", "") or ""
            # Lcom/example/Foo; → Foo
            short_name = cls_name.split("/")[-1].rstrip(";")
            if 1 <= len(short_name) <= _OBFUSCATION_SHORT_NAME_LIMIT:
                short += 1
        if total >= _OBFUSCATION_MIN_CLASSES and short / total > _OBFUSCATION_RATIO_THRESHOLD:
            return True
    except Exception as exc:  # noqa: BLE001
        log.debug("obfuscation 휴리스틱 실패: %s", exc)
    return False


def _references_accessibility_service(analysis) -> bool:
    """`AccessibilityService` 상속 클래스 존재 여부.

    상속 자체는 정상 앱(장애인 보조) 도 가능 — 단독 신호로는 약함.
    다른 신호 (위험 권한 조합·은행 사칭 패키지명 등) 와 누적 시 강함.
    """
    try:
        for cls in analysis.get_classes():
            extends = getattr(cls, "extends", "") or ""
            if "AccessibilityService" in str(extends):
                return True
    except Exception as exc:  # noqa: BLE001
        log.debug("accessibility 탐색 실패: %s", exc)
    return False


# ──────────────────────────────────────────────
# Lv 3 — 동적 분석 (Android 에뮬레이터 behavior 모니터링) — 인터페이스만
# ──────────────────────────────────────────────
#
# ⚠️ **로컬 실행 절대 금지 (HARD BLOCK)** — APK 를 호스트에서 직접 실행하면
#    멀웨어가 호스트를 감염시킬 수 있다 (root escalation, 데이터 유출 등).
#    v3.5 sandbox.py 의 격리 정책과 동일 — production 호스트 ↔ sandbox VM 분리.
#
# **운영 시점에서만 의미** — 별도 VM/VPS 안에 Android 에뮬레이터 + Frida/MobSF
# stack 을 띄우고, ScamGuardian 은 그 VM 에 HTTPS 로 호출만. APK 는 그쪽에서
# 격리 실행되고 behavior 결과 (network call / SMS 가로채기 / overlay / 자격증명
# 탈취 / 지속성 install 등) 만 받아온다.
#
# **현재 상태**: 인터페이스 + flag 카탈로그만 박힘. 실제 remote VM 통합은
# future work. 기본 비활성 — `APK_DYNAMIC_ENABLED=0` (default).
#
# 환경변수:
# - `APK_DYNAMIC_ENABLED` — 0(기본) / 1
# - `APK_DYNAMIC_BACKEND` — auto / local / remote (auto: REMOTE_URL+TOKEN 있으면 remote)
# - `APK_DYNAMIC_REMOTE_URL` — Android 에뮬레이터 stack 이 도는 별도 VM 주소
# - `APK_DYNAMIC_REMOTE_TOKEN` — 그 VM 과 공유하는 Bearer 토큰
# - `APK_DYNAMIC_TIMEOUT` — emulator run timeout (초, 기본 180)


APK_DYNAMIC_ENABLED = os.getenv("APK_DYNAMIC_ENABLED", "0") == "1"
APK_DYNAMIC_BACKEND = os.getenv("APK_DYNAMIC_BACKEND", "auto").lower()  # auto | local | remote
APK_DYNAMIC_REMOTE_URL = os.getenv("APK_DYNAMIC_REMOTE_URL", "").strip().rstrip("/")
APK_DYNAMIC_REMOTE_TOKEN = os.getenv("APK_DYNAMIC_REMOTE_TOKEN", "").strip()
APK_DYNAMIC_TIMEOUT = int(os.getenv("APK_DYNAMIC_TIMEOUT", "180"))


class APKDynamicStatus(str, Enum):
    DISABLED = "disabled"           # APK_DYNAMIC_ENABLED=0 기본
    BLOCKED_LOCAL = "blocked_local"  # 로컬 실행 시도 — HARD BLOCK 정책상 절대 안 돌림
    NOT_CONFIGURED = "not_configured"  # remote backend 인데 URL/TOKEN 없음
    SKIPPED_STATIC = "skipped_static"  # Lv1/Lv2 정적 분석에서 이미 신호 검출 — VM 호출 생략
    COMPLETED = "completed"         # remote VM 에서 정상 완료
    ERROR = "error"                 # remote 호출 실패


@dataclass
class APKDynamicReport:
    """Lv 3 동적 분석 결과 — 격리 VM 안에서 실제 실행 후 behavior 모니터링.

    ⚠️ 실제 APK 실행은 remote 격리 VM 에서만 수행한다.
    로컬 실행은 절대 안 함 (호스트 위험).
    """
    status: APKDynamicStatus = APKDynamicStatus.DISABLED
    detected_flags: list[str] = field(default_factory=list)
    backend: str = ""                   # 실제로 시도한 backend (local / remote)
    duration_ms: int = 0
    error: str = ""
    raw_observations: dict[str, Any] | None = None  # remote VM 가 보내는 raw behavior 로그

    def to_dict(self) -> dict:
        return {
            "status": self.status.value,
            "detected_flags": list(self.detected_flags),
            "backend": self.backend,
            "duration_ms": self.duration_ms,
            "error": self.error,
            "raw_observations": self.raw_observations,
        }


def _resolved_dynamic_backend() -> str:
    """auto 면 REMOTE_URL+TOKEN 둘 다 있을 때 remote, 아니면 local."""
    if APK_DYNAMIC_BACKEND in ("local", "remote"):
        return APK_DYNAMIC_BACKEND
    if APK_DYNAMIC_REMOTE_URL and APK_DYNAMIC_REMOTE_TOKEN:
        return "remote"
    return "local"


def configure_remote(
    url: str,
    token: str,
    *,
    enabled: bool = True,
    timeout: int | None = None,
) -> None:
    """런타임에 remote 동적 분석 설정을 주입한다 (VM 기동 후 컨트롤러가 호출).

    `analyze_apk_dynamic` / `_analyze_apk_dynamic_remote` 는 모듈 레벨 상수를 읽으므로,
    서버 재시작 없이 VM 을 켠 직후 이 함수로 상수를 갱신하면 즉시 remote 분석이 가능하다.
    (테스트의 monkeypatch.setattr 와 동일한 메커니즘 — env 가 아니라 모듈 상수.)
    """
    global APK_DYNAMIC_ENABLED, APK_DYNAMIC_BACKEND
    global APK_DYNAMIC_REMOTE_URL, APK_DYNAMIC_REMOTE_TOKEN, APK_DYNAMIC_TIMEOUT
    APK_DYNAMIC_ENABLED = enabled
    APK_DYNAMIC_BACKEND = "remote"
    APK_DYNAMIC_REMOTE_URL = (url or "").strip().rstrip("/")
    APK_DYNAMIC_REMOTE_TOKEN = (token or "").strip()
    if timeout is not None:
        APK_DYNAMIC_TIMEOUT = int(timeout)


def analyze_apk_dynamic(apk_path: str | Path) -> APKDynamicReport:
    """Lv 3 동적 분석 진입점. 기본 비활성.

    정책:
    - `APK_DYNAMIC_ENABLED=0` (기본) → status=DISABLED, 즉시 반환
    - backend=`local` → **HARD BLOCK** (status=BLOCKED_LOCAL). 호스트 위험.
      로컬 실행 정책은 *어떤 경우에도* 풀지 않음. 격리 VM 만 허용.
    - backend=`remote` → REMOTE_URL+TOKEN 둘 다 있어야 동작. 없으면 NOT_CONFIGURED.
    """
    if not APK_DYNAMIC_ENABLED:
        return APKDynamicReport(
            status=APKDynamicStatus.DISABLED,
            error="APK_DYNAMIC_ENABLED=0 (기본). 동적 분석은 격리 VM 필요 — 호스트 안전상 기본 비활성.",
        )

    backend = _resolved_dynamic_backend()
    if backend == "local":
        # ⚠️ HARD BLOCK — 로컬 실행은 호스트 멀웨어 감염 위험.
        # ScamGuardian 은 이 경로를 *절대* 활성화하지 않는다. 격리 VM 통과 필수.
        log.warning(
            "APK 동적 분석 로컬 실행 시도 차단 — backend=local 은 호스트 위험. "
            "APK_DYNAMIC_BACKEND=remote + REMOTE_URL+TOKEN 설정 필요."
        )
        return APKDynamicReport(
            status=APKDynamicStatus.BLOCKED_LOCAL,
            backend="local",
            error="local execution forbidden — APK 동적 분석은 격리 VM 에서만 허용. APK_DYNAMIC_BACKEND=remote 사용.",
        )

    # backend == "remote"
    if not (APK_DYNAMIC_REMOTE_URL and APK_DYNAMIC_REMOTE_TOKEN):
        return APKDynamicReport(
            status=APKDynamicStatus.NOT_CONFIGURED,
            backend="remote",
            error="APK_DYNAMIC_REMOTE_URL / APK_DYNAMIC_REMOTE_TOKEN 둘 다 설정 필요.",
        )

    return _analyze_apk_dynamic_remote(apk_path)


def _analyze_apk_dynamic_remote(apk_path: str | Path) -> APKDynamicReport:
    """별도 VM 의 Android 에뮬레이터 stack 에 APK 업로드 → behavior 결과 수신.

    현재 *stub* — 실제 remote VM 측 서버는 별도 작업 (sandbox_server/ 와 동일 패턴).
    호출 자체는 동작하지만 받는 schema 가 합의 안 된 상태이므로
    *완전한 stub* 으로 명시. flag 매핑은 응답 받으면 추가.
    """
    import time as _time

    import requests

    t0 = _time.time()
    try:
        with Path(apk_path).open("rb") as f:
            resp = requests.post(
                f"{APK_DYNAMIC_REMOTE_URL}/dynamic-analyze",
                headers={"Authorization": f"Bearer {APK_DYNAMIC_REMOTE_TOKEN}"},
                files={"apk": f},
                timeout=APK_DYNAMIC_TIMEOUT,
            )
        elapsed = int((_time.time() - t0) * 1000)
        if resp.status_code != 200:
            return APKDynamicReport(
                status=APKDynamicStatus.ERROR,
                backend="remote",
                duration_ms=elapsed,
                error=f"remote http {resp.status_code}: {resp.text[:200]}",
            )
        body = resp.json()
        raw_flags = body.get("detected_flags") or []
        # 안전 검증: 알 수 없는 flag 차단 — Lv 3 candidate set 안에 있어야 함
        from pipeline.config import DETECTED_FLAGS as _DF
        validated = [f for f in raw_flags if isinstance(f, str) and f in _DF]
        return APKDynamicReport(
            status=APKDynamicStatus.COMPLETED,
            backend="remote",
            detected_flags=validated,
            duration_ms=elapsed,
            raw_observations=body.get("observations"),
        )
    except requests.RequestException as exc:
        elapsed = int((_time.time() - t0) * 1000)
        return APKDynamicReport(
            status=APKDynamicStatus.ERROR,
            backend="remote",
            duration_ms=elapsed,
            error=f"remote call failed: {type(exc).__name__}: {exc}",
        )
