"""stream_analyze._window_turns / _audio_filter 단위 테스트.

전역 diarization turns 를 ~window 단위로 묶을 때 turn 을 절대 쪼개지 않고
(문장 절단 방지) start_sec/end_sec·transcript 가 올바르게 합쳐지는지 검증.
"""
from __future__ import annotations

import importlib

from api_server_pkg import stream_analyze as s


def _t(speaker, text, start, end):
    return {"speaker": speaker, "text": text, "start_sec": start, "end_sec": end}


def test_window_empty():
    assert s._window_turns([], 60.0) == []


def test_window_single_turn_under_threshold():
    turns = [_t("상대방", "안녕하세요", 0.0, 10.0)]
    w = s._window_turns(turns, 60.0)
    assert len(w) == 1
    assert w[0]["turns"] == turns
    assert w[0]["start_sec"] == 0.0
    assert w[0]["end_sec"] == 10.0
    assert w[0]["transcript"] == "안녕하세요"


def test_window_splits_on_turn_boundary_not_midturn():
    # 누적 길이가 threshold 를 넘는 순간 turn 경계에서 닫힌다 (turn 중간 절단 X).
    turns = [
        _t("상대방", "A", 0.0, 35.0),
        _t("본인", "B", 35.0, 40.0),
        _t("상대방", "C", 40.0, 70.0),   # 70-0 >= 60 → 여기서 window 닫힘
        _t("본인", "D", 70.0, 75.0),
    ]
    w = s._window_turns(turns, 60.0)
    assert len(w) == 2
    # 첫 window 는 A,B,C 모두 포함 (C 가 60 을 넘겼지만 통째로 유지)
    assert [t["text"] for t in w[0]["turns"]] == ["A", "B", "C"]
    assert w[0]["transcript"] == "A B C"
    assert w[0]["start_sec"] == 0.0 and w[0]["end_sec"] == 70.0
    # 둘째 window 는 D 만
    assert [t["text"] for t in w[1]["turns"]] == ["D"]
    assert w[1]["start_sec"] == 70.0 and w[1]["end_sec"] == 75.0


def test_window_preserves_all_turns():
    turns = [_t("상대방" if i % 2 == 0 else "본인", f"t{i}", i * 30.0, i * 30.0 + 28.0) for i in range(6)]
    w = s._window_turns(turns, 60.0)
    flat = [t for win in w for t in win["turns"]]
    assert flat == turns  # 어떤 turn 도 누락·중복·분할되지 않음


def test_audio_filter_clova_is_clean_downsample(monkeypatch):
    # CLOVA 는 정규화 없는 clean downsample 이 STT 정확도 최고 (측정값) → 빈 필터.
    import pipeline.stt as _stt
    monkeypatch.setattr(_stt, "STT_BACKEND", "clova")
    assert s._audio_filter() == ""
    assert s._ffmpeg_af_args() == []  # -af 자체 생략


def test_audio_filter_whisper_keeps_silenceremove(monkeypatch):
    import pipeline.stt as _stt
    monkeypatch.setattr(_stt, "STT_BACKEND", "whisper")
    f = s._audio_filter()
    assert "silenceremove" in f
    assert "dynaudnorm" in f
    assert s._ffmpeg_af_args() == ["-af", f]
