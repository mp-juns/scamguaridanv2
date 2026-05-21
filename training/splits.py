"""train/val/test split — source_ref 그룹 인식 + content_label 균형 (best-effort).

같은 source_ref 를 가진 샘플들(예: 한 뉴스 기사에서 파생된 여러 synthetic 샘플)은
*반드시* 같은 fold 에 배정한다 → 데이터 leakage 방지.

스트라티피케이션은 content_label 별 분포가 크게 깨지지 않게 그리디 배정:
1. 그룹별 dominant content_label 결정
2. 그룹을 크기 내림차순으로 정렬
3. 각 그룹을 *현재 결손이 가장 큰* fold (해당 content_label 기준) 에 배정

source_ref 가 빈/None 인 샘플은 각자 singleton group (id 고유).
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import asdict, is_dataclass
from typing import Any, Sequence

DEFAULT_SEED = 17


def _source_ref(example: Any) -> str | None:
    """examples (dataclass / dict) 에서 source_ref 추출. None 또는 빈 문자열은 None 처리."""
    if is_dataclass(example):
        val = getattr(example, "source_ref", None)
    elif isinstance(example, dict):
        val = example.get("source_ref")
    else:
        val = getattr(example, "source_ref", None)
    if val is None:
        return None
    s = str(val).strip()
    return s or None


def _content_label(example: Any) -> str:
    if is_dataclass(example):
        return getattr(example, "content_label", "") or ""
    if isinstance(example, dict):
        return example.get("content_label", "") or ""
    return getattr(example, "content_label", "") or ""


def _group_key(example: Any, fallback_idx: int) -> str:
    ref = _source_ref(example)
    return ref if ref is not None else f"__singleton__{fallback_idx}"


def group_train_val_test_split(
    examples: Sequence[Any],
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
    seed: int = DEFAULT_SEED,
) -> tuple[list[Any], list[Any], list[Any]]:
    """그룹 인식 + content_label 균형 split — (train, val, test).

    같은 source_ref 의 샘플은 한 fold 로 묶인다. fold 별 비율은 best-effort —
    한 그룹 크기가 전체의 큰 비중을 차지하면 ratio 가 어긋날 수 있다 (leakage 방지가 우선).
    """
    if not 0.0 < val_ratio < 1.0 or not 0.0 < test_ratio < 1.0:
        raise ValueError("val_ratio, test_ratio 는 (0, 1) 사이여야 합니다.")
    if val_ratio + test_ratio >= 1.0:
        raise ValueError("val_ratio + test_ratio < 1.0 이어야 합니다.")

    rng = random.Random(seed)
    n = len(examples)
    if n == 0:
        return [], [], []

    # 1) 그룹화: source_ref → 멤버 인덱스 list
    groups: dict[str, list[int]] = {}
    for i, ex in enumerate(examples):
        key = _group_key(ex, i)
        groups.setdefault(key, []).append(i)

    # 2) 각 그룹의 dominant content_label
    group_dominant: dict[str, str] = {}
    for key, idxs in groups.items():
        labels = [_content_label(examples[i]) for i in idxs]
        group_dominant[key] = Counter(labels).most_common(1)[0][0] if labels else ""

    # 3) 타겟 카운트 — content_label 별 fold target (best-effort)
    label_total: dict[str, int] = Counter(_content_label(ex) for ex in examples)
    train_ratio = 1.0 - val_ratio - test_ratio
    targets: dict[str, dict[str, float]] = {}
    for label, total in label_total.items():
        targets[label] = {
            "train": total * train_ratio,
            "val": total * val_ratio,
            "test": total * test_ratio,
        }
    current: dict[str, dict[str, int]] = {
        label: {"train": 0, "val": 0, "test": 0} for label in label_total
    }

    # 4) 그룹을 크기 내림차순 정렬 (큰 그룹부터 배치 — 결정성 위해 seed 도 활용)
    group_keys = list(groups)
    rng.shuffle(group_keys)
    group_keys.sort(key=lambda k: (-len(groups[k]), k))

    assignment: dict[str, str] = {}
    for key in group_keys:
        label = group_dominant[key]
        size = len(groups[key])
        if label not in targets:
            # content_label 빈 그룹 — train 으로 (드물지만 안전한 기본값)
            assignment[key] = "train"
            continue
        # 결손(deficit) 이 가장 큰 fold 로 배정
        deficits = {
            fold: targets[label][fold] - current[label][fold]
            for fold in ("train", "val", "test")
        }
        # tie-break: train > val > test (train 우선)
        order = sorted(
            deficits.items(),
            key=lambda kv: (-kv[1], 0 if kv[0] == "train" else 1 if kv[0] == "val" else 2),
        )
        fold = order[0][0]
        assignment[key] = fold
        current[label][fold] += size

    train_out: list[Any] = []
    val_out: list[Any] = []
    test_out: list[Any] = []
    bucket = {"train": train_out, "val": val_out, "test": test_out}
    for key, idxs in groups.items():
        fold = assignment[key]
        for i in idxs:
            bucket[fold].append(examples[i])

    return train_out, val_out, test_out


def split_summary(
    train: Sequence[Any],
    val: Sequence[Any],
    test: Sequence[Any],
) -> dict[str, Any]:
    """split 결과 요약 — 검증·디버깅용."""

    def _count(fold: Sequence[Any]) -> dict[str, int]:
        return dict(Counter(_content_label(e) for e in fold).most_common())

    def _refs(fold: Sequence[Any]) -> set[str]:
        return {ref for e in fold if (ref := _source_ref(e)) is not None}

    return {
        "sizes": {"train": len(train), "val": len(val), "test": len(test)},
        "by_content_label": {
            "train": _count(train),
            "val": _count(val),
            "test": _count(test),
        },
        "source_refs": {
            "train": len(_refs(train)),
            "val": len(_refs(val)),
            "test": len(_refs(test)),
        },
    }


def _example_as_dict(ex: Any) -> dict[str, Any]:
    """dataclass → dict (디버깅 출력용)."""
    if is_dataclass(ex):
        return asdict(ex)
    if isinstance(ex, dict):
        return dict(ex)
    return {"value": str(ex)}
