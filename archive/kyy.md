# kyy 브랜치 작업 정리 (2026-05-24)

## 목적

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
