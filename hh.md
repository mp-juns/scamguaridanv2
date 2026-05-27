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

---

## 6. Stage 2 분류기 학습 데이터 진행상황 (2026-05-27)

캐스케이드 Stage 2 (multi-label scam_type) 의 학습 데이터·1차 학습 결과 정리.
Stage 1·3 와 무관 — Stage 2 분류기 품질을 결정짓는 데이터 layer 만 다룸.

### 6.1. classifier-v1 1차 학습 (sanity check)

**데이터**: `data/processed/user_samples_2026-05-26.jsonl` (99줄) + DB
`human_annotations` 머지 → 124 content / **87 scam_type** / 19 gliner.
라벨 <5 건 5종(취업알바·코인·건강식품·납치·부동산) 학습 제외 → 73 샘플 7라벨로 학습.

**환경 패치** ([training/train_classifier.py](training/train_classifier.py)):
- `tokenizer=` → `processing_class=` (transformers 5.1.0 `Trainer` API 변경)
- `fp16=` → `bf16=` (LoRA + fp16 의 `Attempting to unscale FP16 gradients` 회피)

**결과** (`checkpoints/classifier-v1/`):

| metric | value |
|---|---|
| train / val | 65 / 8 |
| eval_macro_f1 | **0.167** (7클래스 랜덤 0.143 근접) |
| eval_accuracy | 0.25 |
| 학습 시간 | 6.9초 (RTX 5070 Ti, LoRA 어댑터) |

**결정**: `active_models.json` swap 안 함 — zero-shot fallback 유지. 본 모델은
재현·디버그 용 산출물로만 보존. 자세한 metric·환경 패치 기록은
[changes.md 2026-05-27 섹션](./changes.md).

### 6.2. 외부 데이터 평가

세션 동안 검토한 3개 데이터 소스의 Stage 2 학습 기여도:

| 소스 | 건수 | 우리 라벨 매핑 | Stage 2 기여도 |
|---|--:|---|---|
| `data/processed/user_samples_*.jsonl` | 99 | 직접 매핑 (사용자 수집·검수) | ✅ 핵심 — 87 scam_type 의 절반+ |
| `data/processed/public_cases.jsonl` | 87 | 미라벨 — `scam_type_hint` 만 있고 normalizer 가 안 읽음 | ❌ 머지 시 전부 `undetermined` 처리, Stage 2 비기여 |
| `data/generated_data/...synthetic_nodup_2026-05-27.jsonl` | 171 | 스키마 완벽 매치, 19개 시나리오, 마스킹 처리 (`non_deployable: true`) | ✅ 즉시 활용 가능 (Stage 2 의 9 라벨 보강) |
| AI Hub 71768 (광주 119) | 20,129 | 119 응급 신고 — 보이스피싱과 *역할/맥락 반대* | ⚠️ Stage 2 직접 매핑 불가, normal 발췌 200~500건 한정 |

### 6.3. v2 목표(라벨당 30) 까지 부족분

user_samples+DB 87 + 합성 91 = **178 scam_type 머지 시**:

| 라벨 | 현재 | +합성 | 합산 | v2 목표 대비 | Stage 2 학습 포함? |
|---|--:|--:|--:|--:|---|
| 스미싱 | 22 | +26 | 48 | ✅ +18 | ✅ |
| 기관 사칭 | 12 | +25 | 37 | ✅ +7 | ✅ |
| 대출 사기 | 10 | +5 | 15 | -15 | ✅ |
| 메신저 피싱 | 9 | +5 | 14 | -16 | ✅ |
| 투자 사기 | 7 | +5 | 12 | -18 | ✅ |
| 중고거래 사기 | 7 | +5 | 12 | -18 | ✅ |
| 로맨스 스캠 | 6 | +5 | 11 | -19 | ✅ |
| 코인 사기 | 4 | +5 | 9 | -21 | ✅ (이전엔 <5 제외) |
| 취업·알바 사기 | 4 | 0 | 4 | -26 ❌ | ❌ |
| 건강식품 사기 | 3 | 0 | 3 | -27 ❌ | ❌ |
| 납치·협방형 | 2 | 0 | 2 | -28 ❌ | ❌ |
| 부동산 사기 | 1 | 0 | 1 | -29 ❌ | ❌ |

**효과**: 합성 머지 시 Stage 2 학습 포함 라벨 **7 → 8개** (코인 사기 회복).
나머지 4 라벨은 별도 sourcing 필요.

### 6.4. 다음 Stage 2 학습 사이클

1. **classifier-v1.5**: user_samples + 합성(171건) `--extra-jsonl` 두 개 동시 머지 학습 →
   합성 비율 증가가 macro_f1 에 미치는 영향 측정 (Stage 2 회의 — 합성 통제선 결정 근거)
2. **부족 4라벨** (취업알바·건강식품·납치·부동산) Claude 합성 시나리오 추가 → 12라벨 학습 가능
3. **AI Hub 71768 normal 발췌** 200~500건 통제 머지 — normal 학습 분포 확장
4. **v2 (라벨당 30, total ~360) 도달 시 base 모델 ablation**:
   mDeBERTa-v3-base-mnli-xnli (현재) vs KcELECTRA-base-v2022 vs klue/roberta-base

### 6.5. Identity Boundary 와의 일관성

본 학습은 **외부 `scam_type` top-1** 유지 + **내부 `candidate_scam_types` top-N** 라우팅
용도로만 쓰임 (Section 4 의 D7·D8 확정사항). 점수·등급 외부 노출 X, 검출 신호만 보고
원칙 그대로. 학습 결과 macro_f1 0.167 이라는 *측정값* 자체도 내부 sanity check 용이지
외부 응답 surface 에 노출되지 않음.
