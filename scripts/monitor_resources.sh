#!/usr/bin/env bash
# Stack freeze 진단용 — WSL 안에 5초 주기 write + 30초마다 Windows 호스트로 rsync.
# 메모리 *아닌* freeze 원인 (9P I/O block / VSCode WSL extension / Defender scan) 까지 잡으려고
# I/O 부하 sampler 추가.
#
# 출력:
#   .scamguardian/logs/                ← 빠른 ext4 write (5초)
#   /mnt/c/Users/mpssh/Documents/wsl_logs/  ← 30초마다 rsync 미러 (9P 부하 최소)
#
# 파일:
#   resources.log — 메모리/CPU/swap/load (5초)
#   processes.log — ps RSS top 10 (5초)
#   io.log        — I/O top + disk stats + uninterruptible sleep (D state) 프로세스 (5초)
#   kernel.log    — dmesg follow (실시간)
#   journal.log   — journalctl warning+ follow

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/.scamguardian/logs"
WIN_LOG_DIR="${WSL_LOG_MIRROR:-/mnt/c/Users/mpssh/Documents/wsl_logs}"

mkdir -p "$LOG_DIR" "$WIN_LOG_DIR"

INTERVAL="${MONITOR_INTERVAL:-5}"
RSYNC_INTERVAL="${MONITOR_RSYNC_INTERVAL:-30}"

PID_FILE="$LOG_DIR/monitor.pids"

# 이전 monitor 정리
if [ -f "$PID_FILE" ]; then
  while read -r pid; do
    kill "$pid" 2>/dev/null || true
  done < "$PID_FILE"
  rm -f "$PID_FILE"
fi

ts() { date '+%Y-%m-%d %H:%M:%S'; }

{
  echo "=== monitor started at $(ts) ==="
  echo "    sampling interval: ${INTERVAL}s"
  echo "    rsync to host:     ${RSYNC_INTERVAL}s"
  echo "    WSL logs:          $LOG_DIR/"
  echo "    Windows mirror:    $WIN_LOG_DIR/"
} >> "$LOG_DIR/resources.log"

# (1) 메모리/CPU/swap/load — 5초 주기
{
  while true; do
    {
      echo "--- $(ts) ---"
      free -h
      echo "uptime: $(uptime)"
      grep -E "^pswp(in|out)" /proc/vmstat 2>/dev/null || true
      grep -E "^pgmajfault" /proc/vmstat 2>/dev/null || true
    } >> "$LOG_DIR/resources.log"
    sleep "$INTERVAL"
  done
} &
echo $! >> "$PID_FILE"

# (2) 프로세스 RSS top 10 — 5초 주기
{
  while true; do
    {
      echo "--- $(ts) ---"
      ps -eo pid,ppid,user,%cpu,%mem,rss,vsz,stat,start,time,comm --sort=-rss | head -12
    } >> "$LOG_DIR/processes.log"
    sleep "$INTERVAL"
  done
} &
echo $! >> "$PID_FILE"

# (3) I/O 부하 sampler — 5초 주기. freeze 원인이 I/O block 인지 확인용.
# D-state (uninterruptible sleep) 프로세스 잡으면 곧 그게 hang trigger.
{
  while true; do
    {
      echo "--- $(ts) ---"
      echo "[D-state procs (kernel I/O wait, hang 후보)]"
      ps -eo pid,user,stat,wchan:30,comm | awk 'NR==1 || $3 ~ /^D/'
      echo "[I/O top — read/write bytes 누적, %CPU 정렬]"
      ps -eo pid,user,%cpu,rss,stat,comm --sort=-%cpu | head -8
      echo "[/proc/diskstats — 누적]"
      cat /proc/diskstats 2>/dev/null | head -5
      echo "[9P 마운트 통계 — /mnt/c hang 여부]"
      grep -E "(9p|drvfs|drvshare)" /proc/mounts 2>/dev/null || echo "  (no 9p mounts visible)"
      echo "[loadavg]"
      cat /proc/loadavg 2>/dev/null
    } >> "$LOG_DIR/io.log"
    sleep "$INTERVAL"
  done
} &
echo $! >> "$PID_FILE"

# (4) dmesg follow — kernel panic / hung_task / 9P stall
{
  echo "=== kernel log follow started at $(ts) ===" >> "$LOG_DIR/kernel.log"
  dmesg --follow-new --human 2>>"$LOG_DIR/kernel.log" >> "$LOG_DIR/kernel.log" || \
    echo "[$(ts)] dmesg follow failed (needs CAP_SYSLOG)" >> "$LOG_DIR/kernel.log"
} &
echo $! >> "$PID_FILE"

# (5) journalctl follow — systemd 에러
{
  echo "=== journal follow started at $(ts) ===" >> "$LOG_DIR/journal.log"
  journalctl --follow --priority warning --no-pager 2>>"$LOG_DIR/journal.log" >> "$LOG_DIR/journal.log" || \
    echo "[$(ts)] journalctl follow failed" >> "$LOG_DIR/journal.log"
} &
echo $! >> "$PID_FILE"

# (6) Windows 호스트로 rsync 미러 — 30초 주기. 9P write 부하 최소화.
# 단방향 (WSL → Windows). rsync 가 변경분만 보내서 호스트 fs 부하 작음.
{
  while true; do
    sleep "$RSYNC_INTERVAL"
    # -t: timestamp 보존, --inplace: 변경분만 write, --no-times-from: 무시
    rsync -t --inplace \
      "$LOG_DIR/resources.log" \
      "$LOG_DIR/processes.log" \
      "$LOG_DIR/io.log" \
      "$LOG_DIR/kernel.log" \
      "$LOG_DIR/journal.log" \
      "$WIN_LOG_DIR/" 2>/dev/null || true
  done
} &
echo $! >> "$PID_FILE"

echo "[monitor] started — pids: $(cat $PID_FILE | tr '\n' ' ')"
echo "[monitor] WSL logs:          $LOG_DIR/"
echo "[monitor] Windows mirror:    $WIN_LOG_DIR/  (30s rsync, freeze 시에도 호스트 접근 가능)"
echo "[monitor] stop with: kill \$(cat $PID_FILE)"
