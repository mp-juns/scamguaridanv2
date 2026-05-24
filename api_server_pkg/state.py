"""모듈 전역 상태 — 카카오 멀티턴 잡, 결과 토큰, 백그라운드 task 보관.

여러 라우터·헬퍼가 공유하므로 한 곳에 모아둔다. 단일 프로세스 가정 (수평 확장 시 외부 store 필요).
"""

from __future__ import annotations

import asyncio
import threading
import time
from typing import Any

# 카카오 콜백 타임아웃 — 카카오 60초 한도, 여유 5초
KAKAO_CALLBACK_TIMEOUT = 55
# 폴링 모드 최대 대기 (STT/분석 백그라운드 시간)
KAKAO_POLL_TIMEOUT = 600
# 완료된 결과 보관 시간 (초)
KAKAO_JOB_TTL = 600

# 결과 상세 페이지 토큰 TTL — 카카오 카드의 "자세히 보기" 링크
RESULT_TOKEN_TTL = 3600

# user_id → job state dict (구조는 kakao.new_job_state 참조)
pending_jobs: dict[str, dict[str, Any]] = {}
# 다중 사용자 동시 접속 race 방지
jobs_lock = threading.Lock()

# asyncio bg task 가 GC 되지 않도록 보관
bg_tasks: set[asyncio.Task] = set()

# token → {result, user_context, input_type, expires_at, user_id, chat_history}
result_tokens: dict[str, dict[str, Any]] = {}

# 공개 URL 캐시 — get_public_base_url() 60초 캐시 + cloudflared 로그 mtime 무효화
public_url_cache: dict[str, Any] = {"url": "", "expires": 0.0, "log_mtime": 0.0}


def spawn_bg(coro) -> asyncio.Task:
    """asyncio bg task 등록 + GC 방지 참조 보관."""
    task = asyncio.create_task(coro)
    bg_tasks.add(task)
    task.add_done_callback(bg_tasks.discard)
    return task


def _record_poll_unsafe(job: dict[str, Any]) -> tuple[int, int, bool]:
    """jobs_lock 이 *이미 잡혀있을 때* 호출. 잡 dict 직접 받아 lock 재획득 없이 처리.

    `record_poll` 은 lock 을 자기가 잡지만, 호출자가 이미 with state.jobs_lock 안에서
    부르면 reentrant 가 안 되는 threading.Lock 특성상 deadlock 발생 — 그 케이스용.
    """
    now = time.time()
    if "first_poll_at" not in job:
        job["first_poll_at"] = now
    job["poll_count"] = job.get("poll_count", 0) + 1
    elapsed = max(0, int(now - job["first_poll_at"]))
    return elapsed, job["poll_count"], bool(job.get("stt_done"))


def record_poll(user_id: str) -> tuple[int, int, bool]:
    """결과확인 polling 한 번을 기록.

    Returns:
        (elapsed_sec, poll_count, stt_done)
        — 잡 없으면 (0, 0, False) 반환.
        elapsed_sec 은 첫 polling 시점부터 경과 초.
        poll_count 는 이번 호출 포함 누적 횟수 (1, 2, 3, ...).

    이미 jobs_lock 안에 있다면 `_record_poll_unsafe(job)` 를 직접 부르세요.
    """
    with jobs_lock:
        job = pending_jobs.get(user_id)
        if job is None:
            return 0, 0, False
        return _record_poll_unsafe(job)
