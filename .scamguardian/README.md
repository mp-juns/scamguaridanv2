# ScamGuardian — 상세 문서

> 메인 README 는 *실행법* 만. 이 문서는 *모든 것* — 철학·시나리오·아키텍처·API·데이터·플래그·프로토콜.

목차:
1. [핵심 철학](#1-핵심-철학----사기-funnel-다단계-인터럽트-시스템)
2. [4단계 인터럽트 시나리오](#2-4단계-인터럽트-시나리오)
3. [시스템 아키텍처](#3-시스템-아키텍처)
4. [채널별 통신 프로토콜](#4-채널별-통신-프로토콜)
5. [API 엔드포인트 전체 목록](#5-api-엔드포인트-전체-목록)
6. [파이프라인 7-Phase 상세](#6-파이프라인-7-phase-상세)
7. [플래그 시스템 (스코어링)](#7-플래그-시스템-스코어링)
8. [데이터 모델 (DB / 토큰 / 잡 상태)](#8-데이터-모델)
9. [Sandbox 격리 정책 (v3.5)](#9-sandbox-격리-정책-v35)
10. [Platform 레이어 (API key / 비용 / 어뷰즈)](#10-platform-레이어)
11. [환경 변수 전체 목록](#11-환경-변수-전체-목록)
12. [배포 토폴로지](#12-배포-토폴로지)
13. [보안·위협 모델](#13-보안위협-모델)
14. [학술 인용·참고문헌](#14-학술-인용참고문헌)

---

## 1. 핵심 철학 — *사기 funnel 다단계 인터럽트 시스템*

ScamGuardian 의 정의는 **사기를 *막는* 시스템이 아니라, 사기 funnel 의 매 단계마다 *피해자 자기인지(metacognition) trip wire 를 박는* 시스템**.

### 왜 차단기가 아니라 인터럽트인가

보이스피싱 피해자는 사기범의 권위·긴박감 프레임 안에서 *자기인지를 잃은 상태* 가 됨. 이 상태에서:
- 가족이 옆에서 "그거 사기야" → **안 들림** (외부 목소리는 이미 사기범 narrative 가 차단함)
- 본인이 머릿속으로 "이상한데" → 사기범의 즉답·압박이 의심을 덮음

**해결 모델**:
- ❌ *방화벽 모델* (단발 차단) — 한 번 뚫리면 끝. 사기 detection 정확도 99% 가 필요
- ✅ *Catch-net 모델* (다단계 인터럽트) — 한 단계 실패해도 다음 단계가 또 흔든다. 각 단계의 정확도가 80% 여도 누적 catch rate 는 (1 - 0.2⁴) ≈ **99.84%**

핵심은 **"흔든다"**:
- "🚨 사기 의심" (외부 판정) ❌
- "방금 본인이 *주민번호를 말씀하셨어요*" (본인 발화 거울) ✅

자기 목소리는 무시 못 한다. 패턴 인터럽트(pattern interrupt) — NLP/심리치료에서 검증된 메커니즘.

### 평가 지표

기존 보이스피싱 연구의 표준 = "탐지 F1". 우리의 표준 = **"사용자가 통화 종료 / 송금 중단 / 정보 누설 멈춘 비율"**. 학술적 새 영역 — *다단계 metacognitive interruption efficacy*.

---

## 2. 4단계 인터럽트 시나리오

```
사기 진행                                    우리의 trip wire
──────────                                   ──────────────────────────────────
Stage 1: 통화 시작                           Interrupt 1 — 실시간 STT 거울 (v4 Live Call Guard)
        사기범 압박                          본인이 민감정보·송금동의·메타인식 발화 시
        피해자: "네 네…"                     웹앱이 "방금 OOO 을 말씀하셨어요" 알람 + 진동
                ↓ 통과
Stage 2: 사기범이 링크 보냄                  Interrupt 2 — 링크 분석 (v3 Phase 0 + v3.5 Phase 0.5)
        "앱 깔아주세요"                      카톡으로 링크 보내면 VT URL 스캔 + 격리 Chromium 디토네이션
                ↓ 통과 (URL 깨끗)
Stage 3: APK/실행파일 도착                   Interrupt 3 — 파일 분석 (v3.5)
                                             EXECUTABLE_URL 자동 분류 → VT 파일 스캔
                                             악성 확정 → fast-path 매우 위험 (80점)
                ↓ 통과 (협박 굴복)
Stage 4: APK 설치 / 정보 누설 / 송금         Interrupt 4 — ?? (현재 미구현, 가장 임팩트 큼)
                                             후보:
                                             A. 가족·보호자 알림톡 (사전 등록 번호)
                                             B. 통화 모니터링 지속 (v4 가 stage 4 까지 동작)
                                             C. 112/금감원 자동 가이드
                                             D. 사후 복구 체크리스트
```

**Stage 4 가 hard problem 인 이유**: OS·은행·통신사 통제 못 함. 우리가 통제할 수 있는 채널 = 가족 알림톡 + UI 가이드 + 음성 모니터링 지속.

---

## 3. 시스템 아키텍처

### 3.1 전체 토폴로지

```
┌────────────────────────────────────────────────────────────────────────────┐
│                           사용자 입력 채널                                 │
│                                                                            │
│  카카오톡 챗봇 ──→  POST /webhook/kakao                                    │
│  웹 브라우저  ──→  Next.js (apps/web) ──→  proxy → POST /api/analyze       │
│  외부 SDK     ──→  POST /api/analyze (X-API-Key 헤더 필요)                 │
│  CLI          ──→  python run_analysis.py                                  │
│  배치         ──→  python scripts/batch_ingest.py                          │
└────────────────────────────────┬───────────────────────────────────────────┘
                                 │
                                 ▼
                  ┌─────────────────────────────┐
                  │  PRODUCTION SERVER          │
                  │  ─────────────────────       │
                  │  api_server.py (FastAPI)    │
                  │  ├── platform_layer         │  ← 모든 요청 통과
                  │  │   ├── api_keys           │   (인증·rate limit·비용 ledger)
                  │  │   ├── rate_limit         │
                  │  │   ├── cost (ledger)      │
                  │  │   ├── abuse_guard        │
                  │  │   └── middleware         │
                  │  │                          │
                  │  ├── pipeline.runner        │  ← 실제 분석 오케스트레이션
                  │  │   └── analyze()          │
                  │  │       ├── Phase 0   safety.py    (VT)
                  │  │       ├── Phase 0.5 sandbox.py   ──┐
                  │  │       ├── Phase 1   stt + vision  │
                  │  │       ├── Phase 2   classifier    │
                  │  │       ├── Phase 3   ┌ extractor   │
                  │  │       │             ├ llm_assessor│
                  │  │       │             └ rag         │
                  │  │       ├── Phase 4   verifier      │
                  │  │       └── Phase 5   scorer        │
                  │  │                                   │
                  │  └── db/                             │
                  │      ├── analysis_runs               │
                  │      ├── human_annotations           │
                  │      ├── api_keys / cost / log       │
                  │      └── transcript_embeddings       │
                  └──────────────┬───────────────────────┘
                                 │ HTTPS + Bearer 토큰
                                 │ (SANDBOX_REMOTE_URL)
                                 ▼
                  ┌─────────────────────────────┐
                  │  SANDBOX SERVER (별도 VM)   │
                  │  ─────────────────────      │
                  │  sandbox_server/app.py      │
                  │  ├── POST /detonate         │  ← 격리 컨테이너 생성/파괴
                  │  └── docker run --rm        │
                  │      └── Playwright Chromium│
                  │          ↓                  │
                  │      JSON + screenshot.b64  │
                  │  → production 으로 반환     │
                  │  (DB X, API key X, 데이터 X)│
                  └─────────────────────────────┘
```

### 3.2 핵심 설계 원칙

1. **API 우선** — 모든 비즈니스 로직은 FastAPI 엔드포인트. 카톡·웹·CLI·SDK 는 얇은 어댑터
2. **Phase 별 격리** — 각 phase 가 다음 phase 의 입력 형태(텍스트)로 정규화. 새 모달리티 추가 시 Phase 1 의 라우터만 수정
3. **Phase 3 병렬 실행** — extractor / llm_assessor / rag 3개를 ThreadPoolExecutor 로 동시 실행. 분류 결과만 prerequisite
4. **Sandbox 물리 분리** — production 호스트와 다른 머신에서 sandbox 가 돌아야 격리 의미 있음
5. **Stateless sandbox** — 디토네이션 결과물 즉시 삭제. 컨테이너 escape 해도 잃을 게 없음
6. **모든 외부 호출 ledger 기록** — Claude / OpenAI / Serper / VirusTotal — `cost_events` 테이블에 USD 단위 합산

### 3.3 상태 관리 위치

| 상태 종류 | 위치 | TTL |
|---|---|---|
| 카카오 멀티턴 잡 (`_pending_jobs`) | api_server.py 인메모리 | 30분 |
| 결과 토큰 (`_result_tokens`) | api_server.py 인메모리 | 1시간 |
| 분석 결과 (`analysis_runs`) | DB | 영구 (retention 정책 별도) |
| 어뷰즈 차단·위반 (`_blocks`, `_violations`) | abuse_guard.py 인메모리 | 1시간 |
| API key | DB | 영구 (revoke 가능) |
| 비용 ledger (`cost_events`) | DB | 영구 (월별 집계) |
| 요청 로그 (`request_log`) | DB | 영구 |
| 업로드 파일 (`.scamguardian/uploads/`) | 로컬 fs | retention.py 로 자동 삭제 (기본 30일) |
| 학습 세션 (`.scamguardian/training_sessions/`) | 로컬 fs (subprocess 메타) | 수동 정리 |
| Sandbox 결과 (`.scamguardian/sandbox/`) | 로컬 fs | 디토네이션 직후 즉시 삭제 |

---

## 4. 채널별 통신 프로토콜

### 4.1 카카오톡 챗봇 (`POST /webhook/kakao`)

#### 입력 페이로드 (카카오 오픈빌더 → 우리)

```jsonc
{
  "userRequest": {
    "utterance": "이거 사기 같은데 봐줘",         // 텍스트 또는 파일이면 CDN URL
    "callbackUrl": "https://kakao.../callback",   // 콜백 모드일 때만 (영상 분석 권장)
    "user": {
      "id": "U12345abcdef..."                     // 카카오 사용자 식별자 (멀티턴 키)
    }
  },
  "action": {
    "params": {
      // 커스텀 블록 파라미터. 다음 키들이 자주 옴 (실제로는 빈 {} 인 경우 많음):
      // image, picture, photo, pdf, document, video, video_url, file, attachment
      // 각 값은 string URL 또는 { "url": "..." } dict
    }
  }
}
```

#### 입력 분류 (`api_server._kakao_detect_input`)

분류 우선순위:
1. `action.params` 의 표준 키 (`image`/`pdf`/`video` 등)
2. `action.params` 의 *커스텀 키* fallback — 모든 값을 훑어 URL 인 것을 확장자로 분류
3. `utterance` 안에 URL 텍스트 → 확장자로 분류
4. 그 외 → 순수 TEXT

**실전 발견 (2026-04-30)**:
- 카카오는 *이미지* 첨부 시 `utterance` 필드에 CDN URL (`https://talk.kakaocdn.net/...png?...`) 통째로 박아 보냄. `action.params` 비어있음
- 카카오 챗봇 클라이언트는 *PDF·일반 파일* 첨부 자체를 차단 — 우리한테 메타데이터 0건 도착. 사용자에게 "캡쳐 이미지나 클라우드 링크" 안내 필요

#### `InputType` (`pipeline/kakao_formatter.py`)

| 값 | 의미 | 후속 처리 |
|---|---|---|
| `text` | 순수 텍스트 | 직접 분석 |
| `url` | 일반 URL | Phase 0 + 0.5 + STT (YouTube 면) |
| `video` | 업로드 영상 | Phase 0 + STT |
| `file` | 일반 파일 | Phase 0 + (확장자별 후속) |
| `image` | 이미지 (jpg/png/webp/…) | 다운로드 + Phase 0 + vision OCR |
| `pdf` | PDF | 다운로드 + Phase 0 + vision OCR (페이지 렌더) |

#### 멀티턴 컨텍스트 수집 흐름

1. 사용자가 콘텐츠 보냄 → 1차 분석 백그라운드 시작 + 첫 질문 즉답 (Static Q1, Claude 호출 X, ~50ms)
2. 사용자 답변 ↔ 봇이 `context_chat.next_turn()` 으로 능동 질문 (Claude Haiku, 1~3s)
3. 1차 분석 끝 → phase 는 `collecting_context` 유지, 사용자 다음 답변에 "💡 분석 끝났어요" 자동 부착 (1회만)
4. 사용자가 *결과확인 동의어* (결과확인 / 결과 알려줘 / 분석 다됐어 등) → refine LLM 호출 (~5-10s) → 결과 카드 + webLink

#### 응답 포맷 (`kakao_formatter.py`)

```jsonc
{
  "version": "2.0",
  "template": {
    "outputs": [
      { "basicCard": { "title": "🚨 매우 위험 | 80점", "description": "...", "buttons": [...] } }
    ],
    "quickReplies": [
      { "label": "사용법", "action": "message", "messageText": "사용법" },
      { "label": "분석 초기화", "action": "message", "messageText": "분석 초기화" }
    ]
  }
}
```

콜백 모드 (영상 분석 같이 오래 걸리는 경우):
```jsonc
{ "version": "2.0", "useCallback": true, "data": {} }
```
→ 이후 `userRequest.callbackUrl` 로 분석 결과를 *POST* 발신.

### 4.2 웹 / 외부 SDK (`POST /api/analyze`)

#### 인증
```
Authorization: Bearer sg_<urlsafe>      // 우선
또는
X-API-Key: sg_<urlsafe>                  // 둘 중 하나 필수
```

옵션:
```
X-User-Id: <외부 사용자 식별자>          // 어뷰즈 가드 per-user 누적용
```

#### 요청 본문
```jsonc
{
  "source": "https://youtube.com/...",   // URL 또는 raw text
  "use_llm": true,                       // Phase 3 LLM 통합 호출 (기본 true)
  "use_rag": true,                       // 유사 사례 검색
  "skip_verification": false,             // Phase 4 Serper 검증 skip
  "whisper_model": "whisper-1"            // 옵션
}
```

파일 업로드는 `POST /api/analyze-upload` (multipart):
```
file=@suspicious.png
options={"use_llm":true,...}
```

#### 응답 — `ScamReport.to_dict()`
```jsonc
{
  "scam_type": "투자 사기",
  "classification_confidence": 0.85,
  "is_uncertain": false,
  "scam_type_source": "llm",                    // classifier | llm | manual
  "scam_type_reason": "...",
  "entities": [
    { "label": "수익 퍼센트", "text": "연 30%", "score": 0.9, "source": "gliner" }
  ],
  "triggered_flags": [
    { "flag": "abnormal_return_rate", "description": "...", "score_delta": 15,
      "evidence": ["..."], "source": "rule" }
  ],
  "total_score": 45,
  "risk_level": "위험",                          // 안전(0-20) / 주의(21-40) / 위험(41-70) / 매우 위험(71-100)
  "risk_description": "다수의 스캠 징후가 확인됨",
  "agent_verdict": "사기 의심",
  "agent_reasoning": ["..."],
  "transcript_preview": "...",
  "llm_assessment": { "summary": "...", "reasoning": [...], ... },
  "safety_check": { "scanner": "virustotal", "threat_level": "safe", ... },
  "sandbox_check": { "scanner": "playwright_sandbox", "status": "completed", ... },
  "rag_context": { "enabled": true, "similar_cases": [...] },
  "analysis_run_id": "<uuid>"                    // DB 저장 시
}
```

### 4.3 Sandbox 서버 (`POST /detonate`) — production → sandbox VM

```
Headers:
  Authorization: Bearer <SANDBOX_REMOTE_TOKEN>
  Content-Type: application/json

Body:
  { "url": "https://suspicious.example", "timeout": 30 }

Response (200):
  {
    "status": "completed" | "timeout" | "blocked" | "error",
    "target_url": "...",
    "final_url": "...",                         // 리디렉션 후 최종 URL
    "redirect_chain": ["...", "..."],
    "title": "Login - Fake Bank",
    "screenshot_path": "/sandbox/out/screenshot.png",  // sandbox 내부 경로
    "screenshot_base64": "iVBORw0KG...",               // 호스트로 inline 전송
    "has_login_form": true,
    "has_password_field": true,
    "sensitive_form_fields": ["password", "주민번호"],
    "download_attempts": [{ "suggested_filename": "app.apk", "url": "..." }],
    "duration_ms": 4321,
    "error": null
  }

Auth 실패: 401 { "detail": "invalid token" }
유효성 실패: 400 { "detail": "invalid url" }
```

### 4.4 결과 공개 페이지 (`GET /api/result/{token}`)

```
Path: /api/result/<token>           // 1시간 TTL, 만료 시 410
Response:
  {
    "result": { ... ScamReport.to_dict() },
    "user_context": { qa_pairs: [...], summary_text: "..." },
    "input_type": "image",
    "chat_history": [{ "role": "user|bot", "message": "..." }, ...],
    "flag_rationale": { "<flag>": { "rationale": "...", "source": "..." } },
    "expires_at": 1730000000.0
  }
```

프론트: `apps/web/src/app/result/[token]/page.tsx` — Next.js SSR, `dynamic = "force-dynamic"`, fetch `cache: "no-store"`.

---

## 5. API 엔드포인트 전체 목록

### 5.1 공개 / 인증 별 분류

| 카테고리 | 엔드포인트 | 인증 | 비고 |
|---|---|---|---|
| **공개** | `GET /health` | 없음 | liveness |
| | `GET /api/methodology` | 없음 | 점수 산정 방식 / 학술 인용 |
| | `GET /api/result/{token}` | 없음 (token 자체가 권한) | 1시간 TTL |
| **분석** | `POST /api/analyze` | API key 필수 | 외부 SDK·웹 |
| | `POST /api/analyze-upload` | API key 필수 | multipart 업로드 |
| **카카오** | `POST /webhook/kakao` | 카카오 자체 인증 | API key skip |
| **어드민** | `/api/admin/*` | 어드민 토큰 (`SCAMGUARDIAN_ADMIN_TOKEN`) — 현재 일부만 적용, NextAuth 통합 진행 중 | |

### 5.2 분석 엔드포인트

| 메소드 | 경로 | 입력 | 출력 |
|---|---|---|---|
| POST | `/api/analyze` | `{source, use_llm, use_rag, skip_verification, ...}` | `ScamReport.to_dict()` |
| POST | `/api/analyze-upload` | multipart `file=` + `options=` | `ScamReport.to_dict()` |
| POST | `/webhook/kakao` | 카카오 페이로드 | 카카오 응답 포맷 |
| GET | `/api/result/{token}` | path param | `{result, user_context, chat_history, flag_rationale, expires_at}` |

### 5.3 어드민 — 라벨링 / 평가

| 메소드 | 경로 | 용도 |
|---|---|---|
| GET | `/api/admin/runs` | 분석 결과 리스트 (페이지네이션·필터) |
| GET | `/api/admin/runs/list` | 라벨링 큐 (claim 정보 포함) |
| GET | `/api/admin/runs/search` | 텍스트·라벨 검색 |
| GET | `/api/admin/runs/next` | 다음 미라벨링 run |
| GET | `/api/admin/runs/{id}` | 단일 run 상세 (metadata, chat_history, user_context 포함) |
| GET | `/api/admin/runs/{id}/media` | 업로드 미디어 다운로드 (이미지·PDF·영상) |
| POST | `/api/admin/runs/{id}/claim` | 검수자 클레임 (TTL 30분) |
| POST | `/api/admin/runs/{id}/annotations` | 정답 라벨 upsert |
| POST | `/api/admin/runs/{id}/ai-draft` | Claude 로 라벨 초안 생성 |
| GET | `/api/admin/metrics` | 평가 지표 (분류 정확도 / 엔티티 F1 / per_labeler / needs_review) |
| GET | `/api/admin/stats` | 대시보드 통계 |

### 5.4 어드민 — 학습 (Fine-tuning)

| 메소드 | 경로 | 용도 |
|---|---|---|
| GET | `/api/admin/training/data-stats` | 라벨 분포·학습 가능 여부 |
| POST | `/api/admin/training/sessions` | 세션 시작 (subprocess 백그라운드) |
| GET | `/api/admin/training/sessions` | 세션 리스트 + active_models |
| GET | `/api/admin/training/sessions/{id}` | 세션 상세 + metrics + log_tail |
| POST | `/api/admin/training/sessions/{id}/cancel` | 세션 중단 |
| POST | `/api/admin/training/sessions/{id}/activate` | active_models.json 갱신 → 파이프라인 swap |

### 5.5 어드민 — 플랫폼 (API key / 비용 / 어뷰즈)

| 메소드 | 경로 | 용도 |
|---|---|---|
| POST | `/api/admin/login` | 어드민 토큰 검증 (HMAC compare_digest) |
| POST | `/api/admin/api-keys` | API key 발급 (`{label, monthly_quota, rpm_limit, monthly_usd_quota}` → plaintext 1회 노출) |
| GET | `/api/admin/api-keys` | 발급된 키 리스트 (해시만) |
| POST | `/api/admin/api-keys/{key_id}/revoke` | 키 비활성화 |
| GET | `/api/admin/observability` | 최근 요청 통계 (p50/p95, error_rate, by_path) |
| GET | `/api/admin/cost` | 외부 API 비용 집계 (by_provider / by_key / daily) |
| GET | `/api/admin/abuse-blocks` | 현재 차단된 user_id 목록 |
| POST | `/api/admin/abuse-blocks/{user_id}/unblock` | 수동 차단 해제 |
| GET | `/api/admin/scam-types` | 스캠 유형 카탈로그 (기본 12 + 런타임 추가) |
| POST | `/api/admin/scam-types` | 신규 스캠 유형 등록 |

### 5.6 Sandbox 서버 (`sandbox_server/app.py`) — 별도 VM

| 메소드 | 경로 | 용도 |
|---|---|---|
| GET | `/health` | mode (docker/subprocess), auth 활성화 여부, 이미지 |
| POST | `/detonate` | Bearer 토큰 검증 후 Playwright 컨테이너 실행 |

### 5.7 Next.js 프록시 (`apps/web/src/app/api/`)

모든 백엔드 어드민 / 분석 엔드포인트에 1:1 매핑되는 프록시. 인증·CORS 관리:
- `_lib/backend.ts` — `proxyJsonRequest` / `proxyGet` 헬퍼
- 각 route handler 는 5줄 이내 (단순 위임)
- `apps/web/src/proxy.ts` — 어드민 페이지 NextAuth 게이팅 미들웨어

---

## 6. 파이프라인 7-Phase 상세

`ScamGuardianPipeline.analyze(source, skip_verification, use_llm, use_rag, precomputed_transcript=None, user_context=None)`

```
Phase 0    Safety Filter           safety.py     ─ VirusTotal SHA256/URL lookup
Phase 0.5  Sandbox Detonation      sandbox.py    ─ 격리 Chromium navigate (URL 한정, opt-in)
Phase 1    STT / Vision            stt.py + vision.py
Phase 2    Classification          classifier.py
Phase 3    [Parallel × 3]          extractor + llm_assessor + rag (ThreadPoolExecutor)
Phase 4    Verification            verifier.py   ─ Serper × top-15 entities
Phase 5    Scoring                 scorer.py     ─ flag aggregation → ScamReport
```

### Phase 0 — Safety Filter (`pipeline/safety.py`)

- **목적**: VT 시그니처 lookup 으로 *알려진* 악성 즉시 탐지
- **입력**: URL 또는 로컬 파일 경로
- **로직**:
  - URL → `POST https://www.virustotal.com/api/v3/urls` (base64 url-safe 변환) → `GET .../analyses/{id}`
  - 파일 → SHA256 lookup → 미스면 업로드 + `analyses/{id}` 폴링 (최대 30s)
  - 4 req/min 토큰버킷 (`VIRUSTOTAL_RPM=4` free tier)
- **출력**: `SafetyResult { threat_level, detections, suspicious, total_engines, threat_categories, ... }`
- **fast-path**: 파일이 *malicious* 면 STT/분류 skip → 즉시 매우 위험 보고
- **비용 ledger**: `record_virustotal()` 호출

### Phase 0.5 — Sandbox Detonation (`pipeline/sandbox.py`, v3.5)

- **활성화**: `SANDBOX_ENABLED=1` + URL 입력일 때만
- **백엔드**: `local` (동일 호스트 Docker/subprocess) 또는 `remote` (별도 VM HTTPS 호출)
- **로직**: 격리 Playwright Chromium 으로 navigate → 행동 관찰
- **감지 항목**:
  - 비밀번호 입력 필드 (`<input type=password>`)
  - 민감 정보 필드 (주민번호·OTP·CVC·계좌·카드)
  - 자동 다운로드 시도 (drive-by)
  - 클로킹 (target ≠ final domain)
  - 과도한 리디렉션 (>3)
- **격리 정책** (운영):
  - 별도 VM/VPS — production 호스트와 다른 머신
  - Docker `--read-only --cap-drop=ALL --network=bridge --memory=512m`
  - 컨테이너 디스크 즉시 폐기
- **출력**: `SandboxResult { status, final_url, redirect_chain, has_password_field, sensitive_form_fields, download_attempts, screenshot_path, ... }`

### Phase 1 — STT / Vision

- `stt.transcribe(source)` 가 확장자 보고 자동 라우팅:
  - 텍스트 → 그대로 패스스루
  - YouTube URL → yt-dlp 로 오디오 추출 → Whisper API
  - 음성 파일 (mp3/wav/m4a/...) → Whisper API
  - **이미지/PDF → vision.transcribe()** — Claude vision (sonnet-4-6)
    - 이미지: long edge 1568px 다운스케일
    - PDF: pypdfium2 로 페이지별 PNG 렌더 (기본 5페이지, 150 DPI)
    - 시스템 프롬프트가 "OCR + 시각 단서 통합 본문" 한 번에 출력 강제
- **비용 ledger**: `record_openai_whisper(audio_seconds)` / Claude vision 은 `record_claude()`

### Phase 2 — Classification (`pipeline/classifier.py`)

- 기본: zero-shot NLI (mDeBERTa) + 키워드 부스팅
- `active_models.json` 에 fine-tuned 체크포인트 있으면 자동 swap → multi-class 분류
- 12종 기본 스캠 유형 + 런타임 확장 가능

### Phase 3 — Parallel Triple

`ThreadPoolExecutor` 로 동시 실행:

1. **`extractor.py` (GLiNER)** — 스캠 유형별 라벨셋으로 엔티티 추출. fine-tuned 가용 시 swap.
2. **`llm_assessor.analyze_unified()`** — Claude 1회 호출로 ① 스캠 유형 재판정 ② 엔티티 제안 ③ 플래그 제안 묶음. `user_context` (Q&A 페어) 가 있으면 prior 로 주입.
3. **`rag.retrieve_similar_runs()`** — SBERT 임베딩으로 과거 사람 라벨 사례 top-K 검색. `use_rag=True` 일 때만.

### Phase 4 — Verification (`pipeline/verifier.py`)

- Serper API 로 엔티티 교차검증 (사업자 등록 여부, FSS 등록 여부, 전화번호 신고 이력 등)
- **엔티티별 병렬 + 세마포어 레이트 리미팅** (`SERPER_MAX_CONCURRENT=3`, `SERPER_BATCH_DELAY=0.2`)
- 검증 대상 상위 15개 (라벨당 최대 2)
- `skip_verification=True` 면 phase 자체 skip

### Phase 5 — Scoring (`pipeline/scorer.py`)

플래그 합산 → 위험 점수 → 등급:

| 점수 구간 | 등급 |
|---|---|
| 0–20 | 안전 ✅ |
| 21–40 | 주의 🔶 |
| 41–70 | 위험 ⚠️ |
| 71–100 | 매우 위험 🚨 |

플래그 합산 규칙:
- Rule 플래그: `SCORING_RULES[flag]` 만큼 가산
- LLM 제안 플래그: `LLM_FLAG_SCORE_RATIO=0.5` 적용 (맹신 방지) — 단 `LLM_FLAG_SCORE_THRESHOLD` 이상의 confidence 필요
- Safety 플래그: `safety_result` → `malware_detected (80)` / `phishing_url_confirmed (75)` / `suspicious_*_signal (25)`
- Sandbox 플래그: `sandbox_result` → 5종 (아래 표 참고)
- 중복 플래그 1회만 가산

---

## 7. 플래그 시스템 (스코어링)

전체 플래그는 `pipeline/config.py:SCORING_RULES` (32종). 카테고리별:

### 7.1 일반 사기 신호 (검증 결과 기반 — Serper 등)

| 플래그 | 점수 | 출처 |
|---|---|---|
| `business_not_registered` | 20 | 국세청 사업자 |
| `phone_scam_reported` | 25 | 더치트 / 후후 |
| `ceo_name_mismatch` | 15 | DART / 사업자 |
| `fss_not_registered` | 15 | 금감원 |
| `fake_certification` | 20 | KOLAS 등 |
| `website_scam_reported` | 20 | 사이트 신고 DB |
| `abnormal_return_rate` | 15 | 자본시장법 (>20% 보장 = 위반) |
| `fake_government_agency` | 25 | 검찰청·경찰청·금감원 합동 가이드 |
| `personal_info_request` | 20 | 개인정보보호법 |
| `medical_claim_unverified` | 20 | 식약처 |
| `fake_exchange` | 20 | 금감원 가상자산사업자 등록 |
| `account_scam_reported` | 25 | 통합사기방지망 |
| `prepayment_requested` | 20 | 대부업법·취업사기 패턴 |
| `urgent_transfer_demand` | 20 | 보이스피싱 1순위 패턴 (경찰청 통계) |
| `threat_or_coercion` | 25 | 협박·강요 발화 |
| `impersonation_family` | 20 | 메신저 피싱 패턴 |
| `romance_foreign_identity` | 15 | Whitty (2018) 로맨스 스캠 |
| `job_deposit_requested` | 20 | 취업·알바 사기 패턴 |
| `smishing_link_detected` | 20 | KISA 스미싱 차단 |
| `fake_escrow_bypass` | 15 | 중고거래 패턴 |

### 7.2 Phase 0 Safety (VT 자동)

| 플래그 | 점수 | 트리거 |
|---|---|---|
| `malware_detected` | **80** | 파일 VT 다중 엔진 malicious |
| `phishing_url_confirmed` | **75** | URL VT 다중 엔진 malicious |
| `suspicious_file_signal` | 25 | 일부 엔진만 의심 |
| `suspicious_url_signal` | 25 | 일부 엔진만 의심 |

### 7.3 Phase 0.5 Sandbox (v3.5)

| 플래그 | 점수 | 트리거 |
|---|---|---|
| `sandbox_password_form_detected` | **50** | 격리 Chromium navigate 결과 `<input type=password>` 발견 |
| `sandbox_sensitive_form_detected` | 35 | 주민번호·OTP·CVC·계좌·카드 입력 필드 |
| `sandbox_auto_download_attempt` | **60** | 페이지 진입만으로 다운로드 트리거 (drive-by) |
| `sandbox_cloaking_detected` | 30 | target 도메인 ≠ 최종 도착지 |
| `sandbox_excessive_redirects` | 15 | 리디렉션 >3회 |

### 7.4 BERT 유사도 / 검색 패턴

| 플래그 | 점수 | 의미 |
|---|---|---|
| `authority_context_mismatch` | 15 | 화자 직업 vs 발화 의미 불일치 (SBERT 코사인) |
| `authority_context_uncertain` | 5 | 경계선 (보수적 가산) |
| `query_a_confirmed` | **−20** | 신뢰 언론 동시 히트 → 신뢰도 ↑ |
| `query_a_unconfirmed` | 20 | 신뢰 언론 확인 불가 |
| `query_b_factcheck_found` | 25 | 팩트체크 의심 단서 |
| `query_b_confirmed` | **−15** | 팩트체크 사실 확인 |
| `query_c_scam_pattern_found` | 15 | 동일/유사 사기 패턴 후기·뉴스 발견 |

각 플래그에 대해 `pipeline/config.py:FLAG_RATIONALE` 가 *왜 이 점수* + *학술/제도 출처* 매핑. 결과 페이지에 표시.

---

## 8. 데이터 모델

### 8.1 DB 스키마 (`db/sqlite_repository.py`, Postgres 동일 구조)

```sql
-- 분석 결과 (모든 run)
CREATE TABLE analysis_runs (
    id TEXT PRIMARY KEY,                  -- uuid
    created_at TEXT,
    input_source TEXT,                    -- URL 또는 텍스트 prefix
    transcript_text TEXT,
    scam_type_predicted TEXT,
    classification_confidence REAL,
    is_uncertain INTEGER,
    entities_predicted TEXT,              -- JSON
    triggered_flags_predicted TEXT,       -- JSON
    total_score_predicted INTEGER NOT NULL,
    risk_level_predicted TEXT NOT NULL,
    llm_assessment TEXT,                  -- JSON
    metadata TEXT,                        -- JSON: steps[], rag_context, user_context, chat_history, refined_llm_assessment, media{}
    claimed_by TEXT,                      -- 어드민 라벨링 클레임 (TTL 30분)
    claimed_at TEXT
);

-- 사람 라벨 정답 (라벨링)
CREATE TABLE human_annotations (
    run_id TEXT PRIMARY KEY,
    labeler TEXT,
    scam_type_truth TEXT,
    entities_truth TEXT,                  -- JSON
    triggered_flags_truth TEXT,           -- JSON
    is_scam INTEGER,
    notes TEXT,
    updated_at TEXT
);

-- 임베딩 (RAG 유사 사례 검색용)
CREATE TABLE transcript_embeddings (
    run_id TEXT PRIMARY KEY,
    embedding TEXT,                       -- SQLite: JSON / Postgres: vector(384)
    model TEXT
);

-- 스캠 유형 카탈로그 (런타임 확장)
CREATE TABLE scam_type_catalog (
    name TEXT PRIMARY KEY,
    description TEXT,
    examples TEXT,                        -- JSON
    created_at TEXT
);

-- API key (v3.x platform)
CREATE TABLE api_keys (
    id TEXT PRIMARY KEY,
    key_hash TEXT UNIQUE,                 -- sha256 of plaintext
    label TEXT,
    monthly_quota INTEGER,                -- 월별 호출 cap
    rpm_limit INTEGER,                    -- per-key 분당 cap
    monthly_usd_quota REAL,               -- 월별 USD cap
    status TEXT,                          -- active | revoked
    created_at TEXT, last_used_at TEXT,
    usage_total INTEGER, usage_month INTEGER, usage_month_at TEXT
);

-- 비용 ledger (v3.x platform)
CREATE TABLE cost_events (
    id INTEGER PRIMARY KEY,
    created_at TEXT,
    request_id TEXT,
    api_key_id TEXT,                      -- nullable (서버 자체 호출)
    provider TEXT,                        -- anthropic | openai | serper | virustotal
    action TEXT,                          -- claude_messages | transcribe | search | scan
    units REAL,                           -- 토큰·초·쿼리 등
    usd_amount REAL,
    metadata TEXT
);

-- 요청 로그 (observability)
CREATE TABLE request_log (
    id INTEGER PRIMARY KEY,
    created_at TEXT,
    request_id TEXT,
    api_key_id TEXT,
    method TEXT, path TEXT,
    status INTEGER,
    latency_ms INTEGER,
    error TEXT
);
```

### 8.2 카카오 잡 상태 (`api_server._pending_jobs[user_id]`, 인메모리)

```python
{
    "status": "running" | "done" | "error",
    "phase": "collecting_context" | "analyzing" | "result_requested" | "error",
    "result": ScamReport.to_dict() | None,
    "input_type": InputType,
    "source": "<url 또는 텍스트>",
    "chat_history": [ContextTurn(role, message), ...],
    "stt_done": bool, "stt_result": TranscriptResult | None,
    "context_done": bool,
    "user_context": dict | None,
    "analyzing_started": bool,
    "result_ready_announced": bool,        # 첫 알림(🎉 완료) 한 번 됐는지
    "done_notice_sent": bool,              # 채팅 중 "분석 끝남" 안내 한 번 부착됐는지
    "refine_started": bool, "refined": bool,
    "started_at": float, "finished_at": float | None,
    "error": Exception | None
}
```

`_jobs_lock` (threading.Lock) 으로 다중 사용자 동시 접속 race 방지.

### 8.3 결과 토큰 (`api_server._result_tokens[token]`, 인메모리, 1시간 TTL)

```python
{
    "result": ScamReport.to_dict(),
    "user_context": { qa_pairs: [...], summary_text: "...", turn_count: int },
    "input_type": "image" | "url" | ...,
    "expires_at": time.time() + 3600,
    "user_id": "<카카오 user.id 또는 null>",
    "chat_history": [ { role, message }, ... ]
}
```

토큰 발급 시 `repository.merge_run_metadata(run_id, {user_context, chat_history})` 로 DB 에도 보존 → 라벨링 풀 컨텍스트 제공.

---

## 9. Sandbox 격리 정책 (v3.5)

### 9.1 위협 모델

새로 도입된 위험 (Phase 0.5 추가 후):
- 우리 서버가 *사용자 제출 untrusted URL/APK 를 직접 처리*
- 같은 호스트에서 처리하면 **컨테이너 escape (Docker CVE) → 호스트 root → DB·API 키·사용자 데이터 노출**

### 9.2 격리 3 tier

| Tier | 격리 강도 | 우리 운영 |
|---|---|---|
| **1. 같은 호스트 + Docker** | ⚠️ 커널 공유 | 개발 전용 (`SANDBOX_BACKEND=local`) |
| **2. gVisor / Kata** | ✅ syscall 가로채기 | 검토만, 미적용 |
| **3. 물리 분리 (별도 VM/VPS)** | ✅✅ 커널·디스크·네트워크 완전 분리 | **운영 표준** (`SANDBOX_BACKEND=remote`) |

### 9.3 운영 토폴로지

```
production server (api.scamguardian)         sandbox VM (별도 머신)
────────────────────────────────────         ──────────────────────────
DB / API 키 / 사용자 데이터                  DB X / API 키 X / 데이터 X
pipeline/sandbox.py:_detonate_remote()  ──→  sandbox_server/app.py
                  HTTPS + Bearer 토큰        POST /detonate
                                             ↓
                                             docker run --rm playwright
                                             ↓
                                             결과 JSON + screenshot.b64
                                  ←──────    [컨테이너 즉시 파괴]
                                             [저장된 파일 즉시 삭제]
```

### 9.4 격리 강제 사항

- `--read-only` (root fs 변경 불가)
- `--tmpfs /tmp:rw,exec,size=256m` (실행 가능한 임시 영역만)
- `--memory=512m --cpus=1` (자원 제한)
- `--cap-drop=ALL` (Linux capability 전부 제거)
- `--network=bridge` (외부 인터넷 OK, 호스트 내부망 X)
- `--rm` (종료 시 컨테이너 자동 삭제)
- `pwuser` 비특권 user 로 실행 (Playwright 이미지 기본)
- 결과 디렉토리는 디토네이션 직후 `shutil.rmtree`

### 9.5 추가 권장 (운영)

- sandbox VM 의 outbound: production 내부망 IP 차단 (방화벽 outbound rule)
- sandbox VM 정기 재부팅 (커널 상태 reset)
- IP rotation: sandbox 가 자주 사기범 차단 당함 → IP 풀 또는 residential proxy 검토
- Headless Chromium 디텍션 회피: `--disable-blink-features=AutomationControlled` 적용 중

---

## 10. Platform 레이어

### 10.1 모듈 구조 (`platform_layer/`)

| 파일 | 역할 |
|---|---|
| `api_keys.py` | `sg_<urlsafe>` 발급, sha256 해시 저장, lookup/list/revoke |
| `pricing.py` | Claude/Whisper/Serper/VirusTotal 가격표 — `claude_cost(model, in, out)` 등 |
| `cost.py` | contextvars `_REQUEST_ID` / `_API_KEY_ID` + `record_*` 함수들 |
| `rate_limit.py` | per-key RPM 슬라이딩 윈도우 + 월별 호출 quota + 월별 USD cap |
| `abuse_guard.py` | 길이/반복/gibberish/dup + 위반 누적 자동 블록 + 짧은 메시지 트래커 |
| `middleware.py` | FastAPI `PlatformMiddleware` — request_id 주입, key 검증, rate limit, request_log |
| `retention.py` | 업로드 파일 자동 retention (mtime > N 일 → 삭제) |

### 10.2 인증 / Rate limit 흐름

```
요청 → PlatformMiddleware
      ├── 1. request_id 생성 (uuid4)
      ├── 2. /webhook/kakao 면 key 검증 skip (카카오 자체 인증)
      ├── 3. /api/admin/* 면 어드민 토큰 (헤더 또는 쿠키)
      ├── 4. 그 외 분석 엔드포인트:
      │     ├── Authorization: Bearer sg_... 또는 X-API-Key
      │     ├── DB lookup (status=active)
      │     ├── rate_limit.check_and_record(key_id):
      │     │     ├── per-key RPM 슬라이딩 윈도우
      │     │     ├── 월별 호출 cap
      │     │     └── 월별 USD cap
      │     └── 어떤 cap 이든 초과 → 429 (RPM) 또는 423 (USD/quota)
      └── 5. 응답 후 request_log 에 latency·status·error 기록
```

### 10.3 비용 ledger 흐름

각 외부 API 호출 직후:
```python
from platform_layer.cost import record_claude, record_openai_whisper, record_serper, record_virustotal
record_claude(model="claude-sonnet-4-6", input_tokens=1000, output_tokens=500)
record_openai_whisper(audio_seconds=30.5)
record_serper(queries=3)
record_virustotal(requests=1)
```

→ `cost_events` 에 row 추가 → `aggregate_costs(days=30)` 가 by_provider / by_key / daily 집계.

### 10.4 어뷰즈 가드 동작

카카오 webhook 진입 시 두 단계:
1. `block_status(user_id)` — 차단 상태면 `format_abuse_blocked` + 잡 강제 종료
2. `track_short_message(user_id, text)` — `< 10자` 시 `record_violation`:
   - count==1: 통과 (1번째 free pass)
   - count==2~3: 응답에 ⚠️ 경고 prepend
   - count==4: blocked=True → 차단 카드 + 1시간 block
3. count >= 2 면 `classify_intent` (Claude Haiku) **호출 자체 skip** — 어뷰저 LLM 통로 차단

**시스템 명령어 화이트리스트** (`api_server._is_system_command`): 결과확인 / 사용법 / 초기화 / 스킵 동의어는 트래커 우회.

---

## 11. 환경 변수 전체 목록

### 11.1 필수

| 이름 | 용도 |
|---|---|
| `ANTHROPIC_API_KEY` | Claude (분석 + 라벨링 + 컨텍스트 챗봇) |
| `OPENAI_API_KEY` | Whisper API |
| `SERPER_API_KEY` | Phase 4 교차검증 |
| `VIRUSTOTAL_API_KEY` | Phase 0 안전성 |

### 11.2 모델·동작

| 이름 | 기본값 |
|---|---|
| `ANTHROPIC_MODEL` | `claude-sonnet-4-6` |
| `ANTHROPIC_HAIKU_MODEL` | `claude-haiku-4-5-20251001` |
| `ANTHROPIC_VISION_MODEL` | `claude-sonnet-4-6` |
| `VISION_PDF_MAX_PAGES` | `5` |
| `VISION_PDF_DPI` | `150` |
| `SERPER_MAX_CONCURRENT` | `3` |
| `SERPER_BATCH_DELAY` | `0.2` |
| `VIRUSTOTAL_RPM` | `4` |

### 11.3 인프라

| 이름 | 기본값 |
|---|---|
| `SCAMGUARDIAN_API_URL` | `http://127.0.0.1:8000` (Next.js 프록시 대상) |
| `SCAMGUARDIAN_DATABASE_URL` | (없음) — 없으면 SQLite |
| `SCAMGUARDIAN_SQLITE_PATH` | `.scamguardian/scamguardian.sqlite3` |
| `SCAMGUARDIAN_PERSIST_RUNS` | `false` |
| `SCAMGUARDIAN_PUBLIC_URL` | (없음) — 결과 페이지 베이스 (없으면 ngrok 자동 발견) |
| `SCAMGUARDIAN_CORS_ORIGINS` | `http://localhost:3000,...` |
| `SCAMGUARDIAN_ADMIN_TOKEN` | (없음) — 설정 시 어드민 토큰 인증 활성화 |

### 11.4 어뷰즈 가드

| 이름 | 기본값 | 의미 |
|---|---|---|
| `ABUSE_SOFT_THRESHOLD` | `10` | "짧은 메시지" 자수 임계 |
| `ABUSE_WARN_LIMIT` | `3` | 경고 횟수 |
| `ABUSE_BLOCK_DURATION` | `3600` | 자동 블록 지속 (초) |
| `ABUSE_VIOLATION_WINDOW` | `3600` | 위반 누적 윈도우 (초) |
| `ANALYZE_MAX_TEXT_LENGTH` | `5000` | 텍스트 최대 글자 |

### 11.5 v3.5 Sandbox

| 이름 | 기본값 |
|---|---|
| `SANDBOX_ENABLED` | `0` |
| `SANDBOX_BACKEND` | `auto` (REMOTE 둘 다 있으면 remote, 아니면 local) |
| `SANDBOX_REMOTE_URL` | (없음) |
| `SANDBOX_REMOTE_TOKEN` | (없음) |
| `SANDBOX_USE_DOCKER` | `0` (local 모드 — Docker 사용 여부) |
| `SANDBOX_DOCKER_IMAGE` | `scamguardian/sandbox:latest` |
| `SANDBOX_TIMEOUT` | `30` |
| `SANDBOX_OUTPUT_DIR` | `.scamguardian/sandbox` |
| `SANDBOX_REMOTE_TIMEOUT` | `60` |

### 11.6 Sandbox 서버 측 (`sandbox_server/app.py` 가 사용)

| 이름 | 기본값 |
|---|---|
| `SANDBOX_TOKEN` | (필수, production 의 `SANDBOX_REMOTE_TOKEN` 과 같은 값) |
| `SANDBOX_INCLUDE_SCREENSHOT` | `1` (base64 inline 반환) |
| `PORT` | `8001` |

### 11.7 학습

| 이름 | 의미 |
|---|---|
| `AIHUB_API_KEY` | AI Hub CLI (`scripts/aihub.py`) |

---

## 12. 배포 토폴로지

### 12.1 개발 (로컬)

```
WSL2 / Mac:
  uvicorn api_server:app    :8000
  next dev                  :3100
  ngrok 또는 Tailscale Funnel
  SQLite (.scamguardian/scamguardian.sqlite3)
  (선택) SANDBOX_BACKEND=local + Docker
```

### 12.2 스테이징 (Multipass VM)

```
Win11 Pro 호스트:
  ├── WSL2 production (api + Next.js)
  └── Multipass Ubuntu VM "sandbox" (Hyper-V):
       ├── Docker
       ├── sandbox_server/app.py :8001
       └── scamguardian/sandbox:latest 이미지
```

### 12.3 운영

```
Vercel:
  └── apps/web/ (Next.js)

Render / 클라우드 VPS:
  └── api_server.py + Postgres (pgvector)

별도 클라우드 VPS ($5/월):
  └── sandbox_server/app.py
        firewall: production IP 만 inbound 허용
        outbound: 인터넷 전부 (디토네이션 대상)
        TLS: Caddy/Traefik + Let's Encrypt
```

### 12.4 카카오 오픈빌더 설정

- 스킬 블록 → "콜백 사용" 체크 (영상 분석 안정성)
- 콜백은 카카오 관리자센터 → 챗봇 → 설정 별도 신청·승인
- 파일 타입 파라미터 추가: `image`, `secureimage` (이미지·문서 첨부 가능 타입)
- 스킬 서버 주소: Tailscale Funnel (`https://scamguardian.tail7e5dfc.ts.net/webhook/kakao`) 또는 ngrok
- **알려진 한계**: PDF·일반 파일·APK 첨부는 카카오 챗봇 클라이언트가 차단. 이미지·URL 텍스트만 도달

---

## 13. 보안·위협 모델

### 13.1 신뢰 경계

```
✅ 신뢰: production 서버 (DB·API 키·사용자 데이터)
❌ 비신뢰: 사용자 제출 컨텐츠 (URL·텍스트·파일·이미지)
⚠️ 부분 신뢰: 카카오 webhook (출처는 검증되나 콘텐츠는 untrusted)
```

### 13.2 보안 layer

1. **API key 인증** + 3중 cap (RPM / 월별 호출 / 월별 USD)
2. **어뷰즈 가드** — 길이·반복·gibberish 필터 + per-user 위반 누적
3. **외부 콘텐츠 격리**:
   - 이미지·PDF: vision API 호출 (Anthropic 측에서 처리, 우리 호스트 영향 없음)
   - URL·실행파일: Phase 0 (VT) + Phase 0.5 (격리 sandbox VM) — 우리 호스트에서 *직접 navigate 안 함*
4. **사용자 PII 최소화** — DB 에 사용자 ID 만 저장, 전화번호·실명 X
5. **결과 토큰** — 1시간 TTL urlsafe 16바이트, 만료 시 410
6. **어드민 인증** (진행 중) — NextAuth + Google OAuth + email allowlist

### 13.3 알려진 위협 + 대응

| 위협 | 대응 |
|---|---|
| 사용자가 악성 URL 제출 | sandbox VM 분리 (production 호스트와 다른 머신) |
| 사용자가 거대 파일 업로드 | `ANALYZE_MAX_TEXT_LENGTH` + `VT_UPLOAD_MAX_BYTES` (32MB) |
| 어뷰저 LLM 무료 통로 | 짧은 메시지 누적 트래커 → Haiku 호출 자체 차단 |
| API key 유출 | revoke 즉시 → DB status='revoked', 다음 요청부터 401 |
| 어드민 URL 직접 접근 | NextAuth 게이팅 (진행 중) — 현재는 obscurity 의존 |
| 카카오 webhook spoofing | 카카오 자체 시그니처 (TODO: 우리도 검증 추가) |
| 사용자 데이터 영구 보존 | retention.py 자동 삭제 (기본 30일) |

### 13.4 미해결 / WIP

- `/api/admin/*` 게이팅 — NextAuth 통합 진행 중, 일부 라우트는 어드민 토큰만 검증
- 카카오 webhook 시그니처 검증 미구현
- API key rotation 정책 부재
- 사용자 별 분석 ledger 부재 (X-User-Id 만 어뷰즈 누적용)

---

## 14. 학술 인용·참고문헌

### 14.1 사기 심리학 / 행동경제학

- **Stajano, F. & Wilson, P. (2011)**. *Understanding scam victims: Seven principles for systems security*. CACM. → 스캠 7원칙 (Distraction, Social Compliance, Herd, Dishonesty, Kindness, Need & Greed, Time)
- **Cialdini, R. (2021)**. *Influence: The Psychology of Persuasion (New and Expanded)*. → 6 원칙 (상호성·일관성·사회적 증거·호감·권위·희소성)
- **Whitty, M. T. (2018)**. *The scammers persuasive techniques model*. British Journal of Criminology. → 로맨스 스캠 페르소나 분석
- **Norris, G., Brookes, A., Dowell, D. (2019)**. *The psychology of internet fraud victimisation*. Journal of Financial Crime. → 보이스피싱 피해자 인지 심리

### 14.2 텍스트·시맨틱 분석

- **Reimers, N. & Gurevych, I. (2019)**. *Sentence-BERT*. EMNLP. → SBERT 의미 유사도
- **Cer, D. et al. (2017)**. *STS Benchmark*.
- **Graves, L. (2016)**. *Deciding What's True: The Rise of Political Fact-Checking*. Columbia UP.

### 14.3 위협 인텔리전스

- **APWG**. *Phishing Activity Trends Report* (분기별)
- **Google Safe Browsing Transparency Report**.
- **NIST SP 800-83**. *Guide to Malware Incident Prevention*.
- **Mavroeidis, V. & Bromander, S. (2017)**. *Cyber Threat Intelligence Model*.

### 14.4 한국 제도·통계

- 금융감독원 *유사수신 감독사례집*
- 경찰청 *사이버범죄 통계*
- KISA *스미싱 차단 시스템 / 방송통신위 스미싱 통계*
- 검찰청·경찰청·금감원 *합동 보이스피싱 가이드*
- *자본시장법* (제49조 — 부당권유 금지, 20% 이상 수익보장 신호)

### 14.5 인터럽트·자기인지 메커니즘 (v4 / 본 framing 의 학술 근거)

- **Bandler, R. & Grinder, J. (1975)**. *Pattern interrupt* (NLP).
- **Flavell, J. (1979)**. *Metacognition and cognitive monitoring*. American Psychologist.
- **Cialdini (2021)** — 사기범의 영향력 원칙이 *피해자 발화* 에서 어떻게 역으로 드러나는지 (본 시스템의 새 응용)

### 14.6 OWASP / 보안 표준

- **OWASP Top 10 (A07: Identification & Authentication Failures)** — 비밀번호 폼 노출 위험
- **PCI DSS 4.0** — 카드정보 입력 필드 정의
- **개인정보보호법 시행령 별표1** — 한국 민감정보 정의

---

## 부록 A. 디렉토리 구조

```
scamguardian-v2/
├── api_server.py                      # FastAPI — 모든 비즈니스 로직
├── run_analysis.py                    # CLI 분석
├── pipeline/                          # 7-Phase 파이프라인
│   ├── runner.py                      # 오케스트레이터
│   ├── safety.py                      # Phase 0 — VT
│   ├── sandbox.py                     # Phase 0.5 — local/remote 분기
│   ├── sandbox_detonate.py            # 컨테이너 안 Playwright 스크립트
│   ├── sandbox.Dockerfile
│   ├── stt.py / vision.py             # Phase 1
│   ├── classifier.py                  # Phase 2
│   ├── extractor.py / llm_assessor.py / rag.py    # Phase 3
│   ├── verifier.py                    # Phase 4
│   ├── scorer.py                      # Phase 5
│   ├── config.py                      # 스캠 유형·플래그·점수·rationale
│   ├── kakao_formatter.py             # 카카오 응답 포맷터
│   ├── context_chat.py                # 멀티턴 컨텍스트 수집 + 의도 분류
│   ├── claude_labeler.py              # 라벨 초안 생성
│   ├── eval.py                        # 평가 지표
│   └── active_models.py               # fine-tuned 모델 swap
├── platform_layer/                    # 인증·rate limit·비용·observability
│   ├── api_keys.py / pricing.py / cost.py
│   ├── rate_limit.py / abuse_guard.py
│   ├── middleware.py / retention.py
├── db/                                # repository facade
│   ├── repository.py                  # SQLite/Postgres 라우팅
│   └── sqlite_repository.py
├── apps/web/                          # Next.js 16 (App Router)
│   └── src/app/
│       ├── api/                       # 백엔드 프록시 라우트
│       ├── admin/                     # 어드민 UI (라벨링 / 학습 / 플랫폼 / 통계)
│       └── result/[token]/            # 결과 공개 페이지
├── sandbox_server/                    # v3.5 — 격리 VM 안 디토네이션 서버
│   ├── app.py                         # FastAPI listener
│   └── README.md                      # Multipass / VPS 배포 가이드
├── training/                          # Fine-tuning (분류기 + GLiNER)
├── experiments/                       # v4 검증 실험
│   ├── v4_intent/                     # Haiku 의도 분류 평가
│   └── v4_whisper/                    # 5초 chunk Whisper STT
├── tests/                             # pytest (93 passed)
├── scripts/                           # 운영·인제스트
└── .scamguardian/                     # 런타임 데이터
    ├── scamguardian.sqlite3           # SQLite (gitignored)
    ├── uploads/                       # 사용자 업로드 (retention 자동 삭제)
    ├── sandbox/                       # sandbox 결과 (즉시 삭제)
    ├── training_sessions/             # 학습 세션 메타
    ├── active_models.json             # fine-tuned 활성 경로
    ├── logs/                          # 운영 로그
    └── README.md                      # 본 문서
```

## 부록 B. 운영 체크리스트

배포 직전 확인:
- [ ] `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` / `SERPER_API_KEY` / `VIRUSTOTAL_API_KEY` 4개 다 세팅
- [ ] `SCAMGUARDIAN_PERSIST_RUNS=true` 분석 결과 DB 저장
- [ ] `SCAMGUARDIAN_PUBLIC_URL` 결과 페이지 베이스 (없으면 ngrok 자동)
- [ ] `SCAMGUARDIAN_DATABASE_URL` Postgres 연결 (운영) / 미설정 시 SQLite (개발)
- [ ] `SANDBOX_BACKEND=remote` + `SANDBOX_REMOTE_URL` + `SANDBOX_REMOTE_TOKEN` (sandbox VM 가동 시)
- [ ] `SANDBOX_ENABLED=1`
- [ ] retention 정책 cron 설정 (`scripts/cleanup_uploads.py`)
- [ ] 어드민 토큰 또는 NextAuth 셋업
- [ ] 카카오 오픈빌더 webhook URL 등록 + 콜백 신청 승인 받음
- [ ] sandbox VM firewall: production IP 만 inbound 허용
- [ ] HTTPS / TLS 인증서 (Tailscale Funnel 또는 Caddy + Let's Encrypt)
- [ ] Postgres pgvector extension 설치 (운영)
- [ ] 비용 cap (월별 USD) per-key 설정
- [ ] `pytest` 통과 확인 (93 passed)
