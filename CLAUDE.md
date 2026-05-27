# CLAUDE.md
## Workflow Orchestration
### 1. Plan Node Default
- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions)
- If something goes sideways, STOP
and re-plan immediately
- Use plan mode for verification steps, not just building Write detailed specs upfront to reduce ambiguity
### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean
- Offload research, exploration, and parallel analysis to subagents
- For complex problems, throw more compute at it via subagents
- One tack per subagent for focused execution
### 3. Self-Improvement Loop
- After ANY correction from the user: update tasks/lessons.md with the pattern
- Write rules for yourself that prevent the same mistake
- Ruthlessly iterate on these lessons until mistake rate drops
- Review lessons at session start for relevant project
### 4. Verification Before Done
Never mark a task complete without proving it works
- Diff behavior between main and your changes when relevant
- Ask yourself:
"Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness
### 5. Demand Elegance (Balanced)
- For non-trivial changes: pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution"
- Skip this for simple, obvious fixes - don't over-engineer
- Challenge your own work before presenting it
### 6. Autonomous Bug Fixing
- When given a bug report: just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests -- then resolve them
- Zero context switching required from the user
- Go fix failing CI tests without being told how
## Task
Management
1. Plan First:
Write plan to tasks/todo.md with checkable items
2.
Verify Plan:
Check in before starting implementation
3.
Track Progress:
Mark items complete as you go
Explain Changes:
High-level summary at each step
Document Results: Add review section to tasks/todo.md
Capture Lessons:
Update tasks/lessons. md after corrections

### Workspace-Separated Todo Files (MANDATORY)

프로젝트 루트 디렉토리 이름의 접미사에 따라 **별도 todo 파일** 을 사용합니다.
같은 `tasks/todo.md` 를 여러 워크스페이스에서 공유하면 머지 충돌·작업 혼선이 생기므로
워크스페이스마다 격리시킵니다.

**규칙**:
- 루트 디렉토리 이름이 `*-phh` 로 끝나면 → `tasks/todo-phh.md` 만 사용·갱신
- 루트 디렉토리 이름이 `*-kyy` 로 끝나면 → `tasks/todo-kyy.md` 만 사용·갱신
- 접미사 없는 (기본 `scamguardian-v2/`) 워크스페이스 → 기존 `tasks/todo.md` 사용
- 새 collaborator 추가 시 같은 패턴으로 `tasks/todo-<initials>.md` 신규 파일

**적용 범위** (이 규칙이 가리키는 "todo 파일" 모두):
- 위 Task Management 1·3 단계의 "Write plan to tasks/todo.md", "Add review section to tasks/todo.md"
- 향후 todo 갱신·체크리스트 마킹·review 추가 시 *반드시* 현재 워크스페이스에 맞는 파일

**금지**:
- `*-phh` 워크스페이스에서 `tasks/todo.md` (접미사 없는 파일) 를 수정하지 말 것
- `*-kyy` 워크스페이스에서 `tasks/todo-phh.md` 를 수정하지 말 것
- 워크스페이스 식별이 모호하면 즉시 사용자에게 확인
## Core Principles
- Simplicity First:
- No Laziness:
- Minimal Impact:
Make every change as simple as possible. Impact minimal code.
Find root causes. No temporary fixes. Senior developer standards.
Changes should only touch what's necessary. Avoid introducing bugs.
This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

ScamGuardian v3 — 한국어 음성·텍스트·이미지·PDF 사기 탐지 AI 파이프라인. 카카오 챗봇·웹·CLI 모두 같은 코어 사용.

- **API 우선 설계**: 모든 비즈니스 로직은 FastAPI (`api_server.py`) 에. Next.js 는 thin proxy(`apps/web/src/app/api/_lib/backend.ts`) + UI. 모바일·외부 SDK 는 같은 REST 엔드포인트 직접 호출 가능.
- **Frontend**: Next.js 16 App Router (`apps/web/`) — Next 16은 기존 버전과 API·컨벤션이 다릅니다. `node_modules/next/dist/docs/`를 먼저 확인하세요.
- **Backend**: FastAPI (`api_server.py`) — 분석·webhook·라벨링·학습 세션·결과 토큰 페이지 모두 한 서버.
- **Pipeline**: `pipeline/` — **7 phase** (Phase 0 Safety + Phase 0.5 Sandbox + Phase 1 STT/Vision + Phase 2~5)
- **Platform layer**: `platform_layer/` — API key·rate limit·cost ledger·observability·abuse_guard middleware
- **DB**: Postgres(+pgvector) 또는 SQLite, `db/repository.py`가 Facade 역할
- **v3 신규**: Phase 0 안전성 필터 (VirusTotal), Phase 1 멀티모달 입력 (이미지·PDF vision OCR), Fine-tuning 웹 UI + 자동 swap.
- **v3.5 신규**: Phase 0.5 — 격리 Chromium 으로 의심 URL 직접 navigate (zero-day 피싱 탐지). 운영은 별도 VM/VPS 분리 (`sandbox_server/`).
- **v3.x 신규**: API key 시스템(3중 cap), 비용 추적 ledger, 어뷰즈 가드(짧은 메시지 누적 자동 블록), pytest 테스트.

## Identity — Detection, not Judgment (Critical Boundary)

ScamGuardian 의 정체성은 **사기 판정 시스템이 아니라 사기 신호 검출 reference implementation** 이다.
모델은 VirusTotal 과 동일 — 70개 백신의 검출 결과를 *보고만* 하고 "이 파일은 사기다" 라고 *판정하지 않음*.
판정 logic 은 통합한 기업(통신사·은행·메신저 앱)이 자기 risk tolerance 에 따라 구현.

이전까지 노출하던 점수(15·20·50·80) 와 등급(안전/의심/위험/매우위험) 은 학부 단계에서
자체 RCT 없이 정당화 불가능 — 따라서 외부 인터페이스에서는 **검출 사실만** 노출하고,
점수·등급은 통합 기업의 use case 별 logic 영역으로 이관한다.

### What ScamGuardian Does NOT Do
- ❌ 사기/정상 **판정 (judgment)** — 안 함
- ❌ **위험 점수** (15·20·50·80 같은 숫자) — 외부 응답 schema 에서 표면 노출 안 함
- ❌ **위험 등급** (안전/의심/위험/매우위험) — 안 함
- ❌ 사용자에게 "이거 사기다" 결론 — 안 함

### What ScamGuardian Does
- ✅ **위험 신호 검출 (detection)** — 함
- ✅ 각 신호의 **학술/법적 근거** transparent 제공 (`FLAG_RATIONALE` 27종 유지)
- ✅ 검출 사실만 응답 schema 로 반환 (`detected_signals[]` 형태)
- ✅ 통합 기업이 자기 use case 에 따라 **판정 logic 직접 구현**

### 카테고리 이름 (Signal Detection API)

지금까지 "사기 검증 API / Verification API" 로 부르던 외부 통합 카테고리는 이제 **"Signal Detection API / 사기 신호 검출 API"** 다.

> 발표 한 줄: **"VirusTotal 이 검출 결과 보고만 하듯, ScamGuardian 은 사기 신호 검출 보고만 합니다 — 판정은 통합 기업이."**

## Forbidden Actions (Identity Boundary)

분석 결과·UI·문서·API 응답 어디서든:

- ❌ **"위험 점수 X점"** 같은 숫자 표현 금지 (현재 행동으로) — 응답 본문, 카드, 챗봇 메시지 모두
- ❌ **"안전 / 의심 / 위험 / 매우위험"** 같은 등급 매기기 금지 (현재 행동으로)
- ❌ **"이 콘텐츠는 사기입니다"** 단정 금지 — "검출되었습니다" / "징후가 있습니다" 표현만
- ✅ **"위험 신호 N개 검출되었습니다, 자세한 근거는 `detected_signals` 참고"** 형식만 사용

> 코드·DB 내부 (예: `pipeline/scorer.py` 의 `total_score`, `pipeline/config.py` 의 `RISK_LEVELS`)
> 는 *historical* 값으로 일단 보존 — 다음 stage 에서 응답 표면을 deprecate 한다.
> 새 외부 인터페이스에는 점수·등급 노출 X.

## APK Detection Architecture (3-tier)

한국 보이스피싱 attack chain 의 핵심은 *사이드로딩으로 설치되는 악성 APK* —
SMS 미끼 → URL 클릭 → APK 다운로드 → 권한 부여 → 통화 가로채기 → 금전 갈취.
ScamGuardian 이 닿는 자리는 1·2·3 단계 (검출만, 차단 안 함 — 차단은 통합 기업의 책임).

VirusTotal 시그니처 lookup 단독으로는 zero-day APK / polymorphic 변형을 못 잡는다.
그래서 다음 3 layer 로 보완:

### Tier 1 — VirusTotal 시그니처 매칭 (이미 있음)
- 70+ 백신 엔진 합의 (다중 출처 검증)
- 알려진 멀웨어 SHA256 hash lookup
- **한계**: zero-day, polymorphic, 신규 패밀리 변형 미탐지

### Tier 2 — 정적 분석 Lv 1 (`pipeline/apk_analyzer.analyze_apk_static`)
- `androguard` 기반 manifest 분석 — `androguard.core.apk.APK`
- **권한 조합** 검사 — `SEND_SMS` + `READ_SMS` + `BIND_ACCESSIBILITY_SERVICE` 등 4 종 이상 → `apk_dangerous_permissions_combo`
- **서명 검증** — subject == issuer 휴리스틱 → `apk_self_signed`
- **패키지명 위장** — 정상 한국 앱 (`com.kakao.talk`, `com.nhn.android.search`, `kr.co.shinhan` 등) typo-squatting → `apk_suspicious_package_name`

### Tier 3 — 심화 정적 분석 Lv 2 (`pipeline/apk_analyzer.analyze_apk_bytecode`)
- `androguard.misc.AnalyzeAPK` — dex disassemble + xref 분석 (코드 *읽기만*, 실행 X)
- **의심 API xref**: `SmsManager.sendTextMessage` → `apk_sms_auto_send_code`, `TelephonyManager.listen` → `apk_call_state_listener`, `AccessibilityService` 상속 → `apk_accessibility_abuse`, `DevicePolicyManager.lockNow` → `apk_device_admin_lock`
- **Hard-coded C&C URL** — IP 직접 / 무료 도메인 (.tk/.ml/.ga/.cf/.gq) / 비표준 포트 → `apk_hardcoded_c2_url`
- **사칭 키워드 string** — dex string pool 의 검찰·금감원·은행·안전계좌 등 → `apk_impersonation_keywords`
- **난독화 흔적** — 1-2 글자 클래스명 비율 > 30% + 클래스 50개 이상 → `apk_string_obfuscation`

> ⚠️ **단일 신호로 사기 판정 X** — bytecode 패턴은 false positive 있음 (정상 메신저 앱도 SmsManager 사용 / 정상 앱도 Accessibility 사용 / 뉴스 앱도 일부 키워드). *누적 + 조합* 시점에서만 강한 신호 — 판정은 통합 기업의 자체 logic.

### 알려진 한국 보이스피싱 패밀리 (Tier 2/3 의 reference)

| 패밀리 | 특징 | 출처 |
|--------|------|------|
| **SecretCalls / SecretCrow** | 보이스피싱 탐지 앱·보안 서비스로 위장 | S2W TALON 보고서 |
| **KrBanker** | 한국 은행 앱 (KB·신한·우리·NH 등) UI 사칭 | KISA 분석 보고서 |
| **MoqHao** | 택배 SMS 위장 (CJ대한통운·한진 등) | KISA·McAfee 합동 추적 |

공통 기술 패턴 (Tier 2/3 신호 design):
- `SmsManager` 자동 SMS 발송 — 인증번호·OTP 가로채기
- `TelephonyManager` 통화 상태 감시 — 경찰·금감원 전화 감지
- `BIND_ACCESSIBILITY_SERVICE` — 다른 앱 화면 가로채기 / 자동 입력
- `SYSTEM_ALERT_WINDOW` — 가짜 은행 앱 오버레이
- Hard-coded C&C 서버 URL (보통 동남아 / 중국 ASN)
- string constants 에 사칭 키워드 ("검찰청", "금융감독원", "보안승급" 등)

### Tier 4 — 동적 분석 Lv 3 (`pipeline/apk_analyzer.analyze_apk_dynamic`, **인터페이스만**)

별도 VM 안 Android 에뮬레이터 stack 에서 APK 를 *실제 실행* 후 behavior 모니터링.
**현재는 인터페이스 + flag 카탈로그만 박힘** — remote VM 측 서버는 future work
(v3.5 sandbox VM 패턴과 동일하게 별도 호스트 분리).

**5 종 candidate flag** (status=COMPLETED 일 때만 검출 신호화):
- `apk_runtime_c2_network_call` — 에뮬레이터 outbound 가 알려진 C&C 도메인·IP 호출
- `apk_runtime_sms_intercepted` — 가상 SMS 수신 시 자동 가로채기·재전송 동작
- `apk_runtime_overlay_attack` — 정상 은행 앱 위에 가짜 화면 띄우는 동작
- `apk_runtime_credential_exfiltration` — 자격증명·민감정보 외부 송신 (Frida hook)
- `apk_runtime_persistence_install` — 재부팅 시 자동 시작 / DeviceAdmin enable

**환경변수 (모두 옵션, 기본 비활성)**:
- `APK_DYNAMIC_ENABLED` — `0` (기본) / `1`. 기본 비활성 — 호스트 안전.
- `APK_DYNAMIC_BACKEND` — `auto` / `local` / `remote`. auto 면 REMOTE_URL+TOKEN 둘 다 있을 때만 remote.
- `APK_DYNAMIC_REMOTE_URL` / `APK_DYNAMIC_REMOTE_TOKEN` — 별도 VM 주소·인증 토큰
- `APK_DYNAMIC_TIMEOUT` — emulator run timeout (초, 기본 180)

**HARD BLOCK 정책**: `backend=local` 은 어떤 경우에도 활성화하지 않는다 — 호스트에서
APK 실행하면 멀웨어 감염 위험. 활성 시 즉시 `status=BLOCKED_LOCAL` 반환. v3.5
sandbox.py 의 격리 정책과 동일.

> ⚠️ 동적 분석은 정적보다 false positive 적지만 (실제 행동 관찰), Identity Boundary
> 일관 — 단일 신호로 사기 판정 X. 검출 보고만, 판정은 통합 기업.

### 미구현 / future work

- **Lv 3 remote VM 측 서버** — Android 에뮬레이터 + Frida hook + MobSF 통합 stack.
  v3.5 sandbox_server/ 와 동일하게 별도 VM/VPS 에 배포. 5-7 주 작업 분량.
- **Lv 4-5: 멀티-스테이지 / 행위 클러스터링** — 한 번의 실행이 아닌 복수 시나리오
  (가짜 SMS 수신 / 가상 은행 앱 설치 / 가상 콜백 등) 에서의 일관된 행동 클러스터링.
  학부 단계 가능 범위 밖 — *호스트 위험 상승* 가능성 + 별도 인프라 필요.

### 검출률에 대한 정직한 표현

학술 문헌 기준 정적 분석 검출률은 **60-80%** (Arzt et al. 2014 FlowDroid, Allix et al.
2016 AndroZoo, Wei et al. 2018 DeepGini 등 측정값 범위). 정교하게 난독화·packing·
reflection 다 쓴 APK 는 정적 분석 영역 밖이며, 그건 진짜 동적 분석 (future work) 자리.

ScamGuardian 의 차별화는 **"100% 잡는다"** 가 아니라 **"VirusTotal·시티즌코난 등
시그니처 솔루션이 zero-day 에 약한 부분을 bytecode 패턴 분석으로 보완하는 reference
architecture"**. 검출된 신호는 학술/법적 근거와 함께 transparent 하게 보고하고,
판정은 통합 기업이 자기 risk tolerance 에 따라 한다 (Identity Boundary).

## 개발 실행 명령

### Python 백엔드

```bash
pip install -r requirements.txt
pip install pypdfium2                          # v3 — PDF 렌더 (필수)
pip install -r training/requirements-train.txt  # 학습할 때만
uvicorn api_server:app --reload
```

### Next.js 프론트엔드

```bash
cd apps/web
npm install
cp .env.example .env.local   # SCAMGUARDIAN_API_URL 설정
npm run dev
npm run lint
npm run build
```

### 전체 스택 한 번에 (로그 포함)

```bash
./scripts/start_stack.sh    # uvicorn + next dev + Tailscale Funnel을 nohup으로 실행
./scripts/watch_logs.sh     # 3개 로그 동시 tail
```

> `start_stack.sh`는 conda 환경(`CONDA_ENV`, 기본 `capstone`)을 사용합니다. conda가 없으면 `scripts/restart_stack.sh`를 사용하세요.
> Ollama는 더 이상 필수가 아닙니다 (LLM이 Claude API로 교체됨).

### CLI 분석 (파이프라인 직접)

```bash
python run_analysis.py "https://youtube.com/watch?v=..."
python run_analysis.py --text "투자 설명 텍스트"
python test_pipeline.py   # 통합 테스트
```

### 라벨링 데이터 배치 생성

```bash
# 내장 시드 샘플(23개) DB 저장
python scripts/batch_ingest.py --skip-verify

# 외부 텍스트 파일로 배치 실행 (줄마다 1개 샘플, # 주석 지원)
python scripts/batch_ingest.py --file samples.txt --skip-verify

# JSONL 파일 (text + metadata 포함)
python scripts/batch_ingest.py --jsonl data/processed/public_cases.jsonl --skip-verify

# DB 저장 없이 결과만 확인
python scripts/batch_ingest.py --dry-run
```

## 환경 변수 (`.env` 또는 `.env.local`)

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `SCAMGUARDIAN_API_URL` | Next.js → FastAPI 프록시 대상 | `http://127.0.0.1:8000` |
| `SCAMGUARDIAN_SQLITE_PATH` | SQLite DB 경로 | `.scamguardian/scamguardian.sqlite3` |
| `SCAMGUARDIAN_PERSIST_RUNS` | 분석 결과 DB 저장 여부 | `false` |
| `SCAMGUARDIAN_DATABASE_URL` | Postgres 연결 문자열 | (없으면 SQLite 사용) |
| `SERPER_API_KEY` | 교차 검증용 Google 검색 API | 필수 (검증 활성 시) |
| `ANTHROPIC_API_KEY` | LLM 보조 판정 + AI 초안 라벨링 + 컨텍스트 수집 챗봇 + 의도 분류 | **필수** |
| `ANTHROPIC_MODEL` | Claude 메인 분석 모델 | `claude-sonnet-4-6` |
| `ANTHROPIC_HAIKU_MODEL` | 컨텍스트 챗봇 + 의도 분류 모델 | `claude-haiku-4-5-20251001` |
| `SCAMGUARDIAN_PUBLIC_URL` | 결과 상세 페이지 베이스 URL (없으면 ngrok 자동 발견) | (없음) |
| `OPENAI_API_KEY` | OpenAI Whisper API 키 | 없으면 로컬 Whisper 사용 |
| `SCAMGUARDIAN_CORS_ORIGINS` | 허용 CORS 오리진 (콤마 구분) | `http://localhost:3000,...` |
| `SERPER_MAX_CONCURRENT` | Serper API 동시 호출 수 | `3` |
| `SERPER_BATCH_DELAY` | Serper 호출 간 딜레이 (초) | `0.2` |
| `VIRUSTOTAL_API_KEY` | **v3** — Phase 0 URL/파일 안전성 검사 | 없으면 Phase 0 skip |
| `VIRUSTOTAL_RPM` | VT 분당 호출 한도 | `4` (free tier) |
| `ANTHROPIC_VISION_MODEL` | **v3** — vision OCR 모델 (이미지/PDF) | `claude-sonnet-4-6` |
| `VISION_PDF_MAX_PAGES` | PDF 처리 시 최대 페이지 수 | `5` |
| `VISION_PDF_DPI` | PDF 페이지 렌더 DPI | `150` |
| `AIHUB_API_KEY` | AI Hub CLI 자동화 (`scripts/aihub.py`) | 학습 데이터 받을 때만 |
| `ABUSE_SOFT_THRESHOLD` | **v3.x** 어뷰즈 가드 — "짧은 메시지" 자수 임계 | `10` |
| `ABUSE_WARN_LIMIT` | 짧은 메시지 누적 경고 횟수 | `3` |
| `ABUSE_BLOCK_DURATION` | 자동 블록 지속 시간(초) | `3600` |
| `ABUSE_VIOLATION_WINDOW` | 위반 누적 윈도우(초) | `3600` |
| `ANALYZE_MAX_TEXT_LENGTH` | `/api/analyze` 텍스트 최대 글자 | `5000` |
| `VIRUSTOTAL_RPM` | VT 분당 호출 한도 (free tier) | `4` |
| `SANDBOX_ENABLED` | **v3.5** Phase 0.5 URL 디토네이션 활성화 | `0` |
| `SANDBOX_BACKEND` | `auto` / `local` / `remote` — auto 면 REMOTE_URL+TOKEN 둘 다 있을 때 remote | `auto` |
| `SANDBOX_REMOTE_URL` | **v3.5** 별도 sandbox VM/VPS 주소 (예: `http://172.x.x.x:8001`) | (없음) |
| `SANDBOX_REMOTE_TOKEN` | **v3.5** sandbox 서버와 공유하는 Bearer 토큰 | (없음) |
| `SANDBOX_USE_DOCKER` | local 모드에서 Docker 격리 사용 (1) vs subprocess (0) | `0` |
| `SANDBOX_DOCKER_IMAGE` | 디토네이션 컨테이너 이미지 | `scamguardian/sandbox:latest` |
| `SANDBOX_TIMEOUT` | 디토네이션 timeout (초) | `30` |

## 아키텍처

### 전체 데이터 흐름

```
┌─────────────────────────────────────────────────────────────────────┐
│  입력 경로                                                           │
│                                                                     │
│  카카오톡 챗봇  ──→  POST /webhook/kakao                            │
│  웹 브라우저   ──→  Next.js (/api/*) ──→  POST /api/analyze        │
│  CLI           ──→  python run_analysis.py                         │
│  배치 인제스트  ──→  python scripts/batch_ingest.py                 │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
                           ▼
              ScamGuardianPipeline.analyze()
              (pipeline/runner.py)
                           │
                  Phase 0: 안전성 (safety.py)  [v3]
                           │  VirusTotal — URL/파일 악성 검사
                           │  악성 확정 시 fast-path → 매우 위험 보고
                           │
                  Phase 1: STT / OCR (stt.py + vision.py)  [v3 vision]
                           │  음성·영상 → Whisper, 이미지·PDF → Claude vision
                           │
                  Phase 2: 분류 (classifier.py)
                           │
                  Phase 3: ─── 병렬 실행 (ThreadPoolExecutor) ───
                           │                │                │
                    LLM 통합 호출     엔티티 추출        RAG 검색
                  (llm_assessor.py)  (extractor.py)    (rag.py)
                    analyze_unified()  GLiNER            SBERT
                           │                │                │
                           └────────────────┴────────────────┘
                                          │
                  Phase 4: 교차 검증 (verifier.py, 내부 병렬)
                           │  Serper API × 상위 15 엔티티
                           │
                  Phase 5: 스코어링 (scorer.py) → ScamReport
                           │
                    ScamReport.to_dict()
                           │
          ┌────────────────┼────────────────┐
          ▼                ▼                ▼
    db/repository      카카오 포맷팅      JSON 응답
    (run 저장)     (kakao_formatter.py)  (웹/CLI)
```

### 파이프라인 단계 (`pipeline/runner.py`)

`ScamGuardianPipeline.analyze(source, skip_verification, use_llm, use_rag)` — **7 Phase (Phase 0~5, 0.5 포함)**:

```
Phase 0:   VirusTotal 안전성 검사 (URL·파일만, v3)
Phase 0.5: 격리 Chromium URL 디토네이션 (v3.5, SANDBOX_ENABLED=1 일 때)
Phase 1:   STT / OCR  — Whisper(음성) | Claude vision(이미지·PDF, v3)
Phase 2:   mDeBERTa 분류 (또는 fine-tuned task-specific, v3)
Phase 3:   ┌ LLM 통합 호출 (analyze_unified) ┐  ← ThreadPoolExecutor 병렬
           ├ GLiNER 엔티티 추출               │
           └ RAG 유사 사례 검색               ┘
Phase 4:   Serper 교차 검증 (내부 병렬, 세마포어 레이트 리미팅)
Phase 5:   스코어링
```

0. **안전성** (`safety.py`, v3): URL → VT URL 스캔, 파일 → SHA256 lookup → 미스 시 업로드. 4 req/min 토큰버킷. 악성 확정 시 fast-path: STT/분류 skip + `malware_detected` (80점) 또는 `phishing_url_confirmed` (75점) 단독 트리거 → "매우 위험" 직행.
0.5. **샌드박스** (`sandbox.py`, v3.5): URL 입력에 한해 격리 Chromium 으로 직접 navigate. 비밀번호 입력폼 / 자동 다운로드 / 클로킹 / 과도한 리디렉션 감지 → 5종 sandbox 플래그. **`SANDBOX_BACKEND=remote`** 면 별도 VM/VPS 의 sandbox 서버에 HTTPS 호출 (production 호스트와 분리).
1. **STT/OCR** (`stt.py` + `vision.py`): 텍스트 패스스루, YouTube URL → Whisper, 음성 파일 → Whisper, **이미지·PDF → Claude vision OCR + 시각 단서 통합** (v3). `stt.transcribe()` 가 확장자 보고 자동 라우팅.
2. **분류** (`classifier.py`): zero-shot NLI + 키워드 부스팅 또는 **fine-tuned multi-class** (v3 — `active_models.json` 에 활성 체크포인트 있으면 자동 swap).
3. **병렬 실행** (Phase 3): 분류 결과를 기반으로 아래 3개를 `ThreadPoolExecutor`로 동시 실행
   - **추출** (`extractor.py`): GLiNER(`taeminlee/gliner_ko` 또는 fine-tuned, v3)로 스캠 유형별 엔티티 추출
   - **LLM 통합** (`llm_assessor.py`): `analyze_unified()` — 스캠 유형 재판정 + 엔티티/플래그 제안을 **1회 API 호출**로 처리
   - **RAG** (`rag.py`): SBERT 임베딩으로 과거 사람 라벨 사례 검색 (use_rag일 때만)
4. **검증** (`verifier.py`): Serper API로 엔티티 교차검증. **엔티티별 병렬 검증** + 세마포어 레이트 리미팅. 검증 대상 상위 15개 (라벨당 최대 2개).
5. **스코어링** (`scorer.py`): 플래그 합산 → 위험 점수 / 레벨. `safety_result` 받아 자동 플래그 추가.

### pipeline/ 파일별 역할

| 파일 | 역할 | 핵심 함수/클래스 |
|------|------|----------------|
| `runner.py` | 전체 파이프라인 오케스트레이터 | `ScamGuardianPipeline.analyze(source, ..., precomputed_transcript, user_context)` |
| `safety.py` | **v3** Phase 0 — VirusTotal URL/파일 스캔 | `scan_url()`, `scan_file()`, `safety_check()` → `SafetyResult` |
| `sandbox.py` | **v3.5** Phase 0.5 — URL 디토네이션 (local Docker 또는 remote VM HTTP) | `detonate_url(url)` → `SandboxResult` |
| `sandbox_detonate.py` | **v3.5** 컨테이너 안 실행 — Playwright Chromium 으로 navigate + JSON output | `detonate(url, output_dir, timeout)` |
| `vision.py` | **v3** Phase 1 — Claude vision OCR (이미지/PDF) | `transcribe(path)`, `transcribe_image()`, `transcribe_pdf()` → `VisionResult` |
| `stt.py` | 음성→텍스트 + **확장자 자동 라우팅** (v3 — vision 자동 호출) | `transcribe(source)` → `TranscriptResult` |
| `classifier.py` | 스캠 유형 분류 (zero-shot 또는 **fine-tuned**, v3) | `classify(text)` → `ClassificationResult` |
| `extractor.py` | GLiNER 엔티티 추출 (**path swap 자동**, v3) | `extract(text, scam_type)` → `list[Entity]` |
| `verifier.py` | Serper API 교차검증 | `verify(entities, scam_type)` → `list[VerificationResult]` |
| `rag.py` | 유사 사례 벡터 검색 | `retrieve_similar_runs(embedding, k)` |
| `llm_assessor.py` | Claude API 보조 판정 | `analyze_unified(text, scam_type, user_context)` → `UnifiedLLMResult` |
| `scorer.py` | 플래그 합산 + **safety 자동 플래그** (v3) + **sandbox 자동 플래그** (v3.5) | `score(verification_results, ..., safety_result, sandbox_result)` → `ScamReport` |
| `active_models.py` | **v3** — `.scamguardian/active_models.json` reader (60s TTL 캐시) | `get_active_path(role)`, `invalidate()` |
| `config.py` | 스캠 유형·플래그·점수·라벨·근거 정의 | `SCORING_RULES`, `FLAG_LABELS_KO`, `FLAG_RATIONALE`, `RISK_LEVELS` |
| `kakao_formatter.py` | ScamReport → 카카오 응답 JSON (**IMAGE/PDF, safety 카드** v3) | `format_result()`, `format_question()`, `format_welcome()` |
| `context_chat.py` | 카카오 챗봇 컨텍스트 수집 + 의도 분류 | `next_turn()`, `classify_intent()`, `summarize_for_pipeline()` |
| `claude_labeler.py` | 라벨링 초안 자동 생성 | `generate_draft(transcript, ...)` |
| `eval.py` | 예측 vs 정답 라벨 비교 | `evaluate_annotated_runs(records)` |

### 스코어링 핵심 (`pipeline/config.py`)

- `SCORING_RULES`: 플래그 → 점수 델타 매핑
- `RISK_LEVELS`: 0–20 안전 / 21–40 주의 / 41–70 위험 / 71+ 매우 위험
- LLM 제안 플래그는 `LLM_FLAG_SCORE_RATIO`(기본 0.5) 비율로 **축소 반영** (맹신 방지)
- LLM 제안 엔티티는 `LLM_ENTITY_MERGE_THRESHOLD` 이상이면 병합, `source="llm"` 표기

### DB 계층 (`db/`)

- `repository.py`: `SCAMGUARDIAN_DATABASE_URL`이 있으면 Postgres, 없으면 SQLite로 라우팅
- `sqlite_repository.py`: 임베딩을 JSON 텍스트로 저장, 유사도는 L2 거리 전체 스캔 (느림)
- Postgres는 pgvector 벡터 컬럼 사용 (빠름)
- 스키마는 `repository.init_db()`에서 `CREATE TABLE IF NOT EXISTS`로 자동 생성
- `analysis_runs`에 `claimed_by` / `claimed_at` 컬럼 존재 (라벨링 큐 claim 시스템용, TTL 30분)

### Next.js API 프록시 (`apps/web/src/app/api/`)

- `_lib/backend.ts`: `proxyJsonRequest` / `proxyGet`으로 FastAPI에 전달
- 모든 Route Handler는 이 두 함수만 사용, 직접 비즈니스 로직 없음
- `SCAMGUARDIAN_API_URL` 환경변수가 없으면 `http://127.0.0.1:8000` 기본값

### 카카오톡 챗봇 웹훅 (`/webhook/kakao`)

카카오 오픈빌더 Skill 엔드포인트. **컨텍스트 수집 멀티턴 + 병렬 분석 + 1.5-pass refine** 흐름.

#### 입력 감지 + 의도 분류

`_kakao_detect_input()` → `(source, InputType)`: action.params 확인 → utterance URL → TEXT.

**TEXT 입력은 추가로 `context_chat.classify_intent()`로 의도 분류** (Claude Haiku, fast-path 우선):
- `GREETING` → format_welcome
- `HELP` → format_help
- `CONTENT` → 컨텍스트 수집 모드 시작 (긴 텍스트는 fast-path, LLM 호출 X)
- `ANALYZE_NO_CONTENT` → "분석할 내용 보여주세요" 응답
- `CHAT` → "어떤 일이세요? 보내주시면 살펴볼게요" 응답

#### 컨텍스트 수집 + 병렬 분석 (모든 입력 유형 공통)

```
사용자가 콘텐츠 보냄 (TEXT/URL/VIDEO/FILE)
   ├─ 1차 분석 백그라운드 시작 (TEXT 즉시 / URL/영상은 STT 후)
   └─ 첫 질문 즉답 (Claude 호출 없는 static Q1, 응답 ~50ms)
         "📩 받았어요! 🔍 분석 시작했어요. 그 동안 정보 좀 여쭤볼게요"

사용자 답변 ↔ 봇이 본문 단서 짚어가며 능동 질문 (Q2부터 Claude Haiku, 1~3s)
   - context_chat.next_turn(input_type, history, transcript_text) 호출
   - Claude는 본문 + 누적 대화 모두 보고 다음 질문 생성

[1차 분석 백그라운드에서 완료] — phase 는 collecting_context 유지, 사용자에게 알리지 않음
   - 사용자 다음 답변에 "💡 분석은 끝났어요. '결과확인'을 누르거나 '결과 알려줘' 라고 해주세요" 자동 부착 (1회만)

사용자가 결과 요청 (`결과확인` / `결과 알려줘` / `분석 다됐어?` 등 자연 표현 인식)
   → "🎉 분석 완료! 정보 반영해 정리 중" + refine 트리거 (LLM phase만 user_context와 재호출, ~5-10s)
   → phase 를 result_requested 로 잠금, 채팅 종료

[refine 완료]
사용자 결과확인 다시 누르면
   → 결과 카드 + "자세한 결과 보기" webLink 버튼 + 잡 정리
```

#### 잡 상태 (`_pending_jobs[user_id]`)

| 필드 | 의미 |
|------|------|
| `status` | `running` / `done` / `error` |
| `phase` | `collecting_context` (채팅 가능) / `result_requested` (정리 중) / `error` |
| `chat_history` | 봇/사용자 발화 시간순 (refine 의 user_context 소스) |
| `stt_done`, `stt_result` | STT 완료 + TranscriptResult |
| `analyzing_started` | 1차 분석 트리거됐는지 |
| `result_ready_announced` | 첫 알림(🎉 완료) 한 번 됐는지 |
| `done_notice_sent` | 채팅 중 "분석 끝남" 안내 한 번 부착했는지 |
| `refine_started`, `refined` | 최종 합본 단계 |
| `result`, `user_context` | 최종 산출물 |

`_jobs_lock` (threading.Lock) 으로 다중 사용자 동시 접속 race 방지. 사용자별 `userRequest.user.id` 키로 격리.

#### 응답 포맷 (`kakao_formatter.py`)

핵심 포맷터:
- `format_welcome()`: 첫 인사 ("안녕하세요! 어떤 일로 오셨어요?")
- `format_help()`: 사용법 안내
- `format_question(question, is_first_turn, input_type)`: 챗봇 질문 (intro + 본문)
- `format_ask_for_content(reason)`: ANALYZE_NO_CONTENT/CHAT 응답
- `format_result(report, input_type, user_context, result_url)`: 최종 결과 카드 + webLink
- `format_result_ready_announce(has_refine)`: 🎉 완료 알림
- `format_refining_in_progress()`: 정리 중 폴링 응답
- `format_reset(had_active_job)`: 분석 초기화 응답
- `format_busy()`: 진행 중인데 새 영상 보냈을 때 거절

**플래그는 모두 한국어 라벨**로 표시: `flag_label_ko()` (FLAG_LABELS_KO 27종 매핑).

**모든 응답에 동일 퀵 리플라이 두 개**: `사용법` / `분석 초기화`.

#### 에러 처리 시스템

`ErrorCode` enum(11종)으로 구조화된 에러 메시지:

| 코드 | 상황 |
|------|------|
| `API_CREDIT` | API 크레딧/쿼터 소진 |
| `SERVER_DOWN` | 서버 연결 불가 |
| `STT_FAIL` | Whisper/음성 인식 실패 |
| `TIMEOUT` | 처리 시간 초과 |
| `LLM_UNAVAILABLE` | Ollama/LLM 메모리 부족 등 |
| `CALLBACK_REQUIRED` | URL/파일인데 콜백 미설정 |
| `FILE_TOO_LARGE` | 100MB 초과 |
| `EMPTY_INPUT` | 빈 입력 |
| `INVALID_URL` | 유효하지 않은 URL |
| `PARSE_ERROR` | 요청 JSON 파싱 실패 |
| `UNKNOWN` | 기타 |

`_classify_error(exc)` 함수가 예외 메시지를 분석하여 적절한 `ErrorCode`로 자동 매핑.

#### 카카오 오픈빌더 설정 필수사항

- 스킬 블록에서 **"콜백 사용"** 체크 → `callbackUrl`이 페이로드에 포함돼야 영상 분석이 안정적
- 콜백 기능은 **카카오 관리자센터 → 챗봇 > 설정 > AI 챗봇 관리에서 별도 신청 후 승인** 필요
- 파일 업로드를 받으려면 블록에 **파일 타입 파라미터** 추가 (`video`, `file`, `video_url` 등)
- 스킬 서버 주소: Tailscale Funnel (`https://scamguardian.tail7e5dfc.ts.net/webhook/kakao`) 또는 ngrok 터널 사용
- **참고**: 카카오 오픈빌더에서 Tailscale `.ts.net` 도메인 접속이 불안정할 수 있음. ngrok 권장: `~/bin/ngrok http 3100`

### 결과 상세 페이지 (공개) + 토큰 (`/result/[token]`)

카카오 카드의 "자세한 결과 보기" 버튼 → 1시간 유효 토큰 기반 공개 페이지.

- 토큰 발급: `_issue_result_token()` (api_server.py) — `secrets.token_urlsafe(16)`, 메모리 저장 (`_result_tokens`)
- TTL: `_RESULT_TOKEN_TTL = 3600` (1시간)
- 공개 URL 베이스: `_get_public_base_url()` — env(`SCAMGUARDIAN_PUBLIC_URL`) 우선, 없으면 ngrok 로컬 API(`127.0.0.1:4040`) 자동 발견 (60초 캐시)
- 백엔드 엔드포인트: `GET /api/result/{token}` → result + user_context + chat_history + flag_rationale + expires_at
- 프론트: `apps/web/src/app/result/[token]/page.tsx` — Tailwind, 서버 컴포넌트
- 섹션: 위험도 배지 / AI 요약 / 사용자 제공 정보(fuchsia 강조) / 점수 산정 방식(합산식 + 등급 테이블 + 플래그별 근거·출처) / 발동 플래그 상세 / 추출 엔티티 / 입력 본문(접기) / 챗봇 대화 전체(접기) / 만료 안내

### 플래그 점수 정당성 (`pipeline/config.py:FLAG_RATIONALE`)

각 플래그 점수의 근거 + 출처 매핑 (27종). 결과 페이지에서 "왜 이 점수?" 답변용.

예:
- `abnormal_return_rate` → "연 20% 이상 수익 보장은 자본시장법상 불법 권유 신호" / 금융감독원 유사수신 감독사례집
- `urgent_transfer_demand` → "즉각 송금 요구는 보이스피싱 1순위 패턴" / 경찰청 사이버수사국 통계
- `fake_government_agency` → "공공기관은 전화·문자로 자금 이체 요구 절대 안 함. 100% 사기" / 검찰청·경찰청·금감원 합동 가이드

### 어드민 라벨링 흐름

```
/admin (큐 리스트)
  ├─ GET /api/admin/runs/list      미완료·진행중·완료 필터링, claimed_by 표시
  ├─ POST /api/admin/runs/{id}/claim  검수자 이름 (미입력 시 "Admin" 기본)
  └─ GET /api/admin/metrics        per_labeler 통계 + needs_review 목록

/admin/[runId] (에디터)
  ├─ GET /api/admin/runs/{id}      run 상세 + metadata + 기존 annotation
  ├─ POST /api/admin/runs/{id}/ai-draft   Claude API로 라벨링 초안 생성
  └─ POST /api/admin/runs/{id}/annotations  정답 upsert (labeler 미입력 시 "Admin")
```

- `AdminRunEditor.tsx`: 예측값을 초기값으로 표시, 정답이 있으면 덮어쓰기
- AI 초안은 fuchsia 섹션에 표시 → "초안 전체 적용" 버튼으로 폼에 덮어쓰기
- 저장된 엔티티/플래그에 `source: "ai-draft"` 태깅
- **풀 컨텍스트 노출** (라벨링 정확도 ↑):
  - `metadata.user_context.qa_pairs` — 사용자가 챗봇과 나눈 Q&A 페어 (fuchsia 섹션)
  - `metadata.chat_history` — 봇/사용자 발화 시간순 전체 (펼치기/접기)
  - 카카오 결과 토큰 발급/refine 완료 시점에 `repository.merge_run_metadata()` 로 DB 보존

### 라벨링 품질 관리 (`pipeline/eval.py`)

`evaluate_annotated_runs(records)` 반환값:

- `classification_accuracy`: 전체 분류 정확도
- `entity_micro` / `flag_micro`: precision / recall / F1 (micro 평균)
- `per_labeler`: 검수자별 완료 수 / 분류 정확도 / 엔티티 F1
- `needs_review`: 분류 불일치 또는 엔티티·플래그 recall 낮은 run 목록 (재검토 권장)

### 스캠 유형 확장

- 기본값: `pipeline/config.py`의 `DEFAULT_SCAM_TYPES` (12종), `DEFAULT_LABEL_SETS`
- 런타임 확장: 어드민에서 추가 → `scam_type_catalog` 테이블 → `get_runtime_scam_taxonomy()`로 즉시 반영

## 분석 결과 스키마 (프론트-백 계약)

`ScamReport.to_dict()` 핵심 필드:

```json
{
  "scam_type": "투자 사기",
  "classification_confidence": 0.85,
  "is_uncertain": false,
  "entities": [{"label": "수익 퍼센트", "text": "연 30%", "score": 0.9, "source": "gliner"}],
  "triggered_flags": [{"flag": "abnormal_return_rate", "score_delta": 15, "evidence": {}}],
  "total_score": 45,
  "risk_level": "위험",
  "risk_description": "다수의 스캠 징후가 확인됨",
  "transcript_text": "...",
  "analysis_run_id": "uuid (DB 저장 시)"
}
```

## 배포

- **Frontend**: Vercel (Root Directory: `apps/web`)
- **Backend**: Render (`uvicorn api_server:app --host 0.0.0.0 --port $PORT`)
- 세부 설정: `DEPLOY.md`, `render.yaml`

## v3.x platform 레이어 (2026-04-29)

### `platform_layer/` 모듈 구조

| 파일 | 역할 |
|------|------|
| `api_keys.py` | `sg_<urlsafe>` 발급, sha256 해시 저장, lookup/list/revoke |
| `pricing.py` | Claude/Whisper/Serper/VirusTotal 가격표 — `claude_cost(model, in, out)` 등 |
| `cost.py` | contextvars `_REQUEST_ID` / `_API_KEY_ID` + `record_claude/openai_whisper/serper/virustotal` |
| `rate_limit.py` | per-key RPM 슬라이딩 윈도우 + 월별 호출 quota + 월별 USD cap |
| `abuse_guard.py` | 길이/반복/gibberish/dup + 위반 누적 자동 블록 + 짧은 메시지 트래커 |
| `middleware.py` | FastAPI `PlatformMiddleware` — request_id 주입, key 검증, rate limit, request_log |

### DB 추가 테이블 (`db/sqlite_repository.py`)

- `api_keys`: id, key_hash, label, monthly_quota, rpm_limit, monthly_usd_quota, status, usage*
- `cost_events`: provider × api_key × request × usd_amount ledger
- `request_log`: 모든 요청 status/latency/error — observability 백본

### 어뷰즈 가드 동작 (카카오 webhook 통합)

각 webhook 진입에서 두 단계 체크:
1. `block_status(user_id)` — 이미 차단 상태면 `format_abuse_blocked` + `_pending_jobs.pop` (채팅 강제 종료)
2. `track_short_message(user_id, text)` — 첨부 없는 텍스트 한정. < 10자 시 `record_violation` 호출
   - count==1: 통과 (1번째 free pass)
   - count==2~3: 응답에 ⚠️ 경고 prepend (`_wrap_with_soft_warning`)
   - count==4: blocked=True → 차단 카드 + 1시간 block
3. count >= 2 면 `classify_intent` (Claude Haiku) **호출 자체 skip** — 어뷰저 무료 LLM 통로 차단

### API 보안 정책

- `/api/analyze`, `/api/analyze-upload` — API key 필수 (`Authorization: Bearer sg_...` 또는 `X-API-Key`)
- `X-User-Id` 헤더 옵션 — 외부 클라이언트 per-user 어뷰즈 누적
- `/webhook/kakao` — 카카오 자체 인증 사용, API key skip
- `/api/admin/*` — 현재 미인증 (TODO 1번 — 어드민 게이팅)
- Rate limit 초과 시 `429 Retry-After`, BLOCKED 시 `423 Locked`

## v3 신규 시스템 (2026-04-29)

### Phase 0 안전성 필터 (`pipeline/safety.py`)

VirusTotal API v3 클라이언트. URL/파일을 분석 전에 자동 검사.

- **SHA256 lookup 우선** — 캐시 히트 시 즉답, 미스면 업로드 + `/analyses/{id}` 폴링(최대 30s)
- **레이트 리미팅** — 단순 토큰 버킷 (분당 4건 free tier 한도)
- **공통 분류**: `ThreatLevel.{SAFE, UNKNOWN, SUSPICIOUS, MALICIOUS}` — malicious >= 3 엔진 / suspicious 2+ / 그 외 safe
- **새 플래그**: `malware_detected`(80), `phishing_url_confirmed`(75), `suspicious_file_signal`(25), `suspicious_url_signal`(25)
- **fast-path** (runner.py): 악성 파일 확정 시 STT/분류 skip + 30점이 아닌 **80점**으로 "매우 위험" 직행

### Phase 1 vision OCR (`pipeline/vision.py`)

이미지·PDF → 한국어 본문(텍스트 + 시각 단서). Claude vision (sonnet-4-6).

- 입력: `.jpg .jpeg .png .webp .gif .bmp .pdf`
- PDF 는 `pypdfium2` 로 페이지별 PNG 렌더 (기본 5페이지, 150 DPI)
- 이미지 다운스케일: long edge 1568px (Anthropic 권장)
- 시스템 프롬프트가 OCR + 시각 단서 통합 본문을 한 번에 출력하도록 강제
- `stt.transcribe()` 가 확장자 보고 vision 자동 라우팅

### Fine-tuning 시스템 (`training/`)

라벨 데이터로 `pipeline/classifier.py` (mDeBERTa) + `pipeline/extractor.py` (GLiNER) 도메인 특화 학습.

| 파일 | 역할 |
|------|------|
| `training/data.py` | DB(human_annotations) + 외부 JSONL → ClassifierExample/GlinerExample. char→token span 자동 변환, stratified split |
| `training/train_classifier.py` | mDeBERTa SFT + LoRA 옵션. HF Trainer + `MetricsEmitCallback` (log/eval/epoch 마다 metrics.jsonl emit) |
| `training/train_gliner.py` | GLiNER fine-tune. fit() 없는 버전은 JSON 만 저장 + 외부 trainer 안내 |
| `training/sessions.py` | subprocess 세션 관리자. `.scamguardian/training_sessions/{id}/{status.json,metrics.jsonl,train.log}` 파일 기반 |
| `training/requirements-train.txt` | peft / datasets / evaluate / accelerate / seqeval / sklearn |

웹 UI: `/admin/training` — 데이터 통계 + 세션 시작 폼 + 진행률 그래프(recharts) + 로그 tail + 활성화 버튼.
설명 페이지: `/admin/training/about` — 모델 역할 + 파이프라인 위치 + before/after 표 + 권장 학습 분량.

### 모델 swap (`pipeline/active_models.py`)

`/admin/training` 의 "파이프라인 적용" 버튼 → `.scamguardian/active_models.json` 갱신.
- 60초 TTL 캐시. 활성화 직후 `invalidate()` 호출되어 즉시 반영.
- `classifier.py` — 활성 경로 있으면 task-specific multi-class pipeline, 없으면 zero-shot fallback.
- `extractor.py` — GLiNER path swap. 활성 경로 변경되면 모델 재로드.
- 경로 무효 시 base 모델로 자동 fallback (안전장치).

### AI Hub CLI 자동화 (`scripts/aihub.py`)

`aihubshell` 래퍼 — 데이터셋 검색·라벨링 zip 만 골라 다운로드.

```bash
export AIHUB_API_KEY=...
python scripts/aihub.py list-datasets --grep 콜센터,상담,민원
python scripts/aihub.py list-files 98
python scripts/aihub.py download-labels 98 --domain 금융 --dry-run
```

신청·승인은 사이트에서만 가능 (CLI 자동화 불가). 승인 후 라벨링 zip 만 골라받아 원천 음성 GB 단위 다운로드 회피.

### 카카오 webhook 멀티모달 (v3)

`_kakao_detect_input` 가 action_params 의 `image / picture / photo / pdf / document / video / file` 키 + URL 확장자 (`.jpg/.png/.pdf` 등) 보고 자동 분류:
- IMAGE / PDF 면 webhook 핸들러가 `_kakao_materialize_url()` 로 카카오 CDN URL → `.scamguardian/uploads/kakao/{uuid}.{ext}` 다운로드 → 로컬 경로로 source 교체
- 그 후 기존 `_kakao_start_context_collection()` 흐름 그대로 — `stt.transcribe()` 가 vision 자동 라우팅
- `format_question` / `format_analyzing` / `format_queued` 모두 IMAGE/PDF 메시지 추가
- **실전 발견** (2026-04-30): 카카오 *챗봇 채널* 은 PDF 첨부 자체 차단 — 이미지는 utterance 필드에 CDN URL 박혀서 도착 (action.params 가 아님). detector fallback (action_params 의 *모든* 키 훑어 URL 분류) 추가. APK/EXE/DMG 등 실행파일 URL 도 InputType.FILE 로 분류해 VT 파일 스캔 강제.

## v3.5 신규 시스템 (2026-04-30)

### Phase 0.5 URL 디토네이션 (`pipeline/sandbox.py`)

VT 시그니처 lookup 의 한계(zero-day 피싱 못 잡음)를 정면 돌파. 의심 URL 을 격리 Chromium 으로 *직접 navigate* 해서 페이지 행동을 관찰.

**감지 항목**:
- 비밀번호 입력 필드 (`<input type=password>`) — 가장 강한 피싱 신호
- 민감 정보 필드 (주민번호·OTP·CVC·계좌·카드)
- 자동 다운로드 시도 (drive-by download)
- 클로킹 (target 도메인 ≠ 최종 도착지)
- 과도한 리디렉션 (>3회)

**새 플래그** (`pipeline/config.py`):
- `sandbox_password_form_detected` (+50)
- `sandbox_sensitive_form_detected` (+35)
- `sandbox_auto_download_attempt` (+60)
- `sandbox_cloaking_detected` (+30)
- `sandbox_excessive_redirects` (+15)

**백엔드 모드** (`SANDBOX_BACKEND`):
- `local` — 동일 호스트 Docker 또는 subprocess (개발 전용)
- `remote` — 별도 VM/VPS 의 sandbox 서버에 HTTPS 호출 (**운영 권장**)
- `auto` (기본) — REMOTE_URL+TOKEN 둘 다 있으면 remote, 아니면 local

**파일 구조**:
- `pipeline/sandbox.py` — Python wrapper. local/remote 자동 분기. 원격 응답의 screenshot base64 → 호스트 파일로 저장.
- `pipeline/sandbox_detonate.py` — 컨테이너 *안에서* 실행되는 Playwright 스크립트. JSON 한 줄 output.
- `pipeline/sandbox.Dockerfile` — Playwright 공식 이미지 기반. `mcr.microsoft.com/playwright/python:v1.47.0-jammy`. 비특권 user.
- `sandbox_server/app.py` — 격리 VM 안에서 도는 FastAPI 서버. `/detonate` + `/health`. Bearer 토큰 인증. screenshot base64 inline 반환. stateless (디토네이션 결과물 즉시 삭제).
- `sandbox_server/README.md` — Multipass VM (Win11 Pro) / 클라우드 VPS 양쪽 배포 가이드 + systemd 서비스 등록.

### 격리 정책 — 왜 분리하나

```
같은 호스트 = 위험:
  production server (DB, API 키, 사용자 데이터)
    ↘ 같은 커널 ↙
  sandbox container (untrusted URL 직접 실행)
  → 컨테이너 이스케이프 한 번에 모든 데이터 노출

분리 = 안전:
  production ←HTTPS+Bearer토큰→ sandbox VM (별도 머신)
  sandbox 가 완전히 털려도 빈 VM (DB·키·데이터 없음) → 잃을 게 없음
```

**개발**: 동일 WSL 내 `SANDBOX_BACKEND=local` + `SANDBOX_USE_DOCKER=1`
**스테이징·운영**: Multipass VM (Win11 Pro Hyper-V) 또는 클라우드 VPS ($5/월) — `SANDBOX_BACKEND=remote`

### 카카오 webhook 이미지·실행파일 (v3.5)

- **이미지**: utterance 필드 안 카카오 CDN URL → detector 자동 인식 → `_kakao_materialize_url` 다운로드 → Phase 0 VT 검사 + Phase 0.5 디토네이션 (URL 인 경우)
- **APK/EXE/DMG**: detector 가 `_EXECUTABLE_URL_RE` 로 `InputType.FILE` 분류 → 다운로드 → Phase 0 VT 파일 스캔 (URL 페이지 스캔 X)
- **PDF**: 카카오 챗봇 클라이언트에서 첨부 자체 차단 — 사용자 안내 필요 ("캡쳐 이미지 또는 클라우드 링크")

### Whisper 비용 추적 (v3.5 버그 수정)

`record_openai_whisper()` 가 정의만 있고 호출되지 않던 버그 — `pipeline/stt.py` 에서 `_probe_audio_seconds()` 헬퍼 분리, OpenAI 호출 후 자동 ledger 기록. v4 chunker 도 동일. 이제 어드민 비용 차트에 OpenAI provider 정상 노출.

## 테스트 (`tests/`)

```bash
pip install pytest
pytest                    # 93 passed (8초 미만)
pytest tests/test_abuse_guard.py -v
pytest tests/test_sandbox_parser.py -v   # v3.5 sandbox dispatch + scoring
```

`tests/conftest.py`:
- `_isolate_env`: 모든 테스트에 격리된 임시 SQLite path 자동 주입
- 외부 API key (ANTHROPIC/OPENAI/SERPER/VIRUSTOTAL) 자동 unset — 실수 호출 방지

테스트 모듈 분포 (총 93):
- `test_abuse_guard.py` (10) + `test_abuse_block.py` (8)
- `test_platform_api_keys.py` (5) + `test_platform_usd_cap.py` (3)
- `test_cost_pricing.py` (4)
- `test_safety_parser.py` (3) + `test_safety_scoring.py` (4)
- `test_kakao_detect_input.py` (14, custom param + APK URL 포함) + `test_kakao_system_commands.py` (4)
- `test_sandbox_parser.py` (15, **v3.5** — backend dispatch + scoring + screenshot)
- `test_v4_whisper_chunker.py` (4)

## 다음 작업 (TODO)

(2026-04-29 정리 — v3.x platform 마무리)

### 🎯 v4 계획 — 실시간 통화 중 사기 탐지 ("Live Call Guard")

**핵심 아이디어**: 사기 *후*가 아닌 사기 *중* 차단. 사용자가 보이스피싱 의심 전화 받는 순간, 카톡으로 트리거 → 웹앱이 사용자 본인 발화를 실시간 분석 → 위험 신호 감지 시 즉시 "전화 끊으세요!" 경보.

**중요 결정 — 사용자 본인 발화만 분석**:
- 상대방(사기범) 음성은 캡처하지 않음 → iOS 마이크 권한·통신비밀보호법·STT 잡음 문제 한 번에 해결
- 학술적으로도 새 영역: 기존 보이스피싱 연구는 모두 사기범 발화 분석. 본 시스템은 *피해자 측 compliance signal* 을 잡는다 (Cialdini 영향력 원리가 피해자 발화에서 어떻게 드러나는지)

**아키텍처**:

```
카톡 트리거 ("지금 검찰청 전화", "사기 같아")
      ↓ context_chat 의도 분류에 INTENT_LIVE_CALL 추가
1회용 세션 토큰 + 웹링크 발급 (TTL 1시간)
      ↓
/live/[token] 페이지 — 마이크 권한 (일반 웹 권한, iOS/Android 모두 OK)
      ↓
WebRTC getUserMedia → AudioWorklet (16kHz mono PCM)
      ↓ WebSocket 스트리밍
FastAPI WebSocket → OpenAI Whisper API (5초 chunk 누적 STT)
      ↓
**즉시 경보 신호** (Haiku 한 줄 호출 또는 정규식):
  - 메타인식: "이거 사기 같은데", "이상한데"
  - 민감정보 누설: "주민번호는...", "OTP는...", "비밀번호는..."
  - 송금 동의: "이체했어요", "보낼게요", "얼마 보내요"
**누적 신호** (슬라이딩 윈도우):
  - 과도한 순응 ("네 알겠습니다" 반복)
  - 권위 굴복 ("검찰청이 진짜인가요?" + 곧 동의)
  - 긴박감 휩쓸림 ("지금 바로요?", "빨리...")
  - 혼란·말더듬 (같은 질문 반복)
      ↓
임계 초과 → WebSocket push 경보:
  - Audio API 경보음 (alarm.mp3 loop)
  - 빨간 fullscreen alert "🚨 전화 끊으세요!"
  - 진동 (모바일)
      ↓
통화 종료 (사용자가 멈춤 버튼) →
  - 전체 transcript DB 저장
  - Phase 4 verifier 사후 검색·재분석
  - 카톡으로 사후 결과 카드 전송
```

**MVP 단계 자르기**:
1. **v4.0** — 사용자 발화 메타인식 표현 검출 (정규식 + Haiku 한 줄). 5초 chunk Whisper. 안드로이드 우선
2. **v4.1** — 누적 슬라이딩 윈도우 + Cialdini 신호 카탈로그 풀패턴
3. **v4.2** — 통화 후 사후 검색 분석 + 카톡 결과 카드
4. **v4.3** — iOS 호환성 검증 + 백그라운드 권한 우회 패턴

**가장 빨리 검증해야 할 것** (들어가기 전 30분 실험):
- 사용자 발화에서 "메타인식·민감정보·송금동의" 표현 검출 정확도 (Haiku 한 줄 분류기 + 합성 발화 30개)
- 5초 chunk Whisper API 한국어 음성(스피커폰 환경) 정확도 — 80%+ 안 나오면 재설계 필요

**기술 스택 결정 포인트**:
- 실시간 STT: OpenAI Whisper API 5초 chunk (가장 단순, 비용 ~$0.006/min) vs Deepgram 한국어 (정확도 ↑, 비용 5×) vs 로컬 whisper-streaming
- WebSocket vs Server-Sent Events: WebSocket (양방향, 경보 push 자연)
- 경보음 형식: 알림음 mp3 loop + 진동 + visual flash (다중 채널)

### 운영 가능 플랫폼이 되려면 남은 것

1. **어드민 인증** — `/admin/*` 게이팅 + RBAC. 현재 URL 만 알면 라벨링·키발급·모델활성화 가능.
2. **데이터 retention 정책** — `.scamguardian/uploads/` 영구 보존 → 30/60/90일 자동 삭제 + 사용자 동의 처리.

### 자잘한 후속

1. **AI Hub 데이터 도착 → ingest 스크립트**: `scripts/ingest_aihub.py` — 데이터셋별 라벨 JSON 스키마 보고 우리 JSONL 포맷(text + label/entities) 으로 변환.
2. **카카오 webhook 실제 이미지·PDF 테스트**: 합성 포스터 말고 진짜 사기 광고/캡쳐로 vision OCR 정확도 검증.
3. **active_models 모델 메타 표시**: `/admin/training` 활성 모델 카드에 학습 데이터 양, 마지막 평가 F1 함께 노출.
4. **GLiNER 학습 보강**: 현재 fit() API 없는 버전 fallback 만 동작. 외부 trainer (urchade/GLiNER 공식 가이드) 통합.
5. **API 통합 테스트**: 현재 단위 테스트만. FastAPI TestClient 로 `/api/analyze` end-to-end (mock provider) 추가.
6. **Postgres 마이그레이션**: `api_keys`/`cost_events`/`request_log` 가 SQLite 만 지원. Postgres 환경 운영 시 facade 확장.
