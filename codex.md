# Codex Project Notes — ScamGuardian v2/v3

이 문서는 Codex가 이 저장소에서 작업하기 전에 빠르게 읽을 기준 문서다. 2026-06-01 기준으로
프로젝트 전체를 훑고, 구현 구조와 작업 시 지켜야 할 경계를 정리했다.

## 1. 프로젝트 정체성

ScamGuardian은 "사기 판정 시스템"이 아니라 한국어 멀티모달 콘텐츠에서 위험 신호를 검출하는
reference implementation이다. VirusTotal처럼 검출 결과와 근거를 보고하고, 최종 판정과 차단은
통합 기업이 자체 risk tolerance에 따라 구현한다.

반드시 지킬 경계:

- 외부 응답, UI, 챗봇 문구에 `total_score`, `risk_level`, `is_scam`, `agent_verdict` 같은 판정 필드를
  되살리지 않는다.
- "사기입니다", "안전/의심/위험/매우위험", "위험 점수 N점" 같은 표현을 새로 만들지 않는다.
- 사용자-facing 문구는 "위험 신호 N개 검출", "징후가 있습니다", "detected_signals 참고" 형태로 유지한다.
- 내부 DB의 `total_score_predicted`, `risk_level_predicted`는 호환성 흔적이다. 현재 의미는 각각
  검출 신호 개수와 빈 문자열에 가깝다.

관련 회귀 가드:

- `tests/test_detection_report_schema.py`
- `tests/test_signal_detection.py`
- `tests/test_result_content_type.py`

## 2. 큰 구조

주요 진입점:

- `api_server.py`: `uvicorn api_server:app`용 얇은 entry point. 실제 앱은 `api_server_pkg/app.py`.
- `api_server_pkg/`: FastAPI 라우터, 공통 실행 헬퍼, 카카오 멀티턴 흐름, 결과 토큰, 어드민 API.
- `pipeline/`: 실제 검출 파이프라인. Phase 0부터 Phase 5까지 대부분의 핵심 로직.
- `platform_layer/`: API key, rate limit, monthly cap, cost ledger, abuse guard, retention, middleware.
- `db/`: Postgres/SQLite facade. `db/repository.py`가 Postgres와 SQLite를 라우팅.
- `apps/web/`: Next.js 16 App Router. 프론트는 thin proxy + UI이며 비즈니스 로직을 넣지 않는다.
- `training/`: classifier/GLiNER fine-tuning, session manager, evaluation utilities.
- `sandbox_server/`: production과 분리된 VM/VPS에서 URL detonation을 수행하는 서버.
- `tests/`: pytest 회귀 테스트 25개 파일.
- `scripts/`: stack 실행, 로그 감시, batch ingest, OpenAPI dump, 리소스 모니터링.

런타임 데이터:

- `.scamguardian/`: SQLite DB, 업로드, 로그, 학습 세션, active model pointer 등. 작업 시 보통 사용자
  데이터로 취급하고 불필요하게 건드리지 않는다.

## 3. API와 요청 흐름

FastAPI 앱 생성:

1. `api_server.py`가 `.env`를 로드하고 `create_app()` 호출.
2. `api_server_pkg/app.py`가 CORS, `PlatformMiddleware`, 라우터를 붙인다.
3. startup에서 DB 초기화, upload retention sweep, 모델 warmup을 시도한다.

Public API:

- `POST /api/analyze`: 텍스트 또는 URL 분석. API key 필수.
- `POST /api/analyze-upload`: 파일 업로드 분석. API key 필수.
- `GET /api/result/{token}`: 1시간 TTL 결과 카드 조회.
- `GET /api/methodology`: 검출 신호 카탈로그와 근거.

`api_server_pkg/common.py`의 핵심:

- `run_pipeline(payload)`는 `use_llm=True`를 강제한다.
- `persist_run(...)`은 `SCAMGUARDIAN_PERSIST_RUNS`가 켜진 경우만 DB 저장한다.
- gate 결과와 candidate scam types는 외부 응답이 아니라 metadata에만 저장한다.

## 4. 파이프라인 지도

`pipeline/runner.py::ScamGuardianPipeline.analyze()`가 전체 오케스트레이터다.

실행 순서:

1. Phase 0 `pipeline/safety.py`: URL/파일 VirusTotal 검사. YouTube는 신뢰 플랫폼으로 skip.
2. Phase 0.5 `pipeline/sandbox.py`: `SANDBOX_ENABLED=1`이고 URL이면 격리 Chromium detonation.
3. Phase 0.6 `pipeline/apk_analyzer.py`: APK 파일이면 정적 Lv1, 심화 정적 Lv2, 동적 Lv3 인터페이스.
4. Phase 1 `pipeline/stt.py` + `pipeline/vision.py`: 텍스트 패스스루, YouTube/음성 Whisper, 이미지/PDF vision OCR.
5. Phase 1.5+2+3: gate, classifier, extractor, RAG를 ThreadPoolExecutor로 eager 병렬 실행.
6. LLM은 gate 결과를 본 뒤 조건부 실행한다. 비용 낭비를 피하기 위해 사전 실행하지 않는다.
7. Phase 4 `pipeline/verifier.py`: 룰 기반 신호는 항상 실행, Serper 검증은 gate profile과 skip flag에 따라 실행.
8. Phase 5 `pipeline/signal_detector.py`: 모든 결과를 `DetectionReport.detected_signals[]`로 종합한다.

중요한 라우팅 원칙:

- gate는 내부 라우팅 전용이다. 외부에 scam attempt/suspicious 같은 판정성 bucket을 노출하지 않는다.
- gate가 normal로 오판해도 룰 기반 신호검출은 항상 수행된다.
- `SCAMGUARDIAN_LLM_ENABLED=0`이면 진입점이 `use_llm=True`를 줘도 파이프라인에서 LLM을 끈다.
- 긴 오디오는 `STT_CHUNK_THRESHOLD_SEC` 초과 시 chunk 병렬 Whisper 호출로 처리한다.

## 5. 카카오 챗봇 흐름

주요 파일:

- `api_server_pkg/kakao/router.py`
- `api_server_pkg/kakao/context_flow.py`
- `api_server_pkg/kakao/tasks.py`
- `api_server_pkg/kakao/detect.py`
- `pipeline/context_chat.py`
- `pipeline/kakao_formatter.py`

흐름:

- `/webhook/kakao`는 raw in/out을 `.scamguardian/logs/kakao_raw.jsonl`에 남긴다.
- 도움말, 초기화, 결과확인, 스킵 같은 시스템 명령을 우선 처리한다.
- 사용자별 job은 `api_server_pkg/state.py`의 `pending_jobs`와 `jobs_lock`으로 관리한다.
- heavy input(URL/영상/파일/이미지/PDF)은 callback이 없으면 컨텍스트 수집 모드로 들어간다.
- 텍스트는 `context_chat.classify_intent()`로 greeting/help/chat/content 등을 분기한다.
- 결과 페이지용 토큰은 `api_server_pkg/result_token.py`에서 1시간 TTL로 발급된다.

주의:

- 카카오는 첨부를 `action.params`가 아니라 `utterance` CDN URL로 보내는 경우가 있다.
- PDF/일반 파일은 카카오 클라이언트에서 막히는 경우가 있어 이미지 캡처 또는 클라우드 링크 안내가 필요하다.
- 모든 카카오 결과 포맷에서도 점수/등급/단정 표현을 되살리면 안 된다.

## 6. Frontend 지도

`apps/web`는 Next.js 16 + React 19 + Tailwind 4 기반이다.

중요한 파일:

- `apps/web/src/app/page.tsx`: 메인 분석 UI.
- `apps/web/src/app/result/[token]/page.tsx`: 공개 결과 페이지.
- `apps/web/src/app/admin/*`: 라벨링, runs, platform, training 어드민 UI.
- `apps/web/src/app/api/_lib/backend.ts`: FastAPI proxy. 분석 호출에 `SCAMGUARDIAN_INTERNAL_API_KEY`를 붙인다.
- `apps/web/src/auth.ts`, `apps/web/src/proxy.ts`: NextAuth/admin protection 관련.

프론트 원칙:

- Next.js route handler는 thin proxy로 유지한다. 분석 비즈니스 로직은 백엔드에 둔다.
- Next 16은 프로젝트 메모리에 이미 문제가 있었다. `package.json`의 `dev`는 `next dev --webpack`으로 고정되어 있다.
- Turbopack root 자동 감지 문제와 WSL freeze 관련 내용은 `tasks/lessons.md`를 먼저 확인한다.
- 결과 UI는 신호 개수에 따른 시각 스타일은 써도 되지만 "등급"으로 표현하면 안 된다.

## 7. Platform/DB 지도

`platform_layer/middleware.py`가 request id, admin auth, API key, rate limit, quota, cost context, request log를 처리한다.

인증 정책:

- `/api/analyze`, `/api/analyze-upload`: API key 필수.
- `/api/result/*`, `/api/methodology`: API key optional.
- `/api/admin/*`: `SCAMGUARDIAN_ADMIN_TOKEN` 필수. `ADMIN_AUTH_DISABLED`는 개발용.
- `/webhook/*`, `/health`, docs/openapi/redoc: 인증 skip.

DB:

- `SCAMGUARDIAN_SQLITE_PATH`가 설정되면 SQLite backend.
- 아니면 `SCAMGUARDIAN_DATABASE_URL`이 있으면 Postgres + pgvector.
- `SCAMGUARDIAN_PERSIST_RUNS=true`일 때만 분석 결과 저장.
- Postgres schema는 `repository._ensure_schema()`, SQLite schema는 `db/sqlite_repository.py`.

비용/사용량:

- `platform_layer/cost.py`, `pricing.py`, `rate_limit.py`, `api_keys.py`가 함께 동작한다.
- 외부 API 호출을 새로 추가하면 가능한 cost ledger 기록 패턴을 따라야 한다.

## 8. Training/Model Swap

주요 파일:

- `training/train_classifier.py`
- `training/train_gliner.py`
- `training/sessions.py`
- `pipeline/active_models.py`
- `apps/web/src/app/admin/training/TrainingClient.tsx`

동작:

- 학습 세션은 `.scamguardian/training_sessions/{session_id}/`에 파일 기반으로 상태를 남긴다.
- `status.json`, `metrics.jsonl`, `train.log`, `output/` 구조를 사용한다.
- 활성 모델 pointer는 `.scamguardian/active_models.json`.
- classifier/GLiNER는 active path가 있으면 자동 swap하는 구조다.

주의:

- 학습은 subprocess를 띄우며 오래 걸리고 리소스를 많이 쓴다.
- `python -m training.train_classifier` prefix는 승인되어 있지만, 새 의존성 다운로드나 네트워크가 막히면 승인이 필요할 수 있다.

## 9. Sandbox/APK 보안 경계

URL sandbox:

- production host는 DB/API key/user data를 가진다.
- untrusted URL detonation은 별도 VM/VPS의 `sandbox_server/`에서 수행해야 한다.
- local mode는 Docker 격리를 쓰더라도 운영상 위험하므로 remote 구성이 기본 철학이다.

APK:

- Lv1 manifest/권한/서명: `analyze_apk_static`.
- Lv2 dex bytecode pattern: `analyze_apk_bytecode`.
- Lv3 dynamic은 인터페이스만 있다. 기본 비활성이고 local backend는 hard block.
- APK 신호는 false positive 가능성이 있으므로 단일 신호를 판정으로 표현하지 않는다.

## 10. 테스트와 검증

기본 명령:

```bash
pytest
cd apps/web && npm run lint
cd apps/web && npm run build
```

상황별로 우선 볼 테스트:

- Identity/schema: `tests/test_detection_report_schema.py`, `tests/test_signal_detection.py`
- Gate/routing: `tests/test_gate.py`, `tests/test_stage2_routing.py`
- Kakao: `tests/test_kakao_detect_input.py`, `tests/test_kakao_system_commands.py`
- Safety/sandbox/APK: `tests/test_safety_parser.py`, `tests/test_safety_scoring.py`, `tests/test_sandbox_parser.py`, `tests/test_apk_analyzer.py`
- Platform: `tests/test_platform_api_keys.py`, `tests/test_platform_usd_cap.py`, `tests/test_abuse_guard.py`, `tests/test_abuse_block.py`
- Training/data: `tests/test_training_data.py`, `tests/test_training_eval.py`
- STT/v4 experiments: `tests/test_stt_chunked.py`, `tests/test_v4_whisper_chunker.py`

검증 원칙:

- 문서만 바꿨다면 최소한 `git diff --check`로 whitespace/patch sanity를 본다.
- schema나 identity 경계를 건드리면 관련 pytest를 반드시 실행한다.
- frontend를 건드리면 lint/build를 우선한다. dev server는 `next dev --webpack` 전제를 기억한다.

## 11. 2026-06-02 KYY 병합 후 재분석

오늘 기준 프로젝트는 세 팀원 작업본 + 현재 fine-tuning/RAG/라이브 분석 작업이 합쳐진 큰 단일 저장소다.
소스 파일만 보아도 약 1,200개 이상이며, 런타임 산출물까지 포함하면 프로젝트 루트는 약 8.6GB다.
용량의 대부분은 `.scamguardian/training_sessions`의 학습 체크포인트와 로그다.

현재 큰 축:

- **Signal Detection API**: `api_server_pkg/analyze.py`, `pipeline/runner.py`, `pipeline/signal_detector.py`
- **Kakao/chatbot**: `api_server_pkg/kakao/*`, `pipeline/context_chat.py`, `pipeline/kakao_formatter.py`
- **Live/stream analysis**: `api_server_pkg/stream_analyze.py`, `api_server_pkg/live_stream.py`, `apps/web/src/app/live/LiveVoiceUpload.tsx`
- **STT 보정**: `pipeline/stt.py`, `pipeline/stt_correct.py`
- **Fine-tuning/model ops**: `api_server_pkg/admin_training.py`, `training/*`, `apps/web/src/app/admin/training/*`
- **Platform/admin**: `platform_layer/*`, `api_server_pkg/admin_platform.py`, `apps/web/src/app/admin/platform/*`
- **Data/RAG**: `data/generated/*`, `data/generated/rag_index/*`, `pipeline/rag.py`
- **Sandbox/APK**: `pipeline/sandbox.py`, `sandbox_server/*`, `pipeline/apk_analyzer.py`

KYY 병합에서 새로 강하게 들어온 기능:

- `api_server_pkg/live_stream.py`
- `apps/web/src/app/api/live-analyze/*`
- `pipeline/stt_correct.py`
- `tests/test_clova_roles.py`
- `tests/test_stream_alert_tier.py`
- `tests/test_stream_window.py`
- `tests/test_stt_correct.py`

병합 중 보존해야 했던 최근 기능:

- `/admin/training/compare`: raw/Claude/fine-tuned 비교, classifier/GLiNER 세션 선택
- `/admin/training/models`: 완료된 모델 세션 관리 + active model 적용
- GLiNER 학습 CUDA 강제, 메모리 절감, `max_steps`, `max_tokens`, bf16 처리
- classifier+GLiNER 선택 시 병렬이 아니라 GLiNER 후 cooldown 후 classifier 순차 학습

현재 구조상 가장 큰 위험:

- `api_server_pkg/admin_training.py`와 `training/sessions.py`는 기능이 계속 모이는 hotspot이다.
  학습 시작, 세션 상태, 모델 활성화, 비교 분석 API가 한곳에 있어서 작은 덮어쓰기에도 UI가 바로 깨진다.
- `apps/web/src/app/live/LiveVoiceUpload.tsx`는 단일 컴포넌트가 매우 커졌다.
  추후에는 upload/session panel, transcript timeline, alert badges, debug panel로 쪼개는 것이 좋다.
- `.scamguardian/training_sessions`는 6GB 이상이다. Git 대상이 아니라 운영 데이터/모델 artifact로 취급해야 한다.
- `.env`는 Git에 올리면 안 되지만, 복구 관점에서는 NAS 백업에 포함해야 한다. 백업 위치 접근권한을 조심한다.

백업 지점:

- KYY 병합 전 GitHub 커밋: `8eb2d5d` (`feat/training-compare-synthetic`)
- Beestation 핵심 데이터 백업:
  `/mnt/c/Users/kimju/BeeStation/A-EYE/ScamGuardianBackups/pre-kyy-20260602_223128/scamguardian-critical-data-with-env.tgz`

백업 스크립트:

- `scripts/backup_project_data_to_beestation.sh`
  - `.env`, SQLite DB, active model pointer, generated data, RAG index, labeling drafts, task notes를 tar로 묶는다.
  - `FULL_TRAINING=1`을 주면 `.scamguardian/training_sessions`까지 별도 아카이브로 묶는다.
- `scripts/backup_project_data_to_beestation_smb.sh`
  - BeeStation SMB 공유를 WSL에 CIFS로 마운트해 같은 핵심 백업을 직접 쓴다.
  - 필요 환경변수: `BEE_SMB_URL`, `BEE_SMB_USER`, `BEE_SMB_PASS`.
  - WSL에 `mount.cifs`가 없으면 `sudo apt install -y cifs-utils`가 먼저 필요하다.
- `scripts/backup_project_data_to_beestation_smb.ps1`
  - Windows PowerShell에서 BeeStation SMB 공유를 매핑하고, WSL 내부 tar 파일을 `\\wsl$` 경유로 SMB에 복사한다.
  - WSL sudo 없이 프로젝트 핵심 데이터 백업을 만들 때 사용한다.
- `scripts/backup_wsl_export_to_beestation.ps1`
  - Windows PowerShell에서 실행한다.
  - 실행 중인 `ext4.vhdx`를 직접 복사하지 않고 `wsl --export Ubuntu ...tar`로 복구 가능한 WSL 스냅샷을 만든다.
- `scripts/backup_wsl_export_to_beestation_smb.ps1`
  - Windows PowerShell에서 BeeStation SMB 경로(`\\server\share`)로 WSL export tar를 직접 저장한다.
  - BeeStation은 System Settings > Advanced Settings > Local Access 에서 Local Account와 SMB Service를 켜야 한다.

검증된 상태:

- `python -m py_compile api_server.py api_server_pkg/*.py pipeline/*.py training/*.py platform_layer/*.py db/*.py`
- `cd apps/web && npx tsc --noEmit`
- `cd apps/web && npm run lint`

다음 정리 추천:

- `.gitignore`를 재점검해 `.scamguardian/*.bak*`, `data/generated/`, `.next/`, cache류가 우발적으로 stage 되지 않게 한다.
- Live UI 대형 컴포넌트 분리.
- `admin_training.py`를 `training_stats`, `training_sessions`, `training_compare`, `training_synthetic_graph` 등으로 나누기.
- 모델 artifact는 Git이 아니라 Beestation/별도 artifact registry에 보관하고, Git에는 manifest만 남기기.

## 11. 알려진 함정과 교훈

`tasks/lessons.md`에서 특히 중요한 항목:

- Next 16 Turbopack + Tailwind 4 root 감지 실패가 WSL freeze를 만들 수 있다. dev는 webpack fallback 유지.
- LLM `max_tokens`를 지나치게 줄이면 JSON이 잘려 gate fallback이 발생하고 오히려 전체 latency가 폭증한다.
- APK bytecode pattern은 심화 정적 분석이지 동적 분석이 아니다. 용어를 정확히 써야 한다.
- 위험 기능은 기본 비활성, local hard block, remote only 패턴으로 추가한다.
- Identity Boundary는 문서가 아니라 테스트로 지켜야 한다.

## 12. 현재 작업트리 관찰

분석 시점의 `git status --short`에는 `.scamguardian/active_models.json.bak`와 SQLite 백업 파일들이
untracked로 보였다. 런타임/백업 데이터로 보이며, 코드 작업 중 임의 삭제하거나 정리하지 않는다.

## 13. 작업 시 우선순위

1. 먼저 `tasks/lessons.md`와 이 파일을 읽는다.
2. 사용자 요청이 3단계 이상이거나 설계 판단이 있으면 `tasks/todo.md`에 체크리스트를 작성하고 확인한다.
3. 변경 범위는 최소화한다. FastAPI 비즈니스 로직, Next proxy/UI, pipeline phase 경계를 섞지 않는다.
4. 새 user-facing 문구는 Identity Boundary를 통과하는지 확인한다.
5. 외부 API, sandbox, APK 실행, 학습 subprocess는 보안/비용/리소스 경계를 먼저 확인한다.
6. 완료 전 diff와 관련 테스트/명령으로 실제 검증한다.
