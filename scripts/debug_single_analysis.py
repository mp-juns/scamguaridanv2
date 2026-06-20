"""단일 텍스트에 대해 Gate / 2차 분류기 / 신호 검출 결과를 콘솔에 출력하는 디버그 스크립트.

사용 예:
  # 텍스트 직접 입력
  python scripts/debug_single_analysis.py --text "고객님 계정이 제한됩니다. 본인인증 링크 클릭"

  # 파일에서 읽기
  python scripts/debug_single_analysis.py --file /tmp/sms.txt

  # stdin (파이프)
  echo "의심 문자 내용" | python scripts/debug_single_analysis.py

  # Gate + 2차 분류만 (신호 검출 skip → 빠름, API 키 불필요)
  python scripts/debug_single_analysis.py --text "..." --gate-only

  # 전체 파이프라인 실행 (Serper·LLM 포함)
  python scripts/debug_single_analysis.py --text "..." --full-pipeline

출력 항목:
  - Gate bucket / confidence / source / reason
  - 2차 scam_type / confidence / is_uncertain
  - 2차 all_scores (상위 5개)
  - detected_signals 목록 (--gate-only 시 생략)

주의:
  - Gate 는 기본적으로 Claude Haiku 를 사용하므로 ANTHROPIC_API_KEY 가 필요합니다.
  - 2차 분류기는 로컬 mDeBERTa 모델 (API 키 불필요).
  - --full-pipeline 은 Serper·LLM 단계까지 실행합니다 (시간·비용 증가).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()


# ────────────────────────────────────────────────
# 출력 헬퍼
# ────────────────────────────────────────────────

def _bar(width: int = 68) -> str:
    return "─" * width


def _header(title: str, width: int = 68) -> str:
    pad = max(0, width - len(title) - 4)
    return f"┌── {title} {'─' * pad}┐"


def _section(title: str) -> None:
    print(f"\n  ┌── {title}")


def _kv(key: str, value: object, indent: int = 4) -> None:
    sp = " " * indent
    print(f"{sp}{key:<28}: {value}")


# ────────────────────────────────────────────────
# Gate 디버그
# ────────────────────────────────────────────────

def run_gate(text: str) -> object:
    from pipeline.gate import classify_gate

    print("\n" + "=" * 68)
    print("  [Stage 1] Gate 분류기")
    print("=" * 68)

    result = classify_gate(text)

    _kv("bucket (영문)", result.bucket)
    _kv("label_ko (한국어)", result.label_ko)
    _kv("confidence", f"{result.confidence:.4f}  ({result.confidence:.1%})")
    _kv("source", result.source)
    _kv("reason", result.reason or "(없음)")
    _kv("model", result.model or "(heuristic)")

    return result


# ────────────────────────────────────────────────
# 2차 분류기 디버그
# ────────────────────────────────────────────────

def run_classifier(text: str) -> object:
    from pipeline.classifier import classify

    print("\n" + "=" * 68)
    print("  [Stage 2] 사기 유형 분류기 (mDeBERTa zero-shot / fine-tuned)")
    print("=" * 68)

    result = classify(text)

    _kv("scam_type", result.scam_type or "(없음)")
    _kv("confidence (정규화 점수)", f"{result.confidence:.4f}  ({result.confidence:.1%})")
    _kv("is_uncertain", str(result.is_uncertain))

    if result.all_scores:
        ranked = sorted(result.all_scores.items(), key=lambda x: x[1], reverse=True)
        print()
        print("    all_scores (상위 5개):")
        for i, (label, score) in enumerate(ranked[:5], 1):
            bar_len = int(score * 30)
            bar = "█" * bar_len + "░" * (30 - bar_len)
            marker = " ◀ top" if i == 1 else ""
            print(f"      {i}. {label:<16} {score:6.4f}  [{bar}]{marker}")
        if len(ranked) > 5:
            print(f"      ... 나머지 {len(ranked) - 5}개 생략")

    return result


# ────────────────────────────────────────────────
# 신호 검출 디버그 (rule-based, 빠름)
# ────────────────────────────────────────────────

def run_signal_detection(text: str, gate_result: object, clf_result: object) -> object:
    from pipeline.signal_detector import detect
    from pipeline.extractor import extract

    print("\n" + "=" * 68)
    print("  [Stage 3] 신호 검출 (rule-based, Serper·LLM skip)")
    print("=" * 68)

    entities = extract(text, clf_result.scam_type)

    report = detect(
        verification_results=[],
        classification=clf_result,
        entities=entities,
        transcript=text,
        llm_assessment=None,
        safety_result=None,
        sandbox_result=None,
        apk_static_result=None,
        apk_bytecode_result=None,
        apk_dynamic_result=None,
    )

    signals = report.detected_signals
    print(f"\n    검출된 신호 수: {len(signals)}개")

    if signals:
        print()
        for i, sig in enumerate(signals, 1):
            print(f"    [{i}] {sig.flag}")
            print(f"         한국어 라벨  : {sig.label_ko}")
            print(f"         검출 출처    : {sig.detection_source}")
            print(f"         근거        : {sig.rationale[:80]}{'…' if len(sig.rationale) > 80 else ''}")
            if sig.evidence:
                ev_preview = sig.evidence[:2]
                print(f"         evidence    : {ev_preview}")
    else:
        print("    (검출된 신호 없음)")

    print(f"\n    summary     : {report.summary}")
    print(f"    disclaimer  : {report.disclaimer[:60]}…")

    return report


# ────────────────────────────────────────────────
# 전체 파이프라인 디버그
# ────────────────────────────────────────────────

def run_full_pipeline(text: str) -> None:
    from pipeline.runner import ScamGuardianPipeline

    print("\n" + "=" * 68)
    print("  [Full Pipeline] Serper·LLM 포함 전체 실행")
    print("=" * 68)
    print("  (시간이 걸릴 수 있습니다...)\n")

    pipeline = ScamGuardianPipeline()
    report = pipeline.analyze(
        text,
        skip_verification=False,
        use_llm=True,
        use_rag=False,
    )

    # Gate 결과 (runner 인스턴스에 저장됨)
    gate = pipeline.last_gate_result
    if gate:
        print("\n  [Gate]")
        _kv("bucket", gate.bucket)
        _kv("confidence", f"{gate.confidence:.4f}  ({gate.confidence:.1%})")
        _kv("source", gate.source)
        _kv("reason", gate.reason or "(없음)")

    print("\n  [DetectionReport]")
    d = report.to_dict()
    _kv("scam_type", d.get("scam_type", ""))
    _kv("scam_category", d.get("scam_category", ""))
    _kv("summary", d.get("summary", ""))

    signals = d.get("detected_signals", [])
    print(f"\n    detected_signals ({len(signals)}개):")
    for i, sig in enumerate(signals, 1):
        print(f"      [{i}] {sig['flag']}  —  {sig['label_ko']}")
        print(f"           근거: {sig['rationale'][:70]}…")

    entities = d.get("entities", [])
    if entities:
        print(f"\n    entities ({len(entities)}개):")
        for e in entities[:10]:
            print(f"      {e.get('label',''):<18} {e.get('text','')}")


# ────────────────────────────────────────────────
# 요약 출력
# ────────────────────────────────────────────────

def print_summary(text: str, gate_result: object, clf_result: object,
                  signal_report: object | None) -> None:
    print("\n" + "=" * 68)
    print("  [교수님께 보여드릴 디버그 요약]")
    print("=" * 68)

    gate_ko = getattr(gate_result, "label_ko", gate_result.bucket)
    gate_conf = gate_result.confidence
    scam_type = clf_result.scam_type or "(없음)"
    clf_conf = clf_result.confidence
    uncertain = clf_result.is_uncertain
    n_signals = len(signal_report.detected_signals) if signal_report else "N/A"

    print(f"""
  입력 텍스트 ({len(text)}자):
  {text[:120].replace(chr(10), ' ')}{'…' if len(text) > 120 else ''}

  ▶ Gate 판정  : {gate_ko} ({gate_result.bucket})  |  신뢰도 {gate_conf:.1%}
  ▶ 사기 유형  : {scam_type}  |  분류 점수 {clf_conf:.1%}  |  uncertain={uncertain}
  ▶ 검출 신호  : {n_signals}개
""")
    print("=" * 68)


# ────────────────────────────────────────────────
# main
# ────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="단일 텍스트 Gate/분류기/신호검출 디버그",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--text", "-t", help="분석할 텍스트 (직접 입력)")
    group.add_argument("--file", "-f", help="텍스트 파일 경로 (UTF-8)")
    parser.add_argument(
        "--gate-only", action="store_true",
        help="Gate + 2차 분류만 실행 (신호 검출 skip, 빠름)",
    )
    parser.add_argument(
        "--full-pipeline", action="store_true",
        help="Serper·LLM 포함 전체 파이프라인 실행",
    )
    parser.add_argument(
        "--json-out", metavar="PATH",
        help="결과를 JSON 파일로도 저장",
    )
    args = parser.parse_args()

    # 텍스트 수집
    if args.text:
        text = args.text
    elif args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        text = sys.stdin.read()
    else:
        parser.print_help()
        print("\n[오류] --text 또는 --file 을 지정하거나 stdin 으로 텍스트를 전달하세요.", file=sys.stderr)
        return 1

    text = text.strip()
    if not text:
        print("[오류] 입력 텍스트가 비어 있습니다.", file=sys.stderr)
        return 1

    print(f"\n{'=' * 68}")
    print("  ScamGuardian — 단일 텍스트 디버그 분석")
    print(f"{'=' * 68}")
    print(f"  입력 길이: {len(text)}자")
    preview = text[:80].replace("\n", "↵ ")
    print(f"  미리보기: {preview}{'…' if len(text) > 80 else ''}")

    if args.full_pipeline:
        run_full_pipeline(text)
        return 0

    gate_result = run_gate(text)
    clf_result = run_classifier(text)
    signal_report = None

    if not args.gate_only:
        try:
            signal_report = run_signal_detection(text, gate_result, clf_result)
        except Exception as e:
            print(f"\n  [경고] 신호 검출 중 오류: {e}", file=sys.stderr)

    print_summary(text, gate_result, clf_result, signal_report)

    if args.json_out:
        out: dict = {
            "text_length": len(text),
            "gate": gate_result.to_dict(),
            "classifier": {
                "scam_type": clf_result.scam_type,
                "confidence": round(clf_result.confidence, 6),
                "is_uncertain": clf_result.is_uncertain,
                "all_scores": {k: round(v, 6) for k, v in (clf_result.all_scores or {}).items()},
            },
        }
        if signal_report is not None:
            out["detected_signals"] = [s.to_dict() for s in signal_report.detected_signals]
            out["summary"] = signal_report.summary

        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  JSON 저장: {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
