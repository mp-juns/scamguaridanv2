#!/usr/bin/env bash
export PATH="$HOME/miniconda3/bin:$HOME/anaconda3/bin:$HOME/.nvm/versions/node/$(ls -1 $HOME/.nvm/versions/node 2>/dev/null | tail -n 1)/bin:/usr/local/bin:/usr/bin:/bin:$PATH"

if [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
  source "$HOME/miniconda3/etc/profile.d/conda.sh"
elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
  source "$HOME/anaconda3/etc/profile.d/conda.sh"
fi

if [ -s "$HOME/.nvm/nvm.sh" ]; then
  source "$HOME/.nvm/nvm.sh"
fi
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/.scamguardian/logs"
OLLAMA_MODELS_DIR="$ROOT_DIR/.scamguardian/ollama_models"
mkdir -p "$LOG_DIR" "$OLLAMA_MODELS_DIR"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3100}"
OLLAMA_PORT="${OLLAMA_PORT:-11434}"

CONDA_ENV="${CONDA_ENV:-capstone}"
ENABLE_FUNNEL="${ENABLE_FUNNEL:-true}"
ENABLE_NGROK="${ENABLE_NGROK:-true}"
# Ollama: CLAUDE.md 명시 — Claude API 로 교체되어 더 이상 필수 아님.
# 켜고 싶으면 ENABLE_OLLAMA=true 로 호출.
ENABLE_OLLAMA="${ENABLE_OLLAMA:-false}"
NGROK_BIN="${NGROK_BIN:-$HOME/bin/ngrok}"
NGROK_DOMAIN="${NGROK_DOMAIN:-}"  # 예약 도메인 있으면 지정, 없으면 매번 랜덤
NGROK_API="http://127.0.0.1:4040/api/tunnels"

echo "[start] root=$ROOT_DIR"
echo "[start] logs=$LOG_DIR"

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

echo "[start] stopping previous processes..."
kill_matches "uvicorn api_server:app"
kill_matches "next dev"
kill_matches "next-server"
kill_matches "npm run dev"
kill_matches "ollama serve"
kill_matches "ngrok http"
kill_port "$BACKEND_PORT"
kill_port "$FRONTEND_PORT"
kill_port "$OLLAMA_PORT"
kill_port 4040

sleep 0.5

if [[ "$ENABLE_OLLAMA" == "true" ]]; then
  echo "[start] starting Ollama..."
  OLLAMA_MODELS="$OLLAMA_MODELS_DIR" nohup ollama serve >"$LOG_DIR/ollama.log" 2>&1 &
  sleep 0.5
else
  echo "[start] skipping Ollama (ENABLE_OLLAMA=false — Claude API 로 교체됨)"
fi

echo "[start] starting backend (uvicorn :$BACKEND_PORT) in conda env '$CONDA_ENV'..."
cd "$ROOT_DIR"
PYTHONUNBUFFERED=1 nohup conda run --no-capture-output -n "$CONDA_ENV" python -u -m uvicorn api_server:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload --log-level info \
  >"$LOG_DIR/backend.log" 2>&1 &
# backend 가 ML 모델 로딩하는 동안 동시 시작 부하 분산 — 메모리 spike 완화.
sleep 3

echo "[start] starting frontend (next dev :$FRONTEND_PORT)..."

setsid bash -lic "
  cd '$ROOT_DIR/apps/web' || exit 1
  export SCAMGUARDIAN_API_URL='http://127.0.0.1:${BACKEND_PORT}'
  export LANG=C.UTF-8
  export LC_ALL=C.UTF-8

  if [ -s \"\$HOME/.nvm/nvm.sh\" ]; then
    source \"\$HOME/.nvm/nvm.sh\"
  fi

  npm run dev -- --hostname 0.0.0.0 --port '$FRONTEND_PORT'
" >"$LOG_DIR/frontend.log" 2>&1 < /dev/null &

if [[ "$ENABLE_FUNNEL" == "true" ]] && command -v tailscale >/dev/null 2>&1; then
  echo "[start] enabling tailscale funnel (frontend:$FRONTEND_PORT)..."
  tailscale funnel --bg "http://127.0.0.1:${FRONTEND_PORT}" || true
  tailscale funnel status 2>/dev/null || true
fi
# 카카오 오픈빌더는 .ts.net 도메인을 거부하므로 ngrok 으로 보조 터널 제공
NGROK_PUBLIC_URL=""
if [[ "$ENABLE_NGROK" == "true" ]] && [[ -x "$NGROK_BIN" ]]; then
  echo "[start] starting ngrok tunnel (frontend:$FRONTEND_PORT)..."
  if [[ -n "$NGROK_DOMAIN" ]]; then
    nohup "$NGROK_BIN" http "$FRONTEND_PORT" --domain="$NGROK_DOMAIN" --log=stdout \
      >"$LOG_DIR/ngrok.log" 2>&1 &
  else
    nohup "$NGROK_BIN" http "$FRONTEND_PORT" --log=stdout \
      >"$LOG_DIR/ngrok.log" 2>&1 &
  fi
  # ngrok 로컬 API 가 뜰 때까지 최대 5초 대기
  for _ in 1 2 3 4 5 6 7 8 9 10; do
    if curl -sS -m 1 "$NGROK_API" >/dev/null 2>&1; then break; fi
    sleep 0.5
  done
  NGROK_PUBLIC_URL="$(curl -sS -m 2 "$NGROK_API" 2>/dev/null \
    | python -c 'import json,sys
try:
    d=json.load(sys.stdin)
    urls=[t["public_url"] for t in d.get("tunnels",[]) if t.get("public_url","").startswith("https")]
    print(urls[0] if urls else "")
except Exception:
    print("")' 2>/dev/null)"
  if [[ -n "$NGROK_PUBLIC_URL" ]]; then
    echo "[start] ngrok up: $NGROK_PUBLIC_URL"
    echo "[start] kakao webhook URL: ${NGROK_PUBLIC_URL}/webhook/kakao"
  else
    echo "[start] ngrok 시작은 했지만 public URL 조회 실패. $LOG_DIR/ngrok.log 확인."
  fi
elif [[ "$ENABLE_NGROK" == "true" ]]; then
  echo "[start] ENABLE_NGROK=true 지만 $NGROK_BIN 가 없음 — ngrok 스킵"
fi

echo "[start] done."
echo "[start] tail logs:"
echo "  tail -f \"$LOG_DIR/ollama.log\""
echo "  tail -f \"$LOG_DIR/backend.log\""
echo "  tail -f \"$LOG_DIR/frontend.log\""
echo "  tail -f \"$LOG_DIR/ngrok.log\""

