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
