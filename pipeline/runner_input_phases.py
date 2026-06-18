"""Input-facing phases for :mod:`pipeline.runner`.

These helpers keep the orchestration method focused on routing while preserving
the existing runtime behavior and console traces.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

from pipeline import apk_analyzer, classifier, safety, sandbox, signal_detector, stt
from pipeline.signal_detector import DetectionReport

if TYPE_CHECKING:
    from pipeline.runner import ScamGuardianPipeline


def run_safety_phase(
    pipe: ScamGuardianPipeline,
    source: str,
    precomputed_transcript: stt.TranscriptResult | None,
    pipeline_start: float,
) -> tuple[safety.SafetyResult | None, DetectionReport | None]:
    """Run VirusTotal safety checks and return an optional fast-path report."""
    safety_result: safety.SafetyResult | None = None
    phase0_start = time.time()
    try:
        if stt._is_youtube_url(source):
            print("[Phase 0] YouTube URL — VirusTotal skip (신뢰 플랫폼)")
        elif source.startswith(("http://", "https://")):
            print("[Phase 0] URL 안전성 검사 중 (VirusTotal)...")
            safety_result = safety.scan_url(source)
        else:
            src_path = source if source else None
            if src_path and len(src_path) < 1024 and "/" in src_path:
                path = Path(src_path)
                if path.exists() and path.is_file():
                    print("[Phase 0] 파일 안전성 검사 중 (VirusTotal)...")
                    safety_result = safety.scan_file(src_path)
    except Exception as exc:  # noqa: BLE001 — safety must not break analysis.
        print(f"[Phase 0] 검사 실패(무시): {exc}")
        safety_result = None

    if safety_result is not None:
        pipe.last_safety_result = safety_result
        pipe._log_step(
            "Safety",
            phase0_start,
            {
                "threat_level": safety_result.threat_level.value,
                "detections": safety_result.detections,
                "total_engines": safety_result.total_engines,
            },
        )
        level = safety_result.threat_level.value
        icon = "🚨" if level == "malicious" else ("⚠️" if level == "suspicious" else "✅")
        print(
            f"      ← {icon} {level} | 탐지 {safety_result.detections}/{safety_result.total_engines} | "
            f"카테고리: {', '.join(safety_result.threat_categories[:3]) or '없음'}"
        )

    if (
        safety_result is not None
        and safety_result.is_malicious
        and safety_result.target_kind == "file"
        and precomputed_transcript is None
    ):
        print("[fast-path] 악성 파일 확정 — STT/분류 skip, safety 결과만으로 보고")
        transcript = stt.TranscriptResult(text="", source_type="file")
        pipe.last_transcript_result = transcript
        empty_classification = classifier.ClassificationResult(
            scam_type="메신저 피싱",
            confidence=0.0,
            all_scores={},
            is_uncertain=True,
        )
        pipe.last_classification = empty_classification
        report = signal_detector.detect(
            verification_results=[],
            classification=empty_classification,
            entities=[],
            source=source,
            transcript="",
            safety_result=safety_result,
        )
        pipe.last_report = report
        pipe._log_step("전체", pipeline_start)
        return safety_result, report

    return safety_result, None


def run_sandbox_phase(pipe: ScamGuardianPipeline, source: str) -> sandbox.SandboxResult | None:
    """Run optional remote/local URL detonation."""
    sandbox_result: sandbox.SandboxResult | None = None
    sandbox_enabled = (
        os.getenv("SANDBOX_ENABLED", "0") == "1"
        and source.startswith(("http://", "https://"))
    )
    if not sandbox_enabled:
        return None

    phase05_start = time.time()
    try:
        print("[Phase 0.5] URL 디토네이션 (격리 Chromium)...")
        sandbox_result = sandbox.detonate_url(source)
    except Exception as exc:  # noqa: BLE001 — sandbox must not break analysis.
        print(f"[Phase 0.5] 디토네이션 실패(무시): {exc}")
        sandbox_result = None

    if sandbox_result is not None:
        pipe.last_sandbox_result = sandbox_result
        pipe._log_step(
            "Sandbox",
            phase05_start,
            {
                "status": sandbox_result.status.value,
                "redirect_count": len(sandbox_result.redirect_chain),
                "has_password_field": sandbox_result.has_password_field,
                "downloads": len(sandbox_result.download_attempts),
                "duration_ms": sandbox_result.duration_ms,
            },
        )
        icon = "🚨" if sandbox_result.is_dangerous else "✅"
        print(
            f"      ← {icon} status={sandbox_result.status.value} "
            f"final={sandbox_result.final_url[:60] if sandbox_result.final_url else '-'} "
            f"pwd_form={sandbox_result.has_password_field} "
            f"downloads={len(sandbox_result.download_attempts)} "
            f"cloaking={sandbox_result.cloaking_detected}"
        )
    return sandbox_result


def run_apk_phase(
    pipe: ScamGuardianPipeline,
    source: str,
    precomputed_transcript: stt.TranscriptResult | None,
) -> tuple[
    bool,
    apk_analyzer.APKStaticReport | None,
    apk_analyzer.APKBytecodeReport | None,
    apk_analyzer.APKDynamicReport | None,
]:
    """Run APK static and optional dynamic analysis for APK file input."""
    apk_static_result: apk_analyzer.APKStaticReport | None = None
    apk_bytecode_result: apk_analyzer.APKBytecodeReport | None = None
    apk_dynamic_result: apk_analyzer.APKDynamicReport | None = None
    apk_input = False

    if precomputed_transcript is not None or not apk_analyzer.is_apk_file(source):
        return apk_input, apk_static_result, apk_bytecode_result, apk_dynamic_result

    apk_input = True
    phase06_start = time.time()
    print("[Phase 0.6] APK 정적 분석 (Lv 1 — manifest·권한·서명)...")
    try:
        apk_static_result = apk_analyzer.analyze_apk_static(source)
        pipe.last_apk_static_result = apk_static_result
        print(
            f"      ← Lv 1: 검출 {len(apk_static_result.detected_flags)}개, "
            f"package={apk_static_result.package_name[:40]}, "
            f"perms={len(apk_static_result.permissions)}, "
            f"self_signed={apk_static_result.is_self_signed}"
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[Phase 0.6] Lv 1 실패 (무시): {exc}")

    print("[Phase 0.6] APK 심화 정적 분석 (Lv 2 — bytecode 패턴)...")
    try:
        apk_bytecode_result = apk_analyzer.analyze_apk_bytecode(source)
        pipe.last_apk_bytecode_result = apk_bytecode_result
        print(
            f"      ← Lv 2: 검출 {len(apk_bytecode_result.detected_flags)}개"
            + (f" — flags={apk_bytecode_result.detected_flags}"
               if apk_bytecode_result.detected_flags else "")
        )
    except Exception as exc:  # noqa: BLE001
        print(f"[Phase 0.6] Lv 2 실패 (무시): {exc}")

    static_flags = set((apk_static_result.detected_flags if apk_static_result else []) or [])
    static_flags.update((apk_bytecode_result.detected_flags if apk_bytecode_result else []) or [])
    if static_flags:
        apk_dynamic_result = apk_analyzer.APKDynamicReport(
            status=apk_analyzer.APKDynamicStatus.SKIPPED_STATIC,
            error="Lv1/Lv2 정적 분석에서 이미 신호가 검출되어 remote VM 동적 분석 생략.",
        )
        pipe.last_apk_dynamic_result = apk_dynamic_result
        print(
            "[Phase 0.6] APK 동적 분석 생략 "
            f"(Lv 1/2 정적 신호 {len(static_flags)}개 검출 — VM 호출 불필요)"
        )
    else:
        print("[Phase 0.6] APK 동적 분석 (Lv 3 — 격리 VM 에뮬레이터)...")
        try:
            apk_dynamic_result = apk_analyzer.analyze_apk_dynamic(source)
            pipe.last_apk_dynamic_result = apk_dynamic_result
            status_val = apk_dynamic_result.status.value
            print(
                f"      ← Lv 3: status={status_val} "
                f"backend={apk_dynamic_result.backend or '-'} "
                f"flags={len(apk_dynamic_result.detected_flags)}"
                + (f" — {apk_dynamic_result.error[:60]}" if apk_dynamic_result.error else "")
            )
        except Exception as exc:  # noqa: BLE001
            print(f"[Phase 0.6] Lv 3 실패 (무시): {exc}")

    pipe._log_step(
        "APK",
        phase06_start,
        {
            "lv1_flags": len((apk_static_result.detected_flags if apk_static_result else []) or []),
            "lv2_flags": len((apk_bytecode_result.detected_flags if apk_bytecode_result else []) or []),
            "lv3_status": apk_dynamic_result.status.value if apk_dynamic_result else "-",
            "lv3_flags": len((apk_dynamic_result.detected_flags if apk_dynamic_result else []) or []),
        },
    )
    return apk_input, apk_static_result, apk_bytecode_result, apk_dynamic_result


def resolve_transcript_phase(
    pipe: ScamGuardianPipeline,
    source: str,
    precomputed_transcript: stt.TranscriptResult | None,
    apk_input: bool,
    apk_static_result: apk_analyzer.APKStaticReport | None,
    apk_bytecode_result: apk_analyzer.APKBytecodeReport | None,
    pipeline_start: float,
) -> stt.TranscriptResult:
    """Resolve Phase 1 transcript, including APK synthetic transcript handling."""
    if precomputed_transcript is not None:
        print("[Phase 1] STT 스킵 (precomputed_transcript 사용)")
        transcript = precomputed_transcript
        pipe.last_transcript_result = transcript
        pipe._log_step(
            "STT",
            pipeline_start,
            {"source_type": transcript.source_type, "text_length": len(transcript.text), "precomputed": True},
        )
        return transcript

    if apk_input:
        pkg = apk_static_result.package_name if apk_static_result else ""
        apk_flags = list((apk_static_result.detected_flags if apk_static_result else []) or [])
        apk_flags += list((apk_bytecode_result.detected_flags if apk_bytecode_result else []) or [])
        synth = f"안드로이드 APK 분석 대상. 패키지명 {pkg or '알 수 없음'}."
        if apk_flags:
            synth += " 정적 분석 검출 신호: " + ", ".join(apk_flags) + "."
        print("[Phase 1] STT 스킵 (APK 입력 — 정적 분석 요약을 분석 텍스트로 사용)")
        transcript = stt.TranscriptResult(text=synth, source_type="apk")
        pipe.last_transcript_result = transcript
        pipe._log_step(
            "STT", pipeline_start,
            {"source_type": "apk", "text_length": len(synth), "apk": True},
        )
        return transcript

    print("[Phase 1] STT 처리 중...")
    print(f"      → 입력: {source[:80]}{'…' if len(source) > 80 else ''}")
    return pipe.transcribe(source)
