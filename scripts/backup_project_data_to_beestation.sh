#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP_ROOT="${BACKUP_ROOT:-/mnt/c/Users/kimju/BeeStation/A-EYE/ScamGuardianBackups}"
STAMP="$(date +%Y%m%d_%H%M%S)"
DEST="${BACKUP_ROOT}/project-data-${STAMP}"

mkdir -p "${DEST}"
cd "${ROOT_DIR}"

tar -czf "${DEST}/scamguardian-critical-data-with-env.tgz" \
  .env \
  .scamguardian/scamguardian.sqlite3 \
  .scamguardian/scamguardian.db \
  .scamguardian/active_models.json \
  data/generated \
  data/processed \
  data/run_drafts.jsonl \
  data/run_drafts.reviewed.jsonl \
  tasks/todo.md \
  tasks/lessons.md \
  codex.md

if [[ "${FULL_TRAINING:-0}" == "1" ]]; then
  tar -czf "${DEST}/scamguardian-training-sessions.tgz" .scamguardian/training_sessions
fi

printf 'Backup written to %s\n' "${DEST}"
