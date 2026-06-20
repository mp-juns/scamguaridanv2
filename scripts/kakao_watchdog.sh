#!/usr/bin/env bash
# kakao_watchdog.sh — 카카오 webhook 자동 점검/복구
#
# 동작:
# - local backend /health 점검
# - local frontend /webhook/kakao(경량 payload) 점검
# - 연속 실패 시 backend/frontend 자동 재기동
# - (선택) funnel 공개 webhook 경로도 점검하고 stale 시 funnel 재기동
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/.scamguardian/logs"
mkdir -p "$LOG_DIR"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3100}"
CONDA_ENV="${CONDA_ENV:-capstone}"
FUNNEL_HOST="${FUNNEL_HOST:-scamguardian.tail7e5dfc.ts.net}"
WATCH_INTERVAL="${KAKAO_WATCH_INTERVAL:-20}"
FAIL_THRESHOLD="${KAKAO_WATCH_FAIL_THRESHOLD:-2}"
COOLDOWN_SEC="${KAKAO_WATCH_COOLDOWN_SEC:-90}"
CHECK_PUBLIC="${KAKAO_WATCH_CHECK_PUBLIC:-true}"
DOH_URL="${KAKAO_WATCH_DOH_URL:-https://dns.google/dns-query}"
PAYLOAD='{"userRequest":{"utterance":"사용법","user":{"id":"watchdog-user"}},"action":{"params":{}}}'

last_front_restart=0
last_back_restart=0
local_back_fails=0
local_front_fails=0
public_fails=0
BACKEND_CODE="000"
LOCAL_ROOT_CODE="000"
LOCAL_WEBHOOK_CODE="000"
PUBLIC_WEBHOOK_CODE="000"

log() { echo "[kakao-watchdog] $(date '+%F %T') $*"; }

now_ts() { date +%s; }

in_cooldown() {
  local last="$1"
  local now
  now="$(now_ts)"
  (( now - last < COOLDOWN_SEC ))
}

probe_backend_local() {
  BACKEND_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 4 "http://127.0.0.1:${BACKEND_PORT}/health" 2>/dev/null)" || BACKEND_CODE="000"
  [[ "$BACKEND_CODE" == "200" ]]
}

probe_front_local_root() {
  LOCAL_ROOT_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://127.0.0.1:${FRONTEND_PORT}/" 2>/dev/null)" || LOCAL_ROOT_CODE="000"
  [[ "$LOCAL_ROOT_CODE" == "200" ]]
}

probe_webhook_local() {
  LOCAL_WEBHOOK_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 7 \
    -H 'content-type: application/json' \
    -X POST \
    --data "$PAYLOAD" \
    "http://127.0.0.1:${FRONTEND_PORT}/webhook/kakao" 2>/dev/null)" || LOCAL_WEBHOOK_CODE="000"
  [[ "$LOCAL_WEBHOOK_CODE" == "200" ]]
}

probe_webhook_public() {
  PUBLIC_WEBHOOK_CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 12 \
    --doh-url "$DOH_URL" \
    -H 'content-type: application/json' \
    -X POST \
    --data "$PAYLOAD" \
    "https://${FUNNEL_HOST}/webhook/kakao" 2>/dev/null)" || PUBLIC_WEBHOOK_CODE="000"
  [[ "$PUBLIC_WEBHOOK_CODE" == "200" ]]
}

diagnose_backend_cause() {
  if ! pgrep -f "uvicorn api_server:app" >/dev/null 2>&1; then
    echo "backend_process_missing"
    return
  fi
  if [[ "$BACKEND_CODE" == "000" ]]; then
    echo "backend_unreachable"
    return
  fi
  if [[ "$BACKEND_CODE" != "200" ]]; then
    echo "backend_http_${BACKEND_CODE}"
    return
  fi
  echo "backend_ok"
}

diagnose_frontend_cause() {
  probe_front_local_root >/dev/null 2>&1 || true
  if ! pgrep -f "next dev" >/dev/null 2>&1; then
    echo "frontend_process_missing"
    return
  fi
  if [[ "$LOCAL_ROOT_CODE" == "000" ]]; then
    echo "frontend_unreachable"
    return
  fi
  if [[ "$LOCAL_ROOT_CODE" =~ ^5 ]]; then
    if [[ -f "$LOG_DIR/frontend.log" ]] && tail -n 120 "$LOG_DIR/frontend.log" | grep -Eiq "Failed to compile|Cannot access 'dynamic' before initialization|Module not found|SyntaxError|Type error|ReferenceError"; then
      echo "frontend_compile_error"
      return
    fi
    echo "frontend_runtime_5xx"
    return
  fi
  if [[ "$LOCAL_WEBHOOK_CODE" == "500" ]]; then
    echo "webhook_500"
    return
  fi
  if [[ "$LOCAL_ROOT_CODE" == "200" && "$LOCAL_WEBHOOK_CODE" != "200" ]]; then
    echo "webhook_route_failure"
    return
  fi
  echo "frontend_http_${LOCAL_ROOT_CODE}_webhook_${LOCAL_WEBHOOK_CODE}"
}

diagnose_public_cause() {
  if [[ "$PUBLIC_WEBHOOK_CODE" == "000" ]]; then
    if [[ "$LOCAL_WEBHOOK_CODE" == "200" ]]; then
      echo "funnel_stale_or_network"
      return
    fi
    echo "public_unreachable_local_also_failing"
    return
  fi
  if [[ "$PUBLIC_WEBHOOK_CODE" != "200" ]]; then
    echo "public_http_${PUBLIC_WEBHOOK_CODE}"
    return
  fi
  echo "public_ok"
}

restart_backend() {
  log "backend 재시작 시작"
  pkill -f "uvicorn api_server:app" >/dev/null 2>&1 || true
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${BACKEND_PORT}/tcp" >/dev/null 2>&1 || true
  fi
  sleep 1
  cd "$ROOT_DIR" || return 1
  PYTHONUNBUFFERED=1 nohup conda run --no-capture-output -n "$CONDA_ENV" \
    python -u -m uvicorn api_server:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload --log-level info \
    >"$LOG_DIR/backend.log" 2>&1 &
  log "backend 재시작 완료"
}

restart_frontend() {
  log "frontend 재시작 시작"
  pkill -f "next dev" >/dev/null 2>&1 || true
  pkill -f "next-server" >/dev/null 2>&1 || true
  pkill -f "npm run dev" >/dev/null 2>&1 || true
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${FRONTEND_PORT}/tcp" >/dev/null 2>&1 || true
  fi
  sleep 1
  setsid bash -lic "
    cd '$ROOT_DIR/apps/web' || exit 1
    export SCAMGUARDIAN_API_URL='http://127.0.0.1:${BACKEND_PORT}'
    export LANG=C.UTF-8
    export LC_ALL=C.UTF-8
    if [ -s \"\$HOME/.nvm/nvm.sh\" ]; then
      source \"\$HOME/.nvm/nvm.sh\"
    fi
    npm run dev -- --port '$FRONTEND_PORT'
  " >"$LOG_DIR/frontend.log" 2>&1 < /dev/null &
  log "frontend 재시작 완료"
}

restart_funnel() {
  log "funnel 재기동 시작"
  tailscale funnel --https=443 off >/dev/null 2>&1 || true
  sleep 1
  if tailscale funnel --bg "http://127.0.0.1:${FRONTEND_PORT}" >/dev/null 2>&1; then
    log "funnel 재기동 완료"
  else
    log "funnel 재기동 실패"
  fi
}

log "시작 — interval=${WATCH_INTERVAL}s threshold=${FAIL_THRESHOLD} cooldown=${COOLDOWN_SEC}s"
log "targets — backend=:${BACKEND_PORT}, frontend=:${FRONTEND_PORT}, public_host=${FUNNEL_HOST}"

while true; do
  # 1) backend health
  if probe_backend_local; then
    local_back_fails=0
  else
    cause="$(diagnose_backend_cause)"
    local_back_fails=$((local_back_fails + 1))
    log "backend /health 실패 (${local_back_fails}/${FAIL_THRESHOLD}) [cause=${cause} code=${BACKEND_CODE}]"
    if (( local_back_fails >= FAIL_THRESHOLD )); then
      if in_cooldown "$last_back_restart"; then
        log "backend 재시작 cooldown 중 — 대기 [cause=${cause}]"
      else
        restart_backend
        last_back_restart="$(now_ts)"
      fi
      local_back_fails=0
    fi
  fi

  # 2) local webhook (실제 카카오 핵심 경로)
  if probe_webhook_local; then
    local_front_fails=0
  else
    cause="$(diagnose_frontend_cause)"
    local_front_fails=$((local_front_fails + 1))
    log "local webhook 실패 (${local_front_fails}/${FAIL_THRESHOLD}) [cause=${cause} root=${LOCAL_ROOT_CODE} webhook=${LOCAL_WEBHOOK_CODE}]"
    if (( local_front_fails >= FAIL_THRESHOLD )); then
      if in_cooldown "$last_front_restart"; then
        log "frontend 재시작 cooldown 중 — 대기 [cause=${cause}]"
      else
        restart_frontend
        last_front_restart="$(now_ts)"
      fi
      local_front_fails=0
    fi
  fi

  # 3) public webhook (선택)
  if [[ "$CHECK_PUBLIC" == "true" ]] && command -v tailscale >/dev/null 2>&1; then
    if probe_webhook_public; then
      public_fails=0
    else
      cause="$(diagnose_public_cause)"
      public_fails=$((public_fails + 1))
      log "public webhook 실패 (${public_fails}/2) [cause=${cause} public=${PUBLIC_WEBHOOK_CODE} local=${LOCAL_WEBHOOK_CODE}]"
      if (( public_fails >= 2 )); then
        restart_funnel
        public_fails=0
      fi
    fi
  fi

  sleep "$WATCH_INTERVAL"
done
