#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LATEST_NODE="$(ls -1 "$HOME/.nvm/versions/node" 2>/dev/null | tail -n 1 || true)"
export PATH="$HOME/miniconda3/bin:$HOME/anaconda3/bin:$HOME/.nvm/versions/node/$LATEST_NODE/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
cd "$ROOT_DIR"
exec python3 scripts/sg_tui.py
