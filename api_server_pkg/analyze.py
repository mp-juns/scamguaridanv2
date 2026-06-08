"""/api/analyze 와 /api/analyze-upload — 외부 API 클라이언트용."""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile

from db import repository

from .common import resolve_source, run_pipeline
from .models import AnalyzeRequest

router = APIRouter()


@router.post(
    "/api/analyze",
    tags=["Public"],
    summary="텍스트·URL 분석 — 위험 신호 검출 (Signal Detection)",
    description=(
        "ScamGuardian 의 메인 검출 엔드포인트. 한국어 텍스트 또는 URL/YouTube/음성·영상·이미지·PDF 파일 경로를 받아 "
        "Phase 0 (안전성) → Phase 0.5 (sandbox) → Phase 1 (STT/OCR) → Phase 2-5 (분류·추출·검증·검출) "
        "전체 파이프라인을 수행한다.\n\n"
        "⚠️ **Identity Boundary** (CLAUDE.md): ScamGuardian 은 **사기 판정을 내리지 않는다**. "
        "검출된 위험 신호 list 와 각 신호의 학술/법적 근거만 transparent 하게 보고한다. "
        "VirusTotal 이 70개 백신의 검출 결과를 보고만 하는 모델과 동일. "
        "최종 판정 logic 은 통합 기업이 자체 risk tolerance 에 따라 구현한다.\n\n"
        "**Request body** (`AnalyzeRequest`):\n"
        "- `source` *or* `text` — 둘 중 하나는 필수. URL 도 `source` 로 전달\n"
        "- `whisper_model` — `tiny|base|small|medium|large` (음성 입력 시에만 영향)\n"
        "- `skip_verification` — true 면 Phase 4 (Serper) 건너뜀, 응답 빨라짐\n"
        "- `use_llm` — 무시됨 (서버에서 강제 true)\n"
        "- `use_rag` — 과거 라벨 사례 RAG 검색 여부\n\n"
        "**응답 핵심 필드** (`DetectionReport`):\n"
        "- `scam_type` — 분류된 스캠 유형 (검출 컨텍스트, 판정 X)\n"
        "- `detected_signals` — `[{flag, label_ko, rationale, source, evidence, description, detection_source}]` "
        "검출된 위험 신호 list. 각 신호마다 학술/법적 근거(`rationale`) 와 출처(`source`) 포함\n"
        "- `summary` — `\"위험 신호 N개 검출되었습니다. 자세한 근거는 detected_signals 참고.\"`\n"
        "- `disclaimer` — 통합 기업 판정 logic 안내 문구\n"
        "- `entities` — `[{label, text, score, source}]` 추출된 엔티티\n"
        "- `transcript_text` — 본문 (URL/파일 입력 시 STT/OCR 결과)\n"
        "- `analysis_run_id` — DB 저장된 경우 UUID\n\n"
        "❌ 응답에 `total_score`, `risk_level`, `is_scam`, `agent_verdict` 등 *판정* 필드는 **없다**.\n\n"
        "**인증**: API key 필수 (`Authorization: Bearer sg_...` 또는 `X-API-Key`).\n\n"
        "**에러**:\n"
        "- `400` — 빈 입력 / 어뷰즈 가드 reject (REPETITIVE / GIBBERISH / DUPLICATE)\n"
        "- `401` — API key 누락 또는 무효\n"
        "- `403` — API key revoked\n"
        "- `423` — 어뷰즈 가드 BLOCKED (위반 누적 차단)\n"
        "- `429` — RPM 또는 월 USD/호출 cap 초과 (`Retry-After` 헤더)\n"
        "- `500` — 파이프라인 내부 오류\n\n"
        "**curl** (텍스트):\n"
        "```bash\n"
        "curl -X POST https://api.example.com/api/analyze \\\n"
        "  -H \"Authorization: Bearer sg_xxx\" \\\n"
        "  -H \"Content-Type: application/json\" \\\n"
        "  -d '{\"text\": \"검찰청입니다. 즉시 300만원 송금하세요.\"}'\n"
        "```\n\n"
        "**curl** (YouTube URL):\n"
        "```bash\n"
        "curl -X POST https://api.example.com/api/analyze \\\n"
        "  -H \"Authorization: Bearer sg_xxx\" \\\n"
        "  -H \"Content-Type: application/json\" \\\n"
        "  -d '{\"source\": \"https://youtu.be/abcd1234\"}'\n"
        "```"
    ),
    responses={
        400: {"description": "빈 입력 / 어뷰즈 reject / 환경 미설정"},
        401: {"description": "API key 누락 또는 무효"},
        423: {"description": "어뷰즈 누적 차단 — 1시간 후 재시도"},
        429: {"description": "Rate limit 초과 — `Retry-After` 헤더 참조"},
    },
)
async def analyze(payload: AnalyzeRequest, request: Request) -> dict:
    log = logging.getLogger("api_analyze")
    source = resolve_source(payload)
    log.info(
        "/api/analyze 요청 (검출 모드):\n"
        "  source: %s\n"
        "  whisper_model: %s, skip_verification: %s, use_llm: true(강제), use_rag: %s",
        source[:100], payload.whisper_model, payload.skip_verification,
        payload.use_rag,
    )
    from platform_layer import abuse_guard as _ag
    key_id = getattr(request.state, "api_key_id", None)
    user_id = request.headers.get("x-user-id", "").strip() or None

    # 프롬프트 인젝션(우회) — source/text 무관하게 본문에 우회 시도가 섞여 있으면 즉시 접근 제한.
    # 웹은 텍스트를 source 로 보내므로(아래 text-only 가드 우회) 여기서 별도 검사.
    if _ag.detect_prompt_injection(source):
        if user_id:
            _ag.force_block(user_id)  # 식별되면 즉시 차단(누적 무관)
        log.warning("/api/analyze 프롬프트 인젝션 차단: %s", source[:120])
        raise HTTPException(
            status_code=423,
            detail={
                "code": "INJECTION",
                "message": "프롬프트 우회 시도가 감지되어 접근이 제한되었습니다.",
                "detail": "",
            },
        )

    # 어뷰즈 가드 — 텍스트 입력에 한해 외부 API 호출 전 차단
    if payload.text and not payload.source:
        rej = _ag.guard(payload.text, key_id=key_id, user_id=user_id)
        if rej is not None:
            status = 423 if rej.code == "BLOCKED" else 400
            raise HTTPException(
                status_code=status,
                detail={"code": rej.code, "message": rej.message, "detail": rej.detail},
            )
    try:
        result = await asyncio.to_thread(run_pipeline, payload)
        log.info(
            "/api/analyze 완료: scam_type=%s, signals=%d",
            result.get("scam_type", "?"),
            len(result.get("detected_signals") or []),
        )
        return result
    except ValueError as exc:
        log.warning("/api/analyze 입력 오류: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except EnvironmentError as exc:
        log.warning("/api/analyze 환경 오류: %s", exc)
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        log.error("/api/analyze 서버 오류: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post(
    "/api/analyze-upload",
    tags=["Public"],
    summary="파일 업로드 검출 (multipart) — Signal Detection",
    description=(
        "음성·영상·이미지·PDF 파일을 multipart/form-data 로 업로드받아 위험 신호를 검출한다. "
        "이미지/PDF 는 Claude vision OCR, 음성/영상은 ffmpeg + Whisper 로 transcript 추출.\n\n"
        "⚠️ **Identity**: 검출만, 판정 X. 응답 schema 는 `/api/analyze` 와 동일 (`DetectionReport`).\n\n"
        "**Form fields**:\n"
        "- `file` — 파일 본문 (필수). 100MB 이하 권장. 지원 확장자: "
        "`.mp4 .mov .webm .mkv .m4a .mp3 .wav .ogg .aac .jpg .jpeg .png .webp .gif .bmp .pdf`\n"
        "- `whisper_model` — `tiny|base|small|medium|large` (기본 medium)\n"
        "- `skip_verification` — 기본 true\n"
        "- `use_llm` — 무시됨 (강제 true)\n"
        "- `use_rag` — 기본 false\n\n"
        "**응답**: `/api/analyze` 와 동일한 `DetectionReport` JSON (`detected_signals[]` + `summary` + `disclaimer`). "
        "업로드 원본은 라벨링용으로 `.scamguardian/uploads/{run_id}/source.{ext}` 에 보존된다.\n\n"
        "**인증**: API key 필수.\n\n"
        "**에러**:\n"
        "- `400` — 빈 파일 / 코덱 추출 실패 / 어뷰즈 reject\n"
        "- `401/403/423/429` — `/api/analyze` 와 동일\n"
        "- `500` — 파이프라인 내부 오류\n\n"
        "**curl**:\n"
        "```bash\n"
        "curl -X POST https://api.example.com/api/analyze-upload \\\n"
        "  -H \"Authorization: Bearer sg_xxx\" \\\n"
        "  -F \"file=@suspect_call.m4a\" \\\n"
        "  -F \"whisper_model=medium\"\n"
        "```"
    ),
    responses={
        400: {"description": "파일 비어있음 / 코덱 오류 / 어뷰즈 reject"},
        401: {"description": "API key 누락 또는 무효"},
        429: {"description": "Rate limit 초과"},
    },
)
async def analyze_upload(
    file: UploadFile = File(...),
    whisper_model: str = Form("medium"),
    skip_verification: bool = Form(True),
    use_llm: bool = Form(True),
    use_rag: bool = Form(False),
) -> dict:
    """영상/음성 파일을 업로드 받아 로컬 파일로 저장한 뒤 파이프라인을 수행한다."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="업로드된 파일 이름이 비어 있습니다.")

    suffix = Path(file.filename).suffix
    upload_dir = Path(".scamguardian") / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    tmp_handle = tempfile.NamedTemporaryFile(
        mode="wb",
        delete=False,
        dir=str(upload_dir),
        prefix="upload_",
        suffix=suffix,
    )
    tmp_path = Path(tmp_handle.name)
    wav_path = tmp_path.with_suffix(".wav")
    media_persisted = False
    try:
        with tmp_handle:
            if file.file is None:
                raise HTTPException(status_code=400, detail="업로드된 파일 본문을 읽을 수 없습니다.")
            shutil.copyfileobj(file.file, tmp_handle)

        if tmp_path.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="업로드된 파일이 비어 있습니다(0 bytes).")

        # v3 Phase 1: 이미지·PDF 는 vision OCR 라우팅 — ffmpeg 단계 skip
        from pipeline import vision as _vision_mod
        is_visual = _vision_mod.supported(tmp_path)
        if is_visual:
            payload = AnalyzeRequest(
                source=str(tmp_path),
                whisper_model=whisper_model,
                skip_verification=skip_verification,
                use_llm=True,
                use_rag=use_rag,
            )
        else:
            extract = subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    str(tmp_path),
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-af",
                    # VAD (침묵 제거) → 음량 정규화. Whisper hallucination 원천 차단.
                    "silenceremove=stop_periods=-1:stop_duration=1:stop_threshold=-40dB,dynaudnorm=f=150:g=15",
                    "-f",
                    "wav",
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

            payload = AnalyzeRequest(
                source=str(wav_path),
                whisper_model=whisper_model,
                skip_verification=skip_verification,
                use_llm=True,
                use_rag=use_rag,
            )
        result = await asyncio.to_thread(run_pipeline, payload)

        run_id = result.get("analysis_run_id") if isinstance(result, dict) else None
        media_persisted = False
        if run_id:
            try:
                target_dir = Path(".scamguardian") / "uploads" / str(run_id)
                target_dir.mkdir(parents=True, exist_ok=True)
                target_path = target_dir / f"source{suffix or ''}"
                shutil.move(str(tmp_path), str(target_path))
                media_persisted = True
                try:
                    repository.merge_run_metadata(run_id, {
                        "media": {
                            "kind": "uploaded_file",
                            "original_filename": file.filename,
                            "stored_path": str(target_path),
                            "size_bytes": target_path.stat().st_size,
                            "suffix": suffix or "",
                        }
                    })
                except Exception as exc:
                    logging.getLogger("upload").warning(
                        "media metadata merge 실패 (run_id=%s): %s", run_id, exc,
                    )
            except Exception as exc:
                logging.getLogger("upload").warning(
                    "원본 업로드 파일 보존 실패 (run_id=%s): %s", run_id, exc,
                )
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        if not media_persisted:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass
        try:
            wav_path.unlink(missing_ok=True)
        except Exception:
            pass
