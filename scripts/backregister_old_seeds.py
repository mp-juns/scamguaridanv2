"""옛 seed 역등록 (provenance 정리 전용).

user_samples_augmented.jsonl 에는 있지만 admin_seeds.jsonl 에는 미등록인 옛 풀 seed 를,
원본 레지스트리(phh_combined_classifier_20260529.jsonl, augmentation=None 원본)에서 복원해
admin_seeds.jsonl 에 append 한다.

- **증강하지 않는다.** 단순 seed 인벤토리 정리.
- 한 source_ref 에 여러 원본이 묶여 있으면 각각 개별 등록(진짜 seed 다양성 보존).
- phh 미존재 ref 는 augmented 의 seed_text 로 복구.
- 검증: JSON / scam_type 유효성 / 기존 admin_seeds 대비 text 중복 / 내부 중복.

사용: python scripts/backregister_old_seeds.py            # dry-run (보고만)
      python scripts/backregister_old_seeds.py --apply   # admin_seeds.jsonl 에 append
"""
from __future__ import annotations
import argparse, json, shutil, sys
from pathlib import Path
from collections import Counter, defaultdict

ROOT = Path(__file__).resolve().parent.parent
AUG = ROOT / "data/generated/user_samples_augmented.jsonl"
ADMIN = ROOT / "data/processed/admin_seeds.jsonl"
PHH = ROOT / ".scamguardian/phh_training/phh_combined_classifier_20260529.jsonl"
STAMP = "2026-06-08"

sys.path.insert(0, str(ROOT))
from pipeline.config import DEFAULT_SCAM_TYPES  # noqa: E402

CORE = ["text", "content_label", "scam_type", "sample_kind", "source_ref", "notes"]


def load(p):
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def norm_ref(o):
    return (o.get("source_ref") or "").split("augment_llm/")[-1]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="admin_seeds.jsonl 에 실제 append")
    args = ap.parse_args()

    aug = load(AUG)
    admin = load(ADMIN)
    phh = load(PHH)

    admin_refs = {o.get("source_ref") for o in admin}
    admin_texts = {o.get("text", "").strip() for o in admin}
    old_refs = sorted({norm_ref(o) for o in aug} - admin_refs)

    phh_by_ref = defaultdict(list)
    for o in phh:
        phh_by_ref[o.get("source_ref")].append(o)

    # source_ref -> 대표 augmented 레코드(seed_text 복구용)
    aug_by_ref = defaultdict(list)
    for o in aug:
        aug_by_ref[norm_ref(o)].append(o)

    new_records, recovered, skipped_dup = [], [], []
    for ref in old_refs:
        originals = []
        if ref in phh_by_ref:
            seen = set()
            for o in phh_by_ref[ref]:
                if o.get("augmentation") is not None:
                    continue  # 증강 변형 제외 — 원본만
                t = o.get("text", "").strip()
                if not t or t in seen:
                    continue
                seen.add(t)
                originals.append({
                    "text": t,
                    "content_label": o.get("content_label"),
                    "scam_type": (o.get("scam_type") or ""),
                    "sample_kind": o.get("sample_kind"),
                })
        if not originals:  # phh 미존재 → seed_text 복구 (대표 1개)
            ex = aug_by_ref[ref][0]
            originals.append({
                "text": (ex.get("seed_text") or "").strip(),
                "content_label": ex.get("content_label"),
                "scam_type": (ex.get("scam_type") or ""),
                "sample_kind": "real_scam_message" if ex.get("content_label") == "scam_attempt" else "normal_content",
            })
            recovered.append(ref)

        n = len(originals)
        for i, base in enumerate(originals, 1):
            note = (f"역등록 {STAMP} (provenance): 옛 user_samples 풀 → admin_seeds 미등록분. "
                    f"원본 {i}/{n} under source_ref. 출처: "
                    + ("phh_combined_classifier_20260529" if ref in phh_by_ref else "augmented.seed_text 복구"))
            if ref == "user-collected-job-investment-scam":
                note += " | ⚠ 재라벨 후보: 로켓 지분 투자유도 → 투자·가상자산형(D2 금전메커니즘)"
            rec = {**base, "source_ref": ref, "notes": note}
            t = rec["text"].strip()
            if not t:
                continue
            if t in admin_texts:
                skipped_dup.append((ref, t[:30]))
                continue
            new_records.append(rec)
            admin_texts.add(t)

    # ---- 검증 ----
    errs = []
    for r in new_records:
        if r["content_label"] == "scam_attempt" and r["scam_type"] not in DEFAULT_SCAM_TYPES:
            errs.append(f"잘못된 scam_type: {r['scam_type']!r} ({r['source_ref']})")
        if r["content_label"] != "scam_attempt" and r["scam_type"]:
            errs.append(f"non-scam 인데 scam_type 존재: {r['source_ref']}")
        if set(r) != set(CORE):
            errs.append(f"스키마 키 불일치: {r['source_ref']}")

    # ---- 보고 ----
    print(f"역등록 대상 source_ref: {len(old_refs)}개")
    print(f"복원된 개별 원본 seed: {len(new_records)}개  (seed_text 복구 ref: {recovered})")
    print(f"기존 admin_seeds 대비 text 중복으로 skip: {len(skipped_dup)}개")
    print(f"검증 오류: {len(errs)}개" + (" ✅" if not errs else ""))
    for e in errs:
        print("   ❌", e)
    print("\n[content_label]", dict(Counter(r["content_label"] for r in new_records)))
    print("[sample_kind]  ", dict(Counter(r["sample_kind"] for r in new_records)))
    print("[scam_type]    ", dict(Counter(r["scam_type"] or "(none)" for r in new_records)))

    if errs:
        print("\n검증 실패 — append 중단.")
        return 1
    if not args.apply:
        print(f"\n[dry-run] --apply 시 admin_seeds.jsonl 에 {len(new_records)}건 append "
              f"({len(admin)} → {len(admin) + len(new_records)}).")
        return 0

    backup = ADMIN.with_suffix(f".jsonl.bak-backregister-{STAMP.replace('-','')}")
    shutil.copy2(ADMIN, backup)
    with ADMIN.open("a", encoding="utf-8") as f:
        for r in new_records:
            f.write(json.dumps({k: r[k] for k in CORE}, ensure_ascii=False) + "\n")
    print(f"\n✅ append 완료: {backup.name} 백업 후 {len(new_records)}건 추가 "
          f"→ admin_seeds.jsonl 총 {len(admin) + len(new_records)}건. (증강 없음)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
