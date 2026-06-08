"""seed 증강 — 병렬 생성 + 일괄 검증 + 단일 append (속도 최적화판).

`augment_seeds.py`(순차) 의 deficit-aware 로직은 유지하되, 다음 구조로 개선한다:
  1. seed 당 작업을 ThreadPoolExecutor(concurrency) 로 **병렬** 생성 (API I/O 대기 겹침)
  2. worker 는 출력 파일에 **직접 쓰지 않음** — 결과를 메모리 리스트로 반환
  3. 실패(예외) seed 는 retry queue 로 최대 N 회 재시도
  4. 모든 worker 완료 후 **한 번에**: 스키마 검증 + 중복 text 제거 (기존 출력 + 신규 간)
  5. 검증 통과분만 출력 파일에 **단일 append** (원본 보존, 덮어쓰기 X)

deficit-aware: 각 seed 의 목표 = variants - (기존 출력의 augment_llm/{source_ref} 수). 0 이면 skip.
FAKE 모드(SCAMGUARDIAN_AUGMENT_FAKE=1): Claude 호출 없이 결정론적 변형 — 흐름 검증용(비용 0).

사용:
  python scripts/augment_seeds_concurrent.py \
    --seed-file data/processed/admin_seeds.jsonl \
    --output data/generated/user_samples_augmented.jsonl \
    --variants 20 --concurrency 4
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
_AUG_PREFIX = "augment_llm/"
REQUIRED_FIELDS = {"text", "content_label", "scam_type", "sample_kind", "source_ref"}


def _load_existing(path: Path) -> tuple[set[str], collections.Counter]:
    seen: set[str] = set()
    per_src: collections.Counter = collections.Counter()
    if not path.exists():
        return seen, per_src
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            continue
        if o.get("text"):
            seen.add(o["text"].strip())
        if o.get("source_ref"):
            per_src[o["source_ref"]] += 1
    return seen, per_src


def main() -> int:
    p = argparse.ArgumentParser(description="seed 증강 (병렬 생성 + 일괄 검증 + 단일 append)")
    p.add_argument("--seed-file", required=True)
    p.add_argument("--output", default="data/generated/user_samples_augmented.jsonl")
    p.add_argument("--variants", type=int, default=20)
    p.add_argument("--batch", type=int, default=5)
    p.add_argument("--buffer", type=int, default=3)
    p.add_argument("--max-tokens", type=int, default=8192)
    p.add_argument("--max-rounds", type=int, default=8)
    p.add_argument("--concurrency", type=int, default=4, help="병렬 worker 수 (4 기본, 6~8 까지 권장)")
    p.add_argument("--max-retries", type=int, default=2, help="실패 seed 재시도 횟수")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--tmp-dir", default="", help="worker 결과 임시 저장 디렉토리(생략 시 메모리)")
    args = p.parse_args()

    concurrency = max(1, min(8, args.concurrency))
    seeds = [json.loads(l) for l in Path(args.seed_file).read_text(encoding="utf-8").splitlines() if l.strip()]
    out_path = Path(args.output)
    existing_texts, per_src = _load_existing(out_path)

    # deficit-aware: seed 별 목표 = variants - 기존 수. 0 이면 skip.
    tasks: list[tuple[dict, int]] = []
    for s in seeds:
        have = per_src.get(f"{_AUG_PREFIX}{s.get('source_ref','')}", 0)
        target = args.variants - have
        if target > 0:
            tasks.append((s, target))
    skipped = len(seeds) - len(tasks)
    print(f"seed {len(seeds)}개 (목표 {args.variants}/seed) → {out_path}")
    print(f"  이미 충족 {skipped} skip / 처리 {len(tasks)} | concurrency={concurrency} | 기존 텍스트 {len(existing_texts)}")
    if not tasks:
        print("✅ 할 일 없음.")
        return 0

    fake = os.getenv("SCAMGUARDIAN_AUGMENT_FAKE", "").strip().lower() in {"1", "true", "yes", "on"}
    if fake:
        print("🧪 FAKE 모드 (Claude 호출 없음)")
        from scripts.run_augment_session import _fake_variants
        gen = None
    else:
        from scripts.augment_user_samples import _augment_seed, _get_client
        gen = _augment_seed
        client = _get_client()

    tmp_dir = Path(args.tmp_dir) if args.tmp_dir else None
    if tmp_dir:
        tmp_dir.mkdir(parents=True, exist_ok=True)

    # ── worker: 한 seed 의 변형 target 개를 생성해 records 리스트로 반환 (파일 쓰기 X) ──
    def work(seed: dict, target: int, idx: int) -> dict[str, Any]:
        src = seed.get("source_ref", "")
        local_seen: set[str] = set(existing_texts)  # 초기 스냅샷 기준(교차 dedup 은 최종 단계)
        collected: list[dict] = []
        round_no, empty_streak = 1, 0
        while len(collected) < target and round_no < args.max_rounds + 1:
            want = target - len(collected)
            if fake:
                recs = _fake_variants(seed, min(want, args.batch), round_no)
                # source_ref 를 실제 seed 기준으로 보정(흐름 검증 사실성)
                for r in recs:
                    r["source_ref"] = f"{_AUG_PREFIX}{src}"
                recs = [r for r in recs if r["text"].strip() not in local_seen]
            else:
                ask = min(want + args.buffer, args.batch)
                raw = gen(client, seed, ask, args.model, round_no, args.max_tokens)
                recs = []
                for r in raw:
                    t = (r.get("text") or "").strip()
                    if not t or t in local_seen:
                        continue
                    local_seen.add(t)
                    recs.append(r)
                    if len(collected) + len(recs) >= target:
                        break
            for r in recs:
                local_seen.add(r["text"].strip())
            collected.extend(recs)
            round_no += 1
            empty_streak = empty_streak + 1 if not recs else 0
            if empty_streak >= 2 and not fake:
                break
        collected = collected[:target]
        # tmp-dir 옵션 시 worker 결과를 임시 파일로도 남김
        if tmp_dir:
            (tmp_dir / f"worker_{idx:04d}.jsonl").write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in collected), encoding="utf-8"
            )
        return {"src": src, "target": target, "records": collected}

    # ── 병렬 실행 + retry queue ──
    pending = list(enumerate(tasks))  # (idx, (seed, target))
    results: dict[str, dict] = {}     # src -> {records, target}
    failures: dict[str, str] = {}
    for attempt in range(args.max_retries + 1):
        if not pending:
            break
        if attempt > 0:
            print(f"  ↻ 재시도 {attempt}/{args.max_retries} — {len(pending)} seed")
        next_pending: list = []
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            fut = {ex.submit(work, s, t, idx): (idx, s, t) for idx, (s, t) in pending}
            for f in as_completed(fut):
                idx, s, t = fut[f]
                src = s.get("source_ref", "")
                try:
                    res = f.result()
                    results[src] = {"records": res["records"], "target": t}
                    failures.pop(src, None)
                    print(f"  ✓ [{idx}] {src} +{len(res['records'])}/{t}")
                except Exception as exc:  # noqa: BLE001
                    failures[src] = f"{type(exc).__name__}: {exc}"
                    next_pending.append((idx, (s, t)))
                    print(f"  ✗ [{idx}] {src} 실패: {exc}")
        pending = next_pending

    # ── 일괄 검증 + 중복 제거 (모든 worker 완료 후 한 번에) ──
    combined: list[dict] = []
    for r in results.values():
        combined.extend(r["records"])
    schema_bad = 0
    seen_text: set[str] = set(existing_texts)  # 기존 + 신규 간 text 중복 제거
    deduped: list[dict] = []
    dup_text = 0
    for rec in combined:
        if not isinstance(rec, dict) or (REQUIRED_FIELDS - set(rec)):
            schema_bad += 1
            continue
        try:
            json.dumps(rec, ensure_ascii=False)
        except (TypeError, ValueError):
            schema_bad += 1
            continue
        t = rec["text"].strip()
        if t in seen_text:
            dup_text += 1
            continue
        seen_text.add(t)
        deduped.append(rec)

    print(f"\n검증: 생성 {len(combined)} → 스키마탈락 {schema_bad} / 중복text제거 {dup_text} → 유효 {len(deduped)}")

    # ── 단일 append (검증 통과분만) ──
    if deduped:
        with out_path.open("a", encoding="utf-8") as fout:
            for rec in deduped:
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"✅ 단일 append: +{len(deduped)}건 → {out_path}")

    # per-seed 보고
    by_src = collections.Counter(rec["source_ref"] for rec in deduped)
    print("seed(source_ref)별 추가:")
    for k in sorted(by_src):
        print(f"   +{by_src[k]:3d}  {k}")
    if failures:
        print(f"⚠️ 최종 실패 seed {len(failures)}개:")
        for k, v in failures.items():
            print(f"   {k}: {v}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
