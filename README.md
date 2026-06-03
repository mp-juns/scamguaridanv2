# ScamGuardian

ScamGuardian 은 **사기 판정 시스템이 아니라 사기 신호 검출 reference implementation** 입니다.
VirusTotal 이 70개 백신의 검출 결과를 보고만 하고 "이 파일은 사기다" 판정하지 않는 것과 동일한 모델로,
ScamGuardian 은 멀티모달 의심 콘텐츠(URL·파일·이미지·PDF·통화 녹음)에서 위험 신호를 검출하고
각 신호의 학술/법적 근거를 transparent 하게 제공합니다.
판정 logic 은 통합한 기업(통신사·은행·메신저 앱)이 자기 risk tolerance 에 따라 구현합니다.

> 📖 **상세 아키텍처·시나리오·API·플래그 명세**: [`.scamguardian/README.md`](./.scamguardian/README.md)
> ⚠️ **Identity Boundary**: 점수·등급은 더 이상 외부에 노출하지 않습니다 — `CLAUDE.md` 의 Forbidden Actions 참조.

## 빠른 실행

### 의존성
```bash
pip install -r requirements.txt
pip install pypdfium2                  # PDF 렌더 (필수)
```

## 담당 역할

ScamGuardian v2는 제가 주도적으로 설계하고 구현한 팀 프로젝트입니다.

전체 시스템 아키텍처, 백엔드 API, 프론트엔드, 데이터베이스 구조, 분석 파이프라인, 샌드박스 연동, 테스트 구조, 운영 관련 요소까지 직접 구현했습니다. 단순히 “사기/정상”을 판정하는 분류기가 아니라, 문자·URL·파일·이미지·PDF·APK 등 다양한 입력에서 의심 신호를 추출하고 근거 기반으로 위험도를 분석하는 멀티모달 사기 신호 탐지 플랫폼으로 설계했습니다.

### 주요 기여

- 멀티모달 사기 신호 탐지 시스템 전체 아키텍처 설계
- FastAPI 기반 백엔드 및 분석 API 구현
- 사용자 흐름에 맞춘 프론트엔드 구현
- 데이터베이스 구조 설계 및 연동
- 텍스트, URL, 파일, 이미지, PDF, APK 관련 위험 신호 분석 파이프라인 구현
- 샌드박스형 분석 구조 및 안전한 처리 흐름 설계
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
pytest    # 114 passed
```

## 브랜치별 작업 정리

### hh — 3단계 캐스케이드 분류 재설계 (2026-05-19, [`hh.md`](./hh.md))

12개 사기유형 단일 강제 분류의 두 결함(정상·뉴스 콘텐츠 강제 분류 / 복합 스캠 단일 유형 강제)을 1단계(게이트) → 2단계(유형) → 3단계(신호) 캐스케이드로 해소.

- **Stage 1 — 콘텐츠 게이트**: Claude Haiku 기반 5-bucket 분류 (`정상` / `사기 시도` / `사기 뉴스·교육` / `의심되지만 불충분` / `판단 불가`). **내부 라우팅 전용** — 외부 API 응답에 비노출 (Identity Boundary 유지). bucket 별 실행 강도 라우팅(Serper·LLM 가지치기), 룰 기반 신호검출은 항상 수행 (게이트 오판 시 검출 누락 방지)
- **Stage 2 — multi-label 라우팅**: 임계값 초과 상위 N개 유형의 엔티티 라벨셋 합집합을 extractor 에 전달 → 복합 스캠 엔티티 누락 해소. 표면 `scam_type` 은 top-1 유지
- **Stage 3 — 신호 그룹핑 레이어**: 51개 세부 `DETECTED_FLAGS` / `FLAG_RATIONALE` 완전 보존, 11개 의미 그룹으로 묶는 표시 레이어만 추가 (`pipeline/flag_groups.py`)
- **학습·평가 파이프라인**: source_ref 기반 leakage 방지 split, gate/scam_type/signals 평가, baseline vs current 라벨 커버리지 비교
- 회귀 가드: 게이트 18 + 룰 신호 6 + 학습평가 21 케이스 추가 (282 통과)

세부 체크리스트: [`tasks/todo.md`](./tasks/todo.md) 의 "3단계 캐스케이드" 섹션.

### kyy — 영상 분석 latency 단축 (2026-05-24, [`kyy.md`](./kyy.md))

baseline ~14.5s → 1분 영상 평균 **~9.2s** (78% 10s 이내, 최단 7.8s).

- **STT 병렬 chunking** (`pipeline/stt.py`): 45s 초과 오디오는 ffmpeg segment 분할 후 ThreadPoolExecutor(4) 로 Whisper API 병렬 호출. 짧은 오디오는 기존 1-shot 유지. chunk 마다 비용 ledger 정확 기록
- **게이트 최적화** (`pipeline/gate.py`): 시스템 프롬프트 트림(~950→600자), 뉴스 narration heuristic fast-path 추가 (강한 마커 2+ & 직접 요구 0 → `scam_news_edu` 즉시, LLM skip)
- **Phase 1.5+2+3 통합 병렬화** (`pipeline/runner.py`): `STT → [Gate ‖ Classify ‖ Extract(union) ‖ RAG] all parallel → LLM (conditional)`. Gate=normal 이면 Extract 무시. LLM 만 sequential ($ 절약)
- **회귀 lesson**: `max_tokens=60` 단축이 JSON 출력 잘림 → fallback bucket → 모든 단계 실행 → 33-40s 폭증. 120 복구. `tasks/lessons.md` 패턴 5 등록 ("출력 캡은 예상 길이 2-3배 안전 마진, fallback 라우팅 비용도 함께 고려")
- 회귀 가드: `tests/test_stt_chunked.py` 6 + `tests/test_gate.py` 6 신규 (322 통과)
- **cloudflared quick tunnel**: phh 의 tailscale funnel + ngrok 와 포트·터널 격리(`8001/3101`)된 `scripts/start_kyy.sh` 신설. phh 카카오 웹훅 보호

## 디버깅 Journal

세션 트랜스크립트 — 사용자 prompt + Claude 가 한 일. 같은 함정 만난 사람이 시간 안 잃기를.

### 2026-05-28 — WSL freeze 4시간 디버깅 ([`journal/2026-05-28-wsl-freeze.md`](./journal/2026-05-28-wsl-freeze.md))

`./scripts/start_stack.sh` 실행 시 WSL 무한 프리징. 메모리 8GB 부족 가설로 시작했지만, 진짜 원인은 **Next 16 Turbopack 무한 resolve 누수 × Acronis True Image 디스크 80% 점유** 의 시너지.

- **1차 trigger** (호스트): Acronis True Image 가 디스크 80% I/O 점유 → WSL 이 남은 20% 만 사용
- **2차 trigger** (WSL): Next 16 Turbopack root 자동 감지 실패 + ESM `__dirname` 함정 → next-server JS heap **3GB → 22GB (30초 만에)**
- **악순환**: WSL swap → 호스트 디스크 saturated → 9P 마운트 hang → D-state 좀비 누적 → load avg 56 → WSL freeze
- **fix**: `next dev --webpack` (Next 16 공식 fallback) + `fileURLToPath(import.meta.url)` ESM-safe root + Acronis 제거 + 진단용 [`scripts/monitor_resources.sh`](./scripts/monitor_resources.sh) 신설
- **교훈**: RSS 가 아닌 VSZ 봐야 누수 보임 / D-state + `folio_wait_bit_common` = 9P I/O hang / 메모리 증설은 임시 버퍼 / *환경 변화 (호스트 백업 SW 활성화 등)* 도 root cause 후보

## 디렉터리

```
api_server.py        FastAPI — 모든 비즈니스 로직 (분석·webhook·라벨링·플랫폼 어드민)
pipeline/            7-Phase 분석 파이프라인 (Phase 0~5, 0.5 sandbox 포함)
platform_layer/      API key·rate limit·cost ledger·observability·abuse_guard
db/                  Postgres / SQLite 라우팅 facade
apps/web/            Next.js 16 — 프록시 + 어드민 UI
sandbox_server/      v3.5 — 격리 VM 안에서 도는 sandbox 디토네이션 서버
training/            Fine-tuning 시스템 (분류기·GLiNER)
experiments/         v4 검증 실험 (intent classifier, whisper chunker)
tests/               pytest 스위트
scripts/             배치 인제스트·운영 스크립트
.scamguardian/       런타임 데이터 + **상세 문서** (README.md)
```

## 주요 채널

- **카카오톡 챗봇**: `POST /webhook/kakao` (오픈빌더 연동)
- **웹 분석**: `https://<host>/` (프론트엔드)
- **어드민**: `https://<host>/admin/*` (라벨링 / 플랫폼 / 학습)
- **REST API**: `POST /api/analyze` (외부 클라이언트, API key 필요)
- **결과 공개 페이지**: `/result/[token]` (1시간 TTL)

자세한 내용은 [`.scamguardian/README.md`](./.scamguardian/README.md) 참고.

## APK 검출 (4-tier — 정적 3 + 동적 1)

한국 보이스피싱은 사이드로딩을 통한 악성 APK 설치가 attack chain 의 핵심입니다.
ScamGuardian 은 의심 APK 를 다음 4 단계로 검출합니다:

1. **VirusTotal 시그니처 매칭** — 70+ 백신 엔진 합의 (알려진 멀웨어). zero-day 는 못 잡음
2. **정적 분석 Lv 1** — `androguard` manifest·권한 조합·서명 검사 (zero-day 의 권한 패턴 검출)
3. **심화 정적 분석 Lv 2** — dex bytecode 패턴 매칭 (SecretCalls·KrBanker·MoqHao 등 한국 보이스피싱 패밀리의 기술 시그니처)
4. **동적 분석 Lv 3** *(격리 VM 필요)* — 별도 Android 에뮬레이터 VM 안에서 실제 실행 후 behavior 모니터링. 기본 비활성 (`APK_DYNAMIC_ENABLED=0`), 로컬 실행은 어떤 경우에도 차단 (호스트 위험).

Lv 3 는 WSL 메인 서버에서 `scripts/apk_dynamic_vm_ctl.sh` 로 Multipass VM/redroid/Frida/FastAPI 를
제어하고, WSL-local bridge(`http://127.0.0.1:18002`) 를 통해 메인 ScamGuardian 파이프라인과
연결할 수 있습니다. 실제 APK 실행은 VM 안에서만 수행합니다.

### APK 동적 분석 수동 활성화

평소 `start_stack.sh` 는 백엔드/프론트엔드만 올리고, APK 동적 분석 VM 은 **필요할 때만 수동 활성화**하는
것을 기본 정책으로 둡니다. 이유는 redroid/Frida VM 이 무겁고, 실제 APK 실행 영역이라 일반 개발 루프에
항상 붙여두기보다 분석 필요 시점에 켜는 편이 안전하고 빠르기 때문입니다.

```bash
# 상태 확인
./scripts/apk_dynamic_vm_ctl.sh status

# VM/redroid/frida/API/WSL bridge 전체 기동
./scripts/apk_dynamic_vm_ctl.sh start

# 메인 ScamGuardian .env 에 APK_DYNAMIC_* 연결값 반영
./scripts/apk_dynamic_vm_ctl.sh apply-env

# 연결 확인
./scripts/apk_dynamic_vm_ctl.sh health

# active fixture 로 5개 런타임 flag 검출 확인
python scripts/check_apk_dynamic_remote.py --apk tests/fixtures/dynamic_active.apk --timeout 30
```

현재 개발 환경의 연결 형태:

```text
ScamGuardian backend (WSL)
  -> http://127.0.0.1:18002
  -> WSL bridge
  -> Multipass VM sg-sandbox
  -> apk_dynamic_server:8002
  -> redroid + frida-server
```

`start_stack.sh` 에 VM 자동 기동을 기본으로 넣지는 않습니다. 데모처럼 매번 APK 동적 분석이 필요한
상황에서는 별도 옵션(`ENABLE_APK_DYNAMIC_VM=true`)으로 붙이는 방식을 권장합니다.

학술 기준 정적 분석 검출률은 **60-80%** 이고, **100% 차단을 약속하지 않습니다**.
검출된 신호와 학술/법적 근거를 transparent 하게 제공하고, 판정·차단은 통합 기업이
자기 risk tolerance 에 따라 합니다 (Identity Boundary).

> 차별화는 "100% 잡는다" 가 아니라 "VirusTotal·시티즌코난 등 시그니처 솔루션이
> zero-day 에 약한 부분을 bytecode 패턴 분석으로 보완하는 reference architecture".

자세한 architecture: `CLAUDE.md` 의 *APK Detection Architecture (3-tier)* 섹션.

## 최근 개발 진행 (2026-05-27)

### classifier-v1 1차 학습 (sanity check, 비활성)

- 누적 `data/processed/user_samples_2026-05-26.jsonl` (99줄) + DB `human_annotations`
  머지본으로 mDeBERTa scam_type 분류기 LoRA fine-tune 1차 시도
- 환경 패치: `training/train_classifier.py` 의 `tokenizer=` → `processing_class=`
  (transformers 5.1.0 Trainer API 변경), `fp16=` → `bf16=` (LoRA 호환)
- 결과 (`checkpoints/classifier-v1/`): train 65 / val 8, **eval_macro_f1 0.167** —
  7클래스 랜덤(0.143) 근접. **활성화 안 함** (`active_models.json` 분류기 비활성 유지),
  파이프라인 sanity check 로만 판정
- 자세한 metric·환경 패치·라벨별 부족분 표: [`changes.md` 2026-05-27 섹션](./changes.md)

### 학습 데이터 정비

- **`data/processed/user_samples_2026-05-26.jsonl`** (99줄): 사용자 수집 + 정상 안내문.
  `scam_attempt 62 / normal 21 / scam_news_edu 16`
- **`data/generated_data/scamguardianv2_manual_diverse_synthetic_nodup_2026-05-27.jsonl`**
  (171건): 마스킹 처리된 합성 데이터 (`[URL_MASKED]` 등, `non_deployable: true`).
  19개 시나리오 × 9 scam_type + normal 40 + scam_news_edu 40. 스키마가 `training/data.py`
  와 완벽 매치 — 즉시 `--extra-jsonl` 머지 가능
- **`data/aihub/original/`** (9.4 GB): AI Hub dataset 71768 — 광주 119 신고 통화 20,129건
  JSON (구급 15,956 / 구조 4,025 / 기타 148). 본질이 *진짜 응급 신고*라 보이스피싱 라벨
  직접 매핑 불가, **normal 보강용 200~500건 발췌 한정**
- **`aihub_download.sh`**: AI Hub dataset 71768 의 6개 filekey 다운로드 스크립트.
  AIHUB_API_KEY 검증 + ./data/aihubshell 호출. 단 dataset 활용 미승인 시 502 반환
  (사이트에서 수동 신청·승인 필요)

### 라벨별 부족분 (2026-05-27 기준)

| 라벨 | user_samples+DB | 합성 합산 후 | v2 목표(30) | v3 목표(50) |
|---|--:|--:|--:|--:|
| 스미싱 | 22 | 48 | ✅ | -2 |
| 기관 사칭 | 12 | 37 | ✅ | -13 |
| 대출 사기 | 10 | 15 | -15 | -35 |
| 메신저 피싱 | 9 | 14 | -16 | -36 |
| 투자 사기 | 7 | 12 | -18 | -38 |
| 중고거래 사기 | 7 | 12 | -18 | -38 |
| 로맨스 스캠 | 6 | 11 | -19 | -39 |
| 코인 사기 | 4 | 9 | -21 | -41 |
| 취업·알바 사기 | 4 | 4 | -26 ❌ | -46 |
| 건강식품 사기 | 3 | 3 | -27 ❌ | -47 |
| 납치·협박형 | 2 | 2 | -28 ❌ | -48 |
| 부동산 사기 | 1 | 1 | -29 ❌ | -49 |

❌ 4종은 합성 데이터로도 미보강 — 별도 sourcing 필요 (Claude 합성 추가 / 119 데이터는
직접 매핑 부적합).

### 다음 행보

1. **classifier-v1.5**: user_samples + 합성(171건) 머지 학습 → macro_f1 변화 측정
2. **부족 4라벨** (취업알바·건강식품·납치·부동산) 시나리오 추가 합성
3. **AI Hub 71768 일부 normal 발췌** (200~500건) — 분량 통제 후 머지
4. **v2 도달 시 base 모델 ablation** — mDeBERTa-v3 vs KcELECTRA-base-v2022 vs klue/roberta-base

## 배포

- **Frontend**: Vercel (Root Directory: `apps/web`)
- **Backend**: Render / VPS (`uvicorn api_server:app --host 0.0.0.0 --port $PORT`)
- **Sandbox 서버 (v3.5)**: 별도 VM/VPS — `sandbox_server/README.md`
- 세부 설정: `DEPLOY.md`, `render.yaml`

## 라이선스 / 기여

내부 프로젝트. 외부 기여 시 사전 협의 필요.
