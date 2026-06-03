"""Live Voice 화자별 계층적 알림 tier 로직 단위 테스트.

같은 키워드라도 화자(본인/상대방)로 심각도가 다름:
- 본인 발설(주민번호·OTP)·송금 동의 → instant danger
- 상대방 사칭·요구·압박 → 누적 경고(non-instant)
tier 단조 증가, instant → 즉시 3, 누적 임계 → 2/3.
"""
from __future__ import annotations

from api_server_pkg import stream_analyze as s


def _turn(speaker, text):
    return {"speaker": speaker, "text": text, "start_sec": 0.0, "end_sec": 1.0}


# ---- 화자별 분류: 같은 단어, 다른 심각도 ----

def test_victim_ssn_disclosure_is_instant():
    # 본인이 주민번호를 말함 = 발설 → instant danger
    _, matches = s._scan_turns([_turn("본인", "내 주민번호는 880101이고")])
    m = next(x for x in matches if x["flag"] == "ssn")
    assert m["instant"] is True
    assert m["level"] == 3
    assert m["speaker"] == "본인"


def test_scammer_ssn_request_is_cumulative():
    # 상대방이 주민번호를 말함 = 요구 → 누적 경고(non-instant)
    _, matches = s._scan_turns([_turn("상대방", "주민번호 좀 알려주세요")])
    m = next(x for x in matches if x["flag"] == "ssn")
    assert m["instant"] is False
    assert m["level"] == 2


def test_victim_transfer_done_is_instant():
    _, matches = s._scan_turns([_turn("본인", "네 방금 이체했어요")])
    m = next(x for x in matches if x["flag"] == "transfer_done")
    assert m["instant"] is True
    assert m["speaker"] == "본인"


def test_scammer_transfer_phrase_ignored():
    # transfer_done 은 사기범 발화면 무시(by_scammer=None)
    _, matches = s._scan_turns([_turn("상대방", "지금 보내드릴게 기다리세요")])
    assert all(x["flag"] != "transfer_done" for x in matches)


def test_scammer_fake_gov_cumulative():
    _, matches = s._scan_turns([_turn("상대방", "여기는 서울중앙지검 수사관입니다")])
    flags = {x["flag"]: x for x in matches}
    assert "fake_gov" in flags
    assert flags["fake_gov"]["instant"] is False


def test_victim_mentioning_gov_ignored():
    # 본인이 검찰청 언급 = 의심·되묻기 → by_victim None → 무시
    _, matches = s._scan_turns([_turn("본인", "검찰청이요? 그게 진짜인가요?")])
    assert all(x["flag"] != "fake_gov" for x in matches)


def test_victim_meta_aware_is_protective_low():
    _, matches = s._scan_turns([_turn("본인", "이거 사기 같은데요")])
    m = next(x for x in matches if x["flag"] == "meta_aware")
    assert m["instant"] is False
    assert m["level"] == 1


# ---- tier 계산 (변동 없음) ----

def test_compute_tier_instant_jumps_to_danger():
    assert s._compute_tier(0, True, True) == 3


def test_compute_tier_cumulative_thresholds():
    assert s._compute_tier(0, False, False) == 0
    assert s._compute_tier(1, False, True) == 1
    assert s._compute_tier(s._TIER_CAUTION_SCORE, False, True) == 2
    assert s._compute_tier(s._TIER_DANGER_SCORE, False, True) == 3


# ---- 통합: 본인 발설이 들어간 통화는 danger 로 ----

def test_victim_disclosure_drives_danger_tier():
    turns = [
        _turn("상대방", "여기는 검찰청입니다"),       # 누적 경고
        _turn("본인", "제 주민번호는 900101이에요"),   # instant → danger
    ]
    _, matches = s._scan_turns(turns)
    instant_seen = any(m["instant"] for m in matches)
    cum = sum(m["level"] for m in matches if not m["instant"])
    assert s._compute_tier(cum, instant_seen, bool(matches)) == 3


def test_scammer_only_call_stays_below_danger():
    # 사기범만 떠드는 통화(뉴스·교육 영상 유사) — 본인 compliance 없음 → danger 직행 X
    turns = [
        _turn("상대방", "검찰청 수사관입니다 주민번호 알려주세요"),
    ]
    _, matches = s._scan_turns(turns)
    instant_seen = any(m["instant"] for m in matches)
    assert instant_seen is False  # 사기범 발화엔 instant 없음


def test_no_match_tier_zero():
    level, matches = s._scan_turns([_turn("본인", "오늘 날씨가 참 좋네요 점심 뭐 먹을까")])
    assert matches == []
    assert level == 0


def test_scan_text_fallback_uses_more_severe():
    # turns 없는 fallback: 화자 미상 → 더 심각한 분류(주민번호=instant) 적용
    _, matches = s._scan_text("주민번호는 880101")
    m = next(x for x in matches if x["flag"] == "ssn")
    assert m["instant"] is True  # 화자 모를 땐 critical 놓치지 않음
