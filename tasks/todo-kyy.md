# Todo — kyy 워크스페이스

> CLAUDE.md 의 워크스페이스 분리 규칙에 따른 kyy 전용 todo.
> phh 워크스페이스에서 발견된 환경 공통 이슈는 아래 "공유" 섹션 참고.

---

# 🚨 공유 — Next 16 Turbopack 메모리 누수 → Webpack fallback (2026-05-28, phh 워크스페이스 발견)

> **환경 공통 이슈**. kyy 워크스페이스 작업자도 알아야. phh 에서 4시간 디버깅 후 root cause 확정.

## 증상

- `./scripts/start_stack.sh` 실행 → WSL 무한 프리징 + 원격(SSH/VSCode) 연결 끊김
- WSL 메모리 8GB → 20GB 증설 후에도 재발
- stack 안 띄웠을 때도 호스트 측 압박 체감 (작업관리자 디스크 활성 시간 50%+)

## 진단

- **첫 freeze (03:04)**: next-server **VSZ 3GB → 22GB (30초 만에 7배)**. RSS 1.2GB 만 보면 못 봄
- **frontend.log 결정 증거**: `resolve 'tailwindcss' in '.../apps'` (apps/web 아님)
- = **Turbopack root 자동 감지가 monorepo 패턴으로 잘못 추론** → tailwindcss resolve 무한 시도 → JS heap 누적 → swap thrashing → 9P 마운트 hang → D-state 좀비 → WSL freeze 악순환

## 적용된 fix (phh 에서 적용 끝)

- `apps/web/next.config.ts` — `fileURLToPath(import.meta.url)` 패턴 (`__dirname` ESM 함정 회피)
- `apps/web/package.json` — `"dev": "next dev --webpack"` (Next 16 공식 webpack fallback)
- `.wslconfig` 메모리 20GB + swap 8GB (응급 버퍼)
- `scripts/monitor_resources.sh` 신설 — D-state + 9P + wchan 진단
- `/mnt/c/Users/mpssh/Documents/wsl_logs/` 호스트 미러 — freeze 후에도 외부 진단

## kyy 워크스페이스가 주의할 것

- **Next 버전 올리지 말 것** (16.2.1 유지)
- **Tailwind 큰 버전 변경 시 재발 가능** (현재 4 사용)
- **`apps/web` 구조 변경 시 turbopack root 재검증 필수**
- **freeze 진단 시 RSS 가 아닌 VSZ + D-state wchan 봐야**

## 상세 기록

- 작업 항목 + Review: [tasks/todo-phh.md](tasks/todo-phh.md) 의 2026-05-28 섹션
- 학습 패턴: [tasks/lessons.md](tasks/lessons.md) 의 2026-05-28 패턴

---

## kyy 워크스페이스 작업 (시작 시 여기에 기록)

(처음 사용 시 채워 넣기)
