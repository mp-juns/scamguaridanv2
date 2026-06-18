#!/usr/bin/env bash
# funnel_watchdog.sh — Tailscale Funnel 공개 경로 자동 복구 워치독
#
# 문제: WSL ↔ DERP(도쿄 릴레이) 연결이 간헐적으로 flapping 하면 tailscaled 는 자동
# 재접속하지만 Funnel ingress 세션은 stale 로 남는다 — 로컬 `funnel status` 는 "on",
# 실제 외부 접속은 TLS ClientHello 직후 EOF. (2026-06-12 진단: derp-7 connGen 반복 증가)
#
# 점검 방법: 이 머신에서 그냥 curl 하면 MagicDNS 가 tailnet 내부 경로로 연결해 버려
# 항상 성공한다. `--doh-url` 로 공개 DNS(DoH) 를 강제해 *진짜 공개 ingress 경로* 를 탄다.
#
# 실행: start_stack.sh 가 nohup 으로 자동 실행. 단독 실행도 가능:
#   nohup ./scripts/funnel_watchdog.sh >> .scamguardian/logs/funnel_watchdog.log 2>&1 &
set -u

HOST="${FUNNEL_HOST:-scamguardian.tail7e5dfc.ts.net}"
FRONTEND_PORT="${FRONTEND_PORT:-3100}"
INTERVAL="${FUNNEL_WATCH_INTERVAL:-120}"   # 점검 주기 (초)
DOH="https://dns.google/dns-query"

log() { echo "[funnel-watchdog] $(date '+%F %T') $*"; }

probe() {
  # 공개 DoH 로 해석 → Funnel ingress 릴레이를 실제로 경유. 2xx/3xx 면 정상.
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 \
    --doh-url "$DOH" "https://${HOST}/" 2>/dev/null) || code=000
  [[ "$code" =~ ^[23] ]]
}

log "시작 — host=$HOST interval=${INTERVAL}s frontend=$FRONTEND_PORT"
fails=0
while true; do
  if probe; then
    if (( fails > 0 )); then log "복구 확인 (이전 연속 실패 ${fails}회)"; fi
    fails=0
  else
    fails=$((fails + 1))
    log "공개 경로 응답 없음 (연속 ${fails}회)"
    # 일시적 출렁임에 과민 반응하지 않도록 2회 연속 실패부터 재기동
    if (( fails >= 2 )); then
      log "funnel 재기동 시도..."
      tailscale funnel --https=443 off >/dev/null 2>&1 || true
      sleep 2
      tailscale funnel --bg "http://127.0.0.1:${FRONTEND_PORT}" >/dev/null 2>&1 \
        && log "funnel 재기동 완료" || log "funnel 재기동 실패 — 다음 주기에 재시도"
      fails=0
    fi
  fi
  sleep "$INTERVAL"
done
