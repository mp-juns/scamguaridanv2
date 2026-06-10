"""
ScamGuardian — STT 백엔드: Claude Audio API

오디오를 base64 로 Claude 에 직접 전송하여 전사한다 (STT_BACKEND=claude).
외부 소비자는 `pipeline.stt` facade 를 통해 import 한다.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Callable


def _transcribe_with_claude(
    audio_path: str,
    logger: Callable[[str], None] | None = None,
    diarize: bool = True,  # 미사용 — 호출부 시그니처 통일용
) -> dict:
    """Claude API에 오디오를 직접 전송하여 전사한다."""
    import base64

    import anthropic

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY가 설정되지 않았습니다. "
            ".env 파일에 ANTHROPIC_API_KEY를 추가해주세요."
        )

    audio_bytes = Path(audio_path).read_bytes()
    file_size_mb = len(audio_bytes) / (1024 * 1024)

    # 확장자로 media_type 결정
    ext = Path(audio_path).suffix.lower().lstrip(".")
    media_type_map = {
        "mp3": "audio/mp3",
        "wav": "audio/wav",
        "flac": "audio/flac",
        "ogg": "audio/ogg",
        "m4a": "audio/mp4",
        "mp4": "audio/mp4",
        "webm": "audio/webm",
    }
    media_type = media_type_map.get(ext, "audio/mp3")
    audio_b64 = base64.standard_b64encode(audio_bytes).decode("utf-8")

    model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    if logger:
        logger(
            f"[STT] Claude Audio API 호출 시작\n"
            f"       → 파일: {Path(audio_path).name} ({file_size_mb:.1f}MB)\n"
            f"       → 모델: {model}, 타입: {media_type}"
        )

    t0 = time.time()
    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=model,
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "audio",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": audio_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": (
                            "위 오디오를 한국어로 전사(transcription)해주세요. "
                            "말한 내용을 그대로 텍스트로 옮기세요. "
                            "전사 결과만 출력하고, 다른 설명은 하지 마세요."
                        ),
                    },
                ],
            }
        ],
    )
    elapsed = time.time() - t0
    text = message.content[0].text.strip()
    preview = text[:150] + "…" if len(text) > 150 else text

    if logger:
        logger(
            f"[STT] Claude Audio API 완료 ({elapsed:.1f}s)\n"
            f"       ← 전사 길이: {len(text)}자\n"
            f"       ← 미리보기: {preview}"
        )
    return {"text": text, "language": "ko", "segments": []}
