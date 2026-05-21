"""
ScamGuardian v2 — 교차 검증 모듈
추출된 엔티티를 Serper API로 검색하여 신뢰성을 검증한다.
LLM 없이 검색 결과 유무(hit/miss)만으로 판단한다.
"""

from __future__ import annotations

import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
import torch
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer, util

from pipeline.config import (
    MODELS,
    SERPER_API_URL,
    SERPER_BATCH_DELAY,
    SERPER_DELAY,
    SERPER_MAX_CONCURRENT,
    TRUSTED_QUERY_A_DOMAINS,
)
from pipeline.extractor import Entity

load_dotenv()


@dataclass
class VerificationResult:
    entity: Entity
    query: str
    flag: str                           # SCORING_RULES의 키
    flag_description: str               # 사람이 읽을 수 있는 설명
    triggered: bool                     # 해당 플래그 발동 여부
    search_hits: int = 0                # 검색 결과 수
    evidence_snippets: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_text": self.entity.text,
            "entity_label": self.entity.label,
            "query": self.query,
            "flag": self.flag,
            "flag_description": self.flag_description,
            "triggered": self.triggered,
            "search_hits": self.search_hits,
            "evidence_snippets": self.evidence_snippets,
        }


_serper_call_count = 0
_serper_call_lock = threading.Lock()
_serper_semaphore = threading.Semaphore(SERPER_MAX_CONCURRENT)


def _serper_search(query: str, num_results: int = 5) -> dict:
    """Serper API를 호출하여 검색 결과를 반환한다. 세마포어로 동시 호출 제한."""
    global _serper_call_count

    with _serper_semaphore:
        api_key = os.getenv("SERPER_API_KEY", "")
        if not api_key:
            raise EnvironmentError("SERPER_API_KEY가 .env에 설정되지 않았습니다.")

        with _serper_call_lock:
            _serper_call_count += 1
            call_num = _serper_call_count
        payload = {"q": query, "num": num_results, "gl": "kr", "hl": "ko"}
        print(f"    [Serper #{call_num}] → 쿼리: {query[:80]}")

        t0 = time.time()
        resp = requests.post(
            SERPER_API_URL,
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        try:
            from platform_layer import cost as _cost
            _cost.record_serper(1, action="verifier.search")
        except Exception:
            pass
        elapsed = time.time() - t0
        hits = len(data.get("organic", []))
        top_titles = [item.get("title", "")[:40] for item in data.get("organic", [])[:2]]
        print(
            f"    [Serper #{call_num}] ← {hits}건 ({elapsed:.1f}s)"
            + (f" | {', '.join(top_titles)}" if top_titles else "")
        )
        time.sleep(SERPER_BATCH_DELAY)
        return data


def _count_hits(result: dict) -> int:
    return len(result.get("organic", []))


def _extract_snippets(result: dict, max_snippets: int = 3) -> list[str]:
    snippets: list[str] = []
    for item in result.get("organic", [])[:max_snippets]:
        snippet = item.get("snippet", "")
        if snippet:
            snippets.append(snippet)
    return snippets


def _has_scam_keywords(snippets: list[str]) -> bool:
    """스니펫에 스캠/사기 관련 키워드가 포함되어 있는지 확인한다."""
    keywords = [
        "사기",
        "스캠",
        "피싱",
        "phishing",
        "fraud",
        "fake",
        "scam",
        "deepfake",
        "신고",
        "피해",
        "주의보",
        "경고",
        "불법",
        "미등록",
        "무허가",
    ]
    text = " ".join(snippets).lower()
    return any(kw in text for kw in keywords)


def _parse_return_rate(text: str) -> float | None:
    """'연 30%', '월 10%' 등에서 퍼센트 수치를 추출한다."""
    match = re.search(r"(\d+(?:\.\d+)?)\s*%", text)
    if match:
        return float(match.group(1))
    return None


# ──────────────────────────────────────────────
# 노션 다음 단계(임베딩/쿼리) 헬퍼
# ──────────────────────────────────────────────

_BERT_SIM_MODEL_NAME = MODELS["sbert_similarity"]
_BERT_SIM_THRESHOLD_UNCERTAIN = 0.6
_BERT_SIM_THRESHOLD_MISMATCH = 0.3

_speaker_profile_model: SentenceTransformer | None = None
_sbert_lock = threading.Lock()


def _project_hf_cache_dir() -> Path:
    return Path(__file__).resolve().parents[1] / ".cache" / "huggingface"


def _resolve_local_hf_snapshot(model_id: str) -> str | None:
    candidate_roots = [
        _project_hf_cache_dir() / "hub",
        Path.home() / ".cache" / "huggingface" / "hub",
    ]
    for cache_root in candidate_roots:
        model_dir = cache_root / f"models--{model_id.replace('/', '--')}"
        refs_main = model_dir / "refs" / "main"
        if not refs_main.exists():
            continue

        revision = refs_main.read_text().strip()
        snapshot_dir = model_dir / "snapshots" / revision
        if snapshot_dir.exists():
            return str(snapshot_dir)
    return None


def _get_sbert_model() -> SentenceTransformer:
    global _speaker_profile_model
    if _speaker_profile_model is not None:
        return _speaker_profile_model
    with _sbert_lock:
        if _speaker_profile_model is not None:
            return _speaker_profile_model
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model_source = _resolve_local_hf_snapshot(f"sentence-transformers/{_BERT_SIM_MODEL_NAME}")
        if model_source:
            _speaker_profile_model = SentenceTransformer(model_source, device=device, local_files_only=True)
        else:
            _speaker_profile_model = SentenceTransformer(
                _BERT_SIM_MODEL_NAME,
                device=device,
                cache_folder=str(_project_hf_cache_dir()),
            )
    return _speaker_profile_model


def _choose_speaker(entities: list[Entity]) -> Entity | None:
    """노션 단계에서 필요한 '화자명' 후보를 뽑는다."""
    # 1순위: 사람 이름
    for e in entities:
        if e.label == "사람 이름":
            return e
    # 2순위: 회사/기관명(현재 extractor에서 머스크가 여기로 잡히는 케이스 대응)
    for e in entities:
        if e.label == "회사명 또는 기관명":
            return e
    return None


def _extract_claim_keyword(entities: list[Entity]) -> str:
    """쿼리 템플릿의 핵심 '주장 키워드'를 뽑는다."""
    preferred_order = [
        "수익 퍼센트",
        "투자 상품명",
        "치료 효능 주장",
        "제품명",
        "금액",
    ]
    for label in preferred_order:
        for e in entities:
            if e.label == label:
                # 금액 라벨 중 '%'가 섞인 케이스는 claim으로는 덜 유용하므로 제외
                if label == "금액" and "%" in e.text:
                    continue
                return e.text
    return ""


def _extract_investment_amount(entities: list[Entity]) -> str:
    """Query C에 쓰기 위한 송금/투자 금액을 최대한 '진짜 금액' 형태로 선택한다."""
    # 예: 300만원 같은 형태 우선. (전화번호나 30% 오인을 줄이기 위함)
    for e in entities:
        if e.label == "금액" and any(unit in e.text for unit in ["만원", "원"]):
            return e.text
    # fallback
    for e in entities:
        if e.label == "금액" and "%" not in e.text:
            return e.text
    return ""


def _extract_year(transcript: str) -> str | None:
    m = re.search(r"(20\d{2})", transcript)
    return m.group(1) if m else None


def _domain_of_link(link: str) -> str:
    try:
        parsed = urlparse(link)
        host = (parsed.netloc or "").lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def _build_query_a(speaker_name: str, claim_keyword: str) -> str:
    # 노션 문서의 S 도메인 우선(confirmed/unconfirmed 판단에 사용)
    site_clause = " OR ".join([f"site:{d}" for d in TRUSTED_QUERY_A_DOMAINS])
    return f'"{speaker_name}" "{claim_keyword}" {site_clause}'


def _build_query_b(claim_keyword: str, year: str | None) -> str:
    if year:
        return f'"{claim_keyword}" "{year}" fact check OR confirmed OR denied'
    return f'"{claim_keyword}" fact check OR confirmed OR denied'


def _build_query_c(speaker_name: str, amount_or_investment: str, claim_keyword: str) -> str:
    seed = amount_or_investment or claim_keyword
    return f'"{speaker_name}" "{seed}" scam OR fraud OR fake OR deepfake'


def _sbert_cosine_similarity(speaker_profile_text: str, speech_content_text: str) -> float:
    model = _get_sbert_model()
    # normalize_embeddings=True면 cos 유사도 범위가 -1~1 대신 0~1 근처로 안정적
    emb1 = model.encode(speaker_profile_text, convert_to_tensor=True, normalize_embeddings=True)
    emb2 = model.encode(speech_content_text, convert_to_tensor=True, normalize_embeddings=True)
    return float(util.cos_sim(emb1, emb2).item())


def _has_factcheck_confirmed(snippets: list[str]) -> bool:
    text = " ".join(snippets).lower()
    confirmed_markers = [
        "confirmed",
        "verified",
        "fact check",
        "denied",
        "사실무근",
        "오보",
        "부인",
        "확인",
        "검증",
        "not true",
    ]
    return any(m in text for m in confirmed_markers)


def _hit_in_sa_domains(organic_items: list[dict[str, Any]]) -> bool:
    for it in organic_items:
        link = it.get("link", "") or ""
        if _domain_of_link(link) in TRUSTED_QUERY_A_DOMAINS:
            return True
    return False


# ──────────────────────────────────────────────
# ──────────────────────────────────────────────
# 엔티티 유형별 검증 전략
# ──────────────────────────────────────────────

def _verify_company(entity: Entity, all_entities: list[Entity]) -> list[VerificationResult]:
    """회사명 검증: 사업자등록 + 금감원 등록 + 스캠 신고"""
    results: list[VerificationResult] = []
    name = entity.text

    # 회사 검증 3개 쿼리를 병렬로 실행
    person_entities = [e for e in all_entities if e.label == "사람 이름"]
    person_name = person_entities[0].text if person_entities else None

    q1 = f'"{name}" 사업자등록 site:bizno.net'
    q2 = f'"{name}" site:fss.or.kr'
    q3 = f'"{person_name}" "{name}" 대표이사' if person_name else None

    queries = [q1, q2] + ([q3] if q3 else [])
    with ThreadPoolExecutor(max_workers=len(queries)) as ex:
        futures = {ex.submit(_serper_search, q): q for q in queries}
        search_results = {}
        for f in as_completed(futures):
            search_results[futures[f]] = f.result()

    sr1 = search_results[q1]
    results.append(VerificationResult(
        entity=entity, query=q1,
        flag="business_not_registered",
        flag_description=f"'{name}' 사업자등록 정보 미확인",
        triggered=_count_hits(sr1) == 0,
        search_hits=_count_hits(sr1),
        evidence_snippets=_extract_snippets(sr1),
    ))

    sr2 = search_results[q2]
    results.append(VerificationResult(
        entity=entity, query=q2,
        flag="fss_not_registered",
        flag_description=f"'{name}' 금융감독원 등록 미확인",
        triggered=_count_hits(sr2) == 0,
        search_hits=_count_hits(sr2),
        evidence_snippets=_extract_snippets(sr2),
    ))

    if q3:
        sr3 = search_results[q3]
        results.append(VerificationResult(
            entity=entity, query=q3,
            flag="ceo_name_mismatch",
            flag_description=f"'{person_name}'이(가) '{name}'의 대표인지 확인 불가",
            triggered=_count_hits(sr3) == 0,
            search_hits=_count_hits(sr3),
            evidence_snippets=_extract_snippets(sr3),
        ))

    return results


def _verify_phone(entity: Entity) -> list[VerificationResult]:
    """전화번호 검증: 스캠 신고 이력"""
    q = f'"{entity.text}" 사기 OR 스캠 OR 피싱 OR 신고'
    sr = _serper_search(q)
    snippets = _extract_snippets(sr)
    return [VerificationResult(
        entity=entity,
        query=q,
        flag="phone_scam_reported",
        flag_description=f"'{entity.text}' 스캠/사기 신고 이력 발견",
        triggered=_has_scam_keywords(snippets),
        search_hits=_count_hits(sr),
        evidence_snippets=snippets,
    )]


def _verify_website(entity: Entity) -> list[VerificationResult]:
    """웹사이트 검증: 피싱 신고"""
    domain = entity.text.replace("http://", "").replace("https://", "").split("/")[0]
    q = f'site:{domain} 사기 OR 피싱 OR 스캠'
    sr = _serper_search(q)
    snippets = _extract_snippets(sr)
    return [VerificationResult(
        entity=entity,
        query=q,
        flag="website_scam_reported",
        flag_description=f"'{domain}' 관련 피싱/사기 신고 발견",
        triggered=_has_scam_keywords(snippets),
        search_hits=_count_hits(sr),
        evidence_snippets=snippets,
    )]


def _verify_account(entity: Entity) -> list[VerificationResult]:
    """계좌번호 검증: 스캠 신고 이력"""
    q = f'"{entity.text}" 사기 OR 보이스피싱 OR 신고'
    sr = _serper_search(q)
    snippets = _extract_snippets(sr)
    return [VerificationResult(
        entity=entity,
        query=q,
        flag="account_scam_reported",
        flag_description=f"계좌 '{entity.text}' 스캠 신고 이력 발견",
        triggered=_has_scam_keywords(snippets),
        search_hits=_count_hits(sr),
        evidence_snippets=snippets,
    )]


def _verify_certification(entity: Entity) -> list[VerificationResult]:
    """인증/보증 기관 검증: 실제 존재 여부"""
    q = f'"{entity.text}" 공식 사이트'
    sr = _serper_search(q)
    return [VerificationResult(
        entity=entity,
        query=q,
        flag="fake_certification",
        flag_description=f"'{entity.text}' 공식 기관 확인 불가",
        triggered=_count_hits(sr) == 0,
        search_hits=_count_hits(sr),
        evidence_snippets=_extract_snippets(sr),
    )]


def _verify_impersonated_agency(entity: Entity) -> list[VerificationResult]:
    """사칭 기관 검증: 공식 전화번호 대조"""
    q = f'"{entity.text}" 공식 대표번호'
    sr = _serper_search(q)
    return [VerificationResult(
        entity=entity,
        query=q,
        flag="fake_government_agency",
        flag_description=f"'{entity.text}' 사칭 의심 — 공식 연락처 불일치",
        triggered=_count_hits(sr) == 0,
        search_hits=_count_hits(sr),
        evidence_snippets=_extract_snippets(sr),
    )]


def _verify_return_rate(entity: Entity) -> list[VerificationResult]:
    """수익률 검증: 비정상 고수익 여부"""
    rate = _parse_return_rate(entity.text)
    triggered = rate is not None and rate > 20.0
    return [VerificationResult(
        entity=entity,
        query="(규칙 기반 판단: 수익률 > 20%)",
        flag="abnormal_return_rate",
        flag_description=f"'{entity.text}' — 비정상적 고수익 주장",
        triggered=triggered,
        search_hits=0,
    )]


def _verify_personal_info(entity: Entity) -> list[VerificationResult]:
    """개인정보 요구 검증: 즉시 플래그"""
    return [VerificationResult(
        entity=entity,
        query="(규칙 기반 판단: 개인정보 요구)",
        flag="personal_info_request",
        flag_description=f"'{entity.text}' — 개인정보 요구 감지",
        triggered=True,
        search_hits=0,
    )]


def _verify_medical_claim(entity: Entity) -> list[VerificationResult]:
    """의료 효능 주장 검증: 식약처 인증 여부"""
    q = f'"{entity.text}" site:mfds.go.kr'
    sr = _serper_search(q)
    return [VerificationResult(
        entity=entity,
        query=q,
        flag="medical_claim_unverified",
        flag_description=f"'{entity.text}' — 식약처 인증 미확인",
        triggered=_count_hits(sr) == 0,
        search_hits=_count_hits(sr),
        evidence_snippets=_extract_snippets(sr),
    )]


def _verify_exchange(entity: Entity) -> list[VerificationResult]:
    """거래소 검증: 실제 등록 거래소인지 확인"""
    q = f'"{entity.text}" 가상자산 거래소 등록'
    sr = _serper_search(q)
    return [VerificationResult(
        entity=entity,
        query=q,
        flag="fake_exchange",
        flag_description=f"'{entity.text}' — 미등록 거래소 의심",
        triggered=_count_hits(sr) == 0,
        search_hits=_count_hits(sr),
        evidence_snippets=_extract_snippets(sr),
    )]


# ──────────────────────────────────────────────
# 레이블 → 검증 함수 매핑
#
# 룰 기반 vs Serper 기반을 분리한다 (Stage 1 게이트 라우팅용):
#   - 룰 기반   : 네트워크 호출 없이 엔티티 텍스트만으로 판단. 모든 gate bucket
#                 에서 *항상* 실행 (detect_rule_signals).
#   - Serper 기반: Serper API 검색 필요. gate profile 에 따라 실행 강도 조절 (verify).
# ──────────────────────────────────────────────

# 룰 기반 — 네트워크 호출 없음. 항상 안전하게 실행 가능.
_RULE_VERIFY_DISPATCH: dict[str, Any] = {
    "수익 퍼센트": _verify_return_rate,
    "개인정보 항목": _verify_personal_info,
}

# Serper 기반 — 네트워크 호출. gate profile 로 게이팅.
_SERPER_VERIFY_DISPATCH: dict[str, Any] = {
    "전화번호": _verify_phone,
    "웹사이트 주소": _verify_website,
    "계좌번호": _verify_account,
    "보증 기관명": _verify_certification,
    "인증 기관명": _verify_certification,
    "인허가 기관명": _verify_certification,
    "사칭 기관명": _verify_impersonated_agency,
    "치료 효능 주장": _verify_medical_claim,
    "거래소명": _verify_exchange,
}

# 회사명은 다른 엔티티 참조가 필요하므로 별도 처리 (Serper 기반)
_COMPANY_LABELS = {"회사명 또는 기관명"}


def detect_rule_signals(entities: list[Entity]) -> list[VerificationResult]:
    """룰 기반 신호 검출 — 네트워크 호출 없음.

    엔티티 텍스트만으로 판단하므로 (수익률 임계 초과, 개인정보 요구) Serper·LLM 과
    무관하게 *모든 gate bucket 에서 항상* 실행할 수 있다. runner 가 게이트 결과와
    상관없이 무조건 호출한다 — 게이트가 normal 로 오판해도 검출 누락이 없도록.
    """
    results: list[VerificationResult] = []
    for entity in entities:
        fn = _RULE_VERIFY_DISPATCH.get(entity.label)
        if fn is not None:
            results.extend(fn(entity))
    return results


def verify(entities: list[Entity], scam_type: str, transcript: str) -> list[VerificationResult]:
    """
    추출된 엔티티 리스트를 **Serper 기반** 교차 검증한다.
    엔티티별 검증을 병렬로 실행하여 속도를 높인다.

    룰 기반 신호(`detect_rule_signals`)는 여기서 다루지 않는다 — runner 가 게이트와
    무관하게 별도로 항상 호출한다. 이 함수는 Serper API 호출이 필요한 검증만 수행하며
    gate profile 에 따라 호출 여부·대상 수가 조절된다.

    Args:
        entities: 검증 대상 엔티티 리스트 (gate profile 의 serper 상한으로 제한된 상태)
        scam_type: 분류된 스캠 유형
        transcript: 원본 텍스트

    Returns:
        검증 결과 리스트 (트리거된 것과 미트리거된 것 모두 포함)
    """
    results: list[VerificationResult] = []

    # ── 엔티티별 검증을 병렬 실행 (Serper 기반만) ──
    def _verify_entity(entity: Entity) -> list[VerificationResult]:
        label = entity.label
        if label in _COMPANY_LABELS:
            return _verify_company(entity, entities)
        verify_fn = _SERPER_VERIFY_DISPATCH.get(label)
        if verify_fn is not None:
            return verify_fn(entity)
        return []

    with ThreadPoolExecutor(max_workers=SERPER_MAX_CONCURRENT) as executor:
        futures = [executor.submit(_verify_entity, e) for e in entities]
        for f in futures:
            results.extend(f.result())

    # ── 화자 프로파일 + 쿼리 A/B/C (병렬) ──
    if transcript and entities:
        speaker_entity = _choose_speaker(entities)
        claim_keyword = _extract_claim_keyword(entities)
        amount_or_investment = _extract_investment_amount(entities)
        year = _extract_year(transcript)

        if speaker_entity and claim_keyword:
            speaker_name = speaker_entity.text

            # 4개 쿼리를 동시 실행
            q_profile = f'"{speaker_name}" 직업 분야 최근 활동'
            q_a = _build_query_a(speaker_name, claim_keyword)
            q_b = _build_query_b(claim_keyword, year)
            q_c = _build_query_c(speaker_name, amount_or_investment, claim_keyword)

            with ThreadPoolExecutor(max_workers=SERPER_MAX_CONCURRENT) as executor:
                f_profile = executor.submit(_serper_search, q_profile, 5)
                f_a = executor.submit(_serper_search, q_a, 10)
                f_b = executor.submit(_serper_search, q_b, 10)
                f_c = executor.submit(_serper_search, q_c, 10)

                sr_profile = f_profile.result()
                sr_a = f_a.result()
                sr_b = f_b.result()
                sr_c = f_c.result()

            # 화자 프로파일 → BERT 유사도
            profile_snippets = _extract_snippets(sr_profile, max_snippets=5)
            speech_content_text = transcript[:2000]
            speaker_profile_text = " ".join(profile_snippets)[:4000]

            if profile_snippets and speech_content_text.strip():
                sim = _sbert_cosine_similarity(speaker_profile_text, speech_content_text)

                if sim < _BERT_SIM_THRESHOLD_MISMATCH:
                    results.append(VerificationResult(
                        entity=speaker_entity, query=q_profile,
                        flag="authority_context_mismatch",
                        flag_description=f"화자 프로파일 vs 발화 맥락 의미가 불일치 (cos={sim:.3f})",
                        triggered=True,
                        search_hits=_count_hits(sr_profile),
                        evidence_snippets=[f"[cosine_similarity] {sim:.3f}", *profile_snippets[:3]],
                    ))
                elif sim < _BERT_SIM_THRESHOLD_UNCERTAIN:
                    results.append(VerificationResult(
                        entity=speaker_entity, query=q_profile,
                        flag="authority_context_uncertain",
                        flag_description=f"화자 프로파일 vs 발화 맥락 의미가 애매 (cos={sim:.3f})",
                        triggered=True,
                        search_hits=_count_hits(sr_profile),
                        evidence_snippets=[f"[cosine_similarity] {sim:.3f}", *profile_snippets[:3]],
                    ))

            # Query A: 신뢰 언론 히트
            organic_a = sr_a.get("organic", []) or []
            hit_in_sa = _hit_in_sa_domains(organic_a)
            snippets_a = _extract_snippets(sr_a, max_snippets=5)
            results.append(VerificationResult(
                entity=speaker_entity, query=q_a,
                flag="query_a_confirmed" if hit_in_sa else "query_a_unconfirmed",
                flag_description=f"신뢰 도메인(S/A)에서 화자+발언 동시 히트 확인 ({'있음' if hit_in_sa else '없음'})",
                triggered=True,
                search_hits=_count_hits(sr_a),
                evidence_snippets=snippets_a,
            ))

            # Query B: 팩트체크
            snippets_b = _extract_snippets(sr_b, max_snippets=5)
            b_has_scam_keywords = _has_scam_keywords(snippets_b)
            b_has_confirmed = _has_factcheck_confirmed(snippets_b)

            if b_has_scam_keywords:
                results.append(VerificationResult(
                    entity=speaker_entity, query=q_b,
                    flag="query_b_factcheck_found",
                    flag_description="팩트체크/검증 결과 스캠/사기 관련 단서 포함",
                    triggered=True,
                    search_hits=_count_hits(sr_b),
                    evidence_snippets=snippets_b,
                ))
            if b_has_confirmed:
                results.append(VerificationResult(
                    entity=speaker_entity, query=q_b,
                    flag="query_b_confirmed",
                    flag_description="팩트체크에서 확인/부인(denied) 등 검증 단서 발견",
                    triggered=True,
                    search_hits=_count_hits(sr_b),
                    evidence_snippets=snippets_b,
                ))

            # Query C: 스캠 패턴
            snippets_c = _extract_snippets(sr_c, max_snippets=5)
            if _has_scam_keywords(snippets_c):
                results.append(VerificationResult(
                    entity=speaker_entity, query=q_c,
                    flag="query_c_scam_pattern_found",
                    flag_description="스캠/사기 패턴 관련 단서가 검색 결과에서 확인됨",
                    triggered=True,
                    search_hits=_count_hits(sr_c),
                    evidence_snippets=snippets_c,
                ))

    return results
