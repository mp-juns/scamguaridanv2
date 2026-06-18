"""
학습 세션이 만든 체크포인트를 파이프라인에 swap 하기 위한 작은 helper.

`/admin/training` 의 "파이프라인 적용" 버튼이 `.scamguardian/active_models.json` 에
{"classifier": ".../output", "gliner": ".../output"} 형태로 기록한다.
이 모듈은 그 파일을 읽어 모델 경로를 반환한다 — 존재하지 않거나 깨졌으면 None.

캐시: 60초 TTL — 개발 중 잦은 재시작 없이도 새 활성화가 곧 반영된다.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

ACTIVE_POINTER = Path(".scamguardian") / "active_models.json"
_TTL_SEC = 60.0

_lock = threading.Lock()
_cache: dict[str, str] = {}
_cache_at: float = 0.0


def _read_raw() -> dict[str, str]:
    if not ACTIVE_POINTER.exists():
        return {}
    try:
        data = json.loads(ACTIVE_POINTER.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if isinstance(v, str)}


def get_active_path(role: str) -> str | None:
    """role 은 'classifier' | 'gliner' | 'gate' 중 하나. 없거나 경로 무효면 None."""
    global _cache, _cache_at
    now = time.time()
    with _lock:
        if now - _cache_at > _TTL_SEC:
            _cache = _read_raw()
            _cache_at = now
        path = _cache.get(role)
    if not path:
        return None
    if not Path(path).exists():
        return None
    return path


def invalidate() -> None:
    """관리자 활성화 직후 호출하면 다음 호출에서 즉시 재로드."""
    global _cache_at
    with _lock:
        _cache_at = 0.0
