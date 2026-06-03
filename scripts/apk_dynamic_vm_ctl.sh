#!/usr/bin/env bash
#
# WSL-side controller for the ScamGuardian APK dynamic-analysis VM.
#
# This script lets the WSL ScamGuardian workspace control the Windows Multipass
# VM that hosts binder/redroid/frida/apk_dynamic_server.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VM_NAME="${APK_DYNAMIC_VM_NAME:-sg-sandbox}"
VM_WORKDIR="${APK_DYNAMIC_VM_WORKDIR:-/home/ubuntu/sg-apkdyn}"
SERVER_PORT="${APK_DYNAMIC_SERVER_PORT:-8002}"
BRIDGE_PORT="${APK_DYNAMIC_BRIDGE_PORT:-18002}"
USE_BRIDGE="${APK_DYNAMIC_USE_BRIDGE:-1}"
SERVER_TOKEN="${APK_DYNAMIC_SERVER_TOKEN:-${APK_DYNAMIC_REMOTE_TOKEN:-dev-secret-123}}"
MULTIPASS_EXE="${MULTIPASS_EXE:-/mnt/c/Program Files/Multipass/bin/multipass.exe}"
REDROID_IMAGE="${APK_DYNAMIC_REDROID_IMAGE:-redroid/redroid:13.0.0-latest}"
ENV_OUT="${APK_DYNAMIC_ENV_OUT:-$ROOT_DIR/.env.apk-dynamic.local}"
BRIDGE_LOG="$ROOT_DIR/.scamguardian/logs/apk-dynamic-bridge.log"
RELAY_LOG="$ROOT_DIR/.scamguardian/logs/apk-dynamic-relay.log"

usage() {
  cat <<EOF
Usage: $0 <command>

Commands:
  start          Start VM, sync server code, start redroid, frida-server, and API server
  stop           Stop the VM and kill the WSL bridge (does not delete the VM)
  status         Show VM/redroid/frida/API status
  status-json    Emit one-line machine-readable JSON status (no VM start)
  sync           Copy apk_dynamic_server/ and APK fixtures into the VM
  bootstrap      Install VM prerequisites (apt packages, Docker, python packages)
  redroid        Ensure redroid container is running and booted
  frida          Ensure frida python package and frida-server are installed/running
  server         Start apk_dynamic_server FastAPI inside the VM
  bridge         Start WSL-local HTTP bridge through multipass exec/transfer
  relay          Start Windows TCP relay (fallback; may be blocked by WSL firewall)
  health         Check API /health from WSL
  print-env      Print main ScamGuardian env values for this VM
  write-env      Write env values to $ENV_OUT
  apply-env      Backup and update .env with APK_DYNAMIC_* values
  logs           Tail VM server log

Environment:
  APK_DYNAMIC_VM_NAME       default: sg-sandbox
  APK_DYNAMIC_SERVER_TOKEN  shared bearer token, default: dev-secret-123
  APK_DYNAMIC_SERVER_PORT   default: 8002
  APK_DYNAMIC_BRIDGE_PORT   default: 18002
  APK_DYNAMIC_USE_BRIDGE    default: 1
  MULTIPASS_EXE             default: /mnt/c/Program Files/Multipass/bin/multipass.exe
EOF
}

mp() {
  if [[ ! -x "$MULTIPASS_EXE" ]]; then
    echo "multipass.exe not found: $MULTIPASS_EXE" >&2
    exit 2
  fi
  "$MULTIPASS_EXE" "$@" | tr -d '\r'
}

vm_exec() {
  mp exec "$VM_NAME" -- bash -lc "$1"
}

vm_ip() {
  mp info "$VM_NAME" | awk '/IPv4/ {print $2; exit}'
}

wsl_windows_gateway() {
  ip route | awk '/^default/ {print $3; exit}'
}

ensure_vm() {
  if ! mp info "$VM_NAME" >/dev/null 2>&1; then
    echo "[apk-vm] VM '$VM_NAME' does not exist."
    echo "[apk-vm] Create it once from Windows/WSL:"
    echo "  multipass launch 22.04 --name $VM_NAME --cpus 4 --memory 6G --disk 30G"
    exit 2
  fi
  echo "[apk-vm] starting VM: $VM_NAME"
  mp start "$VM_NAME" >/dev/null
}

sync_code() {
  ensure_vm
  echo "[apk-vm] syncing apk_dynamic_server and fixtures"
  vm_exec "mkdir -p '$VM_WORKDIR/fixtures'"
  mp transfer -r "$(wslpath -w "$ROOT_DIR/apk_dynamic_server")" "$VM_NAME:$VM_WORKDIR/" >/dev/null
  if [[ -f "$ROOT_DIR/tests/fixtures/dynamic_active.apk" ]]; then
    mp transfer "$(wslpath -w "$ROOT_DIR/tests/fixtures/dynamic_active.apk")" \
      "$VM_NAME:$VM_WORKDIR/fixtures/dynamic_active.apk" >/dev/null
  fi
  if [[ -f "$ROOT_DIR/tests/fixtures/fake_phishing.apk" ]]; then
    mp transfer "$(wslpath -w "$ROOT_DIR/tests/fixtures/fake_phishing.apk")" \
      "$VM_NAME:$VM_WORKDIR/fixtures/fake_phishing.apk" >/dev/null
  fi
}

bootstrap_vm() {
  ensure_vm
  echo "[apk-vm] installing VM prerequisites"
  vm_exec "
    set -euo pipefail
    sudo apt update
    sudo apt install -y linux-modules-extra-\$(uname -r) adb python3-pip xz-utils curl wget
    sudo modprobe binder_linux devices='binder,hwbinder,vndbinder'
    sudo modprobe ashmem_linux 2>/dev/null || true
    sudo mkdir -p /dev/binderfs
    sudo mount -t binder binder /dev/binderfs 2>/dev/null || true
    if ! command -v docker >/dev/null 2>&1; then
      curl -fsSL https://get.docker.com | sudo sh
      sudo usermod -aG docker ubuntu || true
    fi
    python3 -m pip install --user 'frida<17' 'frida-tools<13'
  "
}

ensure_redroid() {
  ensure_vm
  echo "[apk-vm] ensuring redroid container"
  vm_exec "
    set -euo pipefail
    sudo modprobe binder_linux devices='binder,hwbinder,vndbinder' || true
    sudo modprobe ashmem_linux 2>/dev/null || true
    sudo mkdir -p /dev/binderfs
    sudo mount -t binder binder /dev/binderfs 2>/dev/null || true
    if ! command -v docker >/dev/null 2>&1; then
      echo 'docker missing; run: scripts/apk_dynamic_vm_ctl.sh bootstrap' >&2
      exit 2
    fi
    if sudo docker ps -a --format '{{.Names}}' | grep -qx redroid; then
      sudo docker start redroid >/dev/null
    else
      sudo docker run -itd --privileged --name redroid \
        -v /home/ubuntu/redroid-data:/data -p 5555:5555 \
        '$REDROID_IMAGE' \
        androidboot.redroid_width=720 androidboot.redroid_height=1280 >/dev/null
    fi
    adb connect localhost:5555 >/dev/null || true
    for i in \$(seq 1 90); do
      booted=\$(adb -s localhost:5555 shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true)
      if [ \"\$booted\" = 1 ]; then
        echo 'redroid booted'
        exit 0
      fi
      sleep 1
    done
    echo 'redroid did not boot within 90s' >&2
    sudo docker logs --tail 80 redroid >&2 || true
    exit 1
  "
}

ensure_frida() {
  ensure_vm
  echo "[apk-vm] ensuring frida-server"
  vm_exec "
    set -euo pipefail
    python3 -m pip install --user 'frida<17' 'frida-tools<13' >/dev/null
    export PATH=\"\$HOME/.local/bin:\$PATH\"
    adb connect localhost:5555 >/dev/null || true
    adb -s localhost:5555 root >/dev/null 2>&1 || true
    FV=\$(python3 -c 'import frida; print(frida.__version__)')
    if ! adb -s localhost:5555 shell ls /data/local/tmp/frida-server >/dev/null 2>&1; then
      cd /tmp
      rm -f frida-server-\${FV}-android-x86_64 frida-server-\${FV}-android-x86_64.xz
      wget -q \"https://github.com/frida/frida/releases/download/\${FV}/frida-server-\${FV}-android-x86_64.xz\"
      unxz -f \"frida-server-\${FV}-android-x86_64.xz\"
      adb -s localhost:5555 push \"frida-server-\${FV}-android-x86_64\" /data/local/tmp/frida-server >/dev/null
      adb -s localhost:5555 shell chmod 755 /data/local/tmp/frida-server
    fi
    adb -s localhost:5555 shell 'pidof frida-server >/dev/null || setsid /data/local/tmp/frida-server >/dev/null 2>&1 </dev/null &' || true
    for i in \$(seq 1 20); do
      if adb -s localhost:5555 shell pidof frida-server >/dev/null 2>&1; then
        echo \"frida-server running (frida \$FV)\"
        exit 0
      fi
      sleep 0.5
    done
    echo 'frida-server failed to start' >&2
    exit 1
  "
}

start_server() {
  ensure_vm
  sync_code
  echo "[apk-vm] starting dynamic-analysis API server"
  vm_exec "
    set -euo pipefail
    cd '$VM_WORKDIR/apk_dynamic_server'
    python3 -m pip install --user -r requirements.txt >/dev/null
    py=python3
    app_file=app.py
    kill_pattern='[p]ython3 app.py'
    pids=\$(pgrep -f \"\$kill_pattern\" 2>/dev/null || true)
    if [ -n \"\$pids\" ]; then kill \$pids 2>/dev/null || true; fi
    nohup env APK_DYNAMIC_SERVER_TOKEN='$SERVER_TOKEN' PORT='$SERVER_PORT' \
      APK_DYNAMIC_ADB_SERIAL=localhost:5555 \
      \"\$py\" \"\$app_file\" > server.log 2>&1 < /dev/null &
    sleep 1
    pgrep -af '[p]ython3 app.py' || true
  "
}

start_relay() {
  local ip win_script win_log win_err
  ip="$(vm_ip)"
  mkdir -p "$(dirname "$RELAY_LOG")"
  win_script="$(wslpath -w "$ROOT_DIR/scripts/apk_dynamic_windows_relay.ps1")"
  win_log="$(wslpath -w "$RELAY_LOG")"
  win_err="$(wslpath -w "${RELAY_LOG%.log}.err.log")"
  echo "[apk-vm] starting Windows relay: 0.0.0.0:$RELAY_PORT -> $ip:$SERVER_PORT"
  powershell.exe -NoProfile -Command "\$ErrorActionPreference='Stop'; \
    Get-CimInstance Win32_Process | Where-Object { \$_.ProcessId -ne \$PID -and \$_.CommandLine -like '*apk_dynamic_windows_relay.ps1*ListenPort $RELAY_PORT*' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }; \
    Start-Process powershell.exe -WindowStyle Hidden -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File','$win_script','-ListenAddress','0.0.0.0','-ListenPort','$RELAY_PORT','-TargetHost','$ip','-TargetPort','$SERVER_PORT') -RedirectStandardOutput '$win_log' -RedirectStandardError '$win_err';"
  sleep 1
}

remote_url() {
  if [[ "$USE_BRIDGE" == "1" || "$USE_BRIDGE" == "true" ]]; then
    echo "http://127.0.0.1:$BRIDGE_PORT"
  else
    echo "http://$(vm_ip):$SERVER_PORT"
  fi
}

start_bridge() {
  local conda_bin
  mkdir -p "$(dirname "$BRIDGE_LOG")"
  echo "[apk-vm] starting WSL bridge: 127.0.0.1:$BRIDGE_PORT -> multipass:$VM_NAME:$SERVER_PORT"
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${BRIDGE_PORT}/tcp" >/dev/null 2>&1 || true
  fi
  conda_bin="$HOME/anaconda3/bin/conda"
  if [[ -x "$HOME/miniconda3/bin/conda" ]]; then
    conda_bin="$HOME/miniconda3/bin/conda"
  fi
  if [[ -x "$conda_bin" ]]; then
    nohup env APK_DYNAMIC_VM_NAME="$VM_NAME" \
      APK_DYNAMIC_VM_WORKDIR="$VM_WORKDIR" \
      APK_DYNAMIC_SERVER_PORT="$SERVER_PORT" \
      APK_DYNAMIC_SERVER_TOKEN="$SERVER_TOKEN" \
      APK_DYNAMIC_BRIDGE_PORT="$BRIDGE_PORT" \
      MULTIPASS_EXE="$MULTIPASS_EXE" \
      "$conda_bin" run --no-capture-output -n "${CONDA_ENV:-capstone}" \
      python "$ROOT_DIR/scripts/apk_dynamic_wsl_bridge.py" \
      > "$BRIDGE_LOG" 2>&1 < /dev/null &
  else
    nohup env APK_DYNAMIC_VM_NAME="$VM_NAME" \
      APK_DYNAMIC_VM_WORKDIR="$VM_WORKDIR" \
      APK_DYNAMIC_SERVER_PORT="$SERVER_PORT" \
      APK_DYNAMIC_SERVER_TOKEN="$SERVER_TOKEN" \
      APK_DYNAMIC_BRIDGE_PORT="$BRIDGE_PORT" \
      MULTIPASS_EXE="$MULTIPASS_EXE" \
      python3 "$ROOT_DIR/scripts/apk_dynamic_wsl_bridge.py" \
      > "$BRIDGE_LOG" 2>&1 < /dev/null &
  fi
  sleep 1
  pgrep -af '[a]pk_dynamic_wsl_bridge.py' || true
}

print_env() {
  cat <<EOF
APK_DYNAMIC_ENABLED=1
APK_DYNAMIC_BACKEND=remote
APK_DYNAMIC_REMOTE_URL=$(remote_url)
APK_DYNAMIC_REMOTE_TOKEN=$SERVER_TOKEN
APK_DYNAMIC_TIMEOUT=180
EOF
}

write_env() {
  print_env > "$ENV_OUT"
  echo "[apk-vm] wrote $ENV_OUT"
}

apply_env() {
  local tmp backup
  tmp="$(mktemp)"
  backup="$ROOT_DIR/.env.bak-apkdyn-$(date +%Y%m%d-%H%M%S)"
  print_env > "$tmp"
  cp "$ROOT_DIR/.env" "$backup"
  python3 - "$ROOT_DIR/.env" "$tmp" <<'PY'
from pathlib import Path
import sys

env_path = Path(sys.argv[1])
new_path = Path(sys.argv[2])
updates = {}
for line in new_path.read_text().splitlines():
    if "=" in line:
        k, v = line.split("=", 1)
        updates[k] = v

existing = env_path.read_text().splitlines() if env_path.exists() else []
seen = set()
out = []
for line in existing:
    key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
    if key in updates:
        out.append(f"{key}={updates[key]}")
        seen.add(key)
    else:
        out.append(line)

missing = [k for k in updates if k not in seen]
if missing:
    if out and out[-1].strip():
        out.append("")
    out.append("# APK dynamic analysis VM")
    out.extend(f"{k}={updates[k]}" for k in missing)

env_path.write_text("\n".join(out).rstrip() + "\n")
PY
  rm -f "$tmp"
  echo "[apk-vm] updated .env (backup: $backup)"
}

health() {
  local url
  url="$(remote_url)"
  echo "[apk-vm] GET $url/health"
  curl -fsS --connect-timeout 5 --max-time 12 "$url/health" | python3 -m json.tool
}

status() {
  ensure_vm
  echo "[apk-vm] multipass info"
  mp info "$VM_NAME"
  echo
  vm_exec "
    set +e
    echo '--- binderfs ---'
    ls /dev/binderfs 2>/dev/null || true
    echo '--- redroid ---'
    sudo docker ps --filter name=redroid --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || true
    echo '--- adb boot ---'
    adb connect localhost:5555 >/dev/null 2>&1 || true
    adb -s localhost:5555 shell getprop sys.boot_completed 2>/dev/null | tr -d '\r' || true
    echo '--- frida ---'
    adb -s localhost:5555 shell pidof frida-server 2>/dev/null | tr -d '\r' || true
    echo '--- api server ---'
    pgrep -af '[p]ython3 app.py' || true
  "
  echo "--- remote URL from WSL ---"
  echo "$(remote_url)"
}

logs() {
  ensure_vm
  vm_exec "tail -n 120 -f '$VM_WORKDIR/apk_dynamic_server/server.log'"
}

stop_all() {
  # WSL bridge 먼저 정리 (포트 + 프로세스), 그 다음 VM 정지. VM 생성은 안 함.
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${BRIDGE_PORT}/tcp" >/dev/null 2>&1 || true
  fi
  pkill -f '[a]pk_dynamic_wsl_bridge.py' >/dev/null 2>&1 || true
  if mp info "$VM_NAME" >/dev/null 2>&1; then
    echo "[apk-vm] stopping VM: $VM_NAME"
    mp stop "$VM_NAME" >/dev/null 2>&1 || true
    echo "[apk-vm] VM '$VM_NAME' stopped, WSL bridge killed."
  else
    echo "[apk-vm] VM '$VM_NAME' not found (bridge killed, nothing else to stop)."
  fi
}

status_json() {
  # 머신리더블 한 줄 JSON. status() 와 달리 ensure_vm(=VM 시작) 을 호출하지 않는다.
  # 프로브가 실패해도 항상 valid JSON 을 방출한다 (필드는 false 로 채움).
  local vm_running=false redroid_booted=false frida_running=false server_up=false url probe
  url="$(remote_url)"
  if mp info "$VM_NAME" 2>/dev/null | grep -qiE 'State:[[:space:]]*Running'; then
    vm_running=true
    probe="$(vm_exec "
      set +e
      adb connect localhost:5555 >/dev/null 2>&1
      echo BOOTED=\$(adb -s localhost:5555 shell getprop sys.boot_completed 2>/dev/null | tr -d '\r ')
      echo FRIDA=\$(adb -s localhost:5555 shell pidof frida-server 2>/dev/null | tr -d '\r ')
      echo SERVER=\$(pgrep -f '[p]ython3 app.py' 2>/dev/null | head -n1)
    " 2>/dev/null || true)"
    grep -q 'BOOTED=1' <<<"$probe" && redroid_booted=true
    grep -Eq 'FRIDA=[0-9]+' <<<"$probe" && frida_running=true
    grep -Eq 'SERVER=[0-9]+' <<<"$probe" && server_up=true
  fi
  printf '{"vm_running":%s,"redroid_booted":%s,"frida_running":%s,"server_up":%s,"remote_url":"%s"}\n' \
    "$vm_running" "$redroid_booted" "$frida_running" "$server_up" "$url"
}

start_all() {
  ensure_vm
  sync_code
  ensure_redroid
  ensure_frida
  start_server
  if [[ "$USE_BRIDGE" == "1" || "$USE_BRIDGE" == "true" ]]; then
    start_bridge
  fi
  write_env
  health
  echo
  echo "[apk-vm] To let main ScamGuardian read this automatically:"
  echo "  $0 apply-env"
  echo "  ./scripts/start_stack.sh"
}

cmd="${1:-}"
case "$cmd" in
  start) start_all ;;
  stop) stop_all ;;
  status) status ;;
  status-json) status_json ;;
  sync) sync_code ;;
  bootstrap) bootstrap_vm ;;
  redroid) ensure_redroid ;;
  frida) ensure_frida ;;
  server) start_server ;;
  bridge) start_bridge ;;
  relay) start_relay ;;
  health) health ;;
  print-env) print_env ;;
  write-env) write_env ;;
  apply-env) apply_env ;;
  logs) logs ;;
  -h|--help|help|"") usage ;;
  *) echo "Unknown command: $cmd" >&2; usage; exit 2 ;;
esac
