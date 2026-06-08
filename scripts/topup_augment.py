"""미달 씨앗 top-up — 증강이 불균등하게 끝난 JSONL 을 씨앗별 목표 변형 수까지 채운다.

`scripts/augment_user_samples.py` 의 per-seed 코어(`_augment_seed`)를 재사용한다.
씨앗 파일이 없어도 동작한다 — 출력 JSONL 의 `seed_text` 로 (source_ref, seed_text) 별
씨앗을 복원하고, 현재 변형 수가 목표(기본 20)에 미달인 씨앗만 **부족분 만큼만** 생성해
원본 파일에 이어붙인다. 기존 변형 텍스트와 중복되는 새 변형은 버린다.

사용:
  export ANTHROPIC_API_KEY=...
  python scripts/topup_augment.py --file data/generated/user_samples_augmented.jsonl --target 20
  # 비용 0 검증 (결정론적 가짜 변형):
  SCAMGUARDIAN_AUGMENT_FAKE=1 python scripts/topup_augment.py \
    --file /tmp/aug_copy.jsonl --target 20
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
_AUG_PREFIX = "augment_llm/"


def _reconstruct_seeds(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    """출력 JSONL → (source_ref, seed_text) 별 씨앗 메타 + 기존 변형 텍스트 집합."""
    groups: dict[tuple[str, str], dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        o = json.loads(line)
        seed_text = (o.get("seed_text") or "").strip()
        src = o.get("source_ref") or ""
        key = (src, seed_text)
        g = groups.setdefault(
            key,
            {
                "texts": set(),
                "scam_type": collections.Counter(),
                "content_label": collections.Counter(),
            },
        )
        g["texts"].add((o.get("text") or "").strip())
        g["scam_type"][o.get("scam_type") or ""] += 1
        g["content_label"][o.get("content_label") or ""] += 1
    return groups


def _seed_record(src: str, seed_text: str, g: dict[str, Any]) -> dict[str, Any]:
    """_augment_seed 가 기대하는 씨앗 dict 로 변환. source_ref 는 augment_llm/ 접두어 제거."""
    seed_src = src[len(_AUG_PREFIX):] if src.startswith(_AUG_PREFIX) else src
    return {
        "text": seed_text,
        "scam_type": g["scam_type"].most_common(1)[0][0],
        "content_label": g["content_label"].most_common(1)[0][0] or "scam_attempt",
        "source_ref": seed_src,
    }


def _fake_topup(seed: dict[str, Any], n: int, existing: set[str], round_no: int) -> list[dict[str, Any]]:
    """API 없이 결정론적 변형 — 기존 텍스트와 겹치지 않게 round/idx 로 유일화."""
    from pipeline.flag_groups import group_of  # noqa: F401  (스키마 일관성용 import 확인)

    base = (seed.get("text") or "").strip()
    out: list[dict[str, Any]] = []
    i = 0
    attempt = 0
    while len(out) < n and attempt < n * 5:
        attempt += 1
        i += 1
        text = f"[top-up r{round_no}-{i}] {base}"
        if text in existing:
            continue
        existing.add(text)
        out.append({
            "text": text,
            "content_label": seed.get("content_label") or "scam_attempt",
            "scam_type": seed.get("scam_type", ""),
            "sample_kind": "augmented_llm",
            "source_ref": f"{_AUG_PREFIX}{seed.get('source_ref', 'user-collected')}",
            "seed_text": base,
            "entities": [],
            "risk_flags": [],
            "flag_groups": [],
            "rag_texts": [text],
        })
    return out


def main() -> int:
    p = argparse.ArgumentParser(description="미달 씨앗 top-up 증강")
    p.add_argument("--file", default="data/generated/user_samples_augmented.jsonl",
                   help="증강 JSONL (읽어서 씨앗 복원 + 부족분 이어붙임)")
    p.add_argument("--target", type=int, default=20, help="씨앗당 목표 변형 수")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--buffer", type=int, default=3, help="요청 시 dedup 손실 대비 여유분")
    p.add_argument("--max-rounds", type=int, default=8, help="씨앗당 재시도 라운드 상한")
    p.add_argument("--batch", type=int, default=5, help="호출당 최대 변형 요청 수 (긴 씨앗 max_tokens 오버플로 방지)")
    p.add_argument("--max-tokens", type=int, default=8192, help="_augment_seed 호출당 max_tokens")
    p.add_argument("--dry-run", action="store_true", help="씨앗별 부족분만 출력하고 종료")
    args = p.parse_args()

    path = Path(args.file)
    if not path.exists():
        sys.exit(f"❌ 파일 없음: {path}")

    groups = _reconstruct_seeds(path)
    under = {k: g for k, g in groups.items() if len(g["texts"]) < args.target}
    total_deficit = sum(args.target - len(g["texts"]) for g in under.values())
    print(f"고유 씨앗 {len(groups)}개 / 미달 {len(under)}개 / 총 부족분 {total_deficit}건 (목표 {args.target})")

    if args.dry_run:
        for (src, st), g in sorted(under.items(), key=lambda kv: len(kv[1]["texts"])):
            print(f"  현재{len(g['texts']):2d} → +{args.target - len(g['texts']):2d}  {src}  「{st[:30]}…」")
        return 0

    if not under:
        print("✅ 미달 씨앗 없음 — 할 일 없음.")
        return 0

    fake = os.getenv("SCAMGUARDIAN_AUGMENT_FAKE", "").strip().lower() in {"1", "true", "yes", "on"}
    client = None
    augment_fn = None
    if fake:
        print("🧪 FAKE 모드 — Claude 호출 없음 (비용 0)")
    else:
        from scripts.augment_user_samples import _augment_seed, _get_client
        client = _get_client()
        augment_fn = _augment_seed

    added_total = 0
    by_type: collections.Counter[str] = collections.Counter()
    with path.open("a", encoding="utf-8") as fout:
        for idx, ((src, st), g) in enumerate(sorted(under.items()), 1):
            seed = _seed_record(src, st, g)
            existing: set[str] = set(g["texts"])
            need = args.target - len(g["texts"])
            collected: list[dict[str, Any]] = []
            round_no = 2
            empty_streak = 0
            while len(collected) < need and round_no < args.max_rounds + 2:
                want = need - len(collected)
                if fake:
                    recs = _fake_topup(seed, want, existing, round_no)
                else:
                    # 호출당 요청량을 batch 로 제한 — 긴 씨앗은 변형 多 요청 시 출력이 max_tokens 넘어 잘림
                    ask = min(want + args.buffer, args.batch)
                    raw = augment_fn(client, seed, ask, args.model, round_no, args.max_tokens)
                    recs = []
                    for r in raw:
                        t = (r.get("text") or "").strip()
                        if not t or t in existing:
                            continue
                        existing.add(t)
                        recs.append(r)
                        if len(collected) + len(recs) >= need:
                            break
                collected.extend(recs)
                round_no += 1
                # 빈 라운드가 연속 2회면 모델이 새 변형 못 만드는 것 — 중단 (무한루프·낭비 방지)
                empty_streak = empty_streak + 1 if not recs else 0
                if empty_streak >= 2 and not fake:
                    break

            collected = collected[:need]
            for r in collected:
                fout.write(json.dumps(r, ensure_ascii=False) + "\n")
                by_type[r.get("scam_type") or "(normal)"] += 1
            fout.flush()
            added_total += len(collected)
            short = "" if len(collected) == need else f"  ⚠️부족({len(collected)}/{need})"
            print(f"  [{idx}/{len(under)}] +{len(collected)}건 → {len(g['texts']) + len(collected)}/{args.target}  «{seed['scam_type'] or 'normal'}»{short}")
            if not fake:
                time.sleep(0.2)

    print(f"\n✅ 완료: +{added_total}건 추가 → {path}")
    if by_type:
        print("유형별:", ", ".join(f"{k}({v})" for k, v in by_type.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
