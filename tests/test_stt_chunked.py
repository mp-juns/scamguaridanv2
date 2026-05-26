"""STT 병렬 chunking 인프라 테스트 (Whisper API mock)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def _has_ffmpeg() -> bool:
    return shutil.which("ffmpeg") is not None


pytestmark = pytest.mark.skipif(not _has_ffmpeg(), reason="ffmpeg 필요")


def _make_silence(path: Path, seconds: int) -> Path:
    """ffmpeg 으로 N초 무음 mp3 생성."""
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi",
         "-i", "anullsrc=r=16000:cl=mono",
         "-t", str(seconds),
         "-c:a", "libmp3lame", "-b:a", "64k",
         str(path)],
        check=True, capture_output=True,
    )
    return path


def test_split_audio_chunks_count(tmp_path):
    from pipeline import stt

    audio = _make_silence(tmp_path / "x.mp3", seconds=20)
    out_dir = tmp_path / "chunks"
    out_dir.mkdir()
    chunks = stt._split_audio_chunks(str(audio), chunk_sec=7, out_dir=str(out_dir))
    # 20초 → 7+7+6 = 3 chunks
    assert len(chunks) == 3
    for p in chunks:
        assert Path(p).exists()


def test_split_audio_chunks_sorted_order(tmp_path):
    """반환 리스트가 index 순서대로 정렬되어야 한다 (chunk_0000, 0001, ...)."""
    from pipeline import stt

    audio = _make_silence(tmp_path / "x.mp3", seconds=15)
    out_dir = tmp_path / "chunks"
    out_dir.mkdir()
    chunks = stt._split_audio_chunks(str(audio), chunk_sec=5, out_dir=str(out_dir))
    names = [Path(p).name for p in chunks]
    assert names == sorted(names)


def test_short_audio_bypasses_chunking(tmp_path, monkeypatch):
    """threshold 이하 오디오는 _whisper_one 1회만 호출 (chunking skip)."""
    from pipeline import stt

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(stt, "STT_CHUNK_THRESHOLD_SEC", 30)

    calls: list[str] = []

    def fake_whisper_one(path):
        calls.append(path)
        return "단일 호출 결과"

    monkeypatch.setattr(stt, "_whisper_one", fake_whisper_one)

    audio = _make_silence(tmp_path / "short.mp3", seconds=5)
    result = stt._transcribe_with_openai_api(str(audio))

    assert len(calls) == 1
    assert calls[0] == str(audio)
    assert result["text"] == "단일 호출 결과"


def test_long_audio_triggers_parallel_chunking(tmp_path, monkeypatch):
    """threshold 초과 오디오는 chunked path 로 라우팅 + 모든 chunk concat."""
    from pipeline import stt

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(stt, "STT_CHUNK_THRESHOLD_SEC", 5)
    monkeypatch.setattr(stt, "STT_CHUNK_SEC", 5)
    monkeypatch.setattr(stt, "STT_MAX_WORKERS", 2)

    call_order: list[str] = []

    def fake_whisper_one(path):
        name = Path(path).name
        call_order.append(name)
        # chunk 파일명에서 index 추출 — "chunk_0001.mp3" → "1"
        idx = name.split("_")[1].split(".")[0].lstrip("0") or "0"
        return f"청크{idx}"

    monkeypatch.setattr(stt, "_whisper_one", fake_whisper_one)

    audio = _make_silence(tmp_path / "long.mp3", seconds=15)
    result = stt._transcribe_with_openai_api(str(audio))

    # 15초 / 5초 chunk ≈ 3~4개 (ffmpeg -c copy 가 frame 경계라 ±1). 핵심은:
    # (1) 호출 횟수 == chunk 수 (모두 처리됨)
    # (2) concat 결과가 index 순서대로 (병렬 호출이지만 결과는 정렬)
    assert len(call_order) >= 3
    expected = " ".join(f"청크{i}" for i in range(len(call_order)))
    assert result["text"] == expected


def test_chunk_failure_replaced_with_empty(tmp_path, monkeypatch):
    """chunk 한 개가 예외 던져도 나머지 결과는 보존."""
    from pipeline import stt

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(stt, "STT_CHUNK_THRESHOLD_SEC", 5)
    monkeypatch.setattr(stt, "STT_CHUNK_SEC", 5)

    def fake_whisper_one(path):
        idx = Path(path).name.split("_")[1].split(".")[0].lstrip("0") or "0"
        if idx == "1":
            raise RuntimeError("API 일시 장애")
        return f"청크{idx}"

    monkeypatch.setattr(stt, "_whisper_one", fake_whisper_one)

    audio = _make_silence(tmp_path / "long.mp3", seconds=15)
    result = stt._transcribe_with_openai_api(str(audio))

    # 청크1 실패 → 빈 문자열 — concat 에서 누락. 나머지 모두 보존.
    parts = result["text"].split()
    assert "청크1" not in parts
    assert "청크0" in parts
    # 마지막 chunk 가 청크2 또는 청크3 (ffmpeg frame 경계 변동)
    assert any(p in parts for p in ("청크2", "청크3"))


def test_split_missing_file_raises(tmp_path):
    from pipeline import stt

    with pytest.raises(subprocess.CalledProcessError):
        stt._split_audio_chunks(
            str(tmp_path / "nope.mp3"),
            chunk_sec=5,
            out_dir=str(tmp_path),
        )
