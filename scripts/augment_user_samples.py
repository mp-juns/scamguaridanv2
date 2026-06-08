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

SYSTEM_PROMPT = f"""너는 한국어 사기 탐지 모델 학습용 **데이터 증강기** 다.

주어진 *실제 사기 문자/메시지* 하나를 씨앗으로, 같은 사기 유형·수법을 유지하되 표면 디테일만
바꾼 현실적인 변형들을 생성한다. 목적은 학습 데이터 다양성 확보 — 절대 실제로 누구를 속이는
용도가 아니다 (탐지 모델 학습 전용).

## 변형 규칙
- **scam_type 과 content_label 은 절대 바꾸지 않는다** (씨앗과 동일 라벨 유지).
- 바꿀 것: 사람 이름·기관명·금액·날짜·URL·전화번호·계좌·말투/문장 순서·이모지.
- 유지할 것: 사기 수법의 본질(긴급 송금 요구, 링크 유도, 기관 사칭 등)과 한국어 자연스러움.
- 변형끼리·씨앗과 **서로 다르게** (단순 동의어 치환 말고 실제 다른 케이스처럼).
- URL 은 실제 악성 도메인 쓰지 말고 그럴듯한 가짜(예: `http://kookmin-safe23.info/check`).
- 전화번호·계좌는 가공의 번호.

## 각 변형마다 추출할 것
1. `text` — 변형된 메시지 전문(한국어).
2. `entities` — text 안의 핵심 개체. 각 `{{text, label}}`. **label 은 아래 허용 목록에서만**:
{json.dumps(ALL_LABELS, ensure_ascii=False)}
   - entity 의 `text` 는 반드시 변형 `text` 안에 **그대로 등장하는 부분 문자열** 이어야 한다.
3. `risk_flags` — 이 메시지가 보이는 위험 신호 id. **아래 허용 목록에서만**:
{json.dumps(sorted(VALID_FLAGS), ensure_ascii=False)}

허용 목록 밖의 label·flag 는 쓰지 마라. 모르면 비워라(빈 배열 허용).
반드시 `emit_variants` 도구로만 반환한다."""

TOOL = {
    "name": "emit_variants",
    "description": "생성한 증강 변형들을 구조화해 반환",
    "input_schema": {
        "type": "object",
        "properties": {
            "variants": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "text": {"type": "string", "description": "변형된 메시지 전문(한국어)"},
                        "entities": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "text": {"type": "string"},
                                    "label": {"type": "string"},
                                },
                                "required": ["text", "label"],
                            },
                        },
                        "risk_flags": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["text", "entities", "risk_flags"],
                },
            }
        },
        "required": ["variants"],
    },
}


def _get_client():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        sys.exit("❌ ANTHROPIC_API_KEY 미설정 — export ANTHROPIC_API_KEY=... 후 실행")
    import anthropic
    return anthropic.Anthropic(api_key=api_key, max_retries=3)


def _user_prompt(seed: dict[str, Any], n: int, round_no: int = 1) -> str:
    scam_type = seed.get("scam_type") or "(미상)"
    content_label = seed.get("content_label") or "scam_attempt"
    hint_labels = LABEL_SETS.get(seed.get("scam_type", ""), [])
    hint = f"\n이 유형에서 자주 나오는 entity label: {json.dumps(hint_labels, ensure_ascii=False)}" if hint_labels else ""
    fresh = (
        f"\n이번은 추가 라운드(round {round_no}) 다 — 이전에 만든 변형들과 **겹치지 않는 완전히 새로운** "
        f"케이스로 만들어라(다른 기관·다른 상황·다른 말투)." if round_no > 1 else ""
    )
    return (
        f"씨앗 메시지 (scam_type={scam_type}, content_label={content_label}):\n"
        f"```\n{seed.get('text','').strip()}\n```\n\n"
        f"위 메시지의 변형 {n} 개를 생성해라. scam_type/content_label 은 유지.{hint}{fresh}"
    )


def _spanify(text: str, ents: list[dict]) -> list[dict]:
    """entity text 를 변형 text 안에서 찾아 start/end 부여. 못 찾거나 라벨 무효면 제외."""
    out: list[dict] = []
    cursor = 0
    for e in ents:
        et = (e.get("text") or "").strip()
        lab = (e.get("label") or "").strip()
        if not et or lab not in ALL_LABELS:
            continue
        idx = text.find(et, cursor)
        if idx < 0:
            idx = text.find(et)  # cursor 이후 없으면 전체에서
        if idx < 0:
            continue
        out.append({"text": et, "label": lab, "start": idx, "end": idx + len(et)})
        cursor = idx + len(et)
    return out


def _augment_seed(client, seed: dict, n: int, model: str, round_no: int = 1, max_tokens: int = 4096) -> list[dict]:
    msg = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "emit_variants"},
        messages=[{"role": "user", "content": _user_prompt(seed, n, round_no)}],
    )
    payload = None
    for block in msg.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "emit_variants":
            payload = block.input
            break
    if not payload:
        return []

    seed_type = seed.get("scam_type", "")
    seed_label = seed.get("content_label") or "scam_attempt"
    seed_src = seed.get("source_ref", "user-collected")
    records: list[dict] = []
    seen: set[str] = {seed.get("text", "").strip()}
    for v in payload.get("variants", []):
        # 모델이 가끔 변형을 dict 아닌 문자열로 반환 — text 만 있는 dict 로 보정
        if isinstance(v, str):
            v = {"text": v}
        elif not isinstance(v, dict):
            continue
        text = (v.get("text") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        flags = sorted({f for f in (v.get("risk_flags") or []) if f in VALID_FLAGS})
        groups = sorted({group_of(f) for f in flags})
        records.append({
            "text": text,
            "content_label": seed_label,
            "scam_type": seed_type,
            "sample_kind": "augmented_llm",
            "source_ref": f"augment_llm/{seed_src}",
            "seed_text": seed.get("text", "").strip(),
            "entities": _spanify(text, v.get("entities") or []),
            "risk_flags": flags,
            "flag_groups": groups,
            "rag_texts": [text],
        })
    return records


def main() -> int:
    p = argparse.ArgumentParser(description="user_samples LLM 패러프레이즈 증강")
    p.add_argument("--input", default="data/processed/user_samples_2026-05-26.jsonl")
    p.add_argument("--output", default="data/generated/user_samples_augmented.jsonl")
    p.add_argument("--variants", type=int, default=5, help="씨앗당 변형 개수")
    p.add_argument("--limit", type=int, default=0, help="앞 N개 씨앗만 (0=전체, 테스트용)")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--append", action="store_true", help="기존 output에 이어붙이기 (재증강)")
    p.add_argument("--round", type=int, default=1, help="증강 라운드 번호 (>1이면 새 변형 유도)")
    args = p.parse_args()

    in_path = Path(args.input)
    seeds = [json.loads(l) for l in in_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.limit:
        seeds = seeds[: args.limit]
    print(f"씨앗 {len(seeds)}개 × {args.variants}변형 → 목표 ~{len(seeds)*args.variants}건 (model={args.model})")

    client = _get_client()
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    total, failed = 0, 0
    flag_counter: dict[str, int] = {}
    mode = "a" if args.append else "w"
    existing = sum(1 for _ in out_path.open(encoding="utf-8")) if (args.append and out_path.exists()) else 0
    if args.append:
        print(f"append 모드 — 기존 {existing}건에 이어붙임 (round {args.round})")
    with out_path.open(mode, encoding="utf-8") as fout:
        for i, seed in enumerate(seeds, 1):
            try:
                recs = _augment_seed(client, seed, args.variants, args.model, args.round)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"  [{i}/{len(seeds)}] ⚠️ 실패: {type(exc).__name__}: {exc}")
                continue
            for r in recs:
                fout.write(json.dumps(r, ensure_ascii=False) + "\n")
                for f in r["risk_flags"]:
                    flag_counter[f] = flag_counter.get(f, 0) + 1
            total += len(recs)
            print(f"  [{i}/{len(seeds)}] +{len(recs)}건 (누적 {total})  «{seed.get('scam_type','?')}»")
            time.sleep(0.2)  # 가벼운 레이트 완화

    grand = existing + total
    print(f"\n✅ 완료: 이번 +{total}건 (실패 씨앗 {failed}개) → 파일 총 {grand}건 → {out_path}")
    if flag_counter:
        top = sorted(flag_counter.items(), key=lambda x: -x[1])[:10]
        print("상위 risk_flags:", ", ".join(f"{k}({v})" for k, v in top))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
