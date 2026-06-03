#!/usr/bin/env python3
"""Check ScamGuardian main-server connectivity to the APK dynamic VM."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _masked(value: str) -> str:
    if not value:
        return "-"
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "..." + value[-4:]


def _print_json(label: str, payload: Any) -> None:
    print(label)
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", default=str(ROOT / ".env"), help="env file to read before checking")
    parser.add_argument("--url", default="", help="override APK_DYNAMIC_REMOTE_URL")
    parser.add_argument("--token", default="", help="override APK_DYNAMIC_REMOTE_TOKEN")
    parser.add_argument("--apk", default="", help="optional APK path to POST to /dynamic-analyze")
    parser.add_argument("--timeout", type=int, default=20, help="request timeout seconds")
    args = parser.parse_args()

    _load_env_file(Path(args.env_file))
    url = (args.url or os.getenv("APK_DYNAMIC_REMOTE_URL", "")).strip().rstrip("/")
    token = (args.token or os.getenv("APK_DYNAMIC_REMOTE_TOKEN", "")).strip()

    if not url:
        print("APK_DYNAMIC_REMOTE_URL is missing", file=sys.stderr)
        return 2

    print(f"[apk-dynamic] url={url}")
    print(f"[apk-dynamic] token={_masked(token)}")

    try:
        resp = requests.get(f"{url}/health", timeout=args.timeout)
    except requests.RequestException as exc:
        print(f"[apk-dynamic] health failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"[apk-dynamic] health http={resp.status_code}")
    try:
        health = resp.json()
    except ValueError:
        health = {"raw": resp.text[:500]}
    _print_json("[apk-dynamic] health body:", health)
    if resp.status_code != 200:
        return 1

    if not args.apk:
        return 0

    if not token:
        print("APK_DYNAMIC_REMOTE_TOKEN is required when --apk is used", file=sys.stderr)
        return 2

    apk_path = Path(args.apk)
    if not apk_path.is_absolute():
        apk_path = ROOT / apk_path
    if not apk_path.is_file():
        print(f"APK file not found: {apk_path}", file=sys.stderr)
        return 2

    headers = {"Authorization": f"Bearer {token}"}
    try:
        with apk_path.open("rb") as f:
            resp = requests.post(
                f"{url}/dynamic-analyze",
                headers=headers,
                files={"apk": (apk_path.name, f, "application/vnd.android.package-archive")},
                timeout=max(args.timeout, int(os.getenv("APK_DYNAMIC_TIMEOUT", "180"))),
            )
    except requests.RequestException as exc:
        print(f"[apk-dynamic] analyze failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"[apk-dynamic] analyze http={resp.status_code}")
    try:
        body = resp.json()
    except ValueError:
        body = {"raw": resp.text[:1000]}
    _print_json("[apk-dynamic] analyze body:", body)
    return 0 if resp.status_code == 200 else 1


if __name__ == "__main__":
    raise SystemExit(main())
