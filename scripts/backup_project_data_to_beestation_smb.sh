#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MOUNT_POINT="${MOUNT_POINT:-/mnt/beestation}"
BACKUP_SUBDIR="${BACKUP_SUBDIR:-A-EYE/ScamGuardianBackups}"
STAMP="$(date +%Y%m%d_%H%M%S)"

if [[ -z "${BEE_SMB_URL:-}" || -z "${BEE_SMB_USER:-}" || -z "${BEE_SMB_PASS:-}" ]]; then
  cat >&2 <<'EOF'
Missing SMB settings.

Example:
  BEE_SMB_URL='//192.168.0.10/home' \
  BEE_SMB_USER='local-account' \
  BEE_SMB_PASS='local-password' \
  ./scripts/backup_project_data_to_beestation_smb.sh

BeeStation setup:
  System Settings > Advanced Settings > Local Access
  Enable Local Account and SMB Service.
EOF
  exit 2
fi

if ! command -v mount.cifs >/dev/null 2>&1; then
  cat >&2 <<'EOF'
mount.cifs is not installed in WSL.

Install once:
  sudo apt update
  sudo apt install -y cifs-utils
EOF
  exit 2
fi

sudo mkdir -p "${MOUNT_POINT}"

CREDS_FILE="$(mktemp)"
cleanup() {
  rm -f "${CREDS_FILE}"
}
trap cleanup EXIT

{
  printf 'username=%s\n' "${BEE_SMB_USER}"
  printf 'password=%s\n' "${BEE_SMB_PASS}"
} > "${CREDS_FILE}"
chmod 600 "${CREDS_FILE}"

MOUNTED_BY_SCRIPT=0
if ! mountpoint -q "${MOUNT_POINT}"; then
  sudo mount -t cifs "${BEE_SMB_URL}" "${MOUNT_POINT}" \
    -o "credentials=${CREDS_FILE},vers=3.0,uid=$(id -u),gid=$(id -g),iocharset=utf8,file_mode=0660,dir_mode=0770"
  MOUNTED_BY_SCRIPT=1
fi

DEST="${MOUNT_POINT}/${BACKUP_SUBDIR}/project-data-${STAMP}"
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

sync
printf 'SMB backup written to %s\n' "${DEST}"

if [[ "${MOUNTED_BY_SCRIPT}" == "1" && "${KEEP_MOUNTED:-0}" != "1" ]]; then
  sudo umount "${MOUNT_POINT}"
fi
