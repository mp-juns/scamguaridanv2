"""CLOVA 화자 역할 배정 (_assign_clova_roles 등) 단위 테스트.

내용 기반 LLM 역할 배정의 결정적(deterministic) 부분 — 파싱·검증·duration fallback —
을 검증한다. 실제 Haiku 호출은 ANTHROPIC_API_KEY 없으면 graceful 하게 duration 으로
fallback 하는 것까지 확인 (conftest 가 키를 unset 하므로 LLM 경로는 자동 fallback).
"""
from __future__ import annotations

from pipeline import stt


# ---- _parse_role_map: 파싱 + 검증 ----

def test_parse_valid():
    assert stt._parse_role_map('{"1":"상대방","2":"본인"}', {"1", "2"}) == {"1": "상대방", "2": "본인"}


def test_parse_codeblock_wrapped():
    raw = '```json\n{"1":"본인","2":"상대방"}\n```'
    assert stt._parse_role_map(raw, {"1", "2"}) == {"1": "본인", "2": "상대방"}


def test_parse_normalizes_화자_prefix():
    raw = '{"화자 1":"상대방","화자 2":"본인"}'
    assert stt._parse_role_map(raw, {"1", "2"}) == {"1": "상대방", "2": "본인"}


def test_parse_normalizes_speaker_prefix():
    raw = '{"speaker 1":"본인","speaker 2":"상대방"}'
    assert stt._parse_role_map(raw, {"1", "2"}) == {"1": "본인", "2": "상대방"}


def test_parse_rejects_both_same_role():
    assert stt._parse_role_map('{"1":"본인","2":"본인"}', {"1", "2"}) is None


def test_parse_rejects_missing_label():
    assert stt._parse_role_map('{"1":"상대방"}', {"1", "2"}) is None


def test_parse_rejects_garbage():
    assert stt._parse_role_map("총 정상이 아닌 응답", {"1", "2"}) is None


# ---- duration 휴리스틱 ----

def test_duration_role_map_longest_is_상대방():
    segs = [
        {"speaker_label": "1", "start": 0, "end": 90, "text": "길게 말함"},
        {"speaker_label": "2", "start": 90, "end": 100, "text": "네"},
    ]
    assert stt._duration_role_map(stt._label_durations(segs)) == {"1": "상대방", "2": "본인"}


# ---- _assign_clova_roles: 분기 + fallback ----

def test_assign_single_speaker_is_상대방():
    segs = [{"speaker_label": "1", "start": 0, "end": 30, "text": "자동 안내입니다"}]
    assert stt._assign_clova_roles(segs) == {"1": "상대방"}


def test_assign_no_labels_empty():
    segs = [{"speaker_label": "", "start": 0, "end": 5, "text": "라벨 없음"}]
    assert stt._assign_clova_roles(segs) == {}


def test_assign_mode_duration_skips_llm(monkeypatch):
    monkeypatch.setenv("CLOVA_ROLE_ASSIGN", "duration")
    segs = [
        {"speaker_label": "1", "start": 0, "end": 80, "text": "긴 발화"},
        {"speaker_label": "2", "start": 80, "end": 90, "text": "짧음"},
    ]
    assert stt._assign_clova_roles(segs) == {"1": "상대방", "2": "본인"}


def test_assign_llm_falls_back_without_api_key(monkeypatch):
    # 기본 mode=llm 이지만 ANTHROPIC_API_KEY 없으면(conftest unset) duration 으로 graceful fallback.
    monkeypatch.delenv("CLOVA_ROLE_ASSIGN", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    segs = [
        {"speaker_label": "1", "start": 0, "end": 70, "text": "길게 명령조로 말함"},
        {"speaker_label": "2", "start": 70, "end": 80, "text": "네 알겠습니다"},
    ]
    # fallback 이라도 결과는 valid 한 매핑이어야 함
    result = stt._assign_clova_roles(segs)
    assert result == {"1": "상대방", "2": "본인"}
