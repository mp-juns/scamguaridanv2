"""POST /api/live-analyze — 실시간 마이크 누적 오디오 분석 (Live Voice v4 MVP).

스피커폰 양쪽 캡처 시나리오. 클라이언트(브라우저 getUserMedia + MediaRecorder)가
**통화 시작부터 지금까지의 누적 오디오**를 ~7초마다 보내면, 백엔드가 통째로 재분석한다.

실시간 윈도우는 화자 분리를 하지 않는다 (`diarize=False`):
- 역할 배정(상대방/본인)을 건너뛰어 (1) 누적 윈도우마다 화자가 뒤집히던 flip 문제와
  (2) 7초마다의 역할 배정 Claude 호출(비용·지연)을 *동시에* 제거.
- 대신 전사 텍스트에 위험 시그널을 화자 무관으로 즉시 스캔(`stream_analyze._scan_text`,
  패턴별 `agnostic` 분류) → 검출되자마자 경보.
- 중지 시 full 분석(`window_sec==0`)만 화자 분리 1회 — 통화 후 말풍선 리뷰·음성 재생용
  (단일 호출이라 flip 없음). matches 는 항상 화자 무관으로 통일.
- 누적 통째 재분석은 완전한 전사 + 윈도우 sliding(window_sec)로 비용 bound 하기 위함.

stateless — 서버는 상태를 안 들고, 클라이언트가 누적 오디오와 monotonic tier 를 관리.

⚠️ 비용/지연: 매 호출이 누적 오디오 전체를 재-STT → 통화가 길수록 지연·비용 ↑. 데모·MVP
용도. production 은 true streaming STT(CLOVA gRPC 등) 로 전환 필요.

인증: API key 필수 (middleware). Next 프록시가 internal key 자동 첨부.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

router = APIRouter()
LOG = logging.getLogger("api_live_analyze")


@router.post(
    "/api/live-analyze",
    tags=["Public"],
    summary="실시간 마이크 누적 오디오 분석 (Live Voice MVP)",
    description=(
        "브라우저 마이크 누적 오디오(통화 시작~현재)를 받아 전사·화자분리·화자별 위험 신호·"
        "tier 를 반환한다. 클라이언트가 주기적으로(예: 7초) 호출해 실시간처럼 갱신.\n\n"
        "**Form fields**: `file`(누적 오디오), `seq`(옵션, 호출 순번 로깅용)\n\n"
        "**응답**: `{transcript_text, turns, matches, tier, latency_ms}`\n\n"
        "**인증**: API key 필수."
    ),
)
async def live_analyze(
    file: UploadFile = File(...),
    seq: int = Form(0),
    window_sec: int = Form(0),
) -> dict:
    import asyncio

    if not file.filename:
        raise HTTPException(status_code=400, detail="업로드된 파일 이름이 비어 있습니다.")

    suffix = Path(file.filename).suffix or ".webm"
    upload_dir = Path(".scamguardian") / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    tmp_handle = tempfile.NamedTemporaryFile(
        mode="wb", delete=False, dir=str(upload_dir), prefix="live_", suffix=suffix,
    )
    tmp_path = Path(tmp_handle.name)
    wav_path = tmp_path.with_suffix(".wav")
    started = time.monotonic()
    try:
        with tmp_handle:
            if file.file is None:
                raise HTTPException(status_code=400, detail="업로드된 파일 본문을 읽을 수 없습니다.")
            shutil.copyfileobj(file.file, tmp_handle)
        if tmp_path.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="빈 오디오입니다.")

        from api_server_pkg.stream_analyze import (
            _compute_tier, _ffmpeg_af_args, _scan_text,
        )

        # 누적 오디오 → clean 16k mono wav (CLOVA: 무필터가 STT 정확도 최고)
        extract = subprocess.run(
            ["ffmpeg", "-y", "-i", str(tmp_path),
             "-vn", "-ac", "1", "-ar", "16000",
             *_ffmpeg_af_args(),
             "-f", "wav", str(wav_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        if extract.returncode != 0 or not wav_path.exists() or wav_path.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="오디오 추출 실패 (코덱 확인).")

        # 너무 짧으면(< 0.7s) STT 의미 없음 — 빈 결과 반환
        try:
            dur = float(subprocess.run(
                ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                 "-of", "csv=p=0", str(wav_path)],
                capture_output=True, text=True, check=False,
            ).stdout.strip() or 0.0)
        except Exception:
            dur = 0.0
        if dur < 0.7:
            return {"transcript_text": "", "turns": [], "matches": [], "tier": 0,
                    "latency_ms": int((time.monotonic() - started) * 1000)}

        # 슬라이딩 윈도우 — window_sec>0 이고 길이 초과면 *마지막 window_sec 만* CLOVA 에.
        # webm→wav 로컬 변환은 cheap, 지배적 비용(CLOVA STT+역할LLM)을 window 로 bound → O(n²)→선형.
        # window_sec=0(중지 시) 이면 통째 분석 → 완전한 전사/화자분리.
        stt_path = wav_path
        if window_sec > 0 and dur > window_sec:
            wav_trim = tmp_path.with_suffix(".win.wav")
            start_at = max(0.0, dur - window_sec)
            trim = subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{start_at:.2f}", "-i", str(wav_path),
                 "-c", "copy", str(wav_trim)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
            )
            if trim.returncode == 0 and wav_trim.exists() and wav_trim.stat().st_size > 0:
                stt_path = wav_trim
                LOG.info("[live] window 트림: 전체 %.1fs → 최근 %ds (seq=%d)", dur, window_sec, seq)

        from pipeline import stt as _stt
        # 실시간 윈도우(window_sec>0)는 화자 분리 skip → 역할 배정 Claude 호출 제거 +
        # 누적 윈도우 flip 원천 소거 + 지연↓. 중지 시 full 분석(window_sec==0)만 화자 분리
        # 1회 — 통화 후 말풍선 리뷰·재생용(단일 호출이라 flip 없음).
        final_full = window_sec <= 0
        result = await asyncio.to_thread(
            _stt.transcribe, str(stt_path), diarize=final_full,
        )
        turns = result.turns or []  # 실시간 윈도우 []; 중지 시 화자분리 turns

        # 화자 무관 시그널 즉시 스캔 — 검출되자마자 경보. matches 는 항상 화자 무관
        # (speaker=None) 으로 통일해 프론트 dedup 키(flag|snippet|speaker) 일관성 유지.
        # (window 한정 tier; 누적 tier 는 프론트가 dedup match 로 계산)
        level, matches = _scan_text(result.text or "")
        instant_seen = any(m["instant"] for m in matches)
        cum_score = sum(m["level"] for m in matches if not m["instant"])
        tier = _compute_tier(cum_score, instant_seen, bool(matches))

        latency_ms = int((time.monotonic() - started) * 1000)
        LOG.info(
            "/api/live-analyze seq=%d: dur=%.1fs turns=%d matches=%d tier=%d %dms",
            seq, dur, len(turns), len(matches), tier, latency_ms,
        )
        return {
            "transcript_text": result.text or "",
            "turns": turns,
            "matches": matches,
            "tier": tier,
            "latency_ms": latency_ms,
        }
    except HTTPException:
        raise
    except Exception as exc:
        LOG.error("/api/live-analyze 오류: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        for p in (tmp_path, wav_path, tmp_path.with_suffix(".win.wav")):
            try:
                p.unlink(missing_ok=True)
            except Exception:
                pass
