#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/.scamguardian/logs"
OLLAMA_MODELS_DIR="$ROOT_DIR/.scamguardian/ollama_models"
mkdir -p "$LOG_DIR"
mkdir -p "$OLLAMA_MODELS_DIR"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3100}"
OLLAMA_HOST="${OLLAMA_HOST:-127.0.0.1}"
OLLAMA_PORT="${OLLAMA_PORT:-11434}"
ENABLE_FUNNEL="${ENABLE_FUNNEL:-true}"
CONDA_ENV="${CONDA_ENV:-capstone}"

echo "[restart] root=$ROOT_DIR"
echo "[restart] logs=$LOG_DIR"

kill_port() {
  local port="$1"
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${port}/tcp" >/dev/null 2>&1 || true
  fi
}

kill_matches() {
  local pattern="$1"
  pkill -f "$pattern" >/dev/null 2>&1 || true
}

echo "[restart] stopping processes..."
kill_matches "uvicorn api_server:app"
kill_matches "next dev .*--port ${FRONTEND_PORT}"
kill_matches "next-server"
kill_matches "ollama serve"
kill_port "$BACKEND_PORT"
kill_port "$FRONTEND_PORT"
kill_port "$OLLAMA_PORT"

sleep 0.5

echo "[restart] starting Ollama..."
# NOTE: 환경에 따라 기본 ~/.ollama/models 권한 문제가 생길 수 있어서
# workspace 내부 경로로 모델 디렉토리를 고정한다.
OLLAMA_MODELS="$OLLAMA_MODELS_DIR" nohup ollama serve >"$LOG_DIR/ollama.log" 2>&1 &
sleep 0.5

echo "[restart] starting backend (uvicorn :$BACKEND_PORT) in conda env '$CONDA_ENV'..."
cd "$ROOT_DIR"
PYTHONUNBUFFERED=1 nohup conda run --no-capture-output -n "$CONDA_ENV" python -u -m uvicorn api_server:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload --log-level info \
  >"$LOG_DIR/backend.log" 2>&1 &

echo "[restart] starting frontend (next dev :$FRONTEND_PORT)..."
cd "$ROOT_DIR/apps/web"
SCAMGUARDIAN_API_URL="http://127.0.0.1:${BACKEND_PORT}" \
nohup npm run dev -- --hostname 0.0.0.0 --port "$FRONTEND_PORT" \
  >"$LOG_DIR/frontend.log" 2>&1 &

if [[ "$ENABLE_FUNNEL" == "true" ]] && command -v tailscale >/dev/null 2>&1; then
  echo "[restart] enabling tailscale funnel (backend:$BACKEND_PORT, frontend:$FRONTEND_PORT)..."
  # funnel은 실패해도 스택 구동을 막지 않는다.
  nohup tailscale funnel --bg "$BACKEND_PORT" >/dev/null 2>&1 || true
  nohup tailscale funnel --bg "$FRONTEND_PORT" >/dev/null 2>&1 || true
  tailscale funnel status 2>/dev/null || true
fi

echo "[restart] done."
echo "[restart] tail logs:"
echo "  tail -f \"$LOG_DIR/ollama.log\""
echo "  tail -f \"$LOG_DIR/backend.log\""
echo "  tail -f \"$LOG_DIR/frontend.log\""

