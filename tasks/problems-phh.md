# Problems Log (phh workspace)

> 세션 복귀 시 가장 먼저 읽는 곳. 미해결 / 의심 / 재현 가능한 이슈 모음.
> 해결된 항목은 `## Resolved` 섹션으로 이동.

---

## Open

### P1. `./scripts/start_stack.sh` 실행 시 WSL 무한 프리징 + 원격 끊김

**증상**:
- `start_stack.sh` 호출 → 잠시 후 WSL 자체가 응답 불가 → SSH/VSCode 원격 연결 끊김.
- 호스트 Windows 는 살아있지만 WSL 안 모든 작업 정지.

**원인 (3중 복합)**:

1. **WSL 메모리 한도 = 8GB** — `C:\Users\<user>\.wslconfig` 에서 의도적으로 제한 (호스트 보호).
   ```
   [wsl2]
   memory=8GB
   processors=6
   swap=4GB
   ```

2. **백엔드 ML 워밍업 부하** — `api_server.py` startup hook 이 mDeBERTa + GLiNER + SBERT 동시 로딩. 워밍업 자체는 2~3GB 정상 범위.
   - 마지막 로그: `[backend.log]` 가 `Loading the following GLiNER type` 에서 끊김 (워밍업 중 OOM kill 의심).

3. **프론트엔드 무한 에러 루프** (진짜 트리거) — `[frontend.log]` 에 동일 에러 12회+ 반복:
   ```
   Error: Can't resolve 'tailwindcss' in '/home/mpwsl2/a-eye/idea_2/scamguardian-v2-phh/apps'
   ```
   - `tailwindcss` 와 `@tailwindcss/postcss` 둘 다 `apps/web/node_modules/` 에 정상 설치되어 있음.
   - 문제는 **Next.js 16 Turbopack 이 root 디렉토리를 `apps/` 로 잘못 추론**. → resolve 가 `apps/node_modules` 부터 시작해 위로 거슬러 올라가 결국 `/node_modules` 까지 가서 실패.
   - 컴파일 실패 시 Turbopack 은 다음 요청에서 재시도 → 무한 에러 루프 → CPU·메모리 폭주.

**왜 Turbopack 이 root 를 잘못 잡나** (Next 16 신동작):
- Next 16 Turbopack 은 lockfile 위치 (`package-lock.json`/`yarn.lock`/`pnpm-lock.yaml`/`bun.lock`) 로 root 자동 감지.
- 우리 구조: lockfile 은 `apps/web/package-lock.json` 단 하나 존재, 상위에 lockfile 없음.
- 그런데도 Turbopack 이 `apps/` 디렉토리 패턴 (`apps/<name>` monorepo) 으로 추론해 root 를 한 단계 올림.
- 참고: `node_modules/next/dist/docs/01-app/03-api-reference/05-config/01-next-config-js/turbopack.md` 의 "Root directory" 섹션 — `turbopack.root` 옵션으로 명시 override 가능.

**해결 방안**:

A. `apps/web/next.config.ts` 에 `turbopack.root` 명시:
   ```ts
   import path from "node:path";
   import type { NextConfig } from "next";
   const nextConfig: NextConfig = {
     turbopack: {
       root: __dirname,  // 또는 path.resolve(__dirname)
     },
     // ... 기존 옵션
   };
   ```

B. `start_stack.sh` 의 backend ↔ frontend 시작 간격을 더 늘려 ML 워밍업 끝난 뒤 frontend 시작 (현재 `sleep 3` 만으로는 워밍업 완료 전).

C. WSL 메모리 압박 자체는 `.wslconfig` 의 `memory=8GB` 정책 — 호스트 보호 의도이므로 *건드리지 않는다*. 대신 stack 메모리 사용량 줄이는 방향.

**시도 순서** (다음 세션에 적용):
1. A 적용 → frontend 에러 폭주만 멈춰도 OOM 회피 가능성 높음.
2. 그래도 같으면 B (backend 시작 후 `curl /health` 폴링 → 200 받으면 frontend 시작) 로 sequential 화.
3. 그래도 같으면 `start_stack.sh` 에서 `ENABLE_NGROK=false` + tailscale funnel 만으로 테스트해 ngrok 까지 빼고 메모리 측정.

**관찰된 메모리 (kill 직후, baseline)**:
```
total 7.8Gi / used 2.1Gi / free 4.1Gi / swap 4Gi free
```
baseline 만 해도 vscode-server + claude-code + grafana + prometheus + tailscale + ollama 등으로 2.1GB 사용 중. 여기에 backend (2~3GB) + frontend (1~2GB) + ngrok 추가하면 8GB 한도 빠듯.

---

---

## Resolved

### ✅ ollama 무한루프 (이전 세션에 해결됨)

사용자 확인 (2026-05-27): 이미 해결 완료. 정확한 fix 내용은 별도 commit/log 에 있음.
세부 시나리오 (systemd 충돌 / Claude 전환 잔재 / watch_logs tail) 는 재발 시 참고용으로
이 문서 git history 에서 복원 가능.

---

## Quick triage commands

다음 세션 복귀 시 빠르게 상태 보는 명령:

```bash
# 메모리 + 상위 프로세스
free -h && ps aux --sort=-%mem | head -10

# 현재 stack 띄워져 있는지
ps aux | grep -E "(uvicorn|next dev|next-server|ngrok|ollama)" | grep -v grep

# 가장 최근 backend/frontend 로그 끝
tail -30 .scamguardian/logs/backend.log
tail -30 .scamguardian/logs/frontend.log

# WSL 메모리 한도 확인 (호스트에서)
# Windows PowerShell: type $env:USERPROFILE\.wslconfig

# ollama 시스템 서비스 확인
systemctl status ollama 2>/dev/null
ls /etc/systemd/system/ | grep ollama
```
