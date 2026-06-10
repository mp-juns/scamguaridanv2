"""증강 세션 러너 — subprocess 엔트리포인트 (병렬 실행).

`scripts/augment_user_samples.py` 의 per-seed 코어(`_augment_seed`)를 재사용하되,
순차 루프 대신 ThreadPoolExecutor 로 씨앗을 동시에 처리해 벽시계 시간을 단축한다.
진행 상황은 `training.augment_sessions.emit_metric` 으로 metrics.jsonl 에 한 줄씩 append.

웹 어드민(`training.augment_sessions.start_session`)이 이 모듈을 `python -m` 으로 띄운다.
직접 실행도 가능:
  python -m scripts.run_augment_session --seed-file data/processed/admin_seeds.jsonl \
    --output /tmp/aug.jsonl --variants 3 --concurrency 5

테스트/플럼빙용: 환경변수 SCAMGUARDIAN_AUGMENT_FAKE=1 이면 Claude API 호출 없이
결정론적 가짜 변형을 생성한다 (비용 0).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from training.augment_sessions import emit_metric


def _load_seeds(
    path: Path,
    scam_type: str | None,
    limit: int,
    content_label: str | None = None,
) -> list[dict[str, Any]]:
    seeds: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            if scam_type and (rec.get("scam_type") or "").strip() != scam_type:
                continue
            if content_label and (rec.get("content_label") or "").strip() != content_label:
                continue
            seeds.append(rec)
    if limit and limit > 0:
        seeds = seeds[:limit]
    return seeds


def _fake_variants(seed: dict[str, Any], n: int, round_no: int) -> list[dict[str, Any]]:
    """API 없이 결정론적 가짜 변형 — 테스트/플럼빙 전용."""
    base = (seed.get("text") or "").strip()
    st = seed.get("scam_type", "")
    cl = seed.get("content_label") or "scam_attempt"
    out: list[dict[str, Any]] = []
    for i in range(n):
        out.append({
            "text": f"[변형 r{round_no}-{i + 1}] {base}",
            "content_label": cl,
            "scam_type": st,
            "sample_kind": "augmented_llm",
            "source_ref": "augment_llm/fake",
            "seed_text": base,
            "entities": [],
            "risk_flags": [],
            "flag_groups": [],
            "rag_texts": [f"[변형 r{round_no}-{i + 1}] {base}"],
        })
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="증강 세션 러너 (병렬)")
    p.add_argument("--seed-file", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--variants", type=int, default=5)
    p.add_argument("--rounds", type=int, default=1)
    p.add_argument("--model", default=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"))
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--scam-type", default=None)
    p.add_argument("--content-label", default=None,
                   help="게이트 클래스 필터 (normal/scam_attempt/scam_news_edu). 비우면 전체.")
    args = p.parse_args()

    seed_path = Path(args.seed_file)
    seeds = _load_seeds(seed_path, args.scam_type, args.limit, args.content_label)
    rounds = max(1, args.rounds)
    concurrency = max(1, min(16, args.concurrency))
    # (seed, round) 작업 목록
    tasks = [(seed, r) for seed in seeds for r in range(1, rounds + 1)]
    total = len(tasks)
    emit_metric({"kind": "start", "total": total, "seeds": len(seeds), "rounds": rounds})
    print(f"씨앗 {len(seeds)}개 × {rounds}라운드 = {total} 작업 (동시성 {concurrency})", flush=True)

    if total == 0:
        emit_metric({"kind": "done", "total_generated": 0, "by_scam_type": {}})
        print("처리할 씨앗이 없습니다.", flush=True)
        return 0

    fake = os.getenv("SCAMGUARDIAN_AUGMENT_FAKE", "").strip().lower() in {"1", "true", "yes", "on"}
    client = None
    if not fake:
        from scripts.augment_user_samples import _augment_seed, _get_client
        client = _get_client()

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_lock = threading.Lock()
    by_type: Counter[str] = Counter()
    done = 0
    generated = 0

    def _run_one(seed: dict[str, Any], round_no: int) -> list[dict[str, Any]]:
        if fake:
            return _fake_variants(seed, args.variants, round_no)
        return _augment_seed(client, seed, args.variants, args.model, round_no)

    with out_path.open("w", encoding="utf-8") as fout, ThreadPoolExecutor(
        max_workers=concurrency
    ) as ex:
        futures = {ex.submit(_run_one, seed, r): (seed, r) for seed, r in tasks}
        for fut in as_completed(futures):
            seed, round_no = futures[fut]
            st = (seed.get("scam_type") or "").strip()
            try:
                recs = fut.result()
            except Exception as exc:  # noqa: BLE001
                done += 1
                emit_metric({
                    "kind": "augment", "done": done, "total": total,
                    "kept": 0, "scam_type": st, "error": f"{type(exc).__name__}: {exc}",
                })
                print(f"  [{done}/{total}] ⚠️ 실패 «{st}»: {exc}", flush=True)
                continue
            with write_lock:
                for r in recs:
                    fout.write(json.dumps(r, ensure_ascii=False) + "\n")
                fout.flush()
                done += 1
                generated += len(recs)
                if st:
                    by_type[st] += len(recs)
            emit_metric({
                "kind": "augment", "done": done, "total": total,
                "kept": len(recs), "generated": generated, "scam_type": st,
            })
            print(f"  [{done}/{total}] +{len(recs)}건 (누적 {generated}) «{st}»", flush=True)

    emit_metric({
        "kind": "done", "total_generated": generated,
        "by_scam_type": dict(by_type.most_common()),
    })
    print(f"✅ 완료: 총 {generated}건 → {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
