#!/usr/bin/env bash
# kyy 전용 시작 스크립트
# - phh 원본(8000/3100/ngrok)과 포트 완전 분리
# - Public URL: Cloudflare Quick Tunnel (무료, 계정 불필요, 매번 URL 바뀜)
# - Tailscale Funnel + ngrok 모두 비활성 (phh의 카카오 웹훅 보호)
# ⚠️ start_stack.sh 의 kill_matches 가 phh 프로세스도 죽일 수 있으므로
#    여기서 직접 우리 포트만 kill 하고 uvicorn/next 도 직접 띄움
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/.scamguardian/logs"
mkdir -p "$LOG_DIR"

BACKEND_PORT=8001
FRONTEND_PORT=3101
CONDA_ENV="${CONDA_ENV:-capstone}"
CLOUDFLARED_BIN="${CLOUDFLARED_BIN:-$HOME/bin/cloudflared}"

export PATH="$HOME/miniconda3/bin:$HOME/anaconda3/bin:$HOME/.nvm/versions/node/$(ls -1 $HOME/.nvm/versions/node 2>/dev/null | tail -n 1)/bin:/usr/local/bin:/usr/bin:/bin:$PATH"
if [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
  source "$HOME/miniconda3/etc/profile.d/conda.sh"
elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
  source "$HOME/anaconda3/etc/profile.d/conda.sh"
fi
if [ -s "$HOME/.nvm/nvm.sh" ]; then
  source "$HOME/.nvm/nvm.sh"
fi

# 우리 포트만 정리 (phh 포트 8000/3100/4040 은 절대 건드리지 않음)
if command -v fuser >/dev/null 2>&1; then
  fuser -k "${BACKEND_PORT}/tcp" >/dev/null 2>&1 || true
  fuser -k "${FRONTEND_PORT}/tcp" >/dev/null 2>&1 || true
fi
# 이전 kyy cloudflared 프로세스 정리 (frontend port 기준)
pkill -f "cloudflared.*${FRONTEND_PORT}" >/dev/null 2>&1 || true

echo "[kyy] root=$ROOT_DIR (ports: backend=$BACKEND_PORT, frontend=$FRONTEND_PORT)"

# === 1. cloudflared 먼저 띄워서 public URL 확보 ===
PUBLIC_URL=""
if [[ -x "$CLOUDFLARED_BIN" ]]; then
  echo "[kyy] starting cloudflared quick tunnel → :$FRONTEND_PORT"
  : > "$LOG_DIR/cloudflared-kyy.log"
  nohup "$CLOUDFLARED_BIN" tunnel --url "http://localhost:${FRONTEND_PORT}" --no-autoupdate \
    >"$LOG_DIR/cloudflared-kyy.log" 2>&1 &
  # quick tunnel URL 이 로그에 찍힐 때까지 최대 15초 대기
  # -a : 이전 프로세스 잔여 NUL 바이트 때문에 grep 이 binary 로 인식하는 거 방어
  # || true : grep 비매칭 시 pipefail+set -e 가 스크립트 죽이는 거 방어
  for _ in $(seq 1 30); do
    PUBLIC_URL="$(grep -oaE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOG_DIR/cloudflared-kyy.log" 2>/dev/null | head -1 || true)"
    if [[ -n "$PUBLIC_URL" ]]; then break; fi
    sleep 0.5
  done
  if [[ -n "$PUBLIC_URL" ]]; then
    echo "[kyy] public URL: $PUBLIC_URL"
    export SCAMGUARDIAN_PUBLIC_URL="$PUBLIC_URL"
  else
    echo "[kyy] cloudflared URL 추출 실패 — $LOG_DIR/cloudflared-kyy.log 확인"
  fi
else
  echo "[kyy] cloudflared 바이너리 없음 ($CLOUDFLARED_BIN) — 로컬 전용으로만 동작"
fi

# === 2. backend (SCAMGUARDIAN_PUBLIC_URL 환경 상속) ===
echo "[kyy] starting backend (uvicorn :$BACKEND_PORT)..."
cd "$ROOT_DIR"
PYTHONUNBUFFERED=1 nohup conda run --no-capture-output -n "$CONDA_ENV" \
  python -u -m uvicorn api_server:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload --log-level info \
  >"$LOG_DIR/backend-kyy.log" 2>&1 < /dev/null &

# === 3. frontend ===
echo "[kyy] starting frontend (next dev :$FRONTEND_PORT)..."
cd "$ROOT_DIR/apps/web"
nohup bash -lc "
  export SCAMGUARDIAN_API_URL='http://127.0.0.1:${BACKEND_PORT}'
  npm run dev -- --hostname 0.0.0.0 --port '$FRONTEND_PORT'
" >"$LOG_DIR/frontend-kyy.log" 2>&1 < /dev/null &

echo "[kyy] up — logs:"
echo "  backend    : $LOG_DIR/backend-kyy.log"
echo "  frontend   : $LOG_DIR/frontend-kyy.log"
echo "  cloudflared: $LOG_DIR/cloudflared-kyy.log"
echo "  로컬 접속  : http://127.0.0.1:${FRONTEND_PORT}"
[[ -n "$PUBLIC_URL" ]] && echo "  공개 URL   : $PUBLIC_URL"
