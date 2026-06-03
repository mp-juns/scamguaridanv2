"""
ScamGuardian v3 — Phase 0 안전성 필터 (VirusTotal 클라이언트)

분석 대상이 URL·파일일 때 *기존 파이프라인 진입 전*에 악성 여부를 검사한다.
정책: 악성 탐지돼도 분석은 계속 진행하되(policy b), `malware_detected` /
`phishing_url_confirmed` 플래그를 자동 트리거해 점수에 가산하고 결과 카드
최상단에 경고를 띄운다.

VT 무료 티어: 4 req/min · 500 req/day. 해시 lookup 은 즉답, 신규 파일은
업로드 + 폴링(최대 30s). 4 req/min 한도는 단순 인메모리 토큰 버킷으로 제어.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from base64 import urlsafe_b64encode
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import requests

log = logging.getLogger("safety")

VT_API_BASE = "https://www.virustotal.com/api/v3"
VT_TIMEOUT = 15
VT_UPLOAD_MAX_BYTES = 32 * 1024 * 1024  # VT free tier 32MB
VT_ANALYSIS_POLL_INTERVAL = 3
VT_ANALYSIS_MAX_WAIT = 30


class ThreatLevel(str, Enum):
    SAFE = "safe"
    UNKNOWN = "unknown"
    SUSPICIOUS = "suspicious"
    MALICIOUS = "malicious"


@dataclass
class SafetyResult:
    target_kind: str  # "url" | "file"
    target: str       # url 자체 또는 파일명
    scanner: str = "virustotal"
    threat_level: ThreatLevel = ThreatLevel.UNKNOWN
    detections: int = 0          # malicious 탐지 엔진 수
    suspicious: int = 0          # suspicious 엔진 수
    total_engines: int = 0
    threat_categories: list[str] = field(default_factory=list)
    permalink: str | None = None
    error: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_malicious(self) -> bool:
        return self.threat_level == ThreatLevel.MALICIOUS

    @property
    def is_suspicious(self) -> bool:
        return self.threat_level in (ThreatLevel.SUSPICIOUS, ThreatLevel.MALICIOUS)

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_kind": self.target_kind,
            "target": self.target,
            "scanner": self.scanner,
            "threat_level": self.threat_level.value,
            "detections": self.detections,
            "suspicious": self.suspicious,
            "total_engines": self.total_engines,
            "threat_categories": list(self.threat_categories),
            "permalink": self.permalink,
            "error": self.error,
        }


# ──────────────────────────────────
# 레이트 리미팅 (4 req/min) — 단순 토큰 버킷
# ──────────────────────────────────
_RATE_LOCK = threading.Lock()
_RATE_WINDOW_SEC = 60.0
_RATE_MAX = int(os.getenv("VIRUSTOTAL_RPM", "4"))
_rate_timestamps: list[float] = []


def _rate_limit_acquire() -> None:
    while True:
        with _RATE_LOCK:
            now = time.time()
            # 윈도우 밖의 호출 제거
            cutoff = now - _RATE_WINDOW_SEC
            while _rate_timestamps and _rate_timestamps[0] < cutoff:
                _rate_timestamps.pop(0)
            if len(_rate_timestamps) < _RATE_MAX:
                _rate_timestamps.append(now)
                return
            wait = _RATE_WINDOW_SEC - (now - _rate_timestamps[0]) + 0.1
        log.info("VT rate limit 도달 → %.1fs 대기", wait)
        time.sleep(max(wait, 0.5))


def _api_key() -> str | None:
    return os.getenv("VIRUSTOTAL_API_KEY")


def _classify_stats(stats: dict[str, int]) -> ThreatLevel:
    """VT last_analysis_stats → ThreatLevel.

    탐지 엔진 수 기준:
    - malicious >= 3 → MALICIOUS
    - malicious >= 1 또는 suspicious >= 2 → SUSPICIOUS
    - 그 외 → SAFE (분석 결과 있음 + 위 기준 미달)
    """
    malicious = int(stats.get("malicious", 0))
    suspicious = int(stats.get("suspicious", 0))
    if malicious >= 3:
        return ThreatLevel.MALICIOUS
    if malicious >= 1 or suspicious >= 2:
        return ThreatLevel.SUSPICIOUS
    return ThreatLevel.SAFE


def _categories_from_results(results: dict[str, Any]) -> list[str]:
    """탐지 엔진들이 매긴 카테고리 모음 (중복 제거, 상위 5개)."""
    counter: dict[str, int] = {}
    for engine_result in results.values() if isinstance(results, dict) else []:
        cat = (engine_result or {}).get("category")
        if cat in (None, "undetected", "type-unsupported", "harmless"):
            continue
        # 'malicious' / 'suspicious' 자체보단 result 의 키워드가 더 정보량 ↑
        result_str = (engine_result or {}).get("result")
        key = str(result_str or cat)
        counter[key] = counter.get(key, 0) + 1
    return [k for k, _ in sorted(counter.items(), key=lambda x: -x[1])[:5]]


def _vt_request(method: str, path: str, **kwargs) -> requests.Response:
    key = _api_key()
    if not key:
        raise EnvironmentError("VIRUSTOTAL_API_KEY 가 설정되지 않았습니다.")
    headers = kwargs.pop("headers", {}) or {}
    headers["x-apikey"] = key
    _rate_limit_acquire()
    resp = requests.request(
        method,
        f"{VT_API_BASE}{path}",
        headers=headers,
        timeout=VT_TIMEOUT,
        **kwargs,
    )
    try:
        from platform_layer import cost as _cost
        _cost.record_virustotal(1, action=f"{method} {path}")
    except Exception:
        pass
    return resp


def family_label_by_sha256(sha256: str) -> str | None:
    """이미 VT 에 알려진 파일의 SHA256 으로 멀웨어 패밀리/위협 라벨을 조회한다 (업로드 없음).

    `popular_threat_classification.suggested_threat_label` (예: "trojan.airpush/dowgin") 우선,
    없으면 popular_threat_name 1순위. VT 키 없음/미상/오류 시 None — best-effort 보강용.
    """
    if not _api_key():
        return None
    try:
        resp = _vt_request("GET", f"/files/{sha256.strip().lower()}")
        if resp.status_code != 200:
            return None
        attrs = (resp.json().get("data") or {}).get("attributes") or {}
        ptc = attrs.get("popular_threat_classification") or {}
        label = ptc.get("suggested_threat_label")
        if label:
            return label
        names = ptc.get("popular_threat_name") or []
        if names and isinstance(names[0], dict):
            return names[0].get("value")
        return None
    except Exception:  # noqa: BLE001
        return None


# ──────────────────────────────────
# URL 스캔
# ──────────────────────────────────
def _vt_url_id(url: str) -> str:
    """VT 문서대로 URL 의 id = base64url(url) (= 스트립).

    https://docs.virustotal.com/reference/url
    """
    return urlsafe_b64encode(url.encode("utf-8")).decode("ascii").rstrip("=")


def scan_url(url: str) -> SafetyResult:
    result = SafetyResult(target_kind="url", target=url)
    if not _api_key():
        result.error = "VIRUSTOTAL_API_KEY 없음 — 스캔 skip"
        return result

    try:
        url_id = _vt_url_id(url)
        resp = _vt_request("GET", f"/urls/{url_id}")
        if resp.status_code == 404:
            # URL 처음 보는 경우 — 스캔 큐잉 후 폴링
            submit = _vt_request("POST", "/urls", data={"url": url})
            if submit.status_code not in (200, 201):
                result.error = f"VT URL 제출 실패: HTTP {submit.status_code}"
                return result
            analysis_id = submit.json().get("data", {}).get("id")
            if not analysis_id:
                result.error = "VT URL 제출 응답 비어 있음"
                return result
            _wait_for_analysis(analysis_id)
            resp = _vt_request("GET", f"/urls/{url_id}")
        if resp.status_code != 200:
            result.error = f"VT URL 조회 실패: HTTP {resp.status_code}"
            return result

        data = resp.json().get("data", {})
        attrs = data.get("attributes", {})
        stats = attrs.get("last_analysis_stats", {}) or {}
        results_map = attrs.get("last_analysis_results", {}) or {}

        result.threat_level = _classify_stats(stats)
        result.detections = int(stats.get("malicious", 0))
        result.suspicious = int(stats.get("suspicious", 0))
        result.total_engines = sum(int(v) for v in stats.values() if isinstance(v, (int, float)))
        result.threat_categories = _categories_from_results(results_map)
        result.permalink = f"https://www.virustotal.com/gui/url/{url_id}"
        result.raw = {"stats": stats}
    except requests.RequestException as exc:
        result.error = f"VT 통신 오류: {exc}"
    except Exception as exc:  # noqa: BLE001 — 안전성 모듈은 절대 파이프라인을 죽이면 안 됨
        log.warning("scan_url 예외: %s", exc, exc_info=True)
        result.error = f"내부 오류: {exc}"
    return result


# ──────────────────────────────────
# 파일 스캔
# ──────────────────────────────────
def _sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        while True:
            data = fp.read(chunk)
            if not data:
                break
            h.update(data)
    return h.hexdigest()


def _wait_for_analysis(analysis_id: str) -> dict[str, Any]:
    """VT analysis 가 completed 가 될 때까지 폴링."""
    deadline = time.time() + VT_ANALYSIS_MAX_WAIT
    while time.time() < deadline:
        resp = _vt_request("GET", f"/analyses/{analysis_id}")
        if resp.status_code == 200:
            data = resp.json().get("data", {})
            status = data.get("attributes", {}).get("status")
            if status == "completed":
                return data
        time.sleep(VT_ANALYSIS_POLL_INTERVAL)
    return {}


def scan_file(path: str | Path) -> SafetyResult:
    p = Path(path)
    result = SafetyResult(target_kind="file", target=p.name)
    if not _api_key():
        result.error = "VIRUSTOTAL_API_KEY 없음 — 스캔 skip"
        return result
    if not p.exists() or not p.is_file():
        result.error = "파일이 존재하지 않습니다"
        return result

    try:
        sha256 = _sha256_of(p)
        # 해시 lookup (캐시 hit 시 즉답)
        resp = _vt_request("GET", f"/files/{sha256}")

        if resp.status_code == 404:
            # 처음 보는 파일 — 업로드
            size = p.stat().st_size
            if size > VT_UPLOAD_MAX_BYTES:
                result.error = f"파일이 VT 무료 업로드 한도(32MB) 초과 — 크기 {size} bytes"
                return result
            with p.open("rb") as fp:
                files = {"file": (p.name, fp)}
                submit = _vt_request("POST", "/files", files=files)
            if submit.status_code not in (200, 201):
                result.error = f"VT 업로드 실패: HTTP {submit.status_code}"
                return result
            analysis_id = submit.json().get("data", {}).get("id")
            if not analysis_id:
                result.error = "VT 업로드 응답 비어 있음"
                return result
            _wait_for_analysis(analysis_id)
            resp = _vt_request("GET", f"/files/{sha256}")

        if resp.status_code != 200:
            result.error = f"VT 파일 조회 실패: HTTP {resp.status_code}"
            return result

        attrs = resp.json().get("data", {}).get("attributes", {})
        stats = attrs.get("last_analysis_stats", {}) or {}
        results_map = attrs.get("last_analysis_results", {}) or {}

        result.threat_level = _classify_stats(stats)
        result.detections = int(stats.get("malicious", 0))
        result.suspicious = int(stats.get("suspicious", 0))
        result.total_engines = sum(int(v) for v in stats.values() if isinstance(v, (int, float)))
        result.threat_categories = _categories_from_results(results_map)
        result.permalink = f"https://www.virustotal.com/gui/file/{sha256}"
        result.raw = {"sha256": sha256, "stats": stats}
    except requests.RequestException as exc:
        result.error = f"VT 통신 오류: {exc}"
    except Exception as exc:  # noqa: BLE001
        log.warning("scan_file 예외: %s", exc, exc_info=True)
        result.error = f"내부 오류: {exc}"
    return result


# ──────────────────────────────────
# 통합 진입점 — runner 가 호출
# ──────────────────────────────────
def safety_check(*, url: str | None = None, file_path: str | Path | None = None) -> SafetyResult | None:
    """입력 종류에 맞춰 스캔. 둘 다 None 이면 None 반환 (텍스트는 검사 대상 X)."""
    if url:
        return scan_url(url)
    if file_path:
        return scan_file(file_path)
    return None
