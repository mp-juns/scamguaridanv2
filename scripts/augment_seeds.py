"""명시한 seed 파일을 씨앗당 N 변형으로 증강해 기존 출력에 **append** 한다.

신규 seed 만 골라 증강할 때 쓴다(top-up 과 달리 deficit 계산 없이 seed 파일 그대로).
`augment_user_samples._augment_seed` 코어 재사용. 긴 씨앗 max_tokens 오버플로를 피하려
호출당 batch 로 쪼개 여러 라운드 누적하고, **기존 출력 텍스트 + seed 내부** 와 dedup 한다.
출력은 절대 덮어쓰지 않는다(mode="a").

사용:
  python scripts/augment_seeds.py \
    --seed-file data/processed/pending_admin_draft_seeds.jsonl \
    --output data/generated/user_samples_augmented.jsonl \
    --variants 20 --batch 5 --max-tokens 8192
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")


def _load_existing(path: Path) -> tuple[set[str], collections.Counter]:
    """기존 출력에서 (전체 텍스트 집합, source_ref 별 변형 수) — dedup + deficit 계산용."""
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
    p = argparse.ArgumentParser(description="명시 seed 증강 → 출력에 append")
    p.add_argument("--seed-file", required=True)
    p.add_argument("--output", default="data/generated/user_samples_augmented.jsonl")
    p.add_argument("--variants", type=int, default=20, help="씨앗당 목표 변형 수")
    p.add_argument("--batch", type=int, default=5, help="호출당 최대 변형 요청 수")
    p.add_argument("--buffer", type=int, default=3)
    p.add_argument("--max-tokens", type=int, default=8192)
    p.add_argument("--max-rounds", type=int, default=8)
    p.add_argument("--model", default=DEFAULT_MODEL)
    args = p.parse_args()

    seeds = [json.loads(l) for l in Path(args.seed_file).read_text(encoding="utf-8").splitlines() if l.strip()]
    out_path = Path(args.output)
    existing, per_src = _load_existing(out_path)
    # deficit-aware: 이미 목표만큼 있는 seed 는 skip (크래시 후 재실행 안전 / idempotent)
    todo = [s for s in seeds if per_src.get(f"augment_llm/{s.get('source_ref','')}", 0) < args.variants]
    skipped = len(seeds) - len(todo)
    print(f"seed {len(seeds)}개 (목표 {args.variants}변형/seed) → {out_path}")
    print(f"  이미 충족 {skipped}개 skip / 처리 대상 {len(todo)}개 (기존 텍스트 {len(existing)}개와 dedup)")
    seeds = todo

    fake = os.getenv("SCAMGUARDIAN_AUGMENT_FAKE", "").strip().lower() in {"1", "true", "yes", "on"}
    if fake:
        print("🧪 FAKE 모드 (비용 0)")
        from scripts.run_augment_session import _fake_variants
        augment = None
    else:
        from scripts.augment_user_samples import _augment_seed, _get_client
        client = _get_client()
        augment = _augment_seed

    added_total = 0
    by_type: collections.Counter[str] = collections.Counter()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as fout:
        for idx, seed in enumerate(seeds, 1):
            st = seed.get("scam_type", "")
            # 이 seed 의 부족분만 생성 (기존 변형 수 차감)
            have = per_src.get(f"augment_llm/{seed.get('source_ref','')}", 0)
            target = max(0, args.variants - have)
            seen_local: set[str] = set(existing)
            collected: list[dict[str, Any]] = []
            round_no, empty_streak = 1, 0
            while len(collected) < target and round_no < args.max_rounds + 1:
                want = target - len(collected)
                if fake:
                    recs = _fake_variants(seed, min(want, args.batch), round_no)
                    recs = [r for r in recs if r["text"].strip() not in seen_local]
                else:
                    ask = min(want + args.buffer, args.batch)
                    raw = augment(client, seed, ask, args.model, round_no, args.max_tokens)
                    recs = []
                    for r in raw:
                        t = (r.get("text") or "").strip()
                        if not t or t in seen_local:
                            continue
                        seen_local.add(t)
                        recs.append(r)
                        if len(collected) + len(recs) >= target:
                            break
                for r in recs:
                    seen_local.add(r["text"].strip())
                collected.extend(recs)
                round_no += 1
                empty_streak = empty_streak + 1 if not recs else 0
                if empty_streak >= 2 and not fake:
                    break

            collected = collected[:target]
            for r in collected:
                fout.write(json.dumps(r, ensure_ascii=False) + "\n")
                by_type[r.get("scam_type") or "(none)"] += 1
            fout.flush()
            added_total += len(collected)
            short = "" if len(collected) == target else f"  ⚠️부족({len(collected)}/{target})"
            print(f"  [{idx}/{len(seeds)}] +{len(collected)}건 «{st}» [{seed.get('source_ref','')}] (기존 {have})>{short}")
            if not fake:
                time.sleep(0.2)

    print(f"\n✅ 완료: +{added_total}건 append → {out_path}")
    print("유형별:", ", ".join(f"{k}({v})" for k, v in by_type.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
