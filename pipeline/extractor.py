"""
ScamGuardian v2 — 하이브리드 엔티티 추출 모듈
1단계: 정규식으로 구조화된 패턴(전화번호, 이메일, URL, 퍼센트 등)을 먼저 추출
2단계: GLiNER로 의미적 엔티티(사람이름, 회사명, 제품명, 주장 등)를 추출
두 결과를 병합하여 반환한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from gliner import GLiNER

from pipeline.config import (
    GLINER_CHUNK_OVERLAP,
    GLINER_CHUNK_SIZE,
    GLINER_THRESHOLD,
    MODELS,
    get_runtime_scam_taxonomy,
)

_gliner_model: GLiNER | None = None
_gliner_load_error: Exception | None = None

# 규칙 기반으로 추출할 레이블 (GLiNER에서 제외)
RULE_BASED_LABELS: set[str] = {
    "전화번호", "이메일 주소", "웹사이트 주소",
    "수익 퍼센트", "사업자 등록번호", "금액",
    "개인정보 항목", "사건번호 또는 공문번호",
    "전문가 직함", "직함 또는 직책", "사칭 기관명",
    "치료 효능 주장",
}

# 정규식 패턴 정의
_REGEX_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("전화번호", re.compile(
        r"(?:0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4})"
        r"|(?:\+82[-.\s]?\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4})"
    )),
    ("이메일 주소", re.compile(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
    )),
    ("웹사이트 주소", re.compile(
        r"(?:https?://)?(?:www\.)?[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?"
    )),
    ("금액", re.compile(
        r"\d[\d,]*(?:\.\d+)?\s*(?:원|만원|천원|억원|달러|usd|USDT)"
    )),
    ("수익 퍼센트", re.compile(
        r"(?:연|월|일|주)\s*\d+(?:\.\d+)?\s*%"
        r"|(?:연|월|일|주)\s*\d+(?:\.\d+)?\s*퍼센트"
    )),
    ("사업자 등록번호", re.compile(
        r"\d{3}[-]\d{2}[-]\d{5}"
    )),
    ("사건번호 또는 공문번호", re.compile(
        r"\d{4}[-][가-힣]{1,2}[-]\d{3,10}"
    )),
]

# 키워드 매칭 기반 추출 (특화 엔티티용)
_KEYWORD_PATTERNS: dict[str, list[str]] = {
    "개인정보 항목": [
        "주민번호", "주민등록번호", "비밀번호", "비번", "OTP",
        "카드번호", "CVC", "CVV", "계좌 비밀번호", "보안카드",
        "인증번호", "핀번호", "PIN",
    ],
    "전문가 직함": [
        "박사", "교수", "의사", "한의사", "약사", "변호사",
        "회계사", "세무사", "연구원", "원장", "소장",
    ],
    "직함 또는 직책": [
        "수사관", "수사팀", "팀장", "검사", "과장", "부장",
        "담당자", "경감", "경위", "계장", "주임", "대리",
    ],
    "사칭 기관명": [
        "금융감독원", "금감원", "검찰", "검찰청", "경찰", "경찰청",
        "국세청", "법원", "국정원",
    ],
    "치료 효능 주장": [
        "완치", "치료", "효과가 있", "효능", "낫게",
        "고친", "개선", "치유", "회복",
    ],
}

# 스캠 유형별 후처리: GLiNER가 일반 레이블로 추출한 것을 특화 레이블로 재분류
_GOVT_INSTITUTIONS = {
    "금융감독원", "금감원", "검찰", "검찰청", "경찰", "경찰청",
    "국세청", "국정원", "대검찰청", "법원", "수사", "금융위원회",
    "국민은행", "하나은행", "신한은행", "우리은행", "농협", "기업은행",
}

_JOB_TITLES = {
    "수사관", "수사팀", "팀장", "검사", "과장", "부장", "담당자",
    "경감", "경위", "계장", "주임", "대리",
}


@dataclass
class Entity:
    text: str
    label: str
    score: float
    start: int
    end: int
    source: str = "extractor"

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "label": self.label,
            "score": self.score,
            "start": self.start,
            "end": self.end,
            "source": self.source,
        }


_gliner_loaded_path: str | None = None
_compare_gliner_cache: dict[str, GLiNER] = {}


def _resolve_gliner_source() -> str:
    """`/admin/training` 활성 체크포인트가 있으면 그 경로, 없으면 기본 base."""
    from pipeline import active_models
    return active_models.get_active_path("gliner") or MODELS["gliner"]


def _get_model() -> GLiNER | None:
    global _gliner_model, _gliner_load_error, _gliner_loaded_path

    desired = _resolve_gliner_source()

    # 활성 모델이 바뀌었으면 재로드
    if _gliner_model is not None and _gliner_loaded_path != desired:
        _gliner_model = None
        _gliner_load_error = None

    if _gliner_model is not None:
        return _gliner_model
    if _gliner_load_error is not None and _gliner_loaded_path == desired:
        return None

    try:
        _gliner_model = GLiNER.from_pretrained(desired)
        _gliner_loaded_path = desired
        if desired != MODELS["gliner"]:
            print(f"[추출] fine-tuned GLiNER 사용: {desired}")
    except Exception as exc:
        _gliner_load_error = exc
        _gliner_loaded_path = desired
        print(f"[추출] GLiNER 로드 실패({desired}), 규칙 기반 추출로 계속 진행합니다: {exc}")
        return None
    return _gliner_model


def _get_model_from_path(model_path: str) -> GLiNER | None:
    if model_path == MODELS["gliner"]:
        try:
            return _compare_gliner_cache.setdefault(model_path, GLiNER.from_pretrained(model_path))
        except Exception as exc:
            print(f"[추출] base GLiNER 로드 실패({model_path}): {exc}")
            return None
    cached = _compare_gliner_cache.get(model_path)
    if cached is not None:
        return cached
    try:
        model = GLiNER.from_pretrained(model_path)
        _compare_gliner_cache[model_path] = model
        return model
    except Exception as exc:
        print(f"[추출] 비교용 GLiNER 로드 실패({model_path}): {exc}")
        return None


def _extract_by_rules(text: str, target_labels: set[str]) -> list[Entity]:
    """정규식 + 키워드 매칭으로 구조화된/특화 엔티티를 추출한다."""
    entities: list[Entity] = []

    # 정규식 패턴 매칭
    for label, pattern in _REGEX_PATTERNS:
        if label not in target_labels:
            continue
        for match in pattern.finditer(text):
            raw_text = match.group()
            stripped_text = raw_text.strip()
            if not stripped_text:
                continue
            left_trim = len(raw_text) - len(raw_text.lstrip())
            right_trim = len(raw_text) - len(raw_text.rstrip())
            start = match.start() + left_trim
            end = match.end() - right_trim
            entities.append(Entity(
                text=stripped_text,
                label=label,
                score=1.0,
                start=start,
                end=end,
            ))

    # 키워드 매칭 (문맥 포함 추출)
    for label, keywords in _KEYWORD_PATTERNS.items():
        if label not in target_labels:
            continue
        for kw in keywords:
            idx = 0
            while True:
                pos = text.find(kw, idx)
                if pos == -1:
                    break

                # "치료 효능 주장": 주변 문맥 포함하여 의미있는 span 추출
                if label == "치료 효능 주장":
                    ctx_start = max(0, pos - 5)
                    ctx_end = min(len(text), pos + len(kw) + 5)
                    # 공백/마침표 경계로 확장
                    while ctx_start > 0 and text[ctx_start - 1] not in " .,\n":
                        ctx_start -= 1
                    while ctx_end < len(text) and text[ctx_end] not in " .,\n":
                        ctx_end += 1
                    span_text = text[ctx_start:ctx_end].strip()
                else:
                    span_text = kw
                    ctx_start = pos
                    ctx_end = pos + len(kw)

                entities.append(Entity(
                    text=span_text,
                    label=label,
                    score=0.95,
                    start=ctx_start,
                    end=ctx_end,
                ))
                idx = pos + len(kw)

    return entities


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[tuple[str, int]]:
    """텍스트를 겹치는 청크로 분할한다."""
    chunks: list[tuple[str, int]] = []
    start = 0

    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            space_idx = text.rfind(" ", start, end)
            if space_idx > start:
                end = space_idx
        chunks.append((text[start:end], start))
        if end >= len(text):
            break
        start = end - overlap

    return chunks


def _deduplicate(entities: list[Entity]) -> list[Entity]:
    """중복 엔티티를 제거한다 (높은 점수 우선).

    두 가지 기준으로 중복 판단:
    1) 위치가 겹치는 동일 텍스트+라벨 (기존)
    2) 텍스트+라벨이 완전히 같으면 위치 무관하게 최고 점수 하나만 유지
    """
    entities.sort(key=lambda e: -e.score)
    kept: list[Entity] = []
    seen_text_label: set[tuple[str, str]] = set()

    for ent in entities:
        pair = (ent.text, ent.label)
        if pair in seen_text_label:
            continue

        is_dup = False
        for existing in kept:
            if (
                abs(ent.start - existing.start) < 5
                and abs(ent.end - existing.end) < 5
                and ent.label == existing.label
                and ent.text == existing.text
            ):
                is_dup = True
                break
        if not is_dup:
            kept.append(ent)
            seen_text_label.add(pair)

    kept.sort(key=lambda e: e.start)
    return kept


def _extract_by_gliner(
    text: str,
    labels: list[str],
    threshold: float,
    model_path: str | None = None,
) -> list[Entity]:
    """GLiNER로 의미적 엔티티를 추출한다."""
    gliner_labels = [l for l in labels if l not in RULE_BASED_LABELS]
    if not gliner_labels:
        return []

    model = _get_model_from_path(model_path) if model_path else _get_model()
    if model is None:
        return []

    if len(text) <= GLINER_CHUNK_SIZE:
        raw = model.predict_entities(text, gliner_labels, threshold=threshold)
        return [
            Entity(text=e["text"], label=e["label"], score=e["score"],
                   start=e["start"], end=e["end"])
            for e in raw
        ]

    chunks = _chunk_text(text, GLINER_CHUNK_SIZE, GLINER_CHUNK_OVERLAP)
    chunk_texts = [c[0] for c in chunks]
    offsets = [c[1] for c in chunks]

    batch_results = model.batch_predict_entities(
        chunk_texts, gliner_labels, threshold=threshold
    )

    all_entities: list[Entity] = []
    for chunk_entities, offset in zip(batch_results, offsets):
        for e in chunk_entities:
            all_entities.append(Entity(
                text=e["text"], label=e["label"], score=e["score"],
                start=e["start"] + offset, end=e["end"] + offset,
            ))

    return all_entities


def _postprocess(entities: list[Entity], scam_type: str, target_labels: set[str]) -> list[Entity]:
    """
    스캠 유형 컨텍스트를 활용하여 GLiNER 결과를 재분류한다.
    일반 레이블(회사명 등)을 특화 레이블(사칭 기관명 등)로 교정한다.
    """
    result: list[Entity] = []

    for ent in entities:
        new_label = ent.label

        # 기관 사칭: "회사명 또는 기관명" → "사칭 기관명"
        if (
            scam_type == "기관 사칭"
            and ent.label == "회사명 또는 기관명"
            and "사칭 기관명" in target_labels
            and any(inst in ent.text for inst in _GOVT_INSTITUTIONS)
        ):
            new_label = "사칭 기관명"

        # 기관 사칭: "사람 이름"이 직함 키워드를 포함하면 → "직함 또는 직책"
        if (
            scam_type == "기관 사칭"
            and ent.label == "사람 이름"
            and "직함 또는 직책" in target_labels
            and any(title in ent.text for title in _JOB_TITLES)
        ):
            new_label = "직함 또는 직책"

        # 건강식품 사기: "사람 이름"이면서 직함 키워드 포함 → "전문가 직함"
        if (
            scam_type == "건강식품 사기"
            and ent.label == "사람 이름"
            and "전문가 직함" in target_labels
            and any(t in ent.text for t in ["박사", "교수", "의사", "한의사", "약사"])
        ):
            new_label = "전문가 직함"

        result.append(Entity(
            text=ent.text,
            label=new_label,
            score=ent.score,
            start=ent.start,
            end=ent.end,
        ))

    return result


def extract(
    text: str,
    scam_type: str,
    labels: list[str] | None = None,
    threshold: float | None = None,
    model_path: str | None = None,
) -> list[Entity]:
    """
    하이브리드 방식으로 텍스트에서 엔티티를 추출한다.
    1) 규칙 기반(regex + keyword) 2) GLiNER(의미적) 3) 후처리(재분류)

    Args:
        text: 분석 대상 텍스트
        scam_type: 분류된 스캠 유형 (LABEL_SETS 키)
        labels: 직접 레이블을 지정할 경우
        threshold: GLiNER 추출 임계값

    Returns:
        추출된 Entity 리스트 (위치 순 정렬)
    """
    if labels is None:
        runtime_label_sets = get_runtime_scam_taxonomy()["label_sets"]
        labels = runtime_label_sets.get(scam_type, runtime_label_sets.get("투자 사기", []))
    if threshold is None:
        threshold = GLINER_THRESHOLD

    target_labels = set(labels)

    rule_entities = _extract_by_rules(text, target_labels & RULE_BASED_LABELS)
    gliner_entities = _extract_by_gliner(text, labels, threshold, model_path=model_path)

    # GLiNER 결과 후처리: 스캠 유형 컨텍스트 기반 재분류
    gliner_entities = _postprocess(gliner_entities, scam_type, target_labels)

    all_entities = rule_entities + gliner_entities
    return _deduplicate(all_entities)
