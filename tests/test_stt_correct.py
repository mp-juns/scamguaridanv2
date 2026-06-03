"""stt_correct — LLM STT 후처리 교정의 결정적 부분 (파싱·가드·토글) 단위 테스트.

실제 LLM 호출은 conftest 가 ANTHROPIC_API_KEY 를 unset 하므로 자동 실패 → 원본 유지.
가드(개수 불일치, 길이 비율, 전체 비율)는 correct_turns 를 monkeypatch 로 LLM 응답을
주입해 검증한다.
"""
from __future__ import annotations

import pipeline.stt_correct as sc


def test_enabled_toggle(monkeypatch):
    monkeypatch.delenv("STT_CORRECT", raising=False)
    assert sc.enabled() is False
    monkeypatch.setenv("STT_CORRECT", "1")
    assert sc.enabled() is True
    monkeypatch.setenv("STT_CORRECT", "0")
    assert sc.enabled() is False


def test_parse_str_array():
    assert sc._parse_str_array('["a","b"]') == ["a", "b"]
    assert sc._parse_str_array('```json\n["x"]\n```') == ["x"]
    assert sc._parse_str_array("총 아님") is None


def test_correct_turns_empty():
    assert sc.correct_turns([]) == []


def _turns():
    return [
        {"speaker": "상대방", "text": "이선호 수작을 했다", "start_sec": 0.0, "end_sec": 2.0},
        {"speaker": "본인", "text": "뭔데요", "start_sec": 2.0, "end_sec": 3.0},
    ]


def _patch_llm(monkeypatch, returned_array_json):
    """diarize._get_client / record_claude 를 가짜로 — LLM 이 returned_array_json 을 주도록."""
    class _Msg:
        def __init__(self, text):
            self.content = [type("C", (), {"text": text})()]
            self.usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()

    class _Client:
        def __init__(self, text):
            self._text = text
            self.messages = self
        def create(self, **kw):
            return _Msg(self._text)

    import pipeline.diarize as _d
    monkeypatch.setattr(_d, "_get_client", lambda: _Client(returned_array_json))
    monkeypatch.setattr(_d, "_model_name", lambda m=None: "test-model")


def test_correct_turns_applies_fix(monkeypatch):
    _patch_llm(monkeypatch, '["이선호 수사관입니다", "뭔데요"]')
    out = sc.correct_turns(_turns())
    assert out[0]["text"] == "이선호 수사관입니다"  # 교정 적용
    assert out[1]["text"] == "뭔데요"
    # speaker / timestamp 보존
    assert out[0]["speaker"] == "상대방"
    assert out[0]["start_sec"] == 0.0 and out[0]["end_sec"] == 2.0


def test_correct_turns_count_mismatch_keeps_original(monkeypatch):
    _patch_llm(monkeypatch, '["only one"]')  # 2개인데 1개 반환 → 통째 거부
    out = sc.correct_turns(_turns())
    assert out[0]["text"] == "이선호 수작을 했다"


def test_correct_turns_total_ratio_guard(monkeypatch):
    # 전체 길이가 폭증(fabrication) → 통째 거부
    huge = "이것은 원본에 전혀 없던 아주 긴 문장을 창작해서 붙인 것입니다 " * 3
    _patch_llm(monkeypatch, f'["{huge}", "뭔데요"]')
    out = sc.correct_turns(_turns())
    assert out[0]["text"] == "이선호 수작을 했다"  # 원본 유지


def test_correct_turns_per_turn_len_guard(monkeypatch):
    # per-turn 가드 격리: 5 turn 중 1개만 비정상 폭증(>2.5x), 나머지는 비슷한 길이로 정상 교정.
    # 전체 비율은 [0.6,1.8] 안에 머물러 통째 거부는 안 되고, 폭증 turn 만 원본 유지.
    base = "스무 글자 정도 되는 보통 길이의 문장입니다"
    turns = [
        {"speaker": "상대방" if i % 2 == 0 else "본인", "text": base,
         "start_sec": float(i), "end_sec": float(i + 1)}
        for i in range(5)
    ]
    blown = ("원본보다 세 배 넘게 늘어난 의심스러운 교정 " * 3).strip()  # >2.5x → per-turn 가드
    normal = "스무 글자 정도 되는 보통 길이로 교정됨"  # base 와 비슷한 길이 (비율 ~1.0)
    arr = '["%s", "%s", "%s", "%s", "%s"]' % (blown, normal, normal, normal, normal)
    _patch_llm(monkeypatch, arr)
    out = sc.correct_turns(turns)
    assert out[0]["text"] == base       # 폭증 turn → 원본 유지
    assert out[1]["text"] == normal     # 정상 길이 교정 적용


def test_corrected_full_text():
    turns = [{"text": "a"}, {"text": "b"}, {"text": ""}]
    assert sc.corrected_full_text(turns) == "a b"
