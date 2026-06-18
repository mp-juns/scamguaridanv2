# ScamGuardian

ScamGuardian 은 **사기 판정 시스템이 아니라 사기 신호 검출 reference implementation** 입니다.
VirusTotal 이 70개 백신의 검출 결과를 보고만 하고 "이 파일은 사기다" 판정하지 않는 것과 동일한 모델로,
ScamGuardian 은 멀티모달 의심 콘텐츠(텍스트·URL·파일·이미지·PDF·APK·통화 녹음)에서 위험 신호를 검출하고
각 신호의 학술/법적 근거를 transparent 하게 제공합니다.
판정 logic 은 통합한 기업(통신사·은행·메신저 앱)이 자기 risk tolerance 에 따라 구현합니다.

> 📖 **상세 아키텍처·시나리오·API·플래그 명세**: [`.scamguardian/README.md`](./.scamguardian/README.md)
> ⚠️ **Identity Boundary**: 점수·등급은 외부에 노출하지 않습니다 — `CLAUDE.md` 의 Forbidden Actions 참조.
> 📜 **변경 이력**: 마일스톤 단위 상세 기록은 [`changes.md`](./changes.md) 참고.

## 빠른 실행

### 의존성
```bash
pip install -r requirements.txt
pip install pypdfium2                  # PDF 렌더 (필수)
```

## 담당 역할

ScamGuardian v2는 제가 주도적으로 설계하고 구현한 팀 프로젝트입니다.

전체 시스템 아키텍처, 백엔드 API, 프론트엔드, 데이터베이스 구조, 분석 파이프라인, 샌드박스 연동, 테스트 구조, 운영 관련 요소까지 직접 구현했습니다. 단순히 "사기/정상"을 판정하는 분류기가 아니라, 문자·URL·파일·이미지·PDF·APK 등 다양한 입력에서 의심 신호를 추출하고 근거와 함께 보고하는 멀티모달 사기 신호 탐지 플랫폼으로 설계했습니다.

### 주요 기여

- 멀티모달 사기 신호 탐지 시스템 전체 아키텍처 설계
- FastAPI 기반 백엔드 및 분석 API 구현
- 사용자 흐름에 맞춘 프론트엔드 구현
- 데이터베이스 구조 설계 및 연동
- 텍스트, URL, 파일, 이미지, PDF, APK 관련 위험 신호 분석 파이프라인 구현
- 샌드박스형 분석 구조 및 안전한 처리 흐름 설계
- 3단계 캐스케이드 분류(게이트 → 유형 → 신호) + 게이트/분류기 학습·증강 웹 워크플로 구축
- 테스트 코드와 실행 스크립트 구성
- 단순 이진 판정이 아닌 근거 기반 risk signal 중심 구조로 설계

### 환경변수 (`.env`)
```bash
# 분석에 필수
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...                  # Whisper API
SERPER_API_KEY=...                     # 교차검증
VIRUSTOTAL_API_KEY=...                 # Phase 0 안전성

# 옵션
SCAMGUARDIAN_DATABASE_URL=postgresql:// # 없으면 SQLite
SCAMGUARDIAN_PERSIST_RUNS=true          # 분석 결과 DB 저장
SCAMGUARDIAN_PUBLIC_URL=https://...     # 결과 페이지 베이스
```

### 실행
```bash
# 백엔드 (FastAPI)
uvicorn api_server:app --reload

# 프론트엔드 (Next.js)
cd apps/web && npm install && npm run dev

# 한 번에 (Tailscale Funnel 포함)
./scripts/start_stack.sh
./scripts/watch_logs.sh
```

### CLI 분석
```bash
python run_analysis.py "https://youtube.com/watch?v=..."
python run_analysis.py --text "투자 설명 텍스트"
```

### 테스트
```bash
pytest    # 398 passed
```

## 브랜치별 작업 정리

### hh — 3단계 캐스케이드 분류 재설계 (2026-05-19, [`archive/hh.md`](./archive/hh.md))

12개 사기유형 단일 강제 분류의 두 결함(정상·뉴스 콘텐츠 강제 분류 / 복합 스캠 단일 유형 강제)을 1단계(게이트) → 2단계(유형) → 3단계(신호) 캐스케이드로 해소.

- **Stage 1 — 콘텐츠 게이트**: Claude Haiku 기반 5-bucket 분류 (`정상` / `사기 시도` / `사기 뉴스·교육` / `의심되지만 불충분` / `판단 불가`). **내부 라우팅 전용** — 외부 API 응답에 비노출 (Identity Boundary 유지). bucket 별 실행 강도 라우팅(Serper·LLM 가지치기), 룰 기반 신호검출은 항상 수행 (게이트 오판 시 검출 누락 방지)
- **Stage 2 — multi-label 라우팅**: 임계값 초과 상위 N개 유형의 엔티티 라벨셋 합집합을 extractor 에 전달 → 복합 스캠 엔티티 누락 해소. 표면 `scam_type` 은 top-1 유지
- **Stage 3 — 신호 그룹핑 레이어**: 51개 세부 `DETECTED_FLAGS` / `FLAG_RATIONALE` 완전 보존, 11개 의미 그룹으로 묶는 표시 레이어만 추가 (`pipeline/flag_groups.py`)
- **학습·평가 파이프라인**: source_ref 기반 leakage 방지 split, gate/scam_type/signals 평가, baseline vs current 라벨 커버리지 비교

### kyy — 영상 분석 latency 단축 (2026-05-24, [`archive/kyy.md`](./archive/kyy.md))

baseline ~14.5s → 1분 영상 평균 **~9.2s** (78% 10s 이내, 최단 7.8s).

- **STT 병렬 chunking** (`pipeline/stt.py`): 45s 초과 오디오는 ffmpeg segment 분할 후 ThreadPoolExecutor(4) 로 Whisper API 병렬 호출. 짧은 오디오는 기존 1-shot 유지. chunk 마다 비용 ledger 정확 기록
- **게이트 최적화** (`pipeline/gate.py`): 시스템 프롬프트 트림(~950→600자), 뉴스 narration heuristic fast-path 추가 (강한 마커 2+ & 직접 요구 0 → `scam_news_edu` 즉시, LLM skip)
- **Phase 1.5+2+3 통합 병렬화** (`pipeline/runner.py`): `STT → [Gate ‖ Classify ‖ Extract(union) ‖ RAG] all parallel → LLM (conditional)`. Gate=normal 이면 Extract 무시. LLM 만 sequential ($ 절약)
- **회귀 lesson**: `max_tokens=60` 단축이 JSON 출력 잘림 → fallback bucket → 모든 단계 실행 → 33-40s 폭증. 120 복구. `tasks/lessons.md` 패턴 5 등록

## 디버깅 Journal

### 2026-05-28 — WSL freeze 디버깅 ([`journal/2026-05-28-wsl-freeze.md`](./journal/2026-05-28-wsl-freeze.md))

`./scripts/start_stack.sh` 실행 시 WSL 무한 프리징. 메모리 8GB 부족 가설로 시작했지만, 진짜 원인은 **Next 16 Turbopack 무한 resolve 누수 × Acronis True Image 디스크 80% 점유** 의 시너지.

- **fix**: `next dev --webpack` (Next 16 공식 fallback) + `fileURLToPath(import.meta.url)` ESM-safe root + Acronis 제거 + 진단용 [`scripts/monitor_resources.sh`](./scripts/monitor_resources.sh) 신설
- **교훈**: RSS 가 아닌 VSZ 봐야 누수 보임 / D-state + `folio_wait_bit_common` = 9P I/O hang / *환경 변화 (호스트 백업 SW 활성화 등)* 도 root cause 후보

## 디렉터리

```
api_server.py        FastAPI 진입점 — 라우터는 api_server_pkg/ 로 분리
api_server_pkg/      분석·webhook·라벨링·학습·증강·APK 라우터
pipeline/            7-Phase 분석 파이프라인 (Phase 0~5, 0.5 sandbox 포함)
                     — config 는 config_taxonomy/gate/flags, STT 는 stt_common/claude/clova,
                       카카오 포맷터는 kakao_result/dialog 로 분리 (원본 모듈 = facade)
platform_layer/      API key·rate limit·cost ledger·observability·abuse_guard
db/                  Postgres / SQLite 라우팅 facade (sqlite 는 core/runs/platform 분리)
apps/web/            Next.js 16 — 프록시 + 어드민 UI (분석/라벨링/학습/증강/APK)
sandbox_server/      v3.5 — 격리 VM 안에서 도는 sandbox 디토네이션 서버
training/            Fine-tuning 시스템 (분류기·GLiNER·게이트 평가 세션·증강 세션)
experiments/         v4 검증 실험 (intent classifier, whisper chunker)
tests/               pytest 스위트 (398)
scripts/             배치 인제스트·증강·게이트 학습·운영 스크립트
docs/                실험 결과·데이터 감사·통합 가이드 (experiments/, audits/)
archive/             완료된 브랜치 노트·일회성 마이그레이션 스크립트
data/processed/      seed 데이터 — admin_seeds.jsonl + pending_*.jsonl (검증 대기분)
.scamguardian/       런타임 데이터 + **상세 문서** (README.md)
```

## 주요 채널

- **카카오톡 챗봇**: `POST /webhook/kakao` (오픈빌더 연동)
- **웹 분석**: `https://<host>/` (프론트엔드)
- **라이브 보이스 (실시간 통화 탐지)**: `/live` — 브라우저 마이크로 통화 음성을 실시간 전사하며 보이스피싱 신호 검출
- **APK 검사 (공개)**: `/apk` — APK 업로드/샘플 검사 + 동적 분석 상태
- **어드민**: `https://<host>/admin/*` (라벨링 / 플랫폼 / 학습 / 증강 — 게이트 학습·시각화 포함)
- **REST API**: `POST /api/analyze` (외부 클라이언트, API key 필요), `POST /api/live-analyze` (실시간 청크 스트리밍)
- **결과 공개 페이지**: `/result/[token]` (1시간 TTL)

자세한 내용은 [`.scamguardian/README.md`](./.scamguardian/README.md) 참고.

## 라이브 보이스 — 실시간 통화 중 사기 탐지 (`/live`)

통화 *중* 개입을 목표로 하는 v4 기능입니다.

- **Live v4 (기본)**: AudioWorklet 16kHz PCM → WebSocket `/ws/live-transcribe` → 3초 chunk OpenAI Whisper STT → 즉시 신호 스캔
- **PCM HTTP fallback**: WebSocket 실패 시 `POST /api/live-pcm-chunk` 로 같은 16kHz PCM chunk 경로 사용 (최후 수단만 legacy `POST /api/live-analyze`)
- 백엔드: `api_server_pkg/{live_ws,live_pcm_http,live_stream,stream_analyze}.py`, `pipeline/live_stt.py`
- 프론트: `apps/web/src/app/live/` (`useLiveWebSocket.ts`, `useLivePcmHttp.ts`, `live-pcm-processor.js`)
- 환경변수: `LIVE_WS_ENABLED=1`, `OPENAI_API_KEY`, `NEXT_PUBLIC_LIVE_WS_URL` (Tailscale/ngrok WSS)
- 메인 허브 **시연 모드**: `/` 하단 — ML 3-tier + 증강·학습 세션 상태 (`GET /api/demo/ml-snapshot`)

## APK 검출 (4-tier — 정적 3 + 동적 1)

한국 보이스피싱은 사이드로딩을 통한 악성 APK 설치가 attack chain 의 핵심입니다.
ScamGuardian 은 의심 APK 를 다음 4 단계로 검출합니다:

1. **VirusTotal 시그니처 매칭** — 70+ 백신 엔진 합의 (알려진 멀웨어). zero-day 는 못 잡음
2. **정적 분석 Lv 1** — `androguard` manifest·권한 조합·서명 검사 (zero-day 의 권한 패턴 검출)
3. **심화 정적 분석 Lv 2** — dex bytecode 패턴 매칭 (SecretCalls·KrBanker·MoqHao 등 한국 보이스피싱 패밀리의 기술 시그니처)
4. **동적 분석 Lv 3** *(격리 VM 필요)* — 별도 Android 에뮬레이터 VM 안에서 실제 실행 후 behavior 모니터링. 기본 비활성 (`APK_DYNAMIC_ENABLED=0`), 로컬 실행은 어떤 경우에도 차단 (호스트 위험).

공개 페이지 `/apk` 에서 APK 업로드·샘플 검사를 직접 시연할 수 있습니다
(`api_server_pkg/apk_public.py` + `apps/web/src/app/apk/`).

Lv 3 는 WSL 메인 서버에서 `scripts/apk_dynamic_vm_ctl.sh` 로 Multipass VM/redroid/Frida/FastAPI 를
제어하고, WSL-local bridge(`http://127.0.0.1:18002`) 를 통해 메인 ScamGuardian 파이프라인과
연결할 수 있습니다. 실제 APK 실행은 VM 안에서만 수행합니다.

### APK 동적 분석 수동 활성화

평소 `start_stack.sh` 는 백엔드/프론트엔드만 올리고, APK 동적 분석 VM 은 **필요할 때만 수동 활성화**하는
것을 기본 정책으로 둡니다.

```bash
./scripts/apk_dynamic_vm_ctl.sh status      # 상태 확인
./scripts/apk_dynamic_vm_ctl.sh start       # VM/redroid/frida/API/WSL bridge 전체 기동
./scripts/apk_dynamic_vm_ctl.sh apply-env   # 메인 .env 에 APK_DYNAMIC_* 연결값 반영
./scripts/apk_dynamic_vm_ctl.sh health      # 연결 확인
python scripts/check_apk_dynamic_remote.py --apk tests/fixtures/dynamic_active.apk --timeout 30
```

학술 기준 정적 분석 검출률은 **60-80%** 이고, **100% 차단을 약속하지 않습니다**.
검출된 신호와 학술/법적 근거를 transparent 하게 제공하고, 판정·차단은 통합 기업이
자기 risk tolerance 에 따라 합니다 (Identity Boundary).

> 차별화는 "100% 잡는다" 가 아니라 "VirusTotal·시티즌코난 등 시그니처 솔루션이
> zero-day 에 약한 부분을 bytecode 패턴 분석으로 보완하는 reference architecture".

자세한 architecture: `CLAUDE.md` 의 *APK Detection Architecture* 섹션 + [`docs/sg-apk.md`](./docs/sg-apk.md).

## 최근 개발 진행 (2026-06-11)

### 게이트(content_label) 학습·증강 웹 워크플로 완성 (2026-06-10)

- **게이트 학습을 `/admin/training` 에 연결**: 기존 CLI 전용이던 `scripts/content_label_gate.py --train`
  을 파인튜닝 세션(subprocess)으로 배선. 게이트 세션은 `kind=gate`(평가 전용, 파이프라인 적용 불가)로
  표시되고, confusion 히트맵 + per-class P/R/F1 + 집중 오류셀 시각화 제공
- **증강 2파트 분리** (`/admin/augment`): ① 게이트(정상·사기·예방 3-class — content_label 필터 증강,
  정상/예방 hard negative 씨앗 폼) ② 분석 분류기·추출기(scam_type 12종). seed 균형 차트는
  *Seed 후보*(data/processed) vs *실제 학습 데이터*(augmented) 두 기준을 나란히 표시
- **게이트 성능** (3-class, group-split val): accuracy **0.979** / macro_f1 **0.960**,
  정상→사기 오탐 14.5% → **2.6%** (정상 hard negative 보강 효과)

### 5-class scam_category 벤치마크 (2026-06-09, [`docs/experiments/`](./docs/experiments/))

- 12 scam_type 을 5 카테고리(투자·가상자산형 / 관계·지인 사칭형 / 거래·취업형 / 기관·금융 사칭형 /
  링크·문자 유도형)로 묶는 group-split 벤치마크: macro_f1 **0.883 → 0.927 → 0.957** (3차 안정화)
- 개선 동력: romance-crypto 재라벨(D2 규칙: 금전 메커니즘 기준) + 위장형 투자 seed + 실물 seed 보강
- ⚠️ **합성 증강 val 기준** — 실세계 held-out 미검증. seed 다양성(일부 유형 seed 4개 × 110배 복제)
  한계는 [`docs/audits/data_audit_6class_20260608.md`](./docs/audits/data_audit_6class_20260608.md) 참고

### 학습 데이터 현황 (2026-06-11 기준)

- **seed**: `admin_seeds.jsonl` 244건 (scam_attempt 153 / normal 72 / scam_news_edu 19)
  + `pending_*.jsonl` 검증 대기분 — UI 집계 기준 scam_attempt seed 228 / normal 135 / news_edu 22
- **증강 학습 데이터**: `user_samples_augmented.jsonl` **4,362건**
  (scam_attempt 3,120 / normal 911 / scam_news_edu 331) — 정상 hard negative 911건은
  세금·공과금·금융고지·배송 등 "사기와 표면이 닮은 정상문" 중심
- **모델 적용 상태**: fine-tuned 분류기는 **현재 비활성** (`active_models.json` —
  DiaConfig 호환성 오류로 로드 실패 이력, zero-shot fallback 동작 중). 재학습 후
  `/admin/training` 에서 재활성화 필요

### 프로젝트 구조 정리 (2026-06-11)

- 긴 모듈 6개 분리 (facade 패턴, 기존 import 100% 호환): `pipeline/config`(1,059줄→143)·
  `pipeline/stt`(922→365)·`pipeline/kakao_formatter`(765→51)·`db/sqlite_repository`(1,264→57)·
  `TrainingClient.tsx`(1,763→923)·`AdminRunEditor.tsx`(1,268→869)
- 루트 md 13→6개: 실험·감사 → `docs/`, 완료 브랜치노트 → `archive/`. seed 파일 `pending_*` 네이밍 통일

### 남은 일 (우선순위)

1. **실물 seed +48~60 수집** ([`docs/audits/`](./docs/audits/) §3-4 계획) → 신규 seed 만 증강 →
   group-split 재평가 → confusion 감소 확인 후 **5-class 모델 재학습·active 적용**
2. **NextAuth 어드민 게이팅 완성** — 일부 라우트 어드민 토큰만, 전체 적용 대기
3. **sandbox remote VM 운영 배포** — 코드·설계 완료, VPS 프로비저닝·TLS 필요 (`sandbox_server/README.md`)
4. **모니터링·retention 자동화** — 비용 대시보드 상시화, uploads 30일 정리 cron

## Fine-tuning & 합성 데이터

검출 파이프라인의 학습 가능한 모델들을 도메인 특화로 fine-tune 합니다. **전 과정 상세 가이드는
[`training/FINETUNING.md`](./training/FINETUNING.md)** 를 참고하세요.

| 모델 | base | 역할 | 추론 위치 |
|---|---|---|---|
| 콘텐츠 게이트 | `mDeBERTa-v3-base-mnli-xnli` | content_label 3-class (정상/사기/예방) | Stage 1 (평가 전용 세션) |
| 스캠 유형 분류기 | `mDeBERTa-v3-base-mnli-xnli` | scam_type 12종 (대표 분류는 5-class scam_category) | Phase 2 `classifier.py` |
| 엔티티 추출기 | `taeminlee/gliner_ko` | 스캠 엔티티 NER | Phase 3 `extractor.py` |

### 데이터 3소스

1. **사람 라벨링** — `/admin` 큐에서 확정한 `human_annotations` (자동 유입)
2. **외부 JSONL** — AI Hub 등 변환 데이터 (`--extra-jsonl`)
3. **실사례 seed 증강** — `/admin/augment` 웹 UI 또는 `scripts/run_augment_session.py`:
   `admin_seeds.jsonl` 의 실물/사례기반 seed 를 Claude 로 병렬 패러프레이즈 (scam_type ·
   content_label 필터 지원). 산출물 promote → `user_samples_augmented.jsonl` 병합

```bash
# 1) 증강 (웹: /admin/augment, CLI 예시)
python -m scripts.run_augment_session --seed-file data/processed/admin_seeds.jsonl \
    --output /tmp/aug.jsonl --variants 5 --content-label normal
# 2) 게이트 학습+평가 (웹: /admin/training 게이트 패널, CLI 예시)
python scripts/content_label_gate.py --input data/generated/user_samples_augmented.jsonl --train
# 3) 분류기 LoRA fine-tune
python -m training.train_classifier --output-dir checkpoints/classifier-v1 --epochs 3 --lora
# 4) /admin/training "파이프라인 적용" → active_models.json 등록 → 자동 swap
```

### 학습 시스템 특징

- **웹 UI** (`/admin/training`): subprocess 백그라운드 학습 + `metrics.jsonl` 폴링 진행률 그래프 +
  활성화 버튼. classifier/GLiNER 순차 학습 + **게이트 학습 패널**(평가 전용, confusion 시각화)
- **LoRA/PEFT 어댑터** 체크포인트 자동 로딩, `--early-stopping` 지원
- **자동 swap**: `.scamguardian/active_models.json` 등록 시 60초 내 파이프라인 반영, 무효 경로는 base fallback
- **모델 비교** (`/admin/training/compare`): 같은 입력에서 *active 모델 vs Claude(raw) vs fine-tuned* 3관점 대조
- **데이터 증강** (`/admin/augment`): 게이트/분석 2파트 — 씨앗 작성·필터 증강·세션 진행·promote

> `data/generated/` 합성 코퍼스·RAG 인덱스는 `.gitignore` 대상입니다
> (단 `user_samples_augmented.jsonl` 은 학습 기준 데이터라 추적).

## 배포

- **Frontend**: Vercel (Root Directory: `apps/web`)
- **Backend**: Render / VPS (`uvicorn api_server:app --host 0.0.0.0 --port $PORT`)
- **Sandbox 서버 (v3.5)**: 별도 VM/VPS — `sandbox_server/README.md`
- 세부 설정: `DEPLOY.md`, `render.yaml`

## 라이선스 / 기여

내부 프로젝트. 외부 기여 시 사전 협의 필요.
