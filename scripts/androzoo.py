"""
AndroZoo CLI — 실제 안드로이드 악성/정상 APK 샘플을 받아 ScamGuardian 검출 파이프라인 검증용.

핵심 다운로드/스트리밍 로직은 `api_server_pkg/androzoo_client.py` 에 있고 (웹 벤치마크 엔드포인트와
공유), 본 파일은 thin CLI 다.

⚠️ 받은 APK 는 실제 멀웨어일 수 있다 — 정적 분석(읽기만) + 격리 VM 동적 분석만, 호스트 실행 절대 X.

사용법:
    export ANDROZOO_API_KEY="..."                      # 사이트 발급 개인 키 (institutional email)

    # 알려진 해시로 다운로드
    python scripts/androzoo.py download <sha256> [--out data/androzoo]

    # 악성 샘플 N개 자동 수집 (vt_detection >= 임계)
    python scripts/androzoo.py sample --count 5 --min-vt 10 --out data/androzoo/malware
    python scripts/androzoo.py sample --count 5 --min-vt 10 --pkg-grep bank,kakao,gov

    # 받은 샘플을 파이프라인에 태워 검출 신호 확인
    python run_analysis.py data/androzoo/malware/<sha256>.apk

문서: https://androzoo.uni.lu/api_doc  /  인용: Allix et al. (2016) AndroZoo (MSR).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from api_server_pkg import androzoo_client as az

_DEFAULT_OUT = Path("data") / "androzoo"


def _download_many(shas: list[str], out_dir: Path) -> int:
    ok = 0
    for sha in shas:
        try:
            target = az.download_apk(sha, out_dir)
            print(f"  [ok] {target}  ({target.stat().st_size:,} bytes)")
            ok += 1
        except az.AndroZooError as exc:
            print(f"  [error] {sha[:16]}… — {exc}", file=sys.stderr)
    return ok


def cmd_download(args: argparse.Namespace) -> None:
    ok = _download_many(args.sha256, Path(args.out))
    print(f"\n다운로드 완료: {ok}/{len(args.sha256)}")


def cmd_download_file(args: argparse.Namespace) -> None:
    shas = [
        ln.strip() for ln in Path(args.file).read_text().splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    ok = _download_many(shas, Path(args.out))
    print(f"\n다운로드 완료: {ok}/{len(shas)}")


def cmd_sample(args: argparse.Namespace) -> None:
    pkg_filters = [p.strip() for p in (args.pkg_grep or "").split(",") if p.strip()]
    print(f"리스트 스트리밍 (min_vt={args.min_vt}, count={args.count}, pkg_grep={pkg_filters or '-'})…")
    picked = az.sample_malware(args.count, min_vt=args.min_vt, pkg_filters=pkg_filters)
    if not picked:
        sys.exit("조건에 맞는 악성 샘플을 찾지 못했습니다 (min_vt/pkg_grep 조정).")
    print(f"\n선택된 샘플 {len(picked)}개 (스캔 {picked[0]['scanned']:,}행):")
    for r in picked:
        print(f"  - {r['sha256'][:16]}… vt={r['vt_detection']} pkg={r['pkg_name']}")
    print("\n다운로드 시작…")
    ok = _download_many([r["sha256"] for r in picked], Path(args.out))
    print(f"\n악성 샘플 다운로드 완료: {ok}/{len(picked)} → {args.out}")
    print("검출 검증:  python run_analysis.py", Path(args.out) / f"{picked[0]['sha256']}.apk")


def main() -> None:
    parser = argparse.ArgumentParser(description="AndroZoo APK 다운로드 CLI (검출 파이프라인 검증용)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_dl = sub.add_parser("download", help="SHA256 로 APK 단건/다건 다운로드")
    p_dl.add_argument("sha256", nargs="+")
    p_dl.add_argument("--out", default=str(_DEFAULT_OUT))
    p_dl.set_defaults(func=cmd_download)

    p_df = sub.add_parser("download-file", help="해시 목록 파일에서 일괄 다운로드")
    p_df.add_argument("file")
    p_df.add_argument("--out", default=str(_DEFAULT_OUT))
    p_df.set_defaults(func=cmd_download_file)

    p_s = sub.add_parser("sample", help="메타데이터 스트리밍 → vt_detection 으로 악성 N개 자동 수집")
    p_s.add_argument("--count", type=int, default=5)
    p_s.add_argument("--min-vt", type=int, default=10)
    p_s.add_argument("--pkg-grep", default="")
    p_s.add_argument("--out", default=str(_DEFAULT_OUT / "malware"))
    p_s.set_defaults(func=cmd_sample)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
