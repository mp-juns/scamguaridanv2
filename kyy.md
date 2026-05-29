# kyy 브랜치 작업 정리

`main` 브랜치 대비 누적 작업 로그. 최신 작업이 아래에 추가됨.

---

## 2026-05-24 — 영상 분석 latency 단축

### 목적

영상 분석 latency 단축 — baseline ~14.5s → 1분 영상 10s 이내 일관 달성

## 완료한 작업

### 1. STT 병렬 chunking — `pipeline/stt.py`

- 오디오 길이 45s 초과 시 ffmpeg segment 로 chunk 분할 후 ThreadPoolExecutor(4) 로 Whisper API 병렬 호출
- env 튜닝: `STT_CHUNK_SEC=45`, `STT_MAX_WORKERS=4`, `STT_CHUNK_THRESHOLD_SEC=45`
- chunk 1개 실패해도 나머지 결과 보존
- 비용 ledger 는 chunk 마다 `record_openai_whisper(duration)` 호출 (정확도 유지)
- 짧은 오디오 (<45s) 는 기존 1-shot 그대로 — 오버헤드 절약

### 2. 게이트 최적화 — `pipeline/gate.py`

- 시스템 프롬프트 트림 (~950자 → ~600자)
- 뉴스 narration heuristic fast-path 추가 (`_news_edu_fast_path`)
  - `_NEWS_MARKERS` 2개 이상 (라고 밝혔다 / 검찰에 따르면 / 피해 사례 등) + `_DIRECT_DEMAND` 0개 → `scam_news_edu` 즉시 (LLM 호출 skip)
- `max_tokens 60` 회귀 잡음 후 120 복구 + "reason ≤20자" hint 추가
- 사용자 본 영상 narrative 예시 ("서울 한 남성이 현금 5,400만원...") 프롬프트 추가

### 3. Phase 1.5+2+3 통합 병렬화 — `pipeline/runner.py`

- **이전 sequential**: `STT → Gate(1s) → Phase 2(1s) → Phase 3(1-5s) parallel`
- **신규 통합 병렬**: `STT → [Gate || Classify || Extract(union) || RAG] all parallel → LLM (conditional)`
- Gate=normal 이면 Extract 결과 무시 (B 최적화 — 사기 무관 콘텐츠는 entity 추출 의미 X)
- `executor.shutdown(wait=False)` — 게이트가 skip 결정한 future 는 background 에서 자연 종료
- LLM 만 sequential ($ cost 낭비 회피)

## 테스트

- `tests/test_stt_chunked.py` — 신규 6 케이스 (ffmpeg 분할 / 정렬 / threshold 우회 / 병렬 dispatch / chunk 실패 복구 / 파일 누락)
- `tests/test_gate.py` — 신규 6 케이스 (heuristic fast-path: 강한 마커 트리거 / 명령 차단 / 마커 부족 fallthrough / 헬퍼 직접 호출 3개)
- 전체 322/322 통과

## 성과 (실측)

| 단계 | 평균 latency | 10s 이내 비율 |
|---|---|---|
| baseline (오늘 새벽) | ~14.5s | 0% |
| STT 병렬 chunking 후 | ~12s | ~10% |
| 게이트 최적화 후 | ~11s | ~30% |
| **통합 병렬 + B 최적화 후** | **~9.2s** | **78% (7/9)** |

- **최단 기록**: 7834ms (15:24:57)
- 1분 영상 평균 9-10s 안정 구간 진입

## 회귀 발견 + 수정 (중요 lesson)

**증상**: 게이트 최적화 직후 33-40s 분석 폭증 (14:34, 14:40)

**진단**: DB metadata 확인 → `gate.source = "fallback"`, `gate.reason = "bucket 무효('') — fallback"`
- `max_tokens=60` 으로 단축 → Haiku 출력 JSON 중간에 잘림 → 파서 실패 → fallback bucket = `undetermined`
- undetermined 라우팅 정책 = 보수 (모든 단계 실행) → Phase 2 + Phase 3 LLM 모두 돔 → 20+초 추가

**수정**: `max_tokens 120` 복구 + 사용자 본 영상 예시 프롬프트 추가 + reason 20자 hint

**lessons.md 패턴 5 등록**: "LLM max_tokens 단축은 라우팅 결정에 대규모 회귀 — 출력 캡은 예상 길이의 2-3배 안전 마진. fallback bucket 의 라우팅 비용도 함께 고려."

## 변경 파일

| 파일 | 변경 |
|---|---|
| `pipeline/stt.py` | 병렬 chunking 함수 + env 파라미터 |
| `pipeline/gate.py` | 프롬프트 트림 + heuristic fast-path + max_tokens 조정 |
| `pipeline/runner.py` | Phase 1.5+2+3 통합 병렬 블록 |
| `tests/test_stt_chunked.py` | 신규 (6 케이스) |
| `tests/test_gate.py` | 확장 (6 케이스 추가) |
| `tasks/todo.md` | 작업 기록 + 회고 |
| `tasks/lessons.md` | 패턴 5 추가 |

## 내일 결정할 것

### 결과 페이지 콘텐츠 분류 배지 통일 여부

- `apps/web/src/app/result/[token]/page.tsx` 의 `contentTypeBadge()` 확장 검토
- 사용자 의견: `normal` + `scam_news_edu` 두 배지 모두 `✅정상 콘텐츠` 로 통일
- 분석가 권장: **게이트 프롬프트 수정 먼저** → 결과 보고 통일 재검토

### 게이트 오분류 root cause

- 발견: 강도 사건 뉴스 (사기 무관) 가 `scam_news_edu` 로 잘못 분류됨
- 원인: 게이트 시스템 프롬프트가 *사기 vs 일반 범죄* 구분 미흡
- 수정 방향: example 추가 ("편의점 강도" → normal), 명시적 룰 ("일반 범죄·사고는 normal, 사기만 scam_news_edu")
- 회귀 가드: `tests/test_gate.py` 에 강도뉴스 / 보이스피싱뉴스 둘 다 명시 케이스 추가

## 다음 우선순위 후보

1. **게이트 프롬프트 수정** (root cause fix) — 위 내일 결정
2. STT cache (사용자 테스트 workflow 효율, production 영향 X)
3. Speculative gate (production 1분 영상 10s 일관 달성, risk 중)
4. Admin 인증 + RBAC (production 보안 갭)
5. API 통합 테스트 (회귀 가드 강화)
6. v4 Live Call Guard MVP (학술 차별화)

---

## 2026-05-29 — 통화 STT 정확도 강화 + 화자 분리 + 스트리밍 + Live Voice

### 목적

보이스피싱 통화 녹음 분석의 두 약점을 정면 돌파:
1. **Whisper hallucination** — 침묵·노이즈 구간에서 "시청해주셔서 감사합니다" 같은
   학습 데이터 phrase 환각 + 도메인 어휘 prompt 가 무한 반복 출력 유발
2. **화자 미분리** — Whisper 가 상대방(사기범) / 본인(피해자) 발화를 안 나눠줘서
   *피해자 측 compliance signal* 분석 불가

그리고 v4 Live Call Guard 의 사전 단계 — chunk 단위 streaming 분석 + Live Voice UI.

### 완료한 작업

#### 1. Whisper hallucination 강화 — `pipeline/stt.py`

- **도메인 어휘 prompt 제거**: 어휘 list 를 Whisper prompt 에 박으면 침묵 구간에서
  그 어휘를 그대로 transcript 로 토해냄 (12개 어휘로도 무한 반복 관찰). prompt 는
  짧은 컨텍스트 문장만 (`STT_DOMAIN_PROMPT`, 기본 "한국어 전화 통화 녹음입니다.").
- **`_strip_hallucination_phrases()`**: 알려진 YouTube/방송 phrase ("시청해주셔서
  감사합니다", "구독과 좋아요", "[음악]", "MBC 뉴스" 등) 정확 일치 제거.
- **`_squash_repetition()`**: 8-gram→1-gram 순으로 N회 연속 반복 phrase 를 1회로 축약
  (loop 환각 제거).
- **`temperature=0.0`** deterministic 디코딩.
- **chunk 재인코딩**: `-c copy` (mp3 가정) → `libmp3lame mono 16k 64kbps` 재인코딩 —
  wav/m4a 등 어떤 코덱 입력도 chunk 분할 성공 (이전 exit 234 mux 실패 수정).
- **VAD 전처리** (`api_server_pkg/analyze.py`): upload 시 ffmpeg
  `silenceremove + dynaudnorm` 으로 침묵 제거 + 음량 정규화 — hallucination 원천 차단.

#### 2. CLOVA Speech STT 백엔드 — `pipeline/stt.py` (`_transcribe_with_clova`)

- Naver CLOVA Speech API — 한 번의 호출로 전사 + **audio-based 화자 분리** (`segments`
  의 `speaker_label`) 동시 획득 → LLM diarize 불필요.
- `_clova_to_turns()`: 발화 시간 총합 휴리스틱 (긴 화자=상대방/사기범, 짧은 화자=본인)
  으로 `상대방`/`본인` turn 리스트 생성 + 각 turn 의 `start_sec/end_sec` (오디오 재생용).
- **`boostings` 파라미터**: 도메인 어휘 인식 가중치 (Whisper prompt 와 달리 새 텍스트
  생성 X, 단어 출력 bias 만 — hallucination 부작용 없음). 검찰·금감원·대포통장·OTP 등.
- `STT_BACKEND=clova` 선택 시 활성. 전용 진단 로그 `.scamguardian/logs/clova-kyy.log`.
- 비용 ledger: `platform_layer.cost.record_clova_speech()` + `pricing.clova_speech_cost()`
  (≈ $0.003/분, `CLOVA_SPEECH_PER_MIN_USD` override).

#### 3. 텍스트 기반 화자 분리 — `pipeline/diarize.py` (신규)

- CLOVA 가 아닌 백엔드(Whisper)용 fallback — 전사문을 Claude Haiku 로 `상대방`/`본인`
  분리. pyannote 대비 가볍고 (1-2s) 보이스피싱 대화 패턴에 충분.
- **환각 차단 규칙**: "split (나누기) 만, write (쓰기) 금지" — 출력 단어 중 본문에
  없는 비율 15% 초과 시 자동 reject.

#### 4. STT-only 엔드포인트 — `api_server_pkg/transcribe.py` (신규)

- `POST /api/transcribe-upload` — 분석·DB 저장 없이 Phase 1 (STT) 만 수행 후 즉시 반환.
- Live Voice 페이지에서 분석과 *병렬* 호출해 전사 결과를 먼저 보여주는 용도.

#### 5. Chunk 단위 스트리밍 분석 — `api_server_pkg/stream_analyze.py` (신규)

- `POST /api/analyze-stream` — 긴 음성을 `chunk_seconds`(기본 60s) 단위로 잘라 각 chunk
  의 STT + 키워드 alert 를 **NDJSON** 으로 즉시 흘려줌 (`start`/`chunk`/`done`/`error`).
- 클라이언트는 `fetch` 의 ReadableStream 을 line-by-line 파싱 → chunk 별 실시간 표시.
- v4 Live Call Guard (5초 chunk 실시간 검출) 의 사전 녹음 simulation.

#### 6. Live Voice 페이지 — `apps/web/src/app/live/` (신규)

- `/live` — "사기 후가 아닌 사기 중 차단" 컨셉의 통화 분석 UI (`LiveVoiceUpload.tsx`).
- 검출 신호 카탈로그 노출: 메타인식 표현 / 민감정보 누설 / 송금 동의 / 권위 굴복 누적.
- 홈 페이지(`page.tsx`)에 `🎙️ LIVE VOICE` 진입 링크 추가.
- Next.js 프록시 라우트 2개 신규: `api/transcribe-upload`, `api/analyze-stream`.

### 환경 변수 (신규)

| 변수 | 설명 | 기본값 |
|---|---|---|
| `STT_BACKEND` | `whisper` / `claude` / `clova` | `whisper` |
| `STT_DOMAIN_PROMPT` | Whisper prompt 컨텍스트 (빈 문자열=안 보냄) | `한국어 전화 통화 녹음입니다.` |
| `CLOVA_INVOKE_URL` | CLOVA Speech 도메인 invoke URL | (clova 시 필수) |
| `CLOVA_SECRET_KEY` | CLOVA Speech secret key | (clova 시 필수) |
| `CLOVA_BOOSTING_WORDS` | 도메인 어휘 boosting (콤마 구분) | 검찰·금감원·대포통장 등 기본 list |
| `CLOVA_SPEECH_PER_MIN_USD` | CLOVA 분당 단가 (비용 ledger) | `0.003` |

### 변경 파일

| 파일 | 변경 |
|---|---|
| `pipeline/stt.py` | hallucination strip/squash + CLOVA 백엔드 + turns + chunk 재인코딩 |
| `pipeline/diarize.py` | 신규 — 텍스트 기반 Claude Haiku 화자 분리 |
| `api_server_pkg/transcribe.py` | 신규 — `/api/transcribe-upload` (STT only) |
| `api_server_pkg/stream_analyze.py` | 신규 — `/api/analyze-stream` (NDJSON 스트리밍) |
| `api_server_pkg/analyze.py` | upload 시 VAD (silenceremove + dynaudnorm) 전처리 |
| `api_server_pkg/app.py` | transcribe / stream_analyze 라우터 등록 |
| `apps/web/src/app/live/` | 신규 — Live Voice 페이지 + 업로드 컴포넌트 |
| `apps/web/src/app/api/transcribe-upload/`, `.../analyze-stream/` | 신규 프록시 라우트 |
| `apps/web/src/app/page.tsx` | 홈에 LIVE VOICE 링크 |
| `platform_layer/cost.py`, `pricing.py` | CLOVA Speech 비용 ledger |

### 다음 우선순위 (갱신)

1. **CLOVA 화자 분리 정확도 측정** — 합성/실제 통화로 상대방·본인 매핑 정밀도 검증
2. `.env.example` 에 STT_BACKEND / CLOVA_* 변수 추가 (현재 코드만 있음)
3. v4 Live Call Guard 실시간 (5초 chunk WebSocket) — streaming 엔드포인트 위에 구축
4. Admin 인증 + RBAC (production 보안 갭)
