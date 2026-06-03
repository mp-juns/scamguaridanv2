"""파이프라인 실행 공통 헬퍼.

`_persist_run` / `_run_pipeline` 은 카카오·analyze 둘 다 호출.
`_options_payload` 는 admin runs/scam-types 응답에 사용.
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path
from typing import Any

from db import repository
from pipeline import rag
from pipeline.config import DETECTED_FLAGS, get_runtime_scam_taxonomy
from pipeline.runner import ScamGuardianPipeline

from .models import AnalyzeRequest, ScamTypeCatalogRequest


def resolve_source(payload: AnalyzeRequest) -> str:
    return (payload.text or payload.source or "").strip()


def options_payload() -> dict[str, Any]:
    taxonomy = get_runtime_scam_taxonomy()
    return {
        "scam_types": taxonomy["scam_types"],
        "label_sets": taxonomy["label_sets"],
        "flags": list(DETECTED_FLAGS),
    }


def normalize_catalog_payload(payload: ScamTypeCatalogRequest) -> dict[str, Any]:
    normalized_labels: list[str] = []
    seen: set[str] = set()
    for raw_label in payload.labels:
        label = raw_label.strip()
        if not label or label in seen:
            continue
        seen.add(label)
        normalized_labels.append(label)

    return {
        "name": payload.name.strip(),
        "description": (payload.description or "").strip(),
        "labels": normalized_labels,
    }


def require_db() -> None:
    if not repository.database_configured():
        raise EnvironmentError(
            "DB 기능을 사용하려면 SCAMGUARDIAN_DATABASE_URL(Postgres) 또는 "
            "SCAMGUARDIAN_SQLITE_PATH(SQLite)가 설정되어야 합니다."
        )


def persist_run(
    pipeline: ScamGuardianPipeline,
    payload: AnalyzeRequest,
    source: str,
    report_dict: dict[str, Any],
    *,
    user_context: dict[str, Any] | None = None,
) -> str | None:
    if not repository.persistence_enabled():
        return None

    transcript_text = (
        pipeline.last_transcript_result.text if pipeline.last_transcript_result is not None else source
    )
    metadata = {
        "source_type": (
            pipeline.last_transcript_result.source_type
            if pipeline.last_transcript_result is not None
            else "text"
        ),
        "steps": [
            {
                "name": step.name,
                "duration_ms": step.duration_ms,
                "detail": step.detail,
            }
            for step in pipeline.steps
        ],
        "rag_context": report_dict.get("rag_context"),
    }
    if user_context:
        metadata["user_context"] = user_context
    # Stage 1 게이트 결과 — 내부 metadata 에만 (외부 응답 schema 에는 노출 안 함).
    # 어드민에서 게이트 정확도 측정·라벨링에 사용.
    if pipeline.last_gate_result is not None:
        metadata["gate"] = pipeline.last_gate_result.to_dict()
    # Stage 2 multi-label 추출 후보 — 내부 metadata 에만 (외부 응답 비노출).
    if pipeline.last_candidate_scam_types:
        metadata["candidate_scam_types"] = pipeline.last_candidate_scam_types

    run_id = repository.save_analysis_run(
        input_source=source,
        whisper_model=payload.whisper_model,
        skip_verification=payload.skip_verification,
        use_llm=payload.use_llm,
        use_rag=payload.use_rag,
        transcript_text=transcript_text,
        classification_scanner={
            "scam_type": report_dict.get("scam_type", ""),
            "confidence": report_dict.get("classification_confidence", 0.0),
            "is_uncertain": report_dict.get("is_uncertain", False),
        },
        entities_predicted=report_dict.get("entities", []),
        verification_results=pipeline.last_report.all_verifications if pipeline.last_report else [],
        # 컬럼명은 DB schema 호환을 위해 유지 — 의미는 검출 신호 list 로 재해석.
        # `total_score_predicted` 는 검출된 신호 *개수* (점수 X), `risk_level_predicted` 는 빈 문자열 (deprecated).
        triggered_flags_predicted=report_dict.get("detected_signals", []),
        total_score_predicted=len(report_dict.get("detected_signals") or []),
        risk_level_predicted="",
        llm_assessment=report_dict.get("llm_assessment"),
        metadata=metadata,
    )

    try:
        embedding = rag.compute_transcript_embedding(transcript_text)
        repository.save_transcript_embedding(run_id, embedding, rag.embedding_model_name())
    except Exception:
        # 분석 결과 저장은 유지하고, 임베딩 저장 실패만 조용히 건너뛴다.
        pass

    return run_id


# 사기범이 링크로 뿌리는 실행파일 확장자 — kakao detect._EXECUTABLE_URL_RE 와 동일 패턴.
# (common → kakao 순환 import 회피 위해 여기 별도 정의.)
_EXECUTABLE_URL_RE = re.compile(
    r"\.(apk|exe|dmg|msi|jar|bat|cmd|scr|app|ipa|deb|rpm)(\?|$)", re.IGNORECASE
)
_MAX_EXECUTABLE_DOWNLOAD_BYTES = 150 * 1024 * 1024  # 150MB


def is_executable_url(source: str) -> bool:
    """source 가 http(s) 실행파일 다운로드 링크인지."""
    s = (source or "").strip()
    return s.startswith(("http://", "https://")) and bool(_EXECUTABLE_URL_RE.search(s))


def materialize_executable_url(url: str) -> str:
    """실행파일 URL 을 로컬 임시 파일로 다운로드하고 경로를 반환한다 (size cap).

    호출측이 분석 후 파일 삭제 책임을 진다. APK 면 그대로 Phase 0.6 정적/동적 분석으로 흐른다.
    로컬 *실행* 은 절대 없음 — APK 실행은 항상 격리 VM(apk_analyzer HARD BLOCK).
    """
    import requests

    clean = url.split("?", 1)[0]
    idx = clean.rfind(".")
    suffix = clean[idx:] if 0 < idx and len(clean) - idx <= 6 else ".bin"

    target_dir = Path(".scamguardian") / "uploads" / "web_apk"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid.uuid4().hex}{suffix}"

    try:
        with requests.get(url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            total = 0
            with target.open("wb") as fp:
                for chunk in resp.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > _MAX_EXECUTABLE_DOWNLOAD_BYTES:
                        raise ValueError("실행파일 다운로드가 150MB 를 초과합니다.")
                    fp.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    logging.getLogger("web_apk_dl").info(
        "실행파일 다운로드 완료: %s → %s (%d bytes)", url[:80], target.name, target.stat().st_size
    )
    return str(target)


def run_pipeline(payload: AnalyzeRequest) -> dict:
    normalized_payload = AnalyzeRequest(
        source=payload.source,
        text=payload.text,
        whisper_model=payload.whisper_model,
        skip_verification=payload.skip_verification,
        use_llm=True,
        use_rag=payload.use_rag,
    )
    source = resolve_source(normalized_payload)
    if not source:
        raise ValueError("분석할 텍스트 또는 URL을 입력해주세요.")

    # 시연 편의 — APK/실행파일 *다운로드 링크* 를 넣으면 받아서 분석한다.
    # URL → 로컬 임시 파일 materialize → 기존 Phase 0(VT 파일) + Phase 0.6(APK 정적/동적) 그대로.
    original_source = source
    downloaded_path: str | None = None
    if is_executable_url(source):
        downloaded_path = materialize_executable_url(source)
        source = downloaded_path

    try:
        pipeline = ScamGuardianPipeline(whisper_model=normalized_payload.whisper_model)
        report = pipeline.analyze(
            source,
            skip_verification=normalized_payload.skip_verification,
            use_llm=True,
            use_rag=normalized_payload.use_rag,
        )
        transcript_text = pipeline.last_transcript_result.text if pipeline.last_transcript_result else ""
        from platform_layer.abuse_guard import MAX_CHARS as _MAX_CHARS
        if transcript_text and len(transcript_text) > _MAX_CHARS:
            logging.getLogger("abuse_guard").warning(
                "transcript %d자 cap 초과(>%d)", len(transcript_text), _MAX_CHARS,
            )
        report_dict = report.to_dict()
        if downloaded_path:
            report_dict["source"] = original_source  # 응답엔 임시 경로 대신 원본 URL 표기
        report_dict["transcript_text"] = (
            pipeline.last_transcript_result.text if pipeline.last_transcript_result is not None else ""
        )
        run_id = persist_run(pipeline, normalized_payload, original_source, report_dict)
        if run_id:
            report_dict["analysis_run_id"] = run_id

        # Stage 1 게이트 안전 버킷만 content_type 으로 노출 — Identity Boundary.
        # 사기 시도/의심 버킷은 *판정성* 정보라 절대 노출하지 않음 (helper 가 None 반환).
        if pipeline.last_gate_result is not None:
            from .result_token import _safe_content_type
            content_type = _safe_content_type(pipeline.last_gate_result.to_dict())
            if content_type:
                report_dict["content_type"] = content_type

        return report_dict
    finally:
        if downloaded_path:
            Path(downloaded_path).unlink(missing_ok=True)
