"""scam_type → scam_category (12→6) 변환 데이터셋 생성.

원본은 그대로 두고 별도 파일을 만든다. scam_attempt 레코드의 `scam_type` 을 상위
카테고리로 치환(분류기 라벨이 카테고리가 되도록), 그 외(normal/scam_news_edu)는 그대로.
원본 scam_type 은 `scam_type_detail` 로 보존해 추후 세부 후보 표시에 쓸 수 있게 한다.

사용:
  python scripts/make_category_dataset.py \
    --input data/generated/user_samples_augmented.jsonl \
    --output data/generated/user_samples_augmented.category.jsonl
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 12 scam_type → 6 scam_category — 런타임 표시 레이어(config_taxonomy)와 단일 출처
from pipeline.config import SCAM_CATEGORY_MAP  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser(description="scam_type→scam_category 변환셋 생성")
    p.add_argument("--input", default="data/generated/user_samples_augmented.jsonl")
    p.add_argument("--output", default="data/generated/user_samples_augmented.category.jsonl")
    args = p.parse_args()

    inp, outp = Path(args.input), Path(args.output)
    rows = [json.loads(l) for l in inp.read_text(encoding="utf-8").splitlines() if l.strip()]

    out = []
    unmapped: set[str] = set()
    cat_count: collections.Counter = collections.Counter()
    for o in rows:
        r = dict(o)
        st = (o.get("scam_type") or "").strip()
        if o.get("content_label") == "scam_attempt" and st:
            cat = SCAM_CATEGORY_MAP.get(st)
            if cat is None:
                unmapped.add(st)
                out.append(r)  # 매핑 못한 건 원본 유지(드롭 안 함) — 보고용
                continue
            r["scam_type_detail"] = st       # 세부 후보 보존
            r["scam_type"] = cat             # 분류기 라벨 = 카테고리
            cat_count[cat] += 1
        out.append(r)

    outp.parent.mkdir(parents=True, exist_ok=True)
    with outp.open("w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"입력 {len(rows)} → 출력 {len(out)} → {outp}")
    print(f"scam_attempt 카테고리 분포 ({sum(cat_count.values())}건):")
    for k, v in cat_count.most_common():
        print(f"  {v:5d}  {k}")
    if unmapped:
        print(f"⚠️ 매핑 안 된 scam_type(원본 유지): {unmapped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
