# 데이터 증강 소요시간 비교 — 순차/병렬 × 12-class/6-class

작성: 2026-06-08 · 측정 환경: RTX 5070 Ti, Claude `claude-sonnet-4-6`, seed당 20변형

---

## 1. 실측 단가 (핵심)

| 방식 | 초/변형 | 초/seed(20변형) | 분당 생성량 | 측정 근거 |
|---|---:|---:|---:|---|
| **순차** (`augment_seeds.py`) | **8.7s** | 174s | ~7변형 | 31 seed / 620변형 ≈ 90분 |
| **병렬 c=4** (`augment_seeds_concurrent.py`) | **2.82s** | 56.3s | ~21변형 | 6 seed / 120변형 = 338초 |

→ 병렬 c=4 실측 **3.1×** 단축. (이론상 4×, seed 수 적을 때 wave 불균형으로 3.1×; 대량일수록 4× 근접)

---

## 2. 2×2 비교표 — "버킷당 200변형 균형셋 생성" 워크로드

### (A) 개념 기준: 12 vs 6 버킷 (라벨 2.0×)

| | **순차** (기존) | **병렬 c=4** |
|---|---:|---:|
| **12-class** (2,400변형) | 🟥 **5.8시간** (기존 방식) | 1.9시간 |
| **6-class** (1,200변형) | 2.9시간 | 🟩 **56분** (둘 다 적용) |

- 최악(12·순차) **5.8h** → 최선(6·병렬) **56분** = **6.2× 단축**
- 축 분해: 병렬화 **3.1×** × 라벨축소 **2.0×** ≈ 6.2×

### (B) 실제 활성 버킷: 9 vs 5 (기타·특수형 데이터 0 → 라벨 1.8×)

| | 순차 | 병렬 c=4 |
|---|---:|---:|
| **12-class** (1,800변형) | 4.3시간 | 1.4시간 |
| **6-class** (1,000변형) | 2.4시간 | **47분** |

- 최악 → 최선 = **5.6× 단축** (병렬 3.1× × 라벨 1.8×)

---

## 3. 정직하게 짚을 것

1. **"라벨 축소 2×"는 "균형셋을 처음부터 생성할 때"만 유효.** 실제 작업에선 12-class 데이터를 **0.29초에 relabel**해 6-class를 만들었으므로, *이미 만든 데이터*에선 절감 0. 위 2×는 **앞으로 균형 데이터를 새로 모을 때의 계획상 이득**이다.
2. **병렬 3.1×는 c=4 실측.** 대량 배치일수록 4× 근접, c=6/8이면 ~4.5–6× (rate limit 여유 내). 둘 다 적용 시 실질 **7–10×**까지 가능.
3. **변형당 생성 floor 8.7s(LLM 토큰 생성)는 못 줄임** — 병렬은 그 대기를 겹쳐 숨기는 것.

---

## 4. 모델 품질 — 시간 절감이 품질을 깎지 않음

동일 5-카테고리 과제·동일 group-split val(누수0)에서 공정 비교:

| 방식 | accuracy | macro_f1 |
|---|---:|---:|
| 12-class → 카테고리 collapse | 0.7231 | 0.7198 |
| 6-class 직접 학습 | 0.7692 | **0.7824** (+0.063) |

- 6-class는 **더 빠르게 만들고 + 품질 손해 없음**(오히려 +0.063, 단 단일 split 분산 내).
- 헤드라인 "0.69→0.88"은 라벨공간이 쉬워진 착시 — 공정 비교 시 실제 격차는 +0.06 수준.

---

## 5. 기존 증강 코드 — `scripts/augment_user_samples.py` (순차)

각 seed를 직렬로 1개씩 Claude 호출, 결과를 즉시 파일에 append. seed당 0.2s sleep.

```python
"""
user_samples (실제 수집 사기문자) 를 LLM 패러프레이즈로 증강.

각 실제 샘플을 *씨앗* 으로 Claude 가 N 개(기본 5) 변형을 생성한다:
- scam_type / content_label 은 **보존** (라벨 일관성)
- 표면 디테일(이름·금액·URL·전화번호·기관명·말투)만 변화 → 실데이터 분포를 살린 증강
- 출력은 synthetic 데이터(`data/generated/scamguardian_synthetic_*.jsonl`)와 **동일 학습용 스키마**:
  text / content_label / scam_type / sample_kind / source_ref / entities / risk_flags / flag_groups / rag_texts

entity 라벨·risk_flag 는 프로젝트 taxonomy(`pipeline.config`)로 **제약·검증** — 환각 라벨 차단.
entity span(start/end) 은 생성된 text 안에서 substring 매칭으로 계산. flag_groups 는 `flag_groups.group_of`.

사용:
  export ANTHROPIC_API_KEY=...
  python scripts/augment_user_samples.py \
    --input  data/processed/user_samples_2026-05-26.jsonl \
    --output data/generated/user_samples_augmented.jsonl \
    --variants 5
  # 소량 테스트(앞 3개만, API 비용 최소):
  python scripts/augment_user_samples.py --limit 3 --output /tmp/aug_test.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline import config as cfg
from pipeline.flag_groups import group_of

# ── taxonomy (LLM 제약 + 검증용) ────────────────────────────────
VALID_FLAGS: set[str] = set(getattr(cfg, "DETECTED_FLAGS", []) or [])
LABEL_SETS: dict[str, list[str]] = dict(getattr(cfg, "DEFAULT_LABEL_SETS", {}) or {})
ALL_LABELS: list[str] = sorted({lab for labs in LABEL_SETS.values() for lab in labs})
SCAM_TYPES: list[str] = list(getattr(cfg, "DEFAULT_SCAM_TYPES", []) or [])

DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")

# (SYSTEM_PROMPT / TOOL 정의 — taxonomy 제약 + emit_variants 강제. 본문 생략 없이 원본 참조)

def _get_client():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("❌ ANTHROPIC_API_KEY 미설정 — export ANTHROPIC_API_KEY=... 후 실행")
    import anthropic
    return anthropic.Anthropic(api_key=api_key, max_retries=3)


def _augment_seed(client, seed, n, model, round_no=1, max_tokens=4096):
    """seed 1개 → Claude 1회 호출 → 변형 n개 파싱·검증(taxonomy·span·dedup)."""
    msg = client.messages.create(
        model=model, max_tokens=max_tokens,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=[TOOL], tool_choice={"type": "tool", "name": "emit_variants"},
        messages=[{"role": "user", "content": _user_prompt(seed, n, round_no)}],
    )
    payload = next((b.input for b in msg.content
                    if getattr(b, "type", None) == "tool_use" and b.name == "emit_variants"), None)
    if not payload:
        return []
    records, seen = [], {seed.get("text", "").strip()}
    for v in payload.get("variants", []):
        if isinstance(v, str):           # 모델이 가끔 문자열 반환 — 보정
            v = {"text": v}
        elif not isinstance(v, dict):
            continue
        text = (v.get("text") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        flags = sorted({f for f in (v.get("risk_flags") or []) if f in VALID_FLAGS})
        records.append({
            "text": text, "content_label": seed.get("content_label") or "scam_attempt",
            "scam_type": seed.get("scam_type", ""), "sample_kind": "augmented_llm",
            "source_ref": f"augment_llm/{seed.get('source_ref','user-collected')}",
            "seed_text": seed.get("text", "").strip(),
            "entities": _spanify(text, v.get("entities") or []),
            "risk_flags": flags, "flag_groups": sorted({group_of(f) for f in flags}),
            "rag_texts": [text],
        })
    return records


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--input", default="data/processed/user_samples_2026-05-26.jsonl")
    p.add_argument("--output", default="data/generated/user_samples_augmented.jsonl")
    p.add_argument("--variants", type=int, default=5)
    p.add_argument("--append", action="store_true")
    p.add_argument("--round", type=int, default=1)
    args = p.parse_args()

    seeds = [json.loads(l) for l in Path(args.input).read_text(encoding="utf-8").splitlines() if l.strip()]
    client = _get_client()
    out_path = Path(args.output)
    total = 0
    # ── 직렬 루프: seed 하나씩, 즉시 파일 append, 0.2s sleep ──
    with out_path.open("a" if args.append else "w", encoding="utf-8") as fout:
        for i, seed in enumerate(seeds, 1):
            try:
                recs = _augment_seed(client, seed, args.variants, args.model, args.round)
            except Exception as exc:
                print(f"  [{i}/{len(seeds)}] ⚠️ 실패: {exc}")
                continue
            for r in recs:
                fout.write(json.dumps(r, ensure_ascii=False) + "\n")
            total += len(recs)
            print(f"  [{i}/{len(seeds)}] +{len(recs)}건 (누적 {total})")
            time.sleep(0.2)
    print(f"✅ +{total}건 → {out_path}")
    return 0
```

> 위는 핵심 흐름 발췌(가독성). `SYSTEM_PROMPT`/`TOOL`/`_user_prompt`/`_spanify` 전문은 `scripts/augment_user_samples.py` 원본 참조.
> **특징**: 직렬 처리(`for seed in seeds`) + seed별 즉시 append + 0.2s sleep → 안정적이나 느림(8.7s/변형).

---

## 6. 최종 증강 코드 — `scripts/augment_seeds_concurrent.py` (병렬)

`_augment_seed` 코어 재사용. **deficit-aware** + **ThreadPoolExecutor 병렬** + **worker는 파일 미접촉(메모리 수집)** + **일괄 검증·dedup** + **단일 append** + **실패 retry 2회**.

```python
"""seed 증강 — 병렬 생성 + 일괄 검증 + 단일 append (속도 최적화판).

개선점:
  1. seed 당 작업을 ThreadPoolExecutor(concurrency) 로 병렬 생성 (API I/O 대기 겹침)
  2. worker 는 출력 파일에 직접 쓰지 않음 — 결과를 메모리 리스트로 반환
  3. 실패(예외) seed 는 retry queue 로 최대 N 회 재시도
  4. 모든 worker 완료 후 한 번에: 스키마 검증 + 중복 text 제거 (기존 출력 + 신규 간)
  5. 검증 통과분만 출력 파일에 단일 append (원본 보존, 덮어쓰기 X)

deficit-aware: 각 seed 의 목표 = variants - (기존 출력의 augment_llm/{source_ref} 수). 0 이면 skip.
FAKE 모드(SCAMGUARDIAN_AUGMENT_FAKE=1): Claude 호출 없이 결정론적 변형 — 흐름 검증용(비용 0).
"""

from __future__ import annotations

import argparse, collections, json, os, sys, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
_AUG_PREFIX = "augment_llm/"
REQUIRED_FIELDS = {"text", "content_label", "scam_type", "sample_kind", "source_ref"}


def _load_existing(path: Path):
    """기존 출력에서 (전체 텍스트 집합, source_ref 별 변형 수) — dedup + deficit 계산용."""
    seen, per_src = set(), collections.Counter()
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
    p = argparse.ArgumentParser()
    p.add_argument("--seed-file", required=True)
    p.add_argument("--output", default="data/generated/user_samples_augmented.jsonl")
    p.add_argument("--variants", type=int, default=20)
    p.add_argument("--batch", type=int, default=5)
    p.add_argument("--buffer", type=int, default=3)
    p.add_argument("--max-tokens", type=int, default=8192)
    p.add_argument("--max-rounds", type=int, default=8)
    p.add_argument("--concurrency", type=int, default=4, help="병렬 worker 수 (4 기본, 6~8 권장)")
    p.add_argument("--max-retries", type=int, default=2, help="실패 seed 재시도 횟수")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--tmp-dir", default="")
    args = p.parse_args()

    concurrency = max(1, min(8, args.concurrency))
    seeds = [json.loads(l) for l in Path(args.seed_file).read_text(encoding="utf-8").splitlines() if l.strip()]
    out_path = Path(args.output)
    existing_texts, per_src = _load_existing(out_path)

    # deficit-aware: seed 별 목표 = variants - 기존 수. 0 이면 skip.
    tasks = [(s, args.variants - per_src.get(f"{_AUG_PREFIX}{s.get('source_ref','')}", 0))
             for s in seeds]
    tasks = [(s, t) for s, t in tasks if t > 0]
    print(f"처리 {len(tasks)} seed | concurrency={concurrency} | 기존 텍스트 {len(existing_texts)}")
    if not tasks:
        print("✅ 할 일 없음.")
        return 0

    fake = os.getenv("SCAMGUARDIAN_AUGMENT_FAKE", "").strip().lower() in {"1", "true", "yes", "on"}
    if fake:
        from scripts.run_augment_session import _fake_variants
        gen = None
    else:
        from scripts.augment_user_samples import _augment_seed, _get_client
        gen = _augment_seed
        client = _get_client()

    # ── worker: 한 seed 의 변형 target 개를 생성해 records 리스트로 반환 (파일 쓰기 X) ──
    def work(seed, target, idx):
        src = seed.get("source_ref", "")
        local_seen = set(existing_texts)
        collected, round_no, empty_streak = [], 1, 0
        while len(collected) < target and round_no < args.max_rounds + 1:
            want = target - len(collected)
            if fake:
                recs = _fake_variants(seed, min(want, args.batch), round_no)
                for r in recs:
                    r["source_ref"] = f"{_AUG_PREFIX}{src}"
                recs = [r for r in recs if r["text"].strip() not in local_seen]
            else:
                ask = min(want + args.buffer, args.batch)   # batch 로 쪼개 max_tokens 오버플로 방지
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
        return {"src": src, "records": collected[:target]}

    # ── 병렬 실행 + retry queue ──
    pending = list(enumerate(tasks))
    results, failures = {}, {}
    for attempt in range(args.max_retries + 1):
        if not pending:
            break
        next_pending = []
        with ThreadPoolExecutor(max_workers=concurrency) as ex:
            fut = {ex.submit(work, s, t, idx): (idx, s, t) for idx, (s, t) in pending}
            for f in as_completed(fut):
                idx, s, t = fut[f]
                src = s.get("source_ref", "")
                try:
                    results[src] = f.result()
                    failures.pop(src, None)
                except Exception as exc:
                    failures[src] = f"{type(exc).__name__}: {exc}"
                    next_pending.append((idx, (s, t)))
        pending = next_pending

    # ── 일괄 검증 + 중복 제거 (모든 worker 완료 후 한 번에) ──
    combined = [r for res in results.values() for r in res["records"]]
    schema_bad = dup_text = 0
    seen_text, deduped = set(existing_texts), []
    for rec in combined:
        if not isinstance(rec, dict) or (REQUIRED_FIELDS - set(rec)):
            schema_bad += 1
            continue
        t = rec["text"].strip()
        if t in seen_text:
            dup_text += 1
            continue
        seen_text.add(t)
        deduped.append(rec)
    print(f"검증: 생성 {len(combined)} → 스키마탈락 {schema_bad} / 중복 {dup_text} → 유효 {len(deduped)}")

    # ── 단일 append (검증 통과분만) ──
    if deduped:
        with out_path.open("a", encoding="utf-8") as fout:
            for rec in deduped:
                fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"✅ 단일 append: +{len(deduped)}건 → {out_path}")
    if failures:
        print(f"⚠️ 최종 실패 {len(failures)}개: {failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

> **특징**: 병렬 생성(`ThreadPoolExecutor`) + worker는 메모리 반환(파일 미접촉) + 완료 후 일괄 스키마검증·dedup → **단일 append**(원본 보존) + 실패 retry. → 3.1×(c=4) 단축, 데이터 무결성 보장.
> **사용**: `python scripts/augment_seeds_concurrent.py --seed-file <seeds.jsonl> --variants 20 --concurrency 4`

---

## 7. 한 줄 결론

> **라벨 6개로 축소(생성량 ½) × 병렬화(3.1×) = 증강 시간 5.6–6.2× 단축**, 그러면서 모델 품질은 동급 이상. 증강 방향(실사례 seed → LLM 패러프레이즈)은 유효하며, 병목이던 생성시간을 병렬 도구로 실용화함.
