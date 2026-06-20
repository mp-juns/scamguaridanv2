## ScamGuardian Web (v3)

Next.js 16 App Router 기반 웹 어드민 + 결과·methodology·training UI.
**Python FastAPI 가 모든 비즈니스 로직을 가지고**, 이 웹은 thin proxy + UI 레이어.

### 페이지 구조

| 경로 | 용도 |
|------|------|
| `/` | 분석 입력 화면 (텍스트·URL·파일 업로드) |
| `/admin` | 라벨링 큐 — 검수자 claim, 필터 |
| `/admin/[runId]` | 라벨 편집 — AI 초안, 엔티티/플래그, **원본 미디어** (영상·오디오·이미지·PDF) 뷰어 |
| `/admin/stats` | DB 대시보드 — 분포·추이 |
| `/admin/browse` | DB 브라우저 — 검색·필터 |
| `/admin/training` | **v3** — Fine-tuning 세션 (시작·진행률·활성화) |
| `/admin/training/about` | **v3** — 모델 역할 + 파이프라인 위치 + 학습 효과 설명 |
| `/admin/platform` | **v3.x** — API key 발급·revoke + observability(p50/p95) + 비용 대시보드 |
| `/methodology` | 검출 방법론 — 신호 카탈로그·근거·임계값 |
| `/result/[token]` | 카카오 카드 "자세한 결과 보기" 페이지 (1시간 토큰) |

### Local Development

```bash
# 1) Python API 먼저 (루트에서)
uvicorn api_server:app --reload

# 2) 웹 앱
cp .env.example .env.local
npm install
npm run dev -- --port 3100
```

### 환경 변수

```bash
SCAMGUARDIAN_API_URL=http://127.0.0.1:8000
```

### API 우선 — 모든 라우트는 thin proxy

`apps/web/src/app/api/*` 의 모든 Route Handler 는 `proxyJsonRequest` / `proxyGet` 만 사용합니다 (`api/_lib/backend.ts`). 비즈니스 로직 0 — Python API 그대로 통과.

새 엔드포인트가 필요하면:
1. `api_server.py` 에 FastAPI 엔드포인트 추가
2. `apps/web/src/app/api/.../route.ts` 한 줄짜리 프록시 작성
3. UI 에서 `fetch('/api/...')` 호출

이 패턴 덕분에 모바일 앱·외부 SDK 도 같은 Python 엔드포인트를 직접 부를 수 있습니다.

### Next.js 16 주의사항

이 프로젝트는 **Next.js 16** 입니다 — App Router·params·route handler 시그니처 등이 이전 메이저와 다릅니다.

코드 작성 전 `node_modules/next/dist/docs/` 의 관련 가이드를 먼저 확인하세요.

자세한 규칙은 `apps/web/AGENTS.md` 참고.

### v3 신규 페이지 메모

- **`/admin/training`** — recharts 로 학습 메트릭(loss, eval F1, accuracy) 실시간 그래프. 진행 중 세션은 5초 폴링.
- **`/admin/training/about`** — 분류기·GLiNER 가 파이프라인 어디에 쓰이는지 다이어그램 + before/after 표 + 권장 학습 분량.
- **결과 페이지 안전성 경고** (`/result/[token]`) — `safety_check.threat_level` 이 malicious/suspicious 면 검출 요약보다 위에 prominent.
- **AdminRunEditor 미디어 뷰어** — 영상(`<video>`), 오디오(`<audio>`), 이미지(`<img>`), PDF(`<iframe>`) 모두 지원.

### Deploy

- Vercel Root Directory: `apps/web`
- 필수 env: `SCAMGUARDIAN_API_URL`

전체 배포 절차: 루트의 `DEPLOY.md`.
