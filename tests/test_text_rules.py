"""텍스트 룰 고위험 신호 (pipeline/text_rules.py) — 게이트 무관 상시 검사 룰."""

from __future__ import annotations

from pipeline.text_rules import detect_text_risk_signals


def _flags(text: str) -> set[str]:
    return {r.flag for r in detect_text_risk_signals(text)}


# ── 핵심 회귀 케이스: 게이트가 normal 로 오판했던 실제 스미싱 ──

def test_cj_smishing_case_detected():
    text = "[CJ대한통운] 고객님 택배가 주소 불일치로 배송 보류되었습니다. 주소를 재확인해주세요 ▶ cj-delivery.top/Re24"
    flags = _flags(text)
    # 비공식 URL(.top + 브랜드 유사) + 택배 사칭 콤보 — 최소 2종
    assert "smishing_link_detected" in flags
    assert "courier_impersonation_pattern" in flags


def test_cj_smishing_with_annotation_still_detected():
    # "감별 포인트" 해설이 붙어 게이트가 normal 0.97 로 오판하던 입력 — 룰은 영향 없음
    text = (
        "[CJ대한통운] 고객님 택배가 주소 불일치로 배송 보류되었습니다. "
        "주소를 재확인해주세요 ▶ cj-delivery.top/Re24\n\n"
        "감별 포인트: 단축·유사 도메인, 주소 재입력 유도, 발신번호 불명"
    )
    assert {"smishing_link_detected", "courier_impersonation_pattern"} <= _flags(text)


# ── 룰별 ──

def test_unofficial_url_shortener():
    assert "smishing_link_detected" in _flags("자세한 내용은 bit.ly/3xK2 에서 확인하세요")


def test_unofficial_url_suspicious_tld():
    assert "smishing_link_detected" in _flags("확인: http://event-prize.xyz/win")


def test_courier_hold_combo():
    assert "courier_impersonation_pattern" in _flags("한진택배 운송장 배송이 보류되었습니다")


def test_courier_readdress_combo():
    assert "courier_impersonation_pattern" in _flags("롯데택배: 배송지 재확인 바랍니다")


def test_financial_not_me_callback():
    text = "신한은행 대출 승인 안내. 본인이 아니시면 02-1234-5678 로 연락 주시기 바랍니다."
    assert "financial_callback_lure" in _flags(text)


def test_card_issue_callback():
    text = "회원님 명의로 카드가 발급 완료되었습니다. 본인 확인을 위해 고객센터로 문의 바랍니다."
    assert "financial_callback_lure" in _flags(text)


def test_payment_demand_unofficial_link():
    text = "교통 범칙금이 미납되었습니다. 즉시 납부: traffic-fine.top/pay"
    assert "payment_demand_unofficial_link" in _flags(text)


def test_safe_payment_external_link():
    text = "안전결제로 진행해요. 여기서 결제해 주세요: safe-pay-market.com/item/3"
    assert "safe_payment_external_link" in _flags(text)


# ── 무탐 (false positive 방지) ──

def test_normal_delivery_complete_not_flagged():
    # 링크 없는 정상 배송 완료 안내 — 어떤 룰에도 안 걸려야
    text = "CJ대한통운 택배입니다. 고객님께서 기다리시던 상품이 금일 배송 완료되었습니다."
    assert _flags(text) == set()


def test_casual_text_not_flagged():
    assert _flags("엄마 나 오늘 야근해서 늦어. 저녁 먼저 먹어.") == set()


def test_official_govkr_payment_link_not_unofficial():
    # 공식 go.kr 도메인 — 납부 콤보의 '비공식 링크' 조건 미충족
    text = "자동차세 납부 안내: wetax.go.kr 에서 납부하실 수 있습니다."
    assert "payment_demand_unofficial_link" not in _flags(text)


def test_empty_text():
    assert detect_text_risk_signals("") == []


# ── 광고성 쇼핑 문자 오탐 방지 ──

_TEMU_AD = """[Web발신]
(광고)Temu:
이 상품의 원가가 5,750원이었는데, 지금은 575원!
장바구니 상품이 특별가로 판매되고 있습니다! 지금 확인해보세요!
https://temu.com/v/zBdrpD7A

주소: 6 RAFFLES QUAY, #14-06, SINGAPORE
무료수신거부: 0808208368"""


def test_temu_ad_no_flags():
    # 법정 (광고) + 무료수신거부 + temu.com (단축/저평판 TLD 아님) → 신호 없음
    assert _flags(_TEMU_AD) == set()


def test_promo_ad_with_shortener_still_flagged():
    # 광고 문자라도 단축 URL 은 여전히 검출해야 한다
    text = "(광고)이벤트 확인: bit.ly/sale99\n무료수신거부: 0808001234"
    assert "smishing_link_detected" in _flags(text)


def test_promo_ad_with_suspicious_tld_still_flagged():
    # 저평판 TLD(.xyz) 는 광고 컨텍스트에도 검출
    text = "(광고)특가 이벤트: event-shop.xyz/discount\n무료수신거부: 0808001234"
    assert "smishing_link_detected" in _flags(text)


def test_promo_ad_with_account_verify_not_suppressed():
    # (광고) + 무료수신거부 있어도 계정 확인 요구 있으면 억제 안 함
    text = (
        "(광고)계정 확인이 필요합니다. https://evil-bank.com/login\n"
        "무료수신거부: 0808001234"
    )
    # 피싱 오버라이드(로그인/계정 확인)가 있으므로 프로모션 억제 미적용
    # evil-bank.com 은 brand token "bank" 포함 → smishing_link_detected
    assert "smishing_link_detected" in _flags(text)
