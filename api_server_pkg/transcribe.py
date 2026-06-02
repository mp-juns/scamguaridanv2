"""/api/transcribe-upload — 음성 파일 → 텍스트 전사 전용 endpoint.

분석 (`/api/analyze-upload`) 와 동일한 multipart 입력을 받지만,
Phase 1 (STT) 만 수행하고 즉시 반환한다. 분석·DB 저장·signal 검출 없음.

Live Voice 페이지에서 분석과 *병렬* 호출해 사용자에게 전사 결과를 빨리
보여주는 용도.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

router = APIRouter()


@router.post(
    "/api/transcribe-upload",
    tags=["Public"],
    summary="음성 파일 → 텍스트 전사 (STT only, Phase 1)",
    description=(
        "음성·영상 파일을 multipart 로 업로드받아 **전사 결과만** 반환한다. "
        "분석 (`/api/analyze-upload`) 와 같은 시점에 병렬로 호출 가능."
        "\n\n"
        "**응답**:\n"
        "- `transcript_text` — 전사된 한국어 본문\n"
        "- `language` — 감지 언어 코드 (가능한 경우)\n"
        "- `source_type` — `file` / `youtube` 등\n"
        "- `latency_ms` — STT 소요 시간\n"
        "- `duration_seconds` — 오디오 길이 (선택)\n\n"
        "**Form fields**: `analyze-upload` 와 동일 (`file`, `whisper_model` 옵션).\n\n"
        "**인증**: API key 필수 (`/api/analyze-upload` 와 동일)."
    ),
    responses={
        400: {"description": "파일 비어있음 / 코덱 오류"},
        401: {"description": "API key 누락 또는 무효"},
        429: {"description": "Rate limit 초과"},
    },
)
async def transcribe_upload(
    file: UploadFile = File(...),
    whisper_model: str = Form("medium"),
) -> dict:
    log = logging.getLogger("api_transcribe")
    if not file.filename:
        raise HTTPException(status_code=400, detail="업로드된 파일 이름이 비어 있습니다.")

    suffix = Path(file.filename).suffix
    upload_dir = Path(".scamguardian") / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    tmp_handle = tempfile.NamedTemporaryFile(
        mode="wb",
        delete=False,
        dir=str(upload_dir),
        prefix="transcribe_",
        suffix=suffix,
    )
    tmp_path = Path(tmp_handle.name)
    wav_path = tmp_path.with_suffix(".wav")
    try:
        with tmp_handle:
            if file.file is None:
                raise HTTPException(status_code=400, detail="업로드된 파일 본문을 읽을 수 없습니다.")
            shutil.copyfileobj(file.file, tmp_handle)

        if tmp_path.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="업로드된 파일이 비어 있습니다(0 bytes).")

        # 음성/영상만 지원 — 이미지/PDF 는 transcribe 아니라 vision OCR 분기.
        from pipeline import vision as _vision_mod
        if _vision_mod.supported(tmp_path):
            raise HTTPException(
                status_code=400,
                detail="이미지/PDF 는 `/api/analyze-upload` 의 vision OCR 경로를 사용하세요.",
            )

        # ffmpeg 로 16kHz mono wav 추출 + 음향 전처리.
        # 1) silenceremove: 1초 이상 -40dB 이하 침묵 구간 제거 → Whisper hallucination
        #    의 근본 원인 차단 (모델이 환각할 audio 자체가 없게).
        # 2) dynaudnorm: 작은 발화 (피해자 측) 증폭 → STT 인식률 ↑
        extract = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(tmp_path),
                "-vn", "-ac", "1", "-ar", "16000",
                "-af", "silenceremove=stop_periods=-1:stop_duration=1:stop_threshold=-40dB,dynaudnorm=f=150:g=15",
                "-f", "wav",
                str(wav_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if extract.returncode != 0 or not wav_path.exists() or wav_path.stat().st_size == 0:
            raise HTTPException(
                status_code=400,
                detail="업로드된 파일에서 오디오를 추출하지 못했습니다. 다른 파일(코덱)로 시도해주세요.",
            )

        from pipeline import diarize as _diarize
        from pipeline import stt as _stt

        started = time.monotonic()
        result = await asyncio.to_thread(_stt.transcribe, str(wav_path))
        stt_ms = int((time.monotonic() - started) * 1000)

        # 화자 분리 — STT 백엔드가 이미 audio-based diarization 한 경우 (CLOVA 등)
        # 는 그대로 사용 (LLM 후처리 skip). 아니면 Claude Haiku 후처리.
        diarize_started = time.monotonic()
        if result.turns:
            turns_dicts = result.turns
            diarize_source = "stt-native"
        else:
            turns = await asyncio.to_thread(_diarize.diarize, result.text or "")
            turns_dicts = _diarize.turns_to_dict(turns)
            diarize_source = "llm-haiku"
        diarize_ms = int((time.monotonic() - diarize_started) * 1000)
        latency_ms = stt_ms + diarize_ms

        log.info(
            "/api/transcribe-upload 완료: chars=%d, lang=%s, turns=%d, source=%s, stt=%dms, diarize=%dms",
            len(result.text or ""), result.language or "?", len(turns_dicts),
            diarize_source, stt_ms, diarize_ms,
        )

        return {
            "transcript_text": result.text or "",
            "turns": turns_dicts,
            "language": result.language or "",
            "source_type": result.source_type or "file",
            "latency_ms": latency_ms,
            "stt_ms": stt_ms,
            "diarize_ms": diarize_ms,
            "diarize_source": diarize_source,
            "source_filename": file.filename,
        }
    except HTTPException:
        raise
    except Exception as exc:
        log.error("/api/transcribe-upload 서버 오류: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        try:
            wav_path.unlink(missing_ok=True)
        except Exception:
            pass
