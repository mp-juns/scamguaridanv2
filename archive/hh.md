# hh — 3단계 캐스케이드 분류 재설계 (2026-05-19)

ScamGuardian 의 사기유형 분류를 단일 강제 분류에서 **1단계(게이트) → 2단계(유형) → 3단계(신호)**
캐스케이드로 재설계하는 작업 기록 문서입니다. 설계 배경·정밀조사 결과·확정 사항·구현 계획을
한 곳에 모읍니다.

---

## 1. 배경 — 왜 바꾸나

현재 분류기([pipeline/classifier.py](pipeline/classifier.py))는 모든 입력을 `DEFAULT_SCAM_TYPES`
12개 중 **하나로 강제** 분류합니다. 두 가지 결함이 있습니다.

1. **정상·뉴스/교육 콘텐츠도 12개 중 하나로 강제** — 보이스피싱 예방 뉴스 기사, 교육 게시물은
   사기 키워드를 전부 갖고 있어 강하게 오탐합니다. "12개 중 아무것도 아님" 상태가 없습니다.
2. **복합 스캠을 단일 유형으로 강제** — "코인 + 로맨스 + 기관 사칭"이 한 콘텐츠에 섞여 있어도
   `multi_label=False` 라 하나만 고릅니다 → 나머지 유형의 엔티티를 통째로 놓칩니다.

---

## 2. 정밀조사 결과

코드를 직접 검증한 결과입니다.

| 항목 | 사실 |
|---|---|
| 12개 강제 | [config.py:14-27](pipeline/config.py#L14-L27) — `DEFAULT_SCAM_TYPES` 12종 ✓ |
| single-label | [classifier.py:153](pipeline/classifier.py#L153) `multi_label=False` ✓ |
| `confidence` 의미 | 확률 아님 — `(NLI 점수 + 키워드 부스트)` min-shift 정규화값. "12개 중 X의 점수 지분" |
| 정상 클래스 | zero-shot 경로엔 **없음**. 단 학습 경로엔 `NEGATIVE_LABEL = "정상 대화"` 존재 ([training/data.py:24](training/data.py#L24)) → 두 경로 라벨 공간 불일치 |
| 일반 URL 분류 입력 | [stt.py:262](pipeline/stt.py#L262) — YouTube·파일이 아니면 URL 문자열 자체가 분류 입력. 웹페이지 본문은 **fetch 안 함** |
| URL 신호 검출기 | VirusTotal([safety.py](pipeline/safety.py)) + 샌드박스([sandbox.py](pipeline/sandbox.py))뿐. 도메인 나이·TLS·유사도메인 검출기는 코드베이스에 **없음** |

**핵심 재프레이밍**: `scam_type` 은 이미 "판정"이 아니라 "검출의 *컨텍스트*"입니다
([signal_detector.py:77](pipeline/signal_detector.py#L77)). 어떤 `detected_signal` 도 만들지
않고, 라우팅(엔티티 라벨셋·검증 전략·RAG 필터)에만 쓰입니다. 따라서 오분류의 대가는
"틀린 판정"이 아니라 **"틀린 라우팅 = 검출 누락(recall 손실)"** 입니다.

---

## 3. 3단계 캐스케이드 설계

### Stage 1 — 콘텐츠 게이트 (내부 라우팅 전용)

5 bucket: `정상` / `사기 시도` / `사기 뉴스·교육` / `의심되지만 불충분` / `판단 불가`

- **외부 API 응답에 노출하지 않습니다.** 파이프라인 라우팅 + 라벨링 metadata 에만 사용.
- 이유: CLAUDE.md 의 Identity Boundary("사기/정상 판정 안 함")를 유지하기 위함. 게이트
  결과를 응답 표면에 올리면 "검출 시스템"이 "판정 시스템"으로 바뀌고, 차별화 스토리
  ("VirusTotal 처럼 검출만, 판정은 통합 기업")가 무너집니다.
- **게이트는 절대 hard-skip 안 함** — 게이트가 오판해도(사기를 "정상"으로) 룰 기반 신호검출은
  계속 돌립니다. 게이트는 *비싼* 단계(Serper 검증·LLM 보조)만 가지치기합니다.

게이트는 완전 OFF 대신 **bucket 별 실행 강도**를 조절합니다 (룰 기반 신호검출은 항상 수행):

| bucket | 룰 신호검출 | scam_type 분류 | Serper 검증 | LLM 보조 |
|---|---|---|---|---|
| 정상 | ✅ 항상 | skip | OFF | OFF |
| 사기 뉴스·교육 | ✅ 항상 | skip | OFF | OFF |
| 의심되지만 불충분 | ✅ 항상 | ✅ | 제한 (상위 8개) | ✅ |
| 판단 불가 | ✅ 항상 | ✅ | 제한 (상위 8개) | ✅ |
| 사기 시도 | ✅ 항상 | ✅ | 전체 (상위 15개) | ✅ |

게이트 profile 은 호출자 인자(`use_llm`·`skip_verification`)를 **상한선으로 줄이기만** 합니다 —
호출자가 끈 기능을 게이트가 켜지는 않습니다.

bucket 정의(라벨링 일관성용):
- `의심되지만 불충분` = 사기 쪽으로 기울지만 신호가 부족
- `판단 불가` = 입력이 너무 짧거나 깨져 방향조차 못 정함

### Stage 2 — 사기 유형 multi-label 라우팅

- 기존 `scam_type` 유지. 단 단일 강제 대신 임계값을 넘는 **상위 N개 유형의 엔티티 라벨셋을
  합집합**으로 extractor 에 전달 → 복합 스캠 엔티티 누락 해소.
- 표면 `scam_type` 은 top-1 유지 (context 용, 노출 schema 불변).
- "기타 사기" escape hatch 추가.

### Stage 3 — 위험 신호 그룹핑 레이어

- 기존 27개 `DETECTED_FLAGS` / `FLAG_RATIONALE`(학술·법적 근거 매핑)는 **유지**.
- 11개 대표 신호는 27개를 묶는 **표시 그룹핑 레이어** — 27개를 11개로 교체하지 않습니다.

---

## 4. 확정 사항 (2026-05-19 잠금)

- 1단계 게이트: 내부 라우팅 전용, 외부 응답 비노출. CLAUDE.md 개정 없음.
- 게이트가 `정상` 이어도 룰 기반 신호검출은 항상 수행.
- 게이트 모델: **Claude Haiku** 우선 (실패 시 heuristic·fallback).
- 외부 `scam_type` 은 top-1 유지. 내부 `candidate_scam_types` 는 top-N multi-label.
- extractor 는 top-N 유형의 `LABEL_SETS` 합집합 사용.
- 27개 flag + `FLAG_RATIONALE` 유지. 11개 신호는 표시 그룹핑 레이어로만.
- 납치·협박형 유지.

**조건부**
- 건강식품·부동산 유형: 코드에서 삭제 X. 데이터 부족 시 *학습 정책*에서만 `other_scam` 으로 병합.
- Serper/LLM: 완전 OFF 대신 게이트 bucket 별 실행 강도 조절 (위 표).

---

## 5. 구현 계획

세부 체크리스트는 [tasks/todo.md](tasks/todo.md) 의
"3단계 캐스케이드 — 콘텐츠 게이트 + multi-label 라우팅 (2026-05-19)" 섹션 참고.

순서: Stage 1 게이트 → Stage 2 multi-label → Stage 3 그룹핑 (각각 독립 배포 가능).
