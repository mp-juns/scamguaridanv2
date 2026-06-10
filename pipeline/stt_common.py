"""
ScamGuardian — STT 공용 유틸

TranscriptResult 자료형 + 소스 판별/YouTube 다운로드/오디오 프로브 등
모든 STT 백엔드(Whisper/Claude/CLOVA)가 공유하는 코드.
외부 소비자는 `pipeline.stt` facade 를 통해 import 한다.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

_YOUTUBE_PATTERN = re.compile(
    r"https?://(www\.)?(youtube\.com|youtu\.be)/"
)


@dataclass
class TranscriptResult:
    text: str
    language: str = ""
    segments: list[dict] = field(default_factory=list)
    source_type: str = ""  # "youtube" | "file" | "text"
    # CLOVA 등 audio-based diarization 백엔드가 직접 화자 분리한 결과.
    # None 이면 LLM 후처리 diarize 필요. 있으면 그대로 사용 (LLM skip).
    # 형식: [{"speaker": "상대방|본인", "text": "..."}, ...]
    turns: list[dict] | None = None


def _is_youtube_url(source: str) -> bool:
    return bool(_YOUTUBE_PATTERN.match(source.strip()))


def _is_file(source: str) -> bool:
    try:
        p = Path(source)
        return p.exists() and p.is_file()
    except OSError:
        return False


def _download_youtube_audio(
    url: str,
    output_dir: str,
    debug: bool = False,
    logger: Callable[[str], None] | None = None,
) -> str:
    """yt-dlp로 YouTube 오디오를 추출하여 mp3 파일 경로를 반환한다."""
    import yt_dlp

    output_path = str(Path(output_dir) / "audio.%(ext)s")
    ydl_opts = {
        "format": "bestaudio/best",
        "outtmpl": output_path,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "64",
            }
        ],
        "postprocessor_args": {"ExtractAudio": ["-t", "180"]},
        "quiet": not debug,
        "no_warnings": not debug,
    }

    if logger:
        logger(f"[STT] YouTube 오디오 다운로드 시작: {url}")
    t0 = time.time()
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    if logger:
        logger(f"[STT] YouTube 오디오 다운로드 완료 ({time.time() - t0:.1f}s)")

    mp3_path = str(Path(output_dir) / "audio.mp3")
    if not Path(mp3_path).exists():
        raise FileNotFoundError(f"YouTube 오디오 다운로드 실패: {url}")
    return mp3_path


def _probe_audio_seconds(path: str) -> float:
    """ffprobe 로 오디오 길이(초). 측정 실패면 0.0."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True, timeout=10,
        )
        return float(result.stdout.strip() or "0")
    except (subprocess.TimeoutExpired, FileNotFoundError, ValueError):
        return 0.0


def _ensure_audio_nonempty(path: str) -> None:
    """ffprobe로 오디오 길이를 확인한다. 0이면 에러."""
    duration = _probe_audio_seconds(path)
    if duration > 0 and duration < 0.1:
        raise ValueError(
            "오디오를 읽지 못했습니다. 오디오 트랙이 없는 영상이거나 파일이 손상됐을 수 있습니다."
        )
