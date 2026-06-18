#!/usr/bin/env python3
"""
ScamGuardian v2 — 배치 인제스트 스크립트

텍스트 샘플 목록을 분석하여 DB에 run을 쌓는다.
라벨링할 데이터가 없을 때 시드 데이터를 생성하는 용도.

사용법:
    python scripts/batch_ingest.py                        # 내장 샘플 전체
    python scripts/batch_ingest.py --file samples.txt    # 텍스트 파일 (줄마다 1개)
    python scripts/batch_ingest.py --jsonl samples.jsonl # JSONL 파일
    python scripts/batch_ingest.py --skip-verify         # Serper 검증 생략 (빠름)
    python scripts/batch_ingest.py --dry-run             # DB 저장 없이 결과만 출력
    python scripts/batch_ingest.py --workers 6           # 병렬 처리 워커 수 지정
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv()

# fmt: off
SEED_SAMPLES = [
    # ── 투자 사기 ──────────────────────────────────────────────────────────
    "안녕하세요. 저는 KB증권 VIP 고객 담당 팀장 박정훈입니다. 저희가 내부적으로 검토한 종목인데요, 단기간에 연 40% 이상 수익이 가능하고 원금 보장까지 됩니다. 지금 바로 500만 원 이상 입금하시면 특별 우대 혜택을 드립니다.",
    "지금 비트코인 다음으로 뜨는 코인이에요. 일론 머스크도 투자했고 이번 달 안에 10배는 기본입니다. 지금 들어오시면 사전 물량 받으실 수 있어요. 코인 지갑 주소 알려드릴게요.",
    "저희 투자 리딩방에 가입하시면 매달 월 8% 수익 보장해드립니다. 이미 3천 명 회원이 수익 인증하고 있어요. 오늘 딱 10명만 더 받아요. 카카오페이로 보내주시면 돼요.",
    "안녕하세요 삼성자산운용입니다. 저희 신규 펀드 출시 기념으로 초기 투자자 한정 연 25% 확정 수익 상품을 제공합니다. 오늘까지만 가입 가능하니 지금 바로 계좌번호 알려주세요.",

    # ── 보이스피싱 (기관사칭) ──────────────────────────────────────────────
    "저는 서울중앙지검 수사관 이민수입니다. 고객님 명의 계좌가 범죄에 사용되어 현재 수사 중입니다. 자산 보호를 위해 안전 계좌로 즉시 이체가 필요하며 이 내용은 절대 타인에게 누설하면 안 됩니다.",
    "금융감독원입니다. 고객님 개인정보가 유출되어 피해를 입으실 수 있습니다. 현재 보유하신 금융 자산을 저희 보호 계좌로 옮겨야 합니다. 지금 바로 통장 비밀번호와 공인인증서 번호를 알려주세요.",
    "경찰청 사이버수사대입니다. 고객님 명의로 개설된 대포통장이 발견되었습니다. 협조하지 않으시면 즉시 체포영장이 발부됩니다. 지금 당장 현금 인출하셔서 직원에게 전달해주세요.",

    # ── 대출 사기 ──────────────────────────────────────────────────────────
    "저금리 정부지원 대출 상품 안내드립니다. 신용등급 상관없이 연 2.9%로 5천만 원까지 가능합니다. 단 선납 보험료 30만 원 먼저 입금 주셔야 대출 진행됩니다.",
    "안녕하세요. 서민금융진흥원 제휴 대출 상담사입니다. 현재 고객님 신용점수로 최대 1억까지 대출 가능한데요. 오늘 바로 처리해드릴 수 있어요. 계좌번호랑 주민번호 뒷자리 알려주세요.",
    "지금 급하게 돈 필요하신 분 계세요? 저희는 무담보 무보증으로 당일 입금 가능합니다. 단 먼저 공증 비용 20만 원 보내주셔야 해요. 카카오뱅크 계좌로 보내시면 바로 처리해드릴게요.",

    # ── 취업/알바 사기 ──────────────────────────────────────────────────────
    "재택 부업 알바 구하세요? 하루 2시간 스마트폰으로 하는 일인데 일당 15만 원 드립니다. 단 시작 전에 교육 자료비 5만 원 먼저 내셔야 해요. 입금 확인되면 바로 카톡으로 알려드릴게요.",
    "해외 연수 포함 연봉 6천 신입 채용입니다. 서류 합격 축하드립니다. 건강검진 예약금 10만 원 먼저 보내주시면 일정 안내드리겠습니다. 불합격 시 전액 환불 보장합니다.",

    # ── 로맨스 스캠 ─────────────────────────────────────────────────────────
    "안녕하세요 저 미국에서 한국으로 파견된 UN 소속 의사예요. 한국 문화가 좋아서 한국 분이랑 친해지고 싶어요. 저 지금 좀 급하게 돈이 필요한데 도와주실 수 있어요? 다음 달에 귀국하면 꼭 갚을게요.",
    "저 캐나다 미군 장교인데요. 한국 여성분과 진지한 만남 원해요. 지금 임무 중이라 통장 접근이 안 돼서요, 비행기 티켓 값 200만 원만 먼저 보내주시면 바로 귀국할게요. 사랑해요.",

    # ── 메신저 피싱 ─────────────────────────────────────────────────────────
    "엄마 나 핸드폰 고장나서 친구 폰으로 카톡하는 거야. 급하게 돈 50만 원 필요한데 이 계좌로 보내줄 수 있어? 나중에 꼭 갚을게. 빨리 부탁해.",
    "안녕하세요 저 민준 친구 수현인데요. 민준이가 지갑을 잃어버려서 제 카카오페이로 30만 원만 빌려달라고 해서요. 계좌 알려드릴게요.",

    # ── 납치·협박형 ──────────────────────────────────────────────────────────
    "당신 아들 우리가 데리고 있어요. 경찰에 신고하면 죽여버릴 거예요. 지금 당장 현금 500만 원 준비해서 혼자 나오세요. 30분 안에 연락 없으면 어떻게 될지 몰라요.",

    # ── 스미싱 ──────────────────────────────────────────────────────────────
    "[CJ대한통운] 고객님 택배가 주소 불명으로 반송될 예정입니다. 아래 링크에서 주소를 재입력해주세요. http://cj-track.xyz/confirm",
    "[국민은행] 고객님 계좌에서 이상 거래가 감지되었습니다. 본인 확인을 위해 아래 링크를 클릭하여 인증해주세요. http://kbstar-secure.net",

    # ── 중고거래 사기 ────────────────────────────────────────────────────────
    "아이폰 15 프로 미개봉 새상품 80만 원에 팔아요. 당근마켓 수수료 아끼려고 직거래 원해요. 먼저 입금해주시면 바로 택배 보내드릴게요. 운송장 번호 알려드릴게요.",

    # ── 정상 (비사기) ───────────────────────────────────────────────────────
    "오늘 점심 뭐 먹을까요? 삼겹살이 땡기는데 같이 가실 분 계세요?",
    "내일 팀 회의 10시에 있습니다. 3분기 실적 자료 미리 검토해 오시기 바랍니다.",
    "안녕하세요. 국민은행 고객센터입니다. 보안 강화로 인해 OTP 앱 업데이트가 필요합니다. 은행 공식 앱스토어에서 업데이트 해주세요.",
]
# fmt: on


def _default_metadata(metadata: object) -> dict[str, Any]:
    if isinstance(metadata, dict):
        return metadata
    return {"source": "batch_ingest"}


def _detected_signals(report_dict: dict[str, Any]) -> list[dict[str, Any]]:
    signals = report_dict.get("detected_signals")
    if isinstance(signals, list):
        return [s for s in signals if isinstance(s, dict)]
    legacy_flags = report_dict.get("triggered_flags")
    if isinstance(legacy_flags, list):
        return [f for f in legacy_flags if isinstance(f, dict)]
    return []


def _signal_count(report_dict: dict[str, Any]) -> int:
    return len(_detected_signals(report_dict))


def _print_detection_result(report_dict: dict[str, Any], run_id: str | None) -> None:
    signal_count = _signal_count(report_dict)
    suffix = f" | run_id={run_id}" if run_id else " | [dry-run, not saved]"
    print(f"  → {report_dict['scam_type']} | 검출 신호 {signal_count}개{suffix}")


torch.set_default_dtype(torch.float32)
def _analyze_one(
    idx: int,
    total: int,
    sample: dict[str, object],
    skip_verify: bool,
) -> dict[str, Any]:
    from pipeline.runner import ScamGuardianPipeline

    text = str(sample.get("text", "")).strip()
    metadata = _default_metadata(sample.get("metadata"))

    if not text:
        return {
            "idx": idx,
            "total": total,
            "ok": False,
            "error": "비어있는 샘플이라 건너뜁니다.",
            "text": "",
            "metadata": metadata,
        }

    pipe = ScamGuardianPipeline(whisper_model="medium")
    report = pipe.analyze(
        text,
        skip_verification=skip_verify,
        use_llm=False,
        use_rag=False,
    )
    d = report.to_dict()

    transcript_text = (
        pipe.last_transcript_result.text
        if pipe.last_transcript_result is not None
        else text
    )

    return {
        "idx": idx,
        "total": total,
        "ok": True,
        "text": text,
        "metadata": metadata,
        "report": d,
        "transcript_text": transcript_text,
    }


def run_batch(
    samples: list[dict[str, object]],
    skip_verify: bool,
    dry_run: bool,
    delay: float,
    workers: int,
) -> None:
    if dry_run:
        os.environ["SCAMGUARDIAN_PERSIST_RUNS"] = "false"
    else:
        os.environ["SCAMGUARDIAN_PERSIST_RUNS"] = "true"

    from db import repository

    if not dry_run:
        repository.init_db()

    total = len(samples)
    ok = 0
    failed = 0
    started_at = time.perf_counter()

    if workers <= 1:
        for i, sample in enumerate(samples, 1):
            text = str(sample.get("text", "")).strip()
            preview = text[:60].replace("\n", " ") if text else "(empty)"
            print(f"[{i}/{total}] {preview}...")

            try:
                result = _analyze_one(i, total, sample, skip_verify=skip_verify)
                if not result["ok"]:
                    print(f"  ✗ {result['error']}")
                    failed += 1
                    continue

                d = result["report"]
                run_id = None

                if not dry_run:
                    run_id = repository.save_analysis_run(
                        input_source=result["text"][:200],
                        whisper_model="medium",
                        skip_verification=skip_verify,
                        use_llm=False,
                        use_rag=False,
                        transcript_text=result["transcript_text"],
                        classification_scanner={
                            "scam_type": d["scam_type"],
                            "confidence": d["classification_confidence"],
                            "is_uncertain": d["is_uncertain"],
                        },
                        entities_predicted=d["entities"],
                        verification_results=d.get("all_verifications", []),
                        triggered_flags_predicted=_detected_signals(d),
                        total_score_predicted=_signal_count(d),
                        risk_level_predicted="",
                        llm_assessment=d.get("llm_assessment"),
                        metadata=result["metadata"],
                    )

                _print_detection_result(d, run_id)
                ok += 1
            except Exception as exc:
                print(f"  ✗ 오류: {exc}")
                failed += 1

            if i < total and delay > 0:
                time.sleep(delay)
    else:
        print(f"병렬 처리 시작: workers={workers}")

        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_map = {
                executor.submit(_analyze_one, i, total, sample, skip_verify): (i, sample)
                for i, sample in enumerate(samples, 1)
            }

            for future in as_completed(future_map):
                i, sample = future_map[future]
                text = str(sample.get("text", "")).strip()
                preview = text[:60].replace("\n", " ") if text else "(empty)"
                print(f"[{i}/{total}] {preview}...")

                try:
                    result = future.result()
                    if not result["ok"]:
                        print(f"  ✗ {result['error']}")
                        failed += 1
                        continue

                    d = result["report"]
                    run_id = None

                    if not dry_run:
                        run_id = repository.save_analysis_run(
                            input_source=result["text"][:200],
                            whisper_model="medium",
                            skip_verification=skip_verify,
                            use_llm=False,
                            use_rag=False,
                            transcript_text=result["transcript_text"],
                            classification_scanner={
                                "scam_type": d["scam_type"],
                                "confidence": d["classification_confidence"],
                                "is_uncertain": d["is_uncertain"],
                            },
                            entities_predicted=d["entities"],
                            verification_results=d.get("all_verifications", []),
                            triggered_flags_predicted=_detected_signals(d),
                            total_score_predicted=_signal_count(d),
                            risk_level_predicted="",
                            llm_assessment=d.get("llm_assessment"),
                            metadata=result["metadata"],
                        )

                    _print_detection_result(d, run_id)
                    ok += 1
                except Exception as exc:
                    print(f"  ✗ 오류: {exc}")
                    failed += 1

    elapsed = time.perf_counter() - started_at
    print(f"\n완료: {ok}개 성공, {failed}개 실패 (전체 {total}개, {elapsed:.2f}초)")


def _normalize_text_samples(lines: list[str]) -> list[dict[str, object]]:
    return [{"text": line, "metadata": {"source": "batch_ingest"}} for line in lines]


def _load_jsonl_samples(path: Path) -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for lineno, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSONL 파싱 실패: {path}:{lineno}: {exc}") from exc

        if isinstance(item, str):
            samples.append({"text": item, "metadata": {"source": "batch_ingest"}})
            continue
        if not isinstance(item, dict):
            raise ValueError(f"JSONL 각 줄은 객체 또는 문자열이어야 합니다: {path}:{lineno}")

        text = str(item.get("text", "")).strip()
        if not text:
            raise ValueError(f"text 필드가 비어 있습니다: {path}:{lineno}")

        metadata = item.get("metadata")
        if metadata is None:
            metadata = {"source": "batch_ingest"}
        elif not isinstance(metadata, dict):
            raise ValueError(f"metadata 필드는 객체여야 합니다: {path}:{lineno}")

        samples.append({"text": text, "metadata": metadata})

    return samples


def main() -> None:
    parser = argparse.ArgumentParser(description="ScamGuardian 배치 인제스트")
    parser.add_argument(
        "--file", "-f",
        help="분석할 텍스트 파일 경로 (줄마다 1개 샘플, # 주석 지원)",
    )
    parser.add_argument(
        "--jsonl",
        help="분석할 JSONL 파일 경로 (text/metadata 포함 JSONL 형식)",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Serper API 검증 단계 생략 (빠름)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="DB에 저장하지 않고 결과만 출력",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.5,
        help="샘플 간 대기 시간(초), workers=1일 때만 사실상 의미 있음",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=min(6, max(1, (os.cpu_count() or 4))),
        help="병렬 처리 워커 수 (기본값: min(6, CPU 코어 수))",
    )
    args = parser.parse_args()

    cpu_only = not torch.cuda.is_available()
    if cpu_only and args.workers > 1:
        print("[WARN] CPU 환경에서는 PyTorch/Whisper 스레드 병렬 처리 충돌이 날 수 있어 workers=1로 강제합니다.")
        args.workers = 1

    if args.file and args.jsonl:
        print("--file 과 --jsonl 은 동시에 사용할 수 없습니다.", file=sys.stderr)
        sys.exit(1)

    if args.workers < 1:
        print("--workers 는 1 이상이어야 합니다.", file=sys.stderr)
        sys.exit(1)

    if args.jsonl:
        path = Path(args.jsonl)
        if not path.exists():
            print(f"파일을 찾을 수 없습니다: {path}", file=sys.stderr)
            sys.exit(1)
        try:
            samples = _load_jsonl_samples(path)
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            sys.exit(1)
    elif args.file:
        path = Path(args.file)
        if not path.exists():
            print(f"파일을 찾을 수 없습니다: {path}", file=sys.stderr)
            sys.exit(1)
        samples = _normalize_text_samples([
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ])
    else:
        samples = _normalize_text_samples(SEED_SAMPLES)

    print(
        f"총 {len(samples)}개 샘플 "
        f"{'(dry-run)' if args.dry_run else 'DB 저장'} 분석 시작 "
        f"(workers={args.workers})\n"
    )

    run_batch(
        samples,
        skip_verify=args.skip_verify,
        dry_run=args.dry_run,
        delay=args.delay,
        workers=args.workers,
    )


if __name__ == "__main__":
    main()
