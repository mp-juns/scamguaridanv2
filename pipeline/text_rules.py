"""텍스트 룰 고위험 신호 — 게이트·분류기·추출기와 무관하게 원문에서 상시 검사.

배경 (2026-06-13): fine-tuned 게이트가 명백한 택배 사칭 스미싱을 normal 로 오판하면
분류·추출이 skip 되어 엔티티 기반 룰(`verifier.detect_rule_signals`)까지 무력화 —
전체 검출이 0건으로 끝났다. 이 모듈은 *원문 텍스트만* 보는 순수 정규식 룰이라
게이트 bucket·모델 상태와 무관하게 항상 동작한다 (네트워크·모델 호출 없음, <1ms).

Identity Boundary: 여기서도 판정하지 않는다 — "의심 패턴 감지" 신호만 보고.
정상 카드사 안내 문자도 financial_callback_lure 에 걸릴 수 있다 (의도된 보수성 —
추가 확인 필요 신호일 뿐 사기 단정이 아님).
"""

from __future__ import annotations

import re

from pipeline.extractor import Entity
from pipeline.verifier import VerificationResult

# ──────────────────────────────────────────────
# URL 추출 + 비공식/의심 판별
# ──────────────────────────────────────────────
_URL_RE = re.compile(
    r"(?:https?://)?((?:[a-z0-9\-]+\.)+[a-z]{2,})(/[^\s가-힣]*)?",
    re.IGNORECASE,
)

# 정상으로 간주하는 공식 도메인 (suffix 매칭) — 비공식/유사 도메인 판별의 화이트리스트
_OFFICIAL_DOMAIN_SUFFIXES = (
    ".go.kr", ".or.kr", ".ac.kr",
    "cjlogistics.com", "hanjin.co.kr", "hanjin.com", "lotteglogis.com",
    "ilogen.com", "epost.kr",
    "naver.com", "daum.net", "kakao.com", "kakaocorp.com",
    "kakaobank.com", "kakaopay.com", "toss.im", "tossbank.com", "tosspayments.com",
    "kbstar.com", "kbcard.com", "shinhan.com", "shinhancard.com",
    "wooribank.com", "wooricard.com", "hanabank.com", "hanacard.co.kr",
    "ibk.co.kr", "nonghyup.com", "nhbank.com",
    "coupang.com", "gmarket.co.kr", "11st.co.kr",
)

# URL 단축 서비스 — 발신 주체를 숨기는 전형적 수단
_SHORTENER_HOSTS = {
    "bit.ly", "tinyurl.com", "t.ly", "is.gd", "ow.ly", "cutt.ly", "rb.gy",
    "gg.gg", "han.gl", "vo.la", "url.kr", "c11.kr", "buly.kr", "me2.kr",
    "zrr.kr", "lrl.kr", "muz.so",
}

# 스미싱에서 다발하는 저비용·저평판 TLD
_SUSPICIOUS_TLDS = {
    "top", "xyz", "icu", "club", "vip", "tk", "ml", "ga", "cf", "gq",
    "cc", "work", "click", "link", "online", "site", "lat", "rest",
    "buzz", "pw", "cn", "shop",
}

# 브랜드 유사 도메인 토큰 — 호스트에 포함 + 화이트리스트 밖이면 typo-squatting 의심
_BRAND_TOKENS = (
    "cj", "hanjin", "lotte", "logen", "epost", "ems-", "delivery", "parcel",
    "kakao", "toss", "kbank", "kbcard", "shinhan", "woori", "nonghyup", "hana",
    "bank", "card", "pay",
)


def _is_official(host: str) -> bool:
    host = host.lower()
    return any(host == s.lstrip(".") or host.endswith(s) for s in _OFFICIAL_DOMAIN_SUFFIXES)


def _extract_hosts(text: str) -> list[str]:
    return [m.group(1).lower().rstrip(".") for m in _URL_RE.finditer(text)]


def _suspicious_url_reason(host: str) -> str | None:
    """비공식/의심 URL 이면 사유 문자열, 아니면 None."""
    if _is_official(host):
        return None
    if host in _SHORTENER_HOSTS:
        return f"단축 URL ({host})"
    tld = host.rsplit(".", 1)[-1]
    if tld in _SUSPICIOUS_TLDS:
        return f"저평판 TLD .{tld} ({host})"
    for token in _BRAND_TOKENS:
        if token in host:
            return f"브랜드 유사 도메인 의심 ({host} — '{token}' 포함, 공식 도메인 아님)"
    return None


def _unofficial_hosts(text: str) -> list[str]:
    """공식 화이트리스트 밖의 모든 호스트 (납부·안전결제 콤보 룰용)."""
    return [h for h in _extract_hosts(text) if not _is_official(h)]


# ──────────────────────────────────────────────
# 키워드 콤보 룰
# ──────────────────────────────────────────────
_COURIER_RE = re.compile(
    r"CJ\s*대한통운|대한통운|한진\s*택배|롯데\s*(택배|글로벌로지스)|우체국\s*택배"
    r"|로젠\s*택배|경동\s*택배|쿠팡\s*(친구|배송)|택배",
    re.IGNORECASE,
)
_COURIER_COMBOS: list[tuple[str, re.Pattern[str]]] = [
    ("주소 불일치", re.compile(r"주소(지)?\s*(불일치|불명|오류|미기재)")),
    ("배송 보류", re.compile(r"(배송|배달)\s*(이|이가)?\s*(보류|중단|불가|지연)|미배송")),
    ("주소 재확인", re.compile(r"(주소|배송지)\s*(를)?\s*재?\s*(확인|입력|등록)\s*(해|을|이|요망|바랍)")),
]

_FINANCE_RE = re.compile(
    r"은행|카드|캐피탈|저축은행|금융|보험|새마을금고|농협|신한|국민|우리|하나|기업은행|씨티|토스|케이뱅크",
)
_NOT_ME_RE = re.compile(r"본인\s*(이)?\s*아니|타인\s*(이용|사용|결제)|직접\s*(신청|결제)\s*(하지|안)")
_CALLBACK_RE = re.compile(r"연락|문의|전화|콜센터|고객\s*센터|상담")
_CARD_ISSUE_RE = re.compile(r"카드\s*(가|는)?\s*[^\n]{0,12}(발급|신청|승인|개설)|해외\s*[^\n]{0,6}(결제|승인)")

_PAYMENT_RE = re.compile(r"납부|체납|미납|과태료|범칙금|벌금|연체|청구\s*요금")
_SAFE_PAYMENT_RE = re.compile(r"안전\s*결제|에스크로|안전\s*거래")


def _entity(text_snippet: str, label: str = "텍스트 패턴") -> Entity:
    return Entity(text=text_snippet[:80], label=label, score=1.0, start=0, end=0, source="text_rule")


def _result(flag: str, description: str, snippet: str, evidence: list[str]) -> VerificationResult:
    return VerificationResult(
        entity=_entity(snippet),
        query="(텍스트 룰 — 검색 없음)",
        flag=flag,
        flag_description=description,
        triggered=True,
        evidence_snippets=evidence,
    )


# ──────────────────────────────────────────────
# 광고성 문자 컨텍스트 억제
# ──────────────────────────────────────────────
# 한국 정보통신망법 제50조 의무 표시 — (광고) + 무료수신거부 조합은 합법 광고 SMS 의 강한
# 지표다. 이 컨텍스트에서 단순 URL 이나 할인가는 사기 신호가 아니므로 억제한다.
# 단, 피싱 오버라이드(계정·OTP·계좌 요구 등)가 있으면 억제 안 함 — gate.py 와 동일 조건.
_PROMO_AD_MARKER_RE = re.compile(r"\(광고\)|\[광고\]", re.IGNORECASE)
_PROMO_OPT_OUT_RE = re.compile(r"무료\s*수신\s*거부")
_PROMO_PHISHING_OVERRIDE_RE = re.compile(
    r"로그인|계정\s*(확인|인증|정지|비활성)|본인\s*인증"
    r"|주민\s*(등록)?\s*번호|비밀\s*번호|OTP|인증\s*번호"
    r"|카드\s*(번호|정보)|계좌\s*(번호|이체|입금|정보)"
    r"|텔레그램|카카오톡\s*(으로|에서|로\s*연락|아이디)"
    r"|선\s*입금|택배\s*비\s*선|수수\s*료\s*먼저"
    r"|안전\s*계좌|자금\s*(보호|이체)"
    r"|(설치|다운로드)\s*(하세요|해\s*주세요|해야)"
)


def _is_promotional_context(text: str) -> bool:
    """법정 광고 표시 (광고) + 무료수신거부 조합이며 피싱 오버라이드 없음."""
    return (
        bool(_PROMO_AD_MARKER_RE.search(text))
        and bool(_PROMO_OPT_OUT_RE.search(text))
        and not bool(_PROMO_PHISHING_OVERRIDE_RE.search(text))
    )


def detect_text_risk_signals(text: str) -> list[VerificationResult]:
    """원문 텍스트의 고위험 패턴 룰 — 게이트 bucket 과 무관하게 항상 실행.

    triggered=True 인 결과만 반환한다. 룰별 1건, 같은 flag 라도 룰이 다르면
    별도 결과 (signal_detector 가 flag 단위로 dedupe).
    """
    if not text or not text.strip():
        return []
    results: list[VerificationResult] = []
    is_promo = _is_promotional_context(text)

    # 1. 비공식 URL / 유사 도메인
    # 광고성 문자(법정 (광고)+수신거부)에서는 단축 URL·저평판 TLD 조건만 적용.
    # 브랜드 유사 도메인·공식 도메인 아님 이유로 인한 false positive 를 억제한다.
    suspicious = [(h, _suspicious_url_reason(h)) for h in _extract_hosts(text)]
    if is_promo:
        # 프로모션 컨텍스트: 단축 URL 또는 저평판 TLD 만 진짜 신호로 인정
        suspicious = [(h, r) for h, r in suspicious if r and (
            h in _SHORTENER_HOSTS
            or h.rsplit(".", 1)[-1] in _SUSPICIOUS_TLDS
        )]
    else:
        suspicious = [(h, r) for h, r in suspicious if r]
    if suspicious:
        results.append(_result(
            "smishing_link_detected",
            "[텍스트 룰] 비공식 URL / 유사 도메인 감지",
            suspicious[0][0],
            [r for _, r in suspicious[:3]],
        ))

    # 2~4. 택배사명 + (주소 불일치 | 배송 보류 | 주소 재확인)
    courier_match = _COURIER_RE.search(text)
    if courier_match:
        hits = [name for name, pattern in _COURIER_COMBOS if pattern.search(text)]
        if hits:
            results.append(_result(
                "courier_impersonation_pattern",
                "[텍스트 룰] 택배사명 + 주소 재입력 유도 패턴",
                courier_match.group(0),
                [f"택배 키워드 '{courier_match.group(0)}' + {h}" for h in hits],
            ))

    # 5. 금융기관 + "본인 아니면 연락"
    finance_match = _FINANCE_RE.search(text)
    if finance_match and _NOT_ME_RE.search(text) and _CALLBACK_RE.search(text):
        results.append(_result(
            "financial_callback_lure",
            "[텍스트 룰] 금융기관 사칭 의심 — 본인 아님 시 연락 유도",
            finance_match.group(0),
            [f"금융 키워드 '{finance_match.group(0)}' + 본인 아님 문구 + 연락 유도"],
        ))

    # 6. 카드 발급 + 콜백 유도
    card_match = _CARD_ISSUE_RE.search(text)
    if card_match and _CALLBACK_RE.search(text):
        results.append(_result(
            "financial_callback_lure",
            "[텍스트 룰] 카드 발급·승인 통보 + 콜백 유도",
            card_match.group(0),
            [f"'{card_match.group(0).strip()}' + 전화 회신 유도"],
        ))

    # 7. 납부/체납 + 비공식 링크
    payment_match = _PAYMENT_RE.search(text)
    if payment_match:
        unofficial = _unofficial_hosts(text)
        if unofficial:
            results.append(_result(
                "payment_demand_unofficial_link",
                "[텍스트 룰] 납부·체납 요구 + 비공식 링크",
                payment_match.group(0),
                [f"'{payment_match.group(0)}' + 비공식 링크 {unofficial[0]}"],
            ))

    # 8. 안전결제/에스크로 + 외부 링크
    safepay_match = _SAFE_PAYMENT_RE.search(text)
    if safepay_match:
        hosts = _extract_hosts(text)
        if hosts:
            results.append(_result(
                "safe_payment_external_link",
                "[텍스트 룰] 안전결제·에스크로 언급 + 외부 링크",
                safepay_match.group(0),
                [f"'{safepay_match.group(0)}' + 외부 링크 {hosts[0]}"],
            ))

    return results
