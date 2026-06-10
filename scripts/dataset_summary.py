"""증강 데이터셋 분포 요약.

사용: python scripts/dataset_summary.py [--input data/generated/user_samples_augmented.jsonl]
보고: 전체 레코드 수 / content_label / sample_kind / scam_type / 고유 seed(source_ref) /
      중복 text / 스키마 오류 / (옵션) 특정 source_ref prefix 별 생성 수.
"""
from __future__ import annotations
import argparse, collections, json
from pathlib import Path

REQUIRED = {"text", "content_label", "scam_type", "sample_kind", "source_ref"}


def norm_ref(o):
    return (o.get("source_ref") or "").split("augment_llm/")[-1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/generated/user_samples_augmented.jsonl")
    ap.add_argument("--grep-ref", default="", help="이 prefix 의 source_ref 별 생성 수 표시")
    args = ap.parse_args()

    rows, schema_errs = [], 0
    for ln in Path(args.input).read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            o = json.loads(ln)
        except json.JSONDecodeError:
            schema_errs += 1
            continue
        if not REQUIRED.issubset(o):
            schema_errs += 1
        rows.append(o)

    texts = [o.get("text", "").strip() for o in rows]
    dup_text = len(texts) - len(set(texts))
    seeds = {norm_ref(o) for o in rows}

    print(f"입력: {args.input}")
    print(f"전체 레코드 수 : {len(rows)}")
    print(f"고유 seed(source_ref): {len(seeds)}")
    print(f"중복 text      : {dup_text}")
    print(f"스키마 오류    : {schema_errs}")
    print(f"\n[content_label] {dict(collections.Counter(o.get('content_label') for o in rows))}")
    print(f"[sample_kind]   {dict(collections.Counter(o.get('sample_kind') for o in rows))}")
    print("[scam_type]")
    for t, n in collections.Counter(o.get("scam_type") or "(none)" for o in rows).most_common():
        print(f"   {n:5d}  {t}")
    if args.grep_ref:
        print(f"\n[source_ref ~ '{args.grep_ref}'] 별 생성 수")
        c = collections.Counter(norm_ref(o) for o in rows if args.grep_ref in norm_ref(o))
        for r, n in sorted(c.items()):
            print(f"   {n:4d}  {r}")
        print(f"   합계 {sum(c.values())} / 고유 seed {len(c)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
