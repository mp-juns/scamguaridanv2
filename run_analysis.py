#!/usr/bin/env python3
"""
ScamGuardian v2 — CLI 진입점
YouTube URL, 로컬 파일, 또는 텍스트를 분석한다.

사용법:
    python run_analysis.py "https://youtube.com/watch?v=..."
    python run_analysis.py ./suspicious_video.mp4
    python run_analysis.py --text "일론 머스크가 화성 이민 프로젝트에..."
    python run_analysis.py --text "..." --skip-verify    # 검증 단계 생략
    python run_analysis.py --text "..." --json           # JSON 출력
    python run_analysis.py --text "..." --use-llm        # LLM 보조 검출 추가
    python run_analysis.py --text "..." --use-llm --use-rag  # 사람 라벨 사례도 참고
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv

load_dotenv()

from pipeline.runner import ScamGuardianPipeline


def main():
    parser = argparse.ArgumentParser(
        description="ScamGuardian v2 — 스캠 탐지 파이프라인",
    )
    parser.add_argument(
        "source",
        nargs="?",
        help="YouTube URL 또는 로컬 파일 경로",
    )
    parser.add_argument(
        "--text", "-t",
        help="직접 텍스트를 입력 (STT 생략)",
    )
    parser.add_argument(
        "--whisper-model", "-w",
        default="medium",
        choices=["tiny", "base", "small", "medium", "large"],
        help="Whisper 모델 크기 (기본값: medium)",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Serper API 교차 검증 단계를 건너뜀",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="결과를 JSON 형식으로 출력",
    )
    parser.add_argument(
        "--use-llm",
        action="store_true",
        help="LLM 보조 검출을 추가 수행",
    )
    parser.add_argument(
        "--use-rag",
        action="store_true",
        help="DB의 사람 라벨 사례를 RAG로 검색해 LLM 보조 판정에 참고",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="전체 디버그 로그 출력",
    )

    args = parser.parse_args()

    source = args.text or args.source
    if not source:
        parser.print_help()
        sys.exit(1)

    pipe = ScamGuardianPipeline(
        whisper_model=args.whisper_model,
        debug=args.debug,
    )
    report = pipe.analyze(
        source,
        skip_verification=args.skip_verify,
        use_llm=args.use_llm,
        use_rag=args.use_rag,
    )

    if args.json_output:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(report.summary())

    pipe.print_step_log()


if __name__ == "__main__":
    main()
