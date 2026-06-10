"""B 버킷 재매핑 (재증강 없음) — 한 source_ref 에 묶인 여러 원본 seed 를 고유 ref 로 분리.

문제: 옛 풀의 일부 source_ref 가 여러 원본을 번들 → 고유 seed count 과소 + group-split 거침.
해결: 기존 레코드를 **재증강 없이** source_ref 만 `-seed-NN` 으로 재매핑.
  - admin_seeds 원본: 같은 source_ref 내 원본을 text 정렬로 NN 부여
  - augmented 변형: 각 변형의 seed_text 를 원본 text 에 prefix 매칭 → 같은 NN 부여
  - A 버킷(원본 1개) / 단일 ref 는 변경 없음

불변식 검증: 총 레코드 수 / 중복 text / 스키마 / content_label·scam_type 분포 = 전후 동일.

사용: python scripts/remap_bundle_seeds.py           # dry-run
      python scripts/remap_bundle_seeds.py --apply   # 백업 후 실제 재매핑
"""
from __future__ import annotations
import argparse, collections, json, re, shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ADMIN = ROOT / "data/processed/admin_seeds.jsonl"
AUG = ROOT / "data/generated/user_samples_augmented.jsonl"
AUG_PREFIX = "augment_llm/"
STAMP = "20260608"


def load(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def sref(o):
    return (o.get("source_ref") or "").split(AUG_PREFIX)[-1]


def norm(t):
    return re.sub(r"\s+", "", (t or "")).strip()


def stats(rows):
    texts = [(o.get("text") or "").strip() for o in rows]
    return {
        "total": len(rows),
        "dup_text": len(texts) - len(set(texts)),
        "content_label": dict(collections.Counter(o.get("content_label") for o in rows)),
        "scam_type": dict(collections.Counter(o.get("scam_type") or "(none)" for o in rows)),
        "uniq_ref": len({sref(o) for o in rows}),
    }


def build_maps(admin, aug):
    """각 B 버킷의 (원본text→NN), (seed_text→NN) 매핑 구축. 반환: ref -> {orig_text->NN, seedtext->NN}, 경고."""
    admin_by = collections.defaultdict(list)
    for o in admin:
        admin_by[o["source_ref"]].append(o)
    aug_by = collections.defaultdict(list)
    for o in aug:
        aug_by[sref(o)].append(o)

    # 충돌 회피: 재매핑 대상이 아닌 기존 ref 전부 (A 버킷의 -seed-NN 등)
    bundle_refs = {r for r, v in admin_by.items() if len(v) > 1 and aug_by.get(r)}
    existing_refs = ({o["source_ref"] for o in admin} | {sref(o) for o in aug}) - bundle_refs

    maps, warns = {}, []
    for ref, origs in admin_by.items():
        variants = aug_by.get(ref, [])
        if len(origs) <= 1 or not variants:
            continue  # A 버킷 / 미증강 / 단일 → skip
        origs_sorted = sorted(origs, key=lambda o: o["text"])
        # 기존 `<ref>-seed-NN` 와 충돌하지 않는 번호 풀에서 순차 배정
        avail, n = [], 1
        while len(avail) < len(origs_sorted):
            if f"{ref}-seed-{n:03d}" not in existing_refs:
                avail.append(n)
            n += 1
        orig_nn = {o["text"].strip(): avail[i] for i, o in enumerate(origs_sorted)}
        norm_to_nn = {norm(o["text"]): avail[i] for i, o in enumerate(origs_sorted)}

        seedtexts = {(o.get("seed_text") or "") for o in variants}
        seedtexts.discard("")
        st_nn, used = {}, collections.Counter()
        for st in seedtexts:
            n = norm(st)
            # prefix 우선 → 포함 → 부분포함
            cand = [nm for nm in norm_to_nn if nm.startswith(n)]
            if not cand:
                cand = [nm for nm in norm_to_nn if n and (n in nm or nm in n)]
            if not cand:
                import difflib
                cand = [max(norm_to_nn, key=lambda nm: difflib.SequenceMatcher(None, nm, n).ratio())]
            nn = norm_to_nn[cand[0]]
            st_nn[st] = nn
            used[nn] += 1

        # 검증: bijection (seedtext 수 == 원본 수, 각 NN 1회)
        if len(seedtexts) != len(origs) or any(v != 1 for v in used.values()):
            warns.append(f"{ref}: seedtext={len(seedtexts)} origs={len(origs)} used={dict(used)}")
        maps[ref] = {"orig_nn": orig_nn, "st_nn": st_nn, "k": len(origs)}
    return maps, warns


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    admin, aug = load(ADMIN), load(AUG)
    pre_admin, pre_aug = stats(admin), stats(aug)
    maps, warns = build_maps(admin, aug)

    print(f"B 버킷(재매핑 대상): {len(maps)}개")
    print(f"신규 부여 고유 ref: {sum(m['k'] for m in maps.values())}개 "
          f"(기존 {len(maps)} ref → {sum(m['k'] for m in maps.values())} ref)")
    if warns:
        print("⚠️ bijection 경고:")
        for w in warns:
            print("   ", w)

    # 새 source_ref 계산
    def new_admin_ref(o):
        ref = o["source_ref"]
        if ref in maps:
            return f"{ref}-seed-{maps[ref]['orig_nn'][o['text'].strip()]:03d}"
        return ref

    def new_aug_ref(o):
        ref = sref(o)
        if ref in maps:
            nn = maps[ref]["st_nn"].get(o.get("seed_text") or "")
            if nn is not None:
                return f"{AUG_PREFIX}{ref}-seed-{nn:03d}"
        return o.get("source_ref")

    admin2 = [{**o, "source_ref": new_admin_ref(o)} for o in admin]
    aug2 = [{**o, "source_ref": new_aug_ref(o)} for o in aug]
    post_admin, post_aug = stats(admin2), stats(aug2)

    # 불변식 검증 (source_ref/uniq_ref 제외 전부 동일해야)
    def invariant_ok(a, b):
        return (a["total"] == b["total"] and a["dup_text"] == b["dup_text"]
                and a["content_label"] == b["content_label"] and a["scam_type"] == b["scam_type"])
    ok_admin = invariant_ok(pre_admin, post_admin)
    ok_aug = invariant_ok(pre_aug, post_aug)

    print("\n=== 불변식 검증 (전 → 후) ===")
    for name, pre, post, ok in [("admin_seeds", pre_admin, post_admin, ok_admin),
                                ("augmented", pre_aug, post_aug, ok_aug)]:
        print(f"[{name}] total {pre['total']}→{post['total']} | dup_text {pre['dup_text']}→{post['dup_text']} | "
              f"고유ref {pre['uniq_ref']}→{post['uniq_ref']} | content/scam_type 동일={ok} {'✅' if ok else '❌'}")

    if warns or not (ok_admin and ok_aug):
        print("\n검증 실패 또는 경고 — 중단(--apply 무시).")
        return 1
    if not args.apply:
        print("\n[dry-run] --apply 시 백업 후 두 파일 재매핑.")
        return 0

    shutil.copy2(ADMIN, ADMIN.with_suffix(f".jsonl.bak-remap-{STAMP}"))
    shutil.copy2(AUG, AUG.with_suffix(f".jsonl.bak-remap-{STAMP}"))
    ADMIN.write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in admin2) + "\n", encoding="utf-8")
    AUG.write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in aug2) + "\n", encoding="utf-8")
    print(f"\n✅ 재매핑 완료. 백업: *.jsonl.bak-remap-{STAMP}")
    print(f"   admin 고유ref {pre_admin['uniq_ref']}→{post_admin['uniq_ref']} | "
          f"augmented 고유ref {pre_aug['uniq_ref']}→{post_aug['uniq_ref']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
