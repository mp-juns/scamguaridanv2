"""스미싱 분류기 후처리 검증 — pipeline/classifier.py 의 _has_smishing_indicators.

요구 3: 스미싱으로 확정하려면 지시자 2개 이상 필요.
사기 관련 메타 토론 텍스트는 지시자가 없어 is_uncertain=True 로 처리되어야 한다.
"""

from __future__ import annotations

from pipeline.classifier import _has_smishing_indicators


def test_meta_discussion_has_no_smishing_indicators():
    """사기 분류 회의 전사 — URL·OTP·긴급 요구 없음 → 지시자 0개."""
    text = (
        "게이트가 판단한 2단계에서 사기 유형 분류기가 70% 넘으면 사기라고 할 수 있지. "
        "정상인지 사기인지 불명하고. 구독과 좋아요 부탁드려요! 다음 영상에서 만나요."
    )
    assert not _has_smishing_indicators(text, min_count=2)


def test_legit_smishing_url_and_courier_two_indicators():
    """진짜 스미싱 — https URL + 대한통운(은행류 포함) → 2개 지시자."""
    text = "[CJ대한통운] 배송 보류. 주소 재확인: https://cj-fake.top/confirm"
    assert _has_smishing_indicators(text, min_count=2)


def test_otp_and_payment_two_indicators():
    """OTP + 결제 요구 → 2개 지시자."""
    text = "귀하의 계좌에서 결제가 진행됩니다. OTP를 입력해 주세요."
    assert _has_smishing_indicators(text, min_count=2)


def test_url_only_is_single_indicator():
    """URL 하나뿐이고 다른 지시자 없으면 min_count=2 미달."""
    text = "오늘 날씨 정보는 https://weather.example.com 에서 확인 가능합니다."
    # https:// (1 indicator) — "확인 가능합니다" 는 "확인하세요" 패턴 미매칭
    assert not _has_smishing_indicators(text, min_count=2)


def test_app_install_and_account_verify_two_indicators():
    """앱 설치 + 본인인증 요구 → 2개 지시자."""
    text = "지금 바로 앱을 설치하세요. 본인인증이 필요합니다."
    assert _has_smishing_indicators(text, min_count=2)


def test_empty_text_has_no_indicators():
    assert not _has_smishing_indicators("", min_count=2)


def test_casual_chat_has_no_indicators():
    assert not _has_smishing_indicators("엄마 나 오늘 야근해서 늦어. 저녁 먼저 먹어.", min_count=2)
