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
mkdir -p "$LOG_DIR"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3100}"

CONDA_ENV="${CONDA_ENV:-capstone}"
ENABLE_FUNNEL="${ENABLE_FUNNEL:-true}"
ENABLE_NGROK="${ENABLE_NGROK:-true}"
NGROK_BIN="${NGROK_BIN:-$HOME/bin/ngrok}"
NGROK_DOMAIN="${NGROK_DOMAIN:-}"  # 예약 도메인 있으면 지정, 없으면 매번 랜덤
NGROK_API="http://127.0.0.1:4040/api/tunnels"

# APK 동적분석 WSL 브릿지 (127.0.0.1:18002 → VM 안 app.py, multipass exec 우회).
# ⚠️ DEPRECATED: VM 을 Tailscale 에 올려(.env APK_DYNAMIC_REMOTE_URL=http://<vm-tailscale-ip>:8002)
#    api_server 가 VM 에 *직접 HTTP* 하도록 전환 → 매 호출 multipass exec(SSH) 경합 제거.
#    그래서 기본값을 false(스킵)로. 브릿지 방식으로 되돌리려면 ENABLE_APK_BRIDGE=auto/true.
#   auto: VM(sg-sandbox)이 Running 일 때만 기동 / true: 항상 / false(기본): 스킵
ENABLE_APK_BRIDGE="${ENABLE_APK_BRIDGE:-false}"
APK_DYNAMIC_VM_NAME="${APK_DYNAMIC_VM_NAME:-sg-sandbox}"
APK_BRIDGE_PORT="${APK_DYNAMIC_BRIDGE_PORT:-18002}"
MULTIPASS_EXE="${MULTIPASS_EXE:-/mnt/c/Program Files/Multipass/bin/multipass.exe}"

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
kill_matches "ngrok http"
kill_matches "monitor_resources.sh"
kill_matches "funnel_watchdog.sh"
kill_matches "apk_dynamic_wsl_bridge"
kill_port "$BACKEND_PORT"
kill_port "$FRONTEND_PORT"
kill_port "$APK_BRIDGE_PORT"
kill_port 4040

# 이전 monitor PID 정리
if [ -f "$LOG_DIR/monitor.pids" ]; then
  while read -r pid; do kill "$pid" 2>/dev/null || true; done < "$LOG_DIR/monitor.pids"
  rm -f "$LOG_DIR/monitor.pids"
fi

sleep 0.5

# (NEW) 리소스 모니터 *먼저* 시작 — backend/frontend 워밍업 동안 메모리 추이를
# 모두 잡으려면 stack 시작 전에 monitor 가 돌고 있어야 한다.
echo "[start] starting resource monitor (5s sampling)..."
nohup "$ROOT_DIR/scripts/monitor_resources.sh" >>"$LOG_DIR/start_stack.console.log" 2>&1 &
sleep 0.5

echo "[start] starting backend (uvicorn :$BACKEND_PORT) in conda env '$CONDA_ENV'..."
cd "$ROOT_DIR"
PYTHONUNBUFFERED=1 nohup conda run --no-capture-output -n "$CONDA_ENV" python -u -m uvicorn api_server:app --host 0.0.0.0 --port "$BACKEND_PORT" --reload --log-level info \
  >"$LOG_DIR/backend.log" 2>&1 &

# (CHANGED) sleep 3 대신 backend /health 폴링 — ML 워밍업이 끝나야 frontend 시작.
# 두 프로세스가 동시에 메모리 spike 를 일으키면 8GB WSL 한도를 잠깐 넘기고
# swap thrashing → WSL freeze. sequential 화하면 spike 가 분산돼 한도 안 넘김.
echo "[start] waiting for backend warmup (polling /health up to 120s)..."
BACKEND_READY=0
for i in $(seq 1 60); do
  if curl -sS -m 2 "http://127.0.0.1:${BACKEND_PORT}/health" >/dev/null 2>&1; then
    BACKEND_READY=1
    echo "[start] backend ready after ${i}×2s = $((i*2))s"
    break
  fi
  sleep 2
done
if [[ "$BACKEND_READY" != "1" ]]; then
  echo "[start] WARN: backend /health 미응답 120s — 그래도 frontend 시작합니다."
  echo "[start] backend.log 마지막 줄:"
  tail -5 "$LOG_DIR/backend.log" || true
fi

echo "[start] starting frontend (next dev :$FRONTEND_PORT)..."

setsid bash -lic "
  cd '$ROOT_DIR/apps/web' || exit 1
  export SCAMGUARDIAN_API_URL='http://127.0.0.1:${BACKEND_PORT}'
  export LANG=C.UTF-8
  export LC_ALL=C.UTF-8

  if [ -s \"\$HOME/.nvm/nvm.sh\" ]; then
    source \"\$HOME/.nvm/nvm.sh\"
  fi

  # --hostname 0.0.0.0 을 빼고 기본 바인딩(localhost) 사용 — Next dev 가 명시적
  # --hostname 을 받으면 그 값(0.0.0.0)을 OAuth 콜백 origin 으로 써버려 콜백이
  # http://0.0.0.0:3100/... 로 깨진다. 기본 바인딩이면 요청 Host 헤더(localhost)를
  # 그대로 origin 으로 사용. Funnel·ngrok 은 127.0.0.1:3100 로 프록시하므로 영향 없음.
  npm run dev -- --port '$FRONTEND_PORT'
" >"$LOG_DIR/frontend.log" 2>&1 < /dev/null &

# (NEW) frontend 도 첫 컴파일 끝날 때까지 대기 — Turbopack 초기 컴파일이 끝나야
# tunnel 시작 시 첫 요청에서 무거운 컴파일 + 터널 핸드셰이크가 겹치지 않음.
echo "[start] waiting for frontend ready (polling :$FRONTEND_PORT up to 60s)..."
FRONTEND_READY=0
for i in $(seq 1 30); do
  if curl -sS -m 2 "http://127.0.0.1:${FRONTEND_PORT}/" >/dev/null 2>&1; then
    FRONTEND_READY=1
    echo "[start] frontend ready after ${i}×2s = $((i*2))s"
    break
  fi
  sleep 2
done
if [[ "$FRONTEND_READY" != "1" ]]; then
  echo "[start] WARN: frontend 미응답 60s — frontend.log 확인 필요"
  tail -10 "$LOG_DIR/frontend.log" || true
fi

if [[ "$ENABLE_FUNNEL" == "true" ]] && command -v tailscale >/dev/null 2>&1; then
  echo "[start] enabling tailscale funnel (frontend:$FRONTEND_PORT)..."
  tailscale funnel --bg "http://127.0.0.1:${FRONTEND_PORT}" || true
  tailscale funnel status 2>/dev/null || true
  # DERP flapping 으로 funnel ingress 세션이 stale 되는 문제 자동 복구 (2026-06-12)
  echo "[start] starting funnel watchdog (public-path probe, ${FUNNEL_WATCH_INTERVAL:-120}s)..."
  FRONTEND_PORT="$FRONTEND_PORT" nohup "$ROOT_DIR/scripts/funnel_watchdog.sh" \
    >>"$LOG_DIR/funnel_watchdog.log" 2>&1 &
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

# APK 동적분석 WSL 브릿지 — VM 안 app.py(systemd 관리)로 HTTP 포워딩.
if [[ "$ENABLE_APK_BRIDGE" != "false" ]]; then
  apk_vm_running=false
  if [[ -x "$MULTIPASS_EXE" ]] && \
     "$MULTIPASS_EXE" info "$APK_DYNAMIC_VM_NAME" 2>/dev/null | grep -qiE 'State:[[:space:]]*Running'; then
    apk_vm_running=true
  fi
  if [[ "$ENABLE_APK_BRIDGE" == "true" || "$apk_vm_running" == "true" ]]; then
    echo "[start] starting APK dynamic WSL bridge (127.0.0.1:$APK_BRIDGE_PORT → $APK_DYNAMIC_VM_NAME)..."
    if bash "$ROOT_DIR/scripts/apk_dynamic_vm_ctl.sh" bridge >>"$LOG_DIR/start_stack.console.log" 2>&1; then
      sleep 1
      if curl -sS -m 3 "http://127.0.0.1:${APK_BRIDGE_PORT}/health" >/dev/null 2>&1; then
        echo "[start] APK bridge ready (/health ok)"
      else
        echo "[start] APK bridge 기동했지만 /health 미응답 — VM app.py(systemd) 확인 필요"
      fi
    else
      echo "[start] WARN: APK bridge 시작 실패 — start_stack.console.log 확인"
    fi
  else
    echo "[start] skipping APK bridge (VM '$APK_DYNAMIC_VM_NAME' 미기동, ENABLE_APK_BRIDGE=auto). 켜려면 ENABLE_APK_BRIDGE=true 또는 'vm_ctl.sh start'"
  fi
fi

echo "[start] done."
echo "[start] tail logs:"
echo "  tail -f \"$LOG_DIR/backend.log\""
echo "  tail -f \"$LOG_DIR/frontend.log\""
echo "  tail -f \"$LOG_DIR/ngrok.log\""
echo "  tail -f \"$LOG_DIR/apk-dynamic-bridge.log\""
