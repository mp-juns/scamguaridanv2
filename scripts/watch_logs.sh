#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/.scamguardian/logs"

if [[ ! -d "$LOG_DIR" ]]; then
  echo "[logs] log dir not found: $LOG_DIR"
  echo "[logs] 먼저 ./scripts/start_stack.sh 를 실행하세요."
  exit 1
fi

echo "[logs] watching logs in: $LOG_DIR"
echo "[logs] stop: Ctrl+C"
echo

tail -n 200 -F \
  "$LOG_DIR/backend.log" \
  "$LOG_DIR/frontend.log"
