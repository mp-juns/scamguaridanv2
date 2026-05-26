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

## APK 검출 (4-tier — 정적 3 + 동적 1 인터페이스)

한국 보이스피싱은 사이드로딩을 통한 악성 APK 설치가 attack chain 의 핵심입니다.
ScamGuardian 은 의심 APK 를 다음 4 단계로 검출합니다:

1. **VirusTotal 시그니처 매칭** — 70+ 백신 엔진 합의 (알려진 멀웨어). zero-day 는 못 잡음
2. **정적 분석 Lv 1** — `androguard` manifest·권한 조합·서명 검사 (zero-day 의 권한 패턴 검출)
3. **심화 정적 분석 Lv 2** — dex bytecode 패턴 매칭 (SecretCalls·KrBanker·MoqHao 등 한국 보이스피싱 패밀리의 기술 시그니처)
4. **동적 분석 Lv 3** *(인터페이스만 — 격리 VM 필요)* — 별도 Android 에뮬레이터 VM 안에서 실제 실행 후 behavior 모니터링. 기본 비활성 (`APK_DYNAMIC_ENABLED=0`), 로컬 실행은 어떤 경우에도 차단 (호스트 위험).

Lv 3 는 인터페이스 + flag 카탈로그까지 박혔고, 실제 remote VM 측 서버는 v3.5 sandbox_server/
패턴과 동일하게 별도 호스트에 배포해야 동작합니다 (future work).

학술 기준 정적 분석 검출률은 **60-80%** 이고, **100% 차단을 약속하지 않습니다**.
검출된 신호와 학술/법적 근거를 transparent 하게 제공하고, 판정·차단은 통합 기업이
자기 risk tolerance 에 따라 합니다 (Identity Boundary).

> 차별화는 "100% 잡는다" 가 아니라 "VirusTotal·시티즌코난 등 시그니처 솔루션이
> zero-day 에 약한 부분을 bytecode 패턴 분석으로 보완하는 reference architecture".

자세한 architecture: `CLAUDE.md` 의 *APK Detection Architecture (3-tier)* 섹션.

## 배포

- **Frontend**: Vercel (Root Directory: `apps/web`)
- **Backend**: Render / VPS (`uvicorn api_server:app --host 0.0.0.0 --port $PORT`)
- **Sandbox 서버 (v3.5)**: 별도 VM/VPS — `sandbox_server/README.md`
- 세부 설정: `DEPLOY.md`, `render.yaml`

## 라이선스 / 기여

내부 프로젝트. 외부 기여 시 사전 협의 필요.
