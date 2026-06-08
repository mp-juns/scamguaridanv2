"""POST /api/analyze-stream — 음성 파일 화자분리 + 키워드 alert streaming 분석.

업로드 파일 전체를 **통파일 1회 STT/diarization** 으로 처리해 전역 일관 turns 를 얻고
(chunk 경계 절단·CLOVA speaker label 뒤집힘 없음), 그 turns 를 ~`chunk_seconds` window
로 묶어 NDJSON 으로 progressive emit 한다. 클라이언트는 fetch 의 ReadableStream 을
line-by-line 으로 파싱해 window 별 결과를 표시. 이벤트 contract 는 과거 chunk 방식과
동일 (프론트 변경 불필요).

각 라인 schema:
  {"type": "start", "total_chunks": N, "chunk_seconds": 60, "source_filename": "...", "stt_ms": int}
  {"type": "chunk", "chunk_index": i, "start_sec": s, "end_sec": e,
   "transcript": str, "turns": [...], "alert_level": 0-3,
   "matches": [{flag, label_ko, level, snippet, instant, action, speaker}],
   "tier": 0-3, "tier_changed": bool, "latency_ms": int}
  # speaker: "본인"(피해자) / "상대방"(사기범) / null. 같은 키워드라도 화자로 심각도가 다름
  #   — 본인 발설(주민번호·OTP)·송금동의 = instant danger / 사기범 사칭·압박 = 누적 경고.
  {"type": "done", "total_chunks": N, "full_transcript": str,
   "cumulative_matches": [...], "cumulative_alert_level": 0-3, "tier": 0-3}
  {"type": "error", "message": str}

tier(계층적 알림): 0 watch / 1 watch+ / 2 caution / 3 danger. **단조 증가**(내려가지 않음).
  instant 신호(주민번호·OTP·송금동의 등) 1개 → 즉시 3. 비-instant 누적 점수(level 합)가
  임계 넘으면 caution(>=3)·danger(>=6). tier_changed=True 인 window 에서 프론트가 경보 발화.

> "chunk" 이벤트는 이제 시간 슬라이스가 아니라 turn window — start_sec/end_sec 은
> 전역 오디오 timestamp 이고 turns 는 그 window 의 상대방/본인 turn.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import AsyncIterator

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

router = APIRouter()
LOG = logging.getLogger("api_analyze_stream")

# 위험 신호 분류 — 두 가지 읽기 방식을 모두 둔다.
#  - by_victim / by_scammer: *화자별* (level, instant, action). 누가 말했나로 의미가 바뀜.
#       파일 분석(/api/analyze-stream, /api/transcribe-upload)의 화자 경로(_scan_turns)용.
#  - agnostic: *화자 무관* (level, instant, action). Live 즉시 검출(_scan_text)용 —
#       화자 분리를 건너뛰므로 누가 말했는지 모른다. 행동 문구는 **화자 중립**
#       ("방금 송금하셨어요" 같은 단정 X → "송금 정황이 감지됐습니다"). severity 는
#       안전측(높게)으로 두되, 언제든 하향 튜닝 가능.
#  None 이면 그 화자 발화에선 무시.
#  level: 1 watch / 2 warn / 3 danger. instant=True 면 1개로 즉시 danger tier.
#  action: 안전 행동 안내 (Identity Boundary — "사기다" 단정 X, 행동+근거만)
_SPEAKER_PATTERNS: list[dict] = [
    {
        "flag": "ssn", "label_ko": "주민번호",
        "regex": re.compile(r"주민(등록)?\s*번호"),
        "by_victim": (3, True, "주민등록번호를 불러주지 마세요. 지금 멈추세요."),
        "by_scammer": (2, False, "주민번호를 요구받고 있습니다 — 알려주지 마세요."),
        "agnostic": (3, True, "주민등록번호가 통화에 등장했습니다 — 불러주거나 입력하지 마세요."),
    },
    {
        "flag": "otp", "label_ko": "OTP/인증번호/보안카드",
        "regex": re.compile(r"(OTP|일회용\s*비밀번호|보안카드|인증번호)"),
        "by_victim": (3, True, "OTP·인증번호·보안카드 번호를 불러주지 마세요."),
        "by_scammer": (2, False, "OTP·인증번호를 요구받고 있습니다 — 알려주지 마세요."),
        "agnostic": (3, True, "OTP·인증번호·보안카드 번호가 통화에 등장 — 불러주거나 입력하지 마세요."),
    },
    {
        "flag": "password", "label_ko": "비밀번호",
        "regex": re.compile(r"비밀번호"),
        "by_victim": (3, True, "비밀번호를 불러주거나 입력하지 마세요."),
        "by_scammer": (2, False, "비밀번호를 요구받고 있습니다 — 알려주지 마세요."),
        "agnostic": (3, True, "비밀번호가 통화에 등장 — 불러주거나 입력하지 마세요."),
    },
    {
        "flag": "transfer_done", "label_ko": "송금 동의·실행",
        "regex": re.compile(r"(보낼게|보냈|이체했|이체할게|송금했|송금할게|입금했|입금할게|보내드릴게)"),
        # 본인이 "보낼게요/이체했어요" → 결정적 (동의·실행). 사기범 발화면 무시.
        "by_victim": (3, True, "방금 송금에 동의·실행하셨어요. 즉시 은행 고객센터(또는 112)에 지급정지를 요청하세요."),
        "by_scammer": None,
        "agnostic": (3, True, "송금 동의·실행 정황이 감지됐습니다 — 보냈다면 즉시 은행 고객센터(또는 112)에 지급정지를 요청하세요."),
    },
    {
        "flag": "urgent_transfer", "label_ko": "즉각 송금",
        "regex": re.compile(r"(즉시|지금|당장|빨리|얼른).{0,12}(송금|이체|보내|입금)"),
        "by_victim": (3, True, "송금을 멈추세요. 보내기 전에 가족·기관 대표번호로 먼저 확인하세요."),
        "by_scammer": (2, False, "지금 송금하라는 압박을 받고 있습니다 — 서두르지 말고 멈추세요."),
        "agnostic": (3, True, "즉시 송금 정황이 감지됐습니다 — 보내기 전에 가족·기관 대표번호로 먼저 확인하세요."),
    },
    {
        "flag": "safe_account", "label_ko": "안전계좌",
        "regex": re.compile(r"안전\s*(계좌|입금|보관)"),
        # 사기범의 대표 수법 — 강한 누적(level 3, non-instant). 본인이 되묻는 건 낮음.
        "by_victim": (1, False, "'안전계좌' 안내를 받고 있어요 — 그런 계좌는 존재하지 않습니다."),
        "by_scammer": (3, False, "'안전계좌'는 존재하지 않습니다. 어떤 계좌로도 이체하지 마세요."),
        "agnostic": (3, False, "'안전계좌'는 존재하지 않습니다 — 어떤 계좌로도 이체하지 마세요."),
    },
    {
        "flag": "fake_gov", "label_ko": "공공기관 사칭",
        "regex": re.compile(r"(검찰청|금융감독원|경찰청|국정원|금감원|중앙지검|수사관)"),
        "by_victim": None,  # 본인이 기관명 언급 = 의심·되묻기 → 무시
        "by_scammer": (2, False, "검찰·경찰·금감원은 전화로 돈 이체나 계좌 정보를 요구하지 않습니다."),
        "agnostic": (2, False, "검찰·경찰·금감원은 전화로 돈 이체나 계좌 정보를 요구하지 않습니다."),
    },
    {
        "flag": "urgent_call_demand", "label_ko": "통화 유지 압박",
        "regex": re.compile(r"(끊지\s*마|전화\s*끊지|통화\s*유지)"),
        "by_victim": None,
        "by_scammer": (2, False, "전화를 끊어도 됩니다. '끊지 말라'는 요구 자체가 사기 신호입니다."),
        "agnostic": (2, False, "전화를 끊어도 됩니다. '끊지 말라'는 요구 자체가 사기 신호입니다."),
    },
    {
        "flag": "app_install_lure", "label_ko": "앱 설치 유도",
        "regex": re.compile(r"(앱|어플|어플리케이션|보안.{0,3}프로그램|업데이트).{0,8}(설치|다운로드)"),
        "by_victim": None,
        "by_scammer": (1, False, "상대가 요구하는 앱·프로그램을 설치하지 마세요."),
        "agnostic": (1, False, "요구받은 앱·프로그램을 설치하지 마세요."),
    },
    {
        "flag": "meta_aware", "label_ko": "메타인식(본인 의심)",
        "regex": re.compile(r"(사기.{0,5}같|이상한데|진짜.{0,3}인가|이거.{0,3}사기)"),
        # 🟢 보호 신호 — 통화 중 의심 표현. 경보 X (낮은 누적), 사기범 발화면 무시.
        "by_victim": (1, False, "잘 의심하고 계세요. 끊고 해당 기관 대표번호로 직접 다시 확인하세요."),
        "by_scammer": None,
        "agnostic": (1, False, "잘 의심하고 계세요. 끊고 해당 기관 대표번호로 직접 다시 확인하세요."),
    },
]


def _classify(pat: dict, role: str | None) -> tuple[int, bool, str] | None:
    """(패턴, 화자) → (level, instant, action). 무시면 None.

    role 이 None(화자 미상 — Live 즉시 검출, 화자 분리 skip)이면 패턴별 명시 `agnostic`
    분류를 쓴다 (중립 행동 문구 + 안전측 severity). 화자별 정밀 구분은 by_victim/by_scammer
    로 별도 유지(파일 분석의 _scan_turns 경로).
    """
    if role == "본인":
        return pat["by_victim"]
    if role == "상대방":
        return pat["by_scammer"]
    return pat.get("agnostic")


def _match_in(pat: dict, role: str | None, snippet: str) -> dict | None:
    cls = _classify(pat, role)
    if cls is None:
        return None
    level, instant, action = cls
    return {
        "flag": pat["flag"],
        "label_ko": pat["label_ko"],
        "level": level,
        "snippet": snippet,
        "instant": instant,
        "action": action,
        "speaker": role,  # "본인" / "상대방" / None
    }


def _scan_turns(turns: list[dict]) -> tuple[int, list[dict]]:
    """화자(turn)별 스캔 — 누가 말했나로 신호 심각도를 다르게 매긴다."""
    matches: list[dict] = []
    max_level = 0
    for turn in turns:
        role = (turn.get("speaker") or "").strip() or None
        text = turn.get("text", "") or ""
        for pat in _SPEAKER_PATTERNS:
            for m in pat["regex"].finditer(text):
                md = _match_in(pat, role, m.group(0))
                if md is None:
                    continue
                matches.append(md)
                if md["level"] > max_level:
                    max_level = md["level"]
    return max_level, matches


def _scan_text(text: str) -> tuple[int, list[dict]]:
    """화자 미상 fallback (turns 없을 때) — 더 심각한 분류 적용."""
    matches: list[dict] = []
    max_level = 0
    for pat in _SPEAKER_PATTERNS:
        for m in pat["regex"].finditer(text):
            md = _match_in(pat, None, m.group(0))
            if md is None:
                continue
            matches.append(md)
            if md["level"] > max_level:
                max_level = md["level"]
    return max_level, matches


# tier 임계 — 누적 점수(비-instant match 의 level 합)가 이 값 이상이면 해당 tier.
_TIER_CAUTION_SCORE = 3
_TIER_DANGER_SCORE = 6


def _compute_tier(cum_score: int, instant_seen: bool, any_match: bool) -> int:
    """누적 점수 + instant 여부 → tier 0~3."""
    if instant_seen or cum_score >= _TIER_DANGER_SCORE:
        return 3
    if cum_score >= _TIER_CAUTION_SCORE:
        return 2
    if any_match:
        return 1
    return 0


def _ndjson(obj: dict) -> bytes:
    return (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")


def _window_turns(turns: list[dict], window_seconds: float = 60.0) -> list[dict]:
    """전역 diarization turns 를 ~window_seconds 단위 window 로 묶는다.

    통파일 STT 가 준 turn (전역 timestamp·상대방/본인 일관) 을 progressive emit 하기
    위한 그룹핑. turn 은 절대 쪼개지 않음 — window 경계는 항상 turn 사이 (문장 절단 X).
    각 window 는 기존 `chunk` 이벤트 shape 와 호환: turns / transcript / start_sec / end_sec.
    """
    if not turns:
        return []
    windows: list[dict] = []
    current: list[dict] = []
    win_start: float | None = None
    for turn in turns:
        t_start = float(turn.get("start_sec", 0.0))
        t_end = float(turn.get("end_sec", t_start))
        if win_start is None:
            win_start = t_start
        current.append(turn)
        # 현재 window 가 목표 길이를 넘기면 turn 경계에서 닫는다.
        if t_end - win_start >= window_seconds:
            windows.append(_pack_window(current))
            current = []
            win_start = None
    if current:
        windows.append(_pack_window(current))
    return windows


def _pack_window(turns: list[dict]) -> dict:
    transcript = " ".join((t.get("text", "") or "").strip() for t in turns).strip()
    start_sec = float(turns[0].get("start_sec", 0.0))
    end_sec = float(turns[-1].get("end_sec", start_sec))
    return {
        "turns": turns,
        "transcript": transcript,
        "start_sec": start_sec,
        "end_sec": end_sec,
    }


def _use_silenceremove() -> bool:
    """CLOVA backend 는 침묵에서 환각하지 않으므로 silenceremove 불필요 — 오히려 화자
    경계 정적을 깎아 diarization·timestamp 를 망친다. CLOVA 가 아닐 때만 사용."""
    try:
        from pipeline import stt as _stt
        return (_stt.STT_BACKEND or "").lower() != "clova"
    except Exception:
        return True


def _audio_filter() -> str:
    """ffmpeg -af 체인 (빈 문자열이면 -af 생략).

    CLOVA: **정규화 없는 clean 16k downsample 이 STT 정확도 최고** (측정값 — dynaudnorm
    이 단어 사이 노이즈 플로어를 끌어올려 '수사관입니다'→'수작을 했다' 식 오인식 유발).
    → 빈 문자열.
    non-CLOVA(Whisper): silenceremove(환각 차단) + dynaudnorm(작은 발화 증폭).
    """
    if _use_silenceremove():
        return "silenceremove=stop_periods=-1:stop_duration=1:stop_threshold=-40dB,dynaudnorm=f=150:g=15"
    return ""


def _ffmpeg_af_args() -> list[str]:
    """ffmpeg 명령에 끼울 -af 인자 (필터 없으면 빈 리스트)."""
    af = _audio_filter()
    return ["-af", af] if af else []


@router.post(
    "/api/analyze-stream",
    tags=["Public"],
    summary="긴 음성 파일 chunk 스트리밍 분석 (NDJSON)",
    description=(
        "긴 음성 파일을 `chunk_seconds` 단위로 잘라 각 chunk 의 STT + 키워드 alert "
        "결과를 NDJSON 으로 즉시 흘려준다.\n\n"
        "**Form fields**:\n"
        "- `file` — 음성/영상 파일 (필수)\n"
        "- `chunk_seconds` — 청크 길이 초 단위 (기본 60)\n\n"
        "**응답**: `application/x-ndjson` — 각 줄이 한 개의 JSON 이벤트 "
        "(`start` / `chunk` / `done` / `error`)\n\n"
        "**인증**: API key 필수."
    ),
    responses={
        400: {"description": "파일 비어있음 / 코덱 오류"},
        401: {"description": "API key 누락 또는 무효"},
        429: {"description": "Rate limit 초과"},
    },
)
async def analyze_stream(
    file: UploadFile = File(...),
    chunk_seconds: int = Form(60),
) -> StreamingResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="업로드된 파일 이름이 비어 있습니다.")
    if chunk_seconds < 5 or chunk_seconds > 600:
        raise HTTPException(status_code=400, detail="chunk_seconds 는 5~600 범위여야 합니다.")

    suffix = Path(file.filename).suffix
    upload_dir = Path(".scamguardian") / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    tmp_handle = tempfile.NamedTemporaryFile(
        mode="wb", delete=False, dir=str(upload_dir),
        prefix="stream_", suffix=suffix,
    )
    tmp_path = Path(tmp_handle.name)
    wav_path = tmp_path.with_suffix(".wav")

    # 파일 저장 + wav 변환 — generator 시작 전에 동기로 마쳐서 에러는 HTTPException 으로 깔끔히
    try:
        with tmp_handle:
            if file.file is None:
                raise HTTPException(status_code=400, detail="업로드된 파일 본문을 읽을 수 없습니다.")
            shutil.copyfileobj(file.file, tmp_handle)
        if tmp_path.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="업로드된 파일이 비어 있습니다(0 bytes).")

        # wav 변환 + 음향 전처리. CLOVA backend 면 silenceremove 제외 — 화자 경계 정적을
        # 보존해 전역 diarization·timestamp 가 안 망가지게. dynaudnorm 은 항상 (피해자 측
        # 작은 발화 증폭). non-CLOVA(Whisper) 면 silenceremove 로 환각 차단.
        extract = subprocess.run(
            ["ffmpeg", "-y", "-i", str(tmp_path),
             "-vn", "-ac", "1", "-ar", "16000",
             *_ffmpeg_af_args(),
             "-f", "wav", str(wav_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
        )
        if extract.returncode != 0 or not wav_path.exists() or wav_path.stat().st_size == 0:
            raise HTTPException(
                status_code=400,
                detail="업로드된 파일에서 오디오를 추출하지 못했습니다. 다른 파일(코덱)로 시도해주세요.",
            )
    except HTTPException:
        for p in (tmp_path, wav_path):
            try: p.unlink(missing_ok=True)
            except Exception: pass
        raise

    async def event_stream() -> AsyncIterator[bytes]:
        try:
            from pipeline import diarize as _diarize
            from pipeline import stt as _stt

            # 통파일 STT/diarization 1회 — 전역 일관 turns (chunk 경계 절단·label 뒤집힘 없음).
            stt_started = time.monotonic()
            stt_result = None
            full_text = ""
            try:
                stt_result = await asyncio.to_thread(_stt.transcribe, str(wav_path))
                full_text = stt_result.text or ""
            except Exception as exc:
                LOG.warning("통파일 STT 실패: %s", exc)
                yield _ndjson({"type": "error", "message": f"STT 실패: {exc}"})
                return
            stt_ms = int((time.monotonic() - stt_started) * 1000)

            # 화자 분리 — CLOVA 등 audio-based 백엔드가 직접 분리한 경우 그대로.
            # 아니면 Sonnet diarize (전체 텍스트 1회).
            turns: list[dict] = getattr(stt_result, "turns", None) or []
            if not turns and full_text:
                try:
                    diar = await asyncio.to_thread(
                        _diarize.diarize, full_text, _diarize.SONNET_MODEL, True,
                    )
                    turns = _diarize.turns_to_dict(diar)
                except Exception as exc:
                    LOG.warning("통파일 diarize 실패: %s", exc)

            # 전역 turns 를 ~chunk_seconds window 로 묶어 progressive emit.
            windows = _window_turns(turns, float(chunk_seconds))
            if not windows and full_text:
                # turn 이 전혀 없으면 (diarize 실패) 전체 텍스트를 단일 window 로.
                windows = [{"turns": [], "transcript": full_text, "start_sec": 0.0, "end_sec": 0.0}]

            yield _ndjson({
                "type": "start",
                "total_chunks": len(windows),
                "chunk_seconds": chunk_seconds,
                "source_filename": file.filename,
                "stt_ms": stt_ms,
            })

            cumulative_matches: list[dict] = []
            cum_score = 0          # 비-instant 누적 점수
            instant_seen = False   # 한 번이라도 instant 신호가 떴는가
            tier = 0               # 단조 증가 (내려가지 않음 → flicker 방지)
            for idx, win in enumerate(windows):
                started = time.monotonic()
                text = win["transcript"]
                win_turns = win.get("turns") or []
                # 화자별 스캔 (turn 있으면) — 누가 말했나로 심각도 차등. 없으면 transcript fallback.
                if win_turns:
                    level, matches = _scan_turns(win_turns)
                else:
                    level, matches = _scan_text(text)
                cumulative_matches.extend(matches)
                # tier 누적 갱신
                for m in matches:
                    if m["instant"]:
                        instant_seen = True
                    else:
                        cum_score += m["level"]
                new_tier = _compute_tier(cum_score, instant_seen, bool(cumulative_matches))
                tier_prev = tier
                tier = max(tier, new_tier)  # 단조
                tier_changed = tier > tier_prev
                latency_ms = int((time.monotonic() - started) * 1000)
                yield _ndjson({
                    "type": "chunk",
                    "chunk_index": idx,
                    "start_sec": win["start_sec"],
                    "end_sec": win["end_sec"],
                    "transcript": text,
                    "turns": win["turns"],
                    "alert_level": level,
                    "matches": matches,
                    "tier": tier,
                    "tier_changed": tier_changed,
                    "latency_ms": latency_ms,
                })

            cum_level = max((m["level"] for m in cumulative_matches), default=0)
            yield _ndjson({
                "type": "done",
                "total_chunks": len(windows),
                "full_transcript": full_text.strip(),
                "cumulative_matches": cumulative_matches,
                "cumulative_alert_level": cum_level,
                "tier": tier,
            })
        finally:
            try: tmp_path.unlink(missing_ok=True)
            except Exception: pass
            try: wav_path.unlink(missing_ok=True)
            except Exception: pass

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
