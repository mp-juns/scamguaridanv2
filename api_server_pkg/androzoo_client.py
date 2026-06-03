"""AndroZoo API 클라이언트 — 실제 악성/정상 APK 샘플 다운로드 + 메타데이터 스트리밍.

CLI(`scripts/androzoo.py`) 와 웹 벤치마크 엔드포인트가 공유한다. AndroZoo (Univ. of Luxembourg)
는 ~2400만 APK 와 VirusTotal 검출 수(`vt_detection`) 메타데이터를 제공한다.

⚠️ 받은 APK 는 실제 멀웨어일 수 있다 — ScamGuardian 은 정적 분석(읽기만) + 격리 VM 동적 분석만
하고 호스트에서 절대 실행하지 않는다 (apk_analyzer HARD BLOCK).

문서: https://androzoo.uni.lu/api_doc  /  인용: Allix et al. (2016) AndroZoo (MSR).
"""
from __future__ import annotations

import csv
import gzip
import io
import os
from pathlib import Path
from typing import Iterator

import requests

API_BASE = "https://androzoo.uni.lu"
DOWNLOAD_URL = f"{API_BASE}/api/download"
LIST_URL = f"{API_BASE}/static/lists/latest.csv.gz"
APK_ZIP_MAGIC = b"PK\x03\x04"


class AndroZooError(RuntimeError):
    pass


def api_key() -> str:
    key = (os.getenv("ANDROZOO_API_KEY") or "").strip()
    if not key:
        raise AndroZooError("ANDROZOO_API_KEY 환경변수가 없습니다.")
    return key


def download_apk(sha256: str, out_dir: str | Path, *, timeout: int = 300) -> Path:
    """SHA256 로 APK 를 받아 `{out_dir}/{sha256}.apk` 로 저장하고 경로 반환 (ZIP magic 검증)."""
    sha256 = sha256.strip().lower()
    if len(sha256) != 64:
        raise AndroZooError(f"잘못된 SHA256: {sha256[:16]}…")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"{sha256}.apk"
    if target.exists() and target.stat().st_size > 0:
        return target
    params = {"apikey": api_key(), "sha256": sha256}
    try:
        with requests.get(DOWNLOAD_URL, params=params, stream=True, timeout=timeout) as resp:
            if resp.status_code != 200:
                raise AndroZooError(f"다운로드 실패 {resp.status_code}: {resp.text[:120]}")
            with target.open("wb") as fp:
                for chunk in resp.iter_content(chunk_size=256 * 1024):
                    if chunk:
                        fp.write(chunk)
    except AndroZooError:
        target.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001
        target.unlink(missing_ok=True)
        raise AndroZooError(f"다운로드 오류: {exc}") from exc
    with target.open("rb") as fp:
        if fp.read(4) != APK_ZIP_MAGIC:
            target.unlink(missing_ok=True)
            raise AndroZooError("받은 파일이 APK(ZIP) 형식이 아닙니다.")
    return target


def iter_list_rows(*, timeout: int = 120) -> Iterator[dict]:
    """latest.csv.gz 를 스트리밍하며 dict row 를 yield (전체를 디스크에 받지 않음).

    컬럼: sha256,sha1,md5,dex_date,apk_size,pkg_name,vercode,vt_detection,vt_scan_date,dex_size,markets
    """
    with requests.get(LIST_URL, stream=True, timeout=timeout) as resp:
        resp.raise_for_status()
        gz = gzip.GzipFile(fileobj=resp.raw)
        reader = csv.DictReader(io.TextIOWrapper(gz, encoding="utf-8", errors="replace"))
        for row in reader:
            yield row


def sample_malware(
    count: int,
    *,
    min_vt: int = 10,
    pkg_filters: list[str] | None = None,
    max_scan: int = 1_000_000,
    progress=None,
) -> list[dict]:
    """리스트를 스트리밍하며 vt_detection >= min_vt 인 샘플을 count 개 골라 메타 dict 리스트 반환.

    각 dict: {sha256, pkg_name, vt_detection(int), apk_size, scanned(누적 스캔 행수)}.

    progress(scanned:int, found:int) -> bool|None — 25,000행마다 호출. True 반환 시 즉시 중단(취소).
    max_scan 초과해도 중단 (pkg_filters 가 희귀하면 무한 스캔 방지).
    """
    pkg_filters = [p.lower() for p in (pkg_filters or []) if p]
    picked: list[dict] = []
    scanned = 0
    for row in iter_list_rows():
        scanned += 1
        if progress is not None and scanned % 25_000 == 0:
            if progress(scanned, len(picked)):
                break
        if scanned > max_scan:
            break
        try:
            vt = int(row.get("vt_detection") or 0)
        except ValueError:
            continue
        if vt < min_vt:
            continue
        pkg = (row.get("pkg_name") or "").lower()
        if pkg_filters and not any(f in pkg for f in pkg_filters):
            continue
        picked.append({
            "sha256": row["sha256"],
            "pkg_name": row.get("pkg_name") or "",
            "vt_detection": vt,
            "apk_size": row.get("apk_size") or "",
        })
        if len(picked) >= count:
            break
    for p in picked:
        p["scanned"] = scanned
    return picked
