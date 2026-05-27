#!/usr/bin/env bash
# AI Hub dataset 71768 (119 신고 / 협박·위급) 부분 다운로드.
# 데이터는 data/aihub/71768/ 아래 받음.
#
# 필수:
#   - AIHUB_API_KEY 환경변수
#   - ./data/aihubshell 실행 권한 (이미 +x)
#
# 사용:
#   AIHUB_API_KEY=xxxx ./aihub_download.sh
#   AIHUB_API_KEY=xxxx ./aihub_download.sh --dry-run

set -euo pipefail

DATASET_KEY="71768"
FILE_KEYS="539615,539616,539617,539679,539680,539681"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SHELL_BIN="${AIHUB_SHELL:-${SCRIPT_DIR}/data/aihubshell}"
OUT_DIR="${SCRIPT_DIR}/data/aihub/${DATASET_KEY}"

if [[ -z "${AIHUB_API_KEY:-}" ]]; then
  echo "[error] AIHUB_API_KEY 환경변수가 비어 있습니다." >&2
  echo "  export AIHUB_API_KEY=..." >&2
  exit 1
fi

if [[ ! -x "${SHELL_BIN}" ]]; then
  echo "[error] aihubshell 을 찾을 수 없거나 실행 권한 없음: ${SHELL_BIN}" >&2
  echo "  ls -l ${SHELL_BIN}" >&2
  exit 1
fi

mkdir -p "${OUT_DIR}"

echo "[plan] dataset=${DATASET_KEY} filekeys=${FILE_KEYS}"
echo "[plan] 출력 경로: ${OUT_DIR}"

if [[ "${1:-}" == "--dry-run" ]]; then
  echo "[dry-run] 실제 다운로드 안 함"
  exit 0
fi

cd "${OUT_DIR}"
echo "[run] $(date '+%F %T') 다운로드 시작 (cwd=${OUT_DIR})"

"${SHELL_BIN}" \
  -aihubapikey "${AIHUB_API_KEY}" \
  -mode d \
  -datasetkey "${DATASET_KEY}" \
  -filekey "${FILE_KEYS}"

echo "[done] $(date '+%F %T') 다운로드 완료"
echo "[hint] 받은 파일 확인: ls -la ${OUT_DIR}"
