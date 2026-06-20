# ScamGuardian

한국어 멀티모달 **사기 신호 검출** 플랫폼.

> VirusTotal 이 70개 백신의 검출 결과를 보고만 하고 판정하지 않는 것과 동일한 모델 —
> ScamGuardian 은 텍스트·URL·이미지·PDF·APK·통화 음성에서 위험 신호를 추출하고
> 학술/법적 근거를 transparent 하게 제공합니다. **판정은 통합 기업이** 자기 risk tolerance 에 따라 합니다.

## 담당 역할

전체 시스템 아키텍처, 백엔드 API, 프론트엔드, DB 구조, 분석 파이프라인, 샌드박스 연동,
학습 시스템, 테스트 스위트, 운영 스크립트 — 모두 직접 설계·구현한 팀 프로젝트입니다.

단순 이진 분류기가 아닌, 복수 입력 모달에서 의심 신호를 추출하고 근거와 함께 보고하는
**멀티모달 사기 신호 탐지 reference architecture** 로 설계했습니다.

---

## 빠른 실행

### 의존성 설치

```bash
pip install -r requirements.txt
pip install pypdfium2          # PDF vision OCR 에 필수

cd apps/web && npm install
cp .env.example .env.local    # SCAMGUARDIAN_API_URL 설정
```

### 로컬 개발 (개별 실행)

```bash
# 백엔드
uvicorn api_server:app --reload

# 프론트엔드 (별도 터미널)
cd apps/web && npm run dev
```

### 전체 스택 한 번에

```bash
./scripts/start_stack.sh    # conda 환경 capstone 사용, 기본 포트 8000/3100
./scripts/watch_logs.sh     # backend / frontend / ngrok 로그 동시 tail
```

`start_stack.sh` 는 다음 순서로 기동합니다:
1. 리소스 모니터 (`scripts/monitor_resources.sh`, 5s 샘플링)
2. uvicorn 백엔드 (polling /health 최대 120s 대기)
3. Next.js 프론트엔드 (Turbopack 초기 컴파일 완료까지 대기)
4. Tailscale Funnel 공개 터널 + funnel_watchdog (자동 복구)
5. ngrok 보조 터널 (카카오 오픈빌더 전용 — .ts.net 도메인 거부 우회)
6. 카카오 watchdog (`scripts/kakao_watchdog.sh`, 20s 주기 webhook probe)

환경변수 `CONDA_ENV`, `BACKEND_PORT`, `FRONTEND_PORT`, `NGROK_DOMAIN` 으로 조정 가능.

### CLI 분석

```bash
python run_analysis.py "https://youtube.com/watch?v=..."
python run_analysis.py --text "투자 설명 텍스트"
```

### 테스트

```bash
pytest            # ~120 tests
pytest -v tests/test_gate.py
```

---

## 무엇을 만들었나

### 핵심 채널

| 채널 | 경로 | 설명 |
|---|---|---|
| **웹 분석** | `/` | 텍스트·URL·파일·이미지·PDF 업로드 분석 |
| **카카오톡 챗봇** | `POST /webhook/kakao` | 멀티턴 컨텍스트 수집 + 백그라운드 분석 |
| **라이브 통화 탐지** | `/live` `/live/[token]` | 마이크 PCM → WebSocket STT → 실시간 신호 스캔 |
| **APK 검사** | `/apk` | 업로드/샘플 APK 4-tier 정적+동적 검출 |
| **결과 공개 페이지** | `/result/[token]` | 1시간 TTL 공개 링크 (카카오 카드 연결) |
| **REST API** | `POST /api/analyze` | 외부 클라이언트 (API key 필수) |
| **어드민** | `/admin/*` | 라벨링 큐·플랫폼·학습·증강·모델 관리 |
| **데모** | `/demo` | ML 파이프라인·APK·Live 시각화 허브 |

---

## 아키텍처

### 전체 데이터 흐름

```
입력 경로
  카카오톡 챗봇  ─→  POST /webhook/kakao
  웹 브라우저   ─→  Next.js (/api/*) ─→  POST /api/analyze
  CLI           ─→  python run_analysis.py
  라이브 통화   ─→  WebSocket /ws/live-transcribe (PCM 스트림)
        │
        ▼
  ScamGuardianPipeline.analyze()  (pipeline/runner.py)
        │
  Phase 0:   VirusTotal 안전성 검사 (URL·파일)
  Phase 0.5: 격리 Chromium URL 디토네이션 (SANDBOX_ENABLED=1 시)
  Phase 1:   STT / vision OCR — Whisper(음성) | Claude vision(이미지·PDF)
             [병렬] Gate (content_label 3-class 라우팅)
  Phase 2:   스캠 유형 분류 (fine-tuned mDeBERTa 또는 zero-shot NLI)
  Phase 3:   ┌ LLM 통합 호출 (Claude Haiku) ┐  ← ThreadPoolExecutor
             ├ GLiNER 엔티티 추출           │
             └ RAG 유사 사례 검색           ┘
  Phase 4:   Serper API 교차검증 (엔티티별 병렬, 세마포어 레이트 리미팅)
  Phase 5:   스코어링 → ScamReport
        │
  ┌─────┴──────┐
  db/           카카오 포맷   JSON 응답
  (run 저장)   (결과 카드)   (웹/CLI)
```

### 3단계 캐스케이드 분류

```
Stage 1 — 콘텐츠 게이트 (pipeline/gate.py)
  입력 → fine-tuned mDeBERTa (또는 Claude Haiku fallback)
  → content_label: 정상 / 사기시도 / 사기뉴스교육 / 의심불충분 / 판단불가
  → bucket 별 분석 강도 라우팅 (Serper·LLM 가지치기)
  → 룰 기반 신호 검출은 항상 실행 (게이트 오판 시 누락 방지)

Stage 2 — 스캠 유형 분류 (pipeline/classifier.py)
  → scam_type 12종 multi-label + 상위 N개 유형의 엔티티 라벨셋 합집합 전달
  → 복합 스캠 엔티티 누락 해소, 표면 scam_type 은 top-1 유지

Stage 3 — 신호 그룹핑 (pipeline/flag_groups.py)
  → 51개 DETECTED_FLAGS 완전 보존
  → 11개 의미 그룹으로 묶는 표시 레이어만 추가
```

### 파이프라인 단계별 핵심 파일

| 단계 | 파일 | 역할 |
|---|---|---|
| Phase 0 | `pipeline/safety.py` | VirusTotal URL/파일 스캔, 4 req/min 토큰버킷 |
| Phase 0.5 | `pipeline/sandbox.py` | URL 디토네이션 (local Docker or remote VM) |
| Phase 1 | `pipeline/stt.py` `pipeline/vision.py` | Whisper STT + Claude vision OCR |
| Gate | `pipeline/gate.py` | content_label 3-class, 뉴스 heuristic fast-path |
| Phase 2 | `pipeline/classifier.py` | 스캠 유형 분류, active_models.json swap |
| Phase 3 | `pipeline/extractor.py` `pipeline/llm_assessor.py` `pipeline/rag.py` | GLiNER + LLM + RAG 병렬 |
| Phase 4 | `pipeline/verifier.py` | Serper 교차검증 |
| Phase 5 | `pipeline/scorer.py` | 플래그 합산 + ScamReport |
| Kakao | `pipeline/kakao_formatter.py` `pipeline/kakao_dialog.py` | 카드 포맷 + 컨텍스트 챗봇 |

### 카카오 챗봇 흐름

```
사용자가 콘텐츠 전송 (텍스트/URL/이미지/APK)
  └─ 1차 분석 백그라운드 시작
  └─ 첫 질문 즉답 (static Q1, ~50ms)

멀티턴 컨텍스트 수집 (Claude Haiku, 1~3s/turn)
  → 본문 단서 짚으며 능동 질문 → 사용자 답변 누적

[1차 분석 완료 — 사용자에게는 알리지 않음]
  → 다음 답변에 "💡 분석 끝났어요, 결과확인 누르세요" 1회 부착

사용자 "결과확인" 요청
  → user_context 반영 refine (LLM phase만 재호출, ~5-10s)
  → 결과 카드 + "자세한 결과 보기" webLink (/result/[token])
```

### Live v4 — 실시간 통화 중 탐지

```
카카오 트리거 ("지금 검찰청 전화") 또는 /live 직접 접속
  → 1회용 세션 토큰 발급 (TTL 1시간)
  → /live/[token] 페이지로 마이크 권한 요청

브라우저 AudioWorklet (16kHz mono PCM)
  → WebSocket /ws/live-transcribe
  → 3초 chunk 누적 → OpenAI Whisper STT
  → 즉시 신호 스캔 (text_rules + Haiku 한 줄)

임계 초과 → WebSocket push 경보
  → 빨간 fullscreen alert "🚨 전화 끊으세요!" + 경보음

통화 종료 → transcript DB 저장 + 사후 분석
```

구현 파일: `api_server_pkg/live_ws.py`, `pipeline/live_stt.py`,
`apps/web/src/app/live/useLiveWebSocket.ts`, `apps/web/public/live-pcm-processor.js`

WebSocket fallback: `POST /api/live-pcm-chunk` (PCM HTTP, 최후 수단)

환경변수:
- `LIVE_WS_ENABLED=1` — WebSocket 활성화
- `OPENAI_API_KEY` — Whisper STT
- `NEXT_PUBLIC_LIVE_WS_URL` — 브라우저가 직접 연결할 WSS URL (Tailscale/ngrok)

### APK 검출 4-tier

한국 보이스피싱 attack chain 의 핵심은 사이드로딩으로 설치되는 악성 APK.
ScamGuardian 은 네 단계로 검출합니다 (판정 X, 검출 보고만):

| Tier | 구현 | 검출 내용 |
|---|---|---|
| **1 — VT 시그니처** | `pipeline/safety.py` | 70+ 백신 합의, 알려진 멀웨어 hash |
| **2 — 정적 분석 Lv1** | `pipeline/apk_analyzer.py` | manifest 권한 조합 (SMS+Accessibility 등), 자기서명, 패키지명 위장 |
| **3 — 정적 분석 Lv2** | `pipeline/apk_analyzer.py` | dex bytecode xref — SmsManager·TelephonyManager·DeviceAdmin·C&C URL·난독화 |
| **4 — 동적 분석** | `apk_dynamic_server/` (격리 VM) | redroid + Frida 런타임 hook — 실제 실행 관찰 |

Tier 1~3: 정적 분석 검출률 학술 기준 **60-80%** (Arzt et al. FlowDroid, Wei et al. DeepGini).
Tier 4: 격리 VM 에서만 실행, 기본 비활성 (`APK_DYNAMIC_ENABLED=0`).
로컬 실행은 HARD BLOCK (호스트 위험).

---

## 디렉터리 구조

```
api_server.py               FastAPI 진입점
api_server_pkg/             라우터 패키지
  app.py                      FastAPI 앱 생성 + 라우터 등록
  analyze.py                  /api/analyze (메인 분석)
  kakao/                      카카오 webhook (router/detect/commands)
  live_ws.py                  WebSocket /ws/live-transcribe
  live_session_token.py       Live v4 1회용 세션 토큰 발급·검증
  live_pcm_http.py            /api/live-pcm-chunk (WS fallback)
  result_token.py             /api/result/[token] (공개 결과 페이지)
  admin_*.py                  어드민 라우터 (runs/training/platform/augment/users)
  androzoo_*.py               AndroZoo APK 비교 세션
  demo_snapshot.py            /api/demo/ml-snapshot (데모 ML 상태)
  apk_public.py               /apk 공개 APK 검사 페이지

pipeline/                   7-Phase 분석 파이프라인
  runner.py                   오케스트레이터 (ScamGuardianPipeline.analyze)
  runner_input_phases.py      Phase 0~1 입력 처리 분리
  gate.py                     Stage 1 콘텐츠 게이트 (content_label)
  classifier.py               Stage 2 스캠 유형 분류
  extractor.py                GLiNER 엔티티 추출
  llm_assessor.py             Claude Haiku 보조 판정 (analyze_unified)
  rag.py                      SBERT 유사 사례 벡터 검색
  verifier.py                 Serper API 교차검증
  scorer.py                   플래그 합산 → ScamReport
  safety.py                   Phase 0 VirusTotal
  sandbox.py                  Phase 0.5 URL 디토네이션
  stt.py / stt_common.py / stt_claude.py / stt_clova.py   STT 체인
  vision.py                   Claude vision OCR (이미지·PDF)
  live_stt.py                 Live v4 PCM 버퍼 + Whisper chunk
  apk_analyzer.py             APK 정적 분석 Lv1+Lv2
  signal_detector.py          룰 기반 신호 검출
  text_rules.py               텍스트 패턴 룰 (정규식 기반)
  flag_groups.py              Stage 3 신호 그룹핑 레이어
  config.py                   facade → config_taxonomy/gate/flags
  config_taxonomy.py          스캠 유형·라벨셋
  config_gate.py              게이트 bucket 정의
  config_flags.py             FLAG_RATIONALE 51종 (학술/법적 근거)
  kakao_formatter.py          facade → kakao_result/dialog
  kakao_result.py             결과 카드 포맷
  kakao_dialog.py             컨텍스트 챗봇 + 의도 분류
  context_chat.py             멀티턴 컨텍스트 수집
  active_models.py            active_models.json 60s TTL 캐시
  inference_device.py         CUDA/CPU 자동 디바이스 선택

platform_layer/             플랫폼 미들웨어
  api_keys.py                 sg_<urlsafe> 발급·lookup·revoke
  pricing.py                  Claude/Whisper/Serper/VT 가격표
  cost.py                     비용 ledger (contextvars 기반)
  rate_limit.py               per-key RPM + 월별 quota + USD cap
  abuse_guard.py              짧은 메시지 누적 자동 블록
  middleware.py               FastAPI PlatformMiddleware

db/                         DB 계층
  repository.py               Postgres / SQLite facade
  sqlite_repository.py        facade → core/runs/platform
  platform_facade.py          api_keys·cost_events·request_log

apps/web/                   Next.js 16 프론트엔드
  src/app/
    page.tsx                  홈 (분석 입력 + 결과 모달)
    live/                     Live v4 UI (useLiveWebSocket, [token]/)
    admin/                    어드민 (runs/training/augment/models)
    apk/                      APK 공개 검사 페이지
    demo/                     ML·APK·Live 시각화 데모 허브
    result/[token]/           공개 결과 상세 페이지
    api/                      Next.js Route Handler (FastAPI 프록시)
    methodology/              방법론 설명 페이지
    evidence/                 근거 페이지

training/                   Fine-tuning 시스템
  train_classifier.py         mDeBERTa SFT + LoRA
  train_gliner.py             GLiNER fine-tune
  sessions.py                 subprocess 세션 관리자
  session_files.py            세션 파일 I/O 유틸
  data.py                     DB + 외부 JSONL → 학습 예제

scripts/                    운영·배치 스크립트
  start_stack.sh              전체 스택 기동 (권장)
  restart_stack.sh            재시작 (conda 없는 환경)
  watch_logs.sh               3개 로그 동시 tail
  kakao_watchdog.sh           카카오 webhook 자가복구 watchdog
  funnel_watchdog.sh          Tailscale Funnel 자동 복구
  monitor_resources.sh        메모리·CPU 샘플링
  apk_dynamic_vm_ctl.sh       APK 동적 분석 VM 전체 제어
  evaluate_gate.py            게이트 평가 CLI → eval/
  evaluate_gate_holdout.py    게이트 holdout 평가
  evaluate_scam_type.py       스캠 유형 분류 평가 CLI
  train_scam_type_classifier.py  분류기 학습 CLI
  debug_single_analysis.py    단건 파이프라인 디버그
  batch_ingest.py             seed 배치 DB 저장
  augment_seeds.py / augment_seeds_concurrent.py  seed 증강 (CLI)

apk_dynamic_server/         APK 동적 분석 서버 (격리 VM 전용)
  app.py                      FastAPI /dynamic-analyze (Bearer 토큰)
  analyzer.py                 redroid adb install + Frida hook 실행
  frida_hooks.js              SMS·TelephonyManager·Accessibility·DeviceAdmin hook

sandbox_server/             URL 디토네이션 서버 (격리 VM 전용)
  app.py                      FastAPI /detonate + /health (Bearer 토큰)

eval/                       평가 산출물
  gate_eval_report.json       게이트 in-distribution 평가
  gate_holdout_report.json    게이트 holdout 평가
  scam_type_eval_report.json  스캠 유형 분류 평가
  *.csv                       confusion matrix

data/processed/             학습 데이터
  admin_seeds.jsonl           실물 seed 244건
  user_samples_augmented.jsonl  증강 학습 데이터 4,362건

docs/                       실험 결과·데이터 감사·통합 가이드
archive/                    완료된 브랜치 노트
journal/                    디버깅 일지
```

---

## VM 설정

### APK 동적 분석 VM (sg-sandbox)

Multipass Ubuntu 22.04 VM 안에서 redroid(Android-in-Docker) + Frida 로 실제 APK 실행.
**본 프로세스는 VM 안에서만, production 호스트에서 절대 실행 불가.**

```bash
# VM 생성 (최초 1회, Windows PowerShell 또는 WSL)
multipass launch 22.04 --name sg-sandbox --cpus 4 --memory 6G --disk 30G

# VM 부트스트랩 (최초 1회 — Docker·binder·redroid·frida-server 설치)
./scripts/apk_dynamic_vm_ctl.sh bootstrap

# 평소 기동: VM 시작 → 코드 sync → redroid → frida-server → FastAPI
./scripts/apk_dynamic_vm_ctl.sh start

# 메인 .env 에 APK_DYNAMIC_* 연결값 자동 반영
./scripts/apk_dynamic_vm_ctl.sh apply-env

# 상태 확인 / 연결 테스트
./scripts/apk_dynamic_vm_ctl.sh status
./scripts/apk_dynamic_vm_ctl.sh health
python scripts/check_apk_dynamic_remote.py --apk tests/fixtures/dynamic_active.apk

# VM 중지
./scripts/apk_dynamic_vm_ctl.sh stop
```

`apply-env` 실행 후 메인 서버 재시작하면 `APK_DYNAMIC_BACKEND=remote` 로 자동 연결.

VM 이 없거나 꺼져 있으면 APK 동적 분석은 자동 skip (정적 분석 3-tier 만 수행).

### URL Sandbox VM (선택)

피싱 URL 을 격리 Chromium 으로 직접 navigate 해 제로데이 피싱 검출.
별도 VM/VPS 에 `sandbox_server/app.py` 배포 후 환경변수 설정:

```bash
SANDBOX_ENABLED=1
SANDBOX_BACKEND=remote
SANDBOX_REMOTE_URL=http://<vm-ip>:8001
SANDBOX_REMOTE_TOKEN=<shared-bearer-token>
```

Multipass 배포 가이드: `sandbox_server/README.md`.

---

## 환경 변수 (`.env`)

```bash
# 필수
ANTHROPIC_API_KEY=sk-ant-...     # LLM 판정·카카오 챗봇·vision OCR
OPENAI_API_KEY=sk-...            # Whisper STT (없으면 로컬 whisper)
SERPER_API_KEY=...               # Phase 4 교차검증
VIRUSTOTAL_API_KEY=...           # Phase 0 안전성

# 스토리지
SCAMGUARDIAN_SQLITE_PATH=.scamguardian/scamguardian.sqlite3   # 기본
SCAMGUARDIAN_DATABASE_URL=postgresql://...                     # Postgres 사용 시
SCAMGUARDIAN_PERSIST_RUNS=true

# 공개 URL (결과 페이지 링크)
SCAMGUARDIAN_PUBLIC_URL=https://your-domain.com  # 없으면 ngrok 자동 발견

# 모델
ANTHROPIC_MODEL=claude-sonnet-4-6
ANTHROPIC_HAIKU_MODEL=claude-haiku-4-5-20251001
SCAMGUARDIAN_INFERENCE_DEVICE=auto   # auto/cpu/cuda

# 라이브 v4
LIVE_WS_ENABLED=1
LIVE_CHUNK_SEC=3                     # chunk 길이 (s). 정확도 우선 시 5
NEXT_PUBLIC_LIVE_WS_URL=wss://...    # 브라우저 직접 연결 WSS

# APK 동적 분석
APK_DYNAMIC_ENABLED=0                # 기본 비활성
APK_DYNAMIC_BACKEND=auto             # auto/local/remote
APK_DYNAMIC_REMOTE_URL=http://<vm>:8002
APK_DYNAMIC_REMOTE_TOKEN=<token>

# URL Sandbox
SANDBOX_ENABLED=0
SANDBOX_BACKEND=auto
SANDBOX_REMOTE_URL=http://<vm>:8001
SANDBOX_REMOTE_TOKEN=<token>

# 플랫폼
SCAMGUARDIAN_CORS_ORIGINS=http://localhost:3000,...
ABUSE_SOFT_THRESHOLD=10
ABUSE_BLOCK_DURATION=3600
```

---

## Claude 사용 현황

| 단계 | 모델 | 조건 |
|---|---|---|
| Gate — 콘텐츠 판별 | Claude Haiku | fine-tuned 로컬 모델 실패 시 fallback |
| Phase 1 — vision OCR | Claude Sonnet | 이미지·PDF 입력 시 |
| Phase 3 — LLM 보조 판정 | Claude Haiku | gate=scam_attempt 시에만 |
| 카카오 컨텍스트 챗봇 | Claude Haiku | 멀티턴 질문 생성 |
| Live STT 신호 스캔 | Claude Haiku | 즉시 경보 신호 분류 |
| 증강 | Claude Sonnet | /admin/augment seed 패러프레이즈 |

`gate=normal` / `gate=scam_news_edu` 로 라우팅되면 Phase 3 LLM 호출 없음.

---

## API 보안

- `POST /api/analyze` — `Authorization: Bearer sg_...` 또는 `X-API-Key` 필수
- `POST /webhook/kakao` — 카카오 자체 인증, API key skip
- `GET /api/result/[token]` — 1시간 TTL 공개 토큰
- Rate limit 초과 → `429 Retry-After`
- 어뷰즈 자동 블록 → `423 Locked`

---

## 학습 시스템

```bash
# 1) seed 증강 (웹: /admin/augment, CLI:)
python -m scripts.run_augment_session \
    --seed-file data/processed/admin_seeds.jsonl \
    --output /tmp/aug.jsonl --variants 5 --content-label normal

# 2) 게이트 학습·평가 (웹: /admin/training 게이트 패널, CLI:)
python scripts/content_label_gate.py \
    --input data/generated/user_samples_augmented.jsonl --train

# 3) 스캠 유형 분류기 (웹: /admin/training, CLI:)
python scripts/train_scam_type_classifier.py \
    --input data/generated/user_samples_augmented.jsonl \
    --output checkpoints/classifier-v1 --epochs 3

# 4) /admin/training "파이프라인 적용" → .scamguardian/active_models.json 갱신 → 60s 내 적용
```

게이트 성능 (3-class, group-split val): accuracy **0.979** / macro_f1 **0.960**
정상→사기 오탐: 14.5% → **2.6%** (정상 hard negative 보강 후)

---

## 배포

- **Frontend**: Vercel (Root Directory: `apps/web`)
- **Backend**: Render / VPS (`uvicorn api_server:app --host 0.0.0.0 --port $PORT`)
- **Live WebSocket**: 브라우저가 FastAPI 에 직접 연결 — Next.js 프록시 불가
  `NEXT_PUBLIC_LIVE_WS_URL=wss://your-api.onrender.com` 설정 필요
- **APK 동적 분석 VM**: Multipass Ubuntu 22.04 (Win11 Hyper-V) 또는 클라우드 VPS
- **URL Sandbox VM**: 별도 VM/VPS — `sandbox_server/README.md`
- 세부: `DEPLOY.md`, `render.yaml`

---

## 상세 문서

| 문서 | 내용 |
|---|---|
| `CLAUDE.md` | 아키텍처 전체 + APK 4-tier + Identity Boundary + 환경변수 전체 |
| `DEPLOY.md` | Vercel/Render 배포 + Live WS 환경변수 |
| `.scamguardian/README.md` | 런타임 상세 (시나리오·API·플래그 명세) |
| `training/FINETUNING.md` | Fine-tuning 전 과정 가이드 |
| `docs/` | 실험 결과·데이터 감사·통합 가이드 |
| `changes.md` | 마일스톤 단위 변경 이력 |
| `apk_dynamic_server/README.md` | APK VM 상세 배포 가이드 |
| `sandbox_server/README.md` | URL Sandbox VM 배포 가이드 |
