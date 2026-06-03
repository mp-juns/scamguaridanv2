# 3단계 캐스케이드 — 콘텐츠 게이트 + multi-label 라우팅 (2026-05-19)

목적: 12개 사기유형 단일 강제 분류의 두 결함 해결 —
(1) 정상·뉴스/교육 콘텐츠도 12개 중 하나로 강제 → 헛수고·오탐
(2) 복합 스캠("코인+로맨스")을 단일 유형으로 강제 → 한쪽 엔티티 검출 누락

1단계(게이트) → 2단계(유형) → 3단계(신호) 캐스케이드.

## 확정 사항
- **1단계 5-bucket 게이트는 외부 API 응답에 노출 X** — 내부 라우팅 + 라벨링 metadata 에만.
- 외부 응답 schema 불변: `detected_signals[]` + `scam_type` context. CLAUDE.md Identity Boundary 개정 X.
- 1단계는 **절대 hard-skip 안 함** — 게이트 오판 시 검출 누락 방지. 룰 기반 신호검출은 항상 돎,
  비싼 단계(Serper·LLM)만 가지치기 (아래 라우팅 표).

## 확정 (2026-05-19)
- 1단계 게이트 구현: **Claude Haiku** (context_chat.classify_intent 패턴, 실패 시 fallback)
- 2단계 유형: 12개 전부 유지 + "기타 사기" 추가. 건강식품·부동산은 코드 삭제 X —
  데이터 부족 시 학습 정책에서만 `other_scam` 으로 병합
- Serper/LLM: 완전 OFF 대신 bucket 별 실행 강도 조절

## Stage 1 — 콘텐츠 게이트 (internal routing only)

5 bucket: `정상` / `사기 시도` / `사기 뉴스·교육` / `의심되지만 불충분` / `판단 불가`

| bucket | 룰 신호검출 | scam_type 분류 | Serper 검증 | LLM 보조 |
|---|---|---|---|---|
| 정상 | ✅ 항상 | skip | OFF | OFF |
| 사기 뉴스·교육 | ✅ 항상 | skip | OFF | OFF |
| 의심되지만 불충분 | ✅ 항상 | ✅ | 제한 (8) | ✅ |
| 판단 불가 | ✅ 항상 | ✅ | 제한 (8) | ✅ |
| 사기 시도 | ✅ 항상 | ✅ | 전체 (15) | ✅ |

게이트 profile 은 호출자 인자(`use_llm`·`skip_verification`)를 상한선으로 줄이기만 함.

- [x] `pipeline/config.py` — `GATE_BUCKETS` / `GATE_LABELS_KO` / `GATE_EXECUTION_PROFILE` / fallback 정의
- [x] `pipeline/gate.py` 신설 — `classify_gate(text) → GateResult`. Haiku 1회 + heuristic fast-path + fallback
- [x] `tests/test_gate.py` — 18 케이스 (파서·fast-path·fallback·profile). 통과
- [x] `pipeline/verifier.py` — 룰 기반(`detect_rule_signals`) vs Serper 기반(`verify`) 분리
- [x] `tests/test_verifier_rule_signals.py` — 6 케이스. 룰/Serper dispatch disjoint 검증
- [x] `pipeline/runner.py` — Phase 1.5 게이트 + 라우팅 (profile 상한선 적용, 룰 검출 항상)
- [x] `api_server_pkg/common.py` — `persist_run` 이 gate 결과를 내부 metadata 에 기록 (외부 응답 비노출)

## 학습·평가 파이프라인 (2026-05-20 완료)

- [x] `training/splits.py` — source_ref 그룹 인식 70/15/15 split, leakage 방지
- [x] `training/dataset_summary.py` — content_label / sample_kind / scam_type / 출처 / 제외 카운트
- [x] `training/eval_gate.py` — 3-class (normal/scam_attempt/scam_news_edu) 평가
- [x] `training/eval_scam_type.py` — scam_attempt 한정 Top-1/3 + macro/weighted F1
- [x] `training/eval_signals.py` — flag/group 평가 + baseline vs current 라벨 커버리지 비교
- [x] `tests/test_training_eval.py` — 21 케이스 (leakage·제외 정책·baseline 비교)

## Review — Stage 1 (2026-05-20)

**무엇**: Stage 1 콘텐츠 게이트 구현 + 파이프라인 연결 완료.
- 게이트(`gate.py`)가 STT 직후 Phase 1.5 에서 5-bucket 분류 → `execution_profile` 로
  Phase 2(분류)·3(LLM)·4(Serper) 실행 강도 라우팅.
- `verifier.py` 의 룰 기반 신호검출을 Serper 검증과 분리 — `detect_rule_signals` 는
  모든 gate bucket 에서 항상 실행 (게이트 오판 시 검출 누락 방지).
- profile 은 호출자 인자(`use_llm`·`skip_verification`)를 상한선으로 줄이기만 함.
- 게이트 결과는 외부 응답 schema 비노출 — `self.last_gate_result` + DB metadata 만.

**검증**: pytest 208개 통과 (gate 18 + verifier 6 신규). 게이트 미적용(API key 없음)
fallback 경로로 end-to-end 스모크 — 게이트 fallback→분류→추출→룰 검출(`abnormal_return_rate`)
→`to_dict()` 에 gate 키 없음 확인.

**다음**: Stage 2 (multi-label 라우팅) / Stage 3 (신호 그룹핑) — 둘 다 완료 (아래 섹션 참고).

## Stage 2 — 사기 유형 multi-label 라우팅 (2026-05-24 완료, 상태 점검 2026-05-26)

- [x] `classifier.candidate_scam_types(all_scores, top_n, dominance_gap)` 추가
      ([pipeline/classifier.py:226](pipeline/classifier.py#L226)). `STAGE2_CANDIDATE_TOP_N=3`,
      `STAGE2_DOMINANCE_GAP=0.30` 상수는 [pipeline/config.py:322-328](pipeline/config.py#L322-L328).
- [x] `runner.py` — extractor 에 단일 `scam_type` 대신 라벨셋 **합집합** 전달
      ([pipeline/runner.py:471-473](pipeline/runner.py#L471-L473)). 실제 구현은 top-N 보다 더 광범위한
      `_all_label_union()` 전체 라벨 union (Phase 2 결과 기다리지 않고 eager 실행해 wall time
      단축). `COMMON_RISK_LABELS` (개인정보/계좌번호/악성 URL) 도 항상 포함.
- [x] candidate top-N 후보는 별도로 계산해 `last_candidate_scam_types` 에 저장
      ([pipeline/runner.py:516-519](pipeline/runner.py#L516-L519)), metadata 로 persist
      ([api_server_pkg/common.py:95-96](api_server_pkg/common.py#L95-L96)).
- [x] 표면 `scam_type` 은 top-1 유지 (context 용, 노출 schema 불변).
- [x] `tests/test_stage2_routing.py` — top-N 후보 + dominance gap 회귀 테스트.
- [ ] `config.py` — "기타 사기" 유형 + 라벨셋 추가 (escape hatch, 아직 미구현).

## Stage 3 — 위험 신호 그룹핑 레이어 (2026-05-20 완료)

- [x] 기존 51개 `DETECTED_FLAGS`/`FLAG_RATIONALE` 완전 보존 (11개로 교체 X)
- [x] `pipeline/flag_groups.py` 신설 — `FLAG_GROUPS`(11종) + `group_detected_flags()`.
      매핑 없는 flag 는 `other_signals` 로 fallback.
- [x] `pipeline/signal_detector.py` — `DetectionReport.signal_groups` optional 필드 +
      `detect()` 가 자동 populate, `to_dict()` 에 포함.
- [x] `tests/test_flag_groups.py` — 22 케이스 (그룹핑·other·중복 dedup·입력 형식·기존
      schema 보존·FLAG_GROUPS 무결성).
- [ ] (선택, 다음 패스) `kakao_formatter.py` / 결과 페이지 / AdminRunEditor 가 `signal_groups`
      를 실제로 표시 — schema 는 이미 준비됨.

## 검증
- [ ] 합성 발화로 게이트 5-bucket 정확도 (특히 사기 뉴스/교육 vs 사기 시도 혼동률) — 측정 미실시
- [ ] 복합 스캠 텍스트로 multi-label 합집합 → 엔티티 recall 개선 측정 — 측정 미실시
- [x] `tests/test_gate.py` 신설 + pytest 회귀 없음 (2026-05-26 기준 322 tests collected, 기존 93 → 322 확장).

## Review
(구현 후 작성)

---

# Stage 2 — APK 정적 분석 Lv 1 진짜 구현 (2026-05-05)

목적: Stage 1 narrative 의 Tier 2 (정적 Lv1) 를 실제 코드로. androguard 기반 manifest·
권한·서명 분석 → 3 종 검출 신호 (`apk_dangerous_permissions_combo`, `apk_self_signed`,
`apk_suspicious_package_name`) 추가. Stage 3 (Tier 3 bytecode) 는 다음.

## 작업 범위

### 건드릴 곳
- `requirements.txt` — `androguard` 추가
- `pipeline/apk_analyzer.py` — 신설, Lv 1 분석 함수
- `pipeline/config.py` — DETECTED_FLAGS / FLAG_LABELS_KO / FLAG_RATIONALE 에 3 종 신호 추가
- `pipeline/runner.py` — Phase 0.6 (APK 정적 분석) 통합
- `pipeline/signal_detector.py` — `apk_static_result` 인자 + 검출 로직
- `tests/test_apk_analyzer.py` — 신설, helper 함수 + 통합 contract
- `docs/openapi.json` — scripts/dump_openapi.py 재생성

### 안 건드릴 곳
- `pipeline/dex_pattern_analyzer.py` — Stage 3 (Lv 2)
- 동적 분석 — 결정대로 Lv 2 까지만
- `pipeline/kakao_formatter.py` — 검출 reframe 에서 이미 detected_signals 기반

## Step 1: 의존성
- [x] `requirements.txt` 에 androguard>=4.1.0 추가
- [x] `pip install androguard` (4.1.3 설치 확인)
- [x] import path 검증 — `androguard.core.apk.APK` + `androguard.misc.AnalyzeAPK`

## Step 2: pipeline/apk_analyzer.py (Lv 1 + Lv 2 통합)
- [x] `APKStaticReport` + `APKBytecodeReport` dataclass
- [x] **Lv 1**: `analyze_apk_static(apk_path)` — 위험 권한 4종 임계 / `_check_self_signed` (asn1crypto subject==issuer) / `_is_suspicious_impersonation` (정상 한국 앱 typo-squatting)
- [x] **Lv 2**: `analyze_apk_bytecode(apk_path)` — `AnalyzeAPK` 결과로 7 종 패턴 검출
  - `_has_method_xref` — SmsManager.sendTextMessage / TelephonyManager.listen / DevicePolicyManager.lockNow xref
  - `_references_accessibility_service` — AccessibilityService 상속
  - `_contains_string_keywords` — 사칭 키워드 (검찰·금감원·은행·안전계좌)
  - `_has_suspicious_url_constants` — IP 직접·무료 도메인·비표준 포트 regex
  - `_looks_obfuscated` — 1-2글자 클래스명 비율 + 클래스 50개 이상 임계
- [x] `is_apk_file(path)` — `.apk` 확장자 또는 `PK\x03\x04` ZIP magic
- [x] 정상 한국 앱 list 16 개 + 의심 suffix list 7 개 — 모두 명시적 list (magic number X)
- [x] 모든 분석 함수 try/except graceful — 실패 시 빈 detected_flags + error 필드

## Step 3: pipeline/config.py
- [x] `DETECTED_FLAGS` 에 10 종 추가 (Lv 1 × 3 + Lv 2 × 7)
- [x] `FLAG_LABELS_KO` 한국어 매핑 10 종
- [x] `FLAG_RATIONALE` 학술/법적 근거 10 종:
  - S2W TALON (SecretCalls·KrBanker·SecretCrow·MoqHao 보고서)
  - KISA (사이버 위협 인텔리전스 / 모바일 보안)
  - 안랩 보이스피싱 분석 리포트
  - 정보통신망법 제48조, 통신사기피해환급법 제2조 제2호, 형법 제283조
  - Cialdini (2021), Stajano & Wilson (2011)
  - Allix et al. (2016) AndroZoo, Wei et al. (2018), Mavroeidis & Bromander (2017)
  - OWASP Mobile Top 10, Android API Documentation

## Step 4: pipeline/signal_detector.py
- [x] `detect()` 시그니처에 `apk_static_result` + `apk_bytecode_result` 추가
- [x] Lv 1 → DetectedSignal (detection_source="static_lv1")
- [x] Lv 2 → DetectedSignal (detection_source="static_lv2")
- [x] `DETECTED_FLAGS` 외 flag 무시 (환각 차단)
- [x] dedupe (같은 flag 가 양쪽에서 들어와도 1번만)
- [x] `DetectionReport` 에 `apk_static_check` + `apk_bytecode_check` 필드 추가

## Step 5: pipeline/runner.py
- [x] `apk_analyzer` import
- [x] Phase 0.6 (Phase 0.5 sandbox 직후 / Phase 1 STT 직전)
  - `is_apk_file(source)` 감지
  - Lv 1 + Lv 2 순차 호출, 각각 try/except graceful
  - StepLog "APK" 로 lv1_flags + lv2_flags 카운트 기록
- [x] signal_detector.detect() 호출 시 두 result 전달

## Step 6: 테스트
- [x] tests/test_apk_analyzer.py 신설 — 55 테스트:
  - `is_apk_file` (5): 확장자·magic bytes·missing·directory·text 거부
  - `_is_suspicious_impersonation` (12 parametrize): 정상 일치 vs typo-squatting vs suffix
  - 합성 minimal APK fixture (2): parse 실패에도 graceful return contract
  - schema 키 검증 (2): `total_score`/`risk_level` 절대 없음
  - signal_detector 통합 (4): static/bytecode → DetectedSignal, dedupe, 환각 차단
  - 매핑 검증 (30 parametrize): 10 flag × (DETECTED_FLAGS 멤버 + FLAG_LABELS_KO + FLAG_RATIONALE rationale·source)
- [x] **pytest -q → 169 passed** (직전 114 + 신규 55)

## Step 7: docs
- [x] `scripts/dump_openapi.py` 재실행 → 33 endpoint, 75,938 bytes
- [x] `CLAUDE.md` Tier 2/3 — *미구현* 표시 → 실제 동작 (function 명·flag 명 명시) 으로 갱신
- [x] `README.md` 동일 — *(Stage 2 — 미구현)* / *(Stage 3 — 미구현)* 표시 제거
- [x] `INTEGRATION_GUIDE.md` 의 7 신호 예시 헤더 — "Stage 2·3 미구현" → "Stage 2·3 구현 완료" + 동작 메커니즘 명시

## Step 8: lessons.md (4 신규 패턴)
- [x] **패턴 5**: 한국 보이스피싱 APK 검출은 시그니처+정적+심화정적 3-tier 가 학술 표준
- [x] **패턴 6**: bytecode 패턴은 단독 신호로 약함, 누적+조합으로만 강함 — 5 종 false positive 시나리오 명시
- [x] **패턴 7**: "동적 분석" vs "심화 정적 분석" 학술 용어 정확히 구분
- [x] **패턴 8**: androguard LGPL — 동적 링크 OK, fork/embed 는 라이선스 의무

## 검증
- [x] `pytest -q` → **169 passed, 0 failed**
- [x] `python -c "from api_server import app"` → boot OK, 39 routes
- [x] `from pipeline.apk_analyzer import ...` 모든 심볼 import OK
- [x] 합성 minimal APK fixture (parse 불가능한 invalid manifest) 던져서 graceful (error 필드만 채워짐) 확인
- [x] 10 APK flag × 3 (DETECTED_FLAGS + FLAG_LABELS_KO + FLAG_RATIONALE) = 30 매칭 확인
- [x] Forbidden Actions 위반 0: "차단합니다" / "production-grade" / "위험 점수" 신규 추가 0건

## 주의 (CLAUDE.md Forbidden Actions)
- ❌ 점수·등급 신규 추가 X — Stage 2 reframe 이후 절대 X
- ❌ "production" / "차단합니다" / "100% 잡는다" X
- ❌ magic number X — 모든 임계는 명시적 list
- ✅ FLAG_RATIONALE 신규 3 종은 학술/법적 근거 (S2W TALON / KISA / 정보통신망법 / Cialdini) 동반 필수

## Review (2026-05-05) — Stage 2/3 통합 (APK 정적 분석 Lv 1 + Lv 2)

### 산출물

**신설 (3 파일)**:
- `pipeline/apk_analyzer.py` (~340 줄) — `APKStaticReport` + `APKBytecodeReport` + `analyze_apk_static()` + `analyze_apk_bytecode()` + `is_apk_file()` + helper 7 종
- `tests/test_apk_analyzer.py` (~270 줄, 55 테스트) — unit + integration + schema contract + 매핑 검증

**수정 (5 파일)**:
- `requirements.txt` — `androguard>=4.1.0`
- `pipeline/config.py` — `DETECTED_FLAGS` × 10 / `FLAG_LABELS_KO` × 10 / `FLAG_RATIONALE` × 10 추가
- `pipeline/signal_detector.py` — `detect()` 시그니처 확장 + DetectionReport 에 `apk_static_check`/`apk_bytecode_check` 필드
- `pipeline/runner.py` — Phase 0.6 (Lv 1 + Lv 2) 통합
- `CLAUDE.md` + `README.md` + `docs/INTEGRATION_GUIDE.md` + `tasks/lessons.md` — 미구현 표시 → 실제 동작 + 4 신규 패턴

### 핵심 metric

| 항목 | 결과 |
|------|------|
| pytest | **169 passed, 0 failed** (114 → +55) |
| 새 검출 신호 | 10 종 (Lv 1 × 3 + Lv 2 × 7) |
| 학술 출처 동반 | 10/10 — 모든 신호에 `rationale` + `source` (S2W TALON / KISA / 정보통신망법 / Cialdini / Stajano-Wilson / OWASP / Allix·Wei 학술 논문) |
| 서버 부팅 | OK, 39 routes |
| openapi.json | 33 endpoint, 75,938 bytes |
| Forbidden Actions 위반 | 0 — "차단합니다" / "production-grade" / "위험 점수" 신규 추가 0건 |

### 학술 정직성 (핵심 boundary)

- **"심화 정적 분석" 용어 일관 사용** — "동적 분석" 단어 신규 사용 0건. CLAUDE.md / README / INTEGRATION_GUIDE / apk_analyzer.py 모두 "정적 분석 / bytecode pattern matching" 으로 정확히 표기
- **false positive 한계 명시** — apk_analyzer.py 모듈 docstring + FLAG_RATIONALE 본문 + lessons.md 패턴 6 에 "정상 메신저 앱도 SmsManager 사용 / 정상 앱도 Accessibility 사용 / 단독 신호로는 약함" 명시
- **"단일 신호로 사기 판정 X"** — signal_detector / kakao_formatter 가 누적 신호만 보고, 판정은 통합 기업 (Identity Boundary 일관)
- **검출률 60-80% 정직 표현** — README + CLAUDE.md 학술 인용 (Allix et al. 2016 / Wei et al. 2018) 동반

### Identity Boundary 준수

- ❌ 점수·등급 응답에 노출 0 — 10 신호 모두 검출 사실 + rationale + source 만
- ❌ "위험 점수 X점" / "안전·의심·위험 등급" 신규 추가 0
- ❌ "100% 잡는다" / "production-grade" / "차단합니다" 0
- ❌ magic number 신규 0 — 모든 임계 (`_DANGEROUS_PERMISSION_THRESHOLD = 4`, `_OBFUSCATION_RATIO_THRESHOLD = 0.30` 등) 명시적 named constant
- ✅ FLAG_RATIONALE 신규 10 종은 모두 학술/법적 근거 (Cialdini 2021 / Stajano-Wilson 2011 / Allix 2016 / Wei 2018 / S2W TALON / KISA / 정보통신망법 / 통신사기피해환급법 / 형법 / Android API Doc / OWASP) 동반

### 의도적으로 *안* 한 것

- **진짜 동적 분석 stub 0** — 사용자 명시 결정 (Lv 2 까지만)
- **에뮬레이터 통합 0** — future work 영역, 호스트 위험 + 5-7주 작업
- **악성 APK 샘플 commit 0** — 합성 minimal APK fixture 만, 진짜 샘플은 KISA 수동 fetch (gitignore)
- **카카오 카드 포맷 변경 0** — 직전 detection reframe 에서 이미 detected_signals 기반

### 미해결 (다음 stage 후보)

- 실제 악성 APK 샘플 (KISA 공개 분석 자료) 으로 검출 정확도 측정 — 별도 fixture 디렉토리 + gitignore 정책 필요
- false positive 측정 — Play Store 정상 앱 (카카오톡 / 네이버 / 은행 앱) 던져서 어떤 신호가 잘못 검출되는지 통계
- Phase 0.6 의 timeout 정책 — 매우 큰 APK (>100MB) 에서 AnalyzeAPK 가 분 단위 걸릴 수 있음, signal 처리로 cap 필요
- `runner.py` 의 source detection — 현재 `is_apk_file()` 만, MIME type / 다운로드 후 검사 등 더 견고한 routing

---

# STT 병렬 chunking — 영상 분석 latency 단축 (2026-05-24)

목적: 현재 `_transcribe_with_openai_api()` 가 오디오 전체를 1회 호출 → 180s 영상이면 STT 단독으로 5~10s. 분석 전체 시간의 큰 비중. 오디오를 45s chunk 로 분할 후 4 워커 병렬 호출 → 3배 단축 목표.

## 설계

- chunk size 45s, 워커 4, threshold 45s (이하면 기존 1-shot 유지 — 오버헤드 절약)
- 모든 파라미터 env 로 조정 가능 (`STT_CHUNK_SEC`, `STT_MAX_WORKERS`, `STT_CHUNK_THRESHOLD_SEC`)
- chunk 경계 단어 잘림 허용 — 분석은 누락 1~2단어 영향 무시 가능 (분류·엔티티·LLM 모두 견고)
- 비용 ledger 는 chunk 마다 `record_openai_whisper(duration)` 호출 (기존과 동일 정확도)
- Claude 백엔드는 변경 X — audio API 가 다른 모델, 별 이득 없음

## 작업

- [x] `pipeline/stt.py` — `_transcribe_chunks_parallel()` + `_split_audio_chunks()` + `_whisper_one()` 추가
- [x] `_transcribe_with_openai_api()` 에 길이 분기 — threshold 초과 시 chunked 호출
- [x] env 변수 default + 파싱 (STT_CHUNK_SEC=45, STT_MAX_WORKERS=4, STT_CHUNK_THRESHOLD_SEC=45)
- [x] `tests/test_stt_chunked.py` — 6 케이스 (분할 카운트·정렬·threshold 우회·병렬 dispatch·chunk 실패 복구·파일 누락)

## 검증

- [x] `tests/test_stt_chunked.py` 6/6 통과
- [x] 기존 `test_v4_whisper_chunker.py` 4개 통과 (회귀 없음)
- [x] 전체 스위트 316/316 통과
- [x] 짧은 오디오(<45s)는 `_whisper_one` 1회만 호출 (mock 으로 확인)

## 리뷰 (2026-05-24)

**핵심 변경**: `pipeline/stt.py` 의 `_transcribe_with_openai_api` 가 오디오 길이를 보고 자동 분기. 45s 이하는 기존 1-shot, 초과 시 ffmpeg segment 로 자르고 ThreadPoolExecutor 로 4 워커 병렬 호출. chunk index 정렬해 concat.

**예상 latency**: 180s 영상 기준 1×Whisper(180s) → 4×Whisper(45s) 병렬. RTT/오버헤드 떼면 약 3× 단축.

**비용 영향 없음**: Whisper 가격은 audio 초당 — chunk 마다 `record_openai_whisper(chunk_duration)` 호출해 ledger 정확도 유지.

**실패 격리**: chunk 한 개가 API 에러 던져도 빈 문자열로 대체. 나머지 chunk 결과는 보존 (catastrophic failure 회피).

**조정 가능한 손잡이** (env):
- `STT_CHUNK_SEC` (기본 45) — chunk 길이
- `STT_MAX_WORKERS` (기본 4) — 동시 Whisper 호출 수
- `STT_CHUNK_THRESHOLD_SEC` (기본 45) — 이하면 chunking skip

**의도적으로 안 한 것**:
- chunk 경계 overlap — 단어 1~2개 잘릴 수 있으나 분류·엔티티에 영향 미미. 복잡도 비례한 이득 없음
- Claude audio 백엔드 변경 — audio API 가 다른 호출 패턴이라 분리 유지
- YouTube 180s 캡 변경 — 현재 캡 유지 (`pipeline/stt.py:64`), 캡 확장은 별도 결정 필요
- runner.py 변경 — `transcribe()` 호출부는 그대로

---

# Phase 1.5 게이트 latency 단축 (2026-05-24)

목적: 14:24 분석 로그 분석 결과 — 게이트 Claude Haiku 호출이 2.4s 차지 (총 12s 중). 시스템 프롬프트 트림 + max_tokens 단축 + 뉴스 narration heuristic fast-path 로 줄임.

## 작업

- [x] `pipeline/gate.py` — `max_tokens 120 → 60`. 출력 JSON 60 tokens 안에 충분히 들어감
- [x] `pipeline/gate.py` — 시스템 프롬프트 ~950자 → ~600자 트림 (중복 설명 제거, 예시 5개 → 3개)
- [x] `pipeline/gate.py` — `_news_edu_fast_path()` 추가. 뉴스 마커 2개 이상 + 직접 명령 0개 → LLM skip
- [x] `tests/test_gate.py` — heuristic 케이스 6개 추가 (강한 마커 트리거 / 명령 차단 / 마커 부족 fallthrough / 헬퍼 직접 호출 3개)

## 검증

- [x] `test_gate.py` 24/24 통과 (기존 18 + 신규 6)
- [x] 전체 322/322 통과 (이전 316 + STT 신규 6, gate 신규 6 — 회귀 0)
- [x] 사용자 본 transcript 로 heuristic 트리거 안 됨 확인 — narrative ~ㅂ니다 만 쓰고 명시적 마커 없음 (의도된 보수성)

## 리뷰

**heuristic fast-path 동작 조건** (둘 다 만족):
1. NEWS_MARKERS 2개 이상 — `라고 밝혔다/전했다`, `[기자]`, `검찰/경찰/금감원에 따르면`, `피해자/피의자는`, `수사 중`, `급증하`, `주의가 필요`, `예방 안내`, `피해 사례`, `(보도|기사|뉴스|방송)에서/에 따르면`
2. DIRECT_DEMAND 0개 — `지금 (송금|입금|이체)`, `OTP/인증번호 (입력|알려)`, `계좌(번호)? (입력|알려|로 보내)`, `클릭하세요`, `(설치|다운로드) 하세요`

**보수성 이유**: heuristic 가 false positive → Phase 2/LLM/Serper 모두 skip 됨 = 진짜 사기 놓침. 그래서 마커 *2개* + 명령 0개 강제. 1개만이면 LLM 으로 위임.

**예상 latency 효과**:
- 명시적 뉴스 마커 있는 콘텐츠 (기사·보도): 2.4s → ~0ms (heuristic 즉시)
- 그 외: 2.4s → ~1.5s (max_tokens + 프롬프트 트림만)
- 사용자 본 영상 같은 narrative 콘텐츠: heuristic 안 걸리지만 LLM 경로에서 ~0.5s 단축

**의도적으로 안 한 것**:
- Anthropic prompt caching — 시스템 프롬프트가 cache 최소 토큰(2048) 못 넘음. 인위적으로 padding 하면 비용 낭비
- 스캠_시도 heuristic — 마커 (지금 송금, OTP 등) 가 사기·뉴스 양쪽에 다 등장 가능, 보수적으로 보류
- 게이트 ↔ Phase 3 LLM 병렬화 — 게이트 결과로 LLM skip 결정하기 때문에 병렬 의미 없음

## 회귀 → 긴급 수정 (2026-05-24, 첫 회귀 보고 후)

**증상**: 14:34, 14:40 분석 동일 transcript 가 12s → 33-40s 폭증.

**진단**: `.scamguardian/scamguardian.sqlite3` 의 latest run metadata 확인 →
`gate.source = "fallback"`, `gate.reason = "bucket 무효('') — fallback"`. 즉
`max_tokens=60` 이 Haiku 출력을 잘라 파서 실패 → fallback bucket = undetermined → 보수 라우팅으로 Phase 2 + Phase 3 LLM 전체 실행.

**수정** (`pipeline/gate.py`):
- `max_tokens 60 → 120` 복구 (출력 token 캡은 latency 절약 < 라우팅 회귀 비용)
- 프롬프트에 "보이스피싱 피해 사례" 예시 + "사건 narration" 예시 복원 (사용자 본 영상 같은 케이스가 명확히 매칭되도록)
- 프롬프트에 "reason 은 20자 이내" hint 추가 (출력 길이 안정화)
- news fast-path + 시스템 프롬프트 트림은 그대로 유지 (그 자체는 안전)

**검증**:
- `test_gate.py` 24/24 통과 (회귀 없음)
- 사용자 다음 분석 로그에서 `gate.source = "haiku"` + bucket = scam_news_edu (또는 적절한 분류) 회복 확인 필요

**Lessons.md 패턴 5 등록**: "LLM max_tokens 단축은 라우팅 결정에 *대규모* 회귀 — 출력 캡은 예상 길이의 2-3배 안전 마진. fallback bucket 의 라우팅 비용도 함께 고려."

---

# Phase 1.5+2+3 통합 병렬화 — 1분 영상 10s 목표 (2026-05-24)

목적: 사용자 목표 "1분 영상 10s 이내". 현재 11s (STT 8s + Gate 1s + Phase 2 1s + Phase 3 1-2s). Whisper 안 건드는 전제로 post-STT phase 를 통합 병렬화.

## 설계

이전 sequential: `STT → Gate(1s) → Phase 2(1s) → Phase 3 parallel(1-5s)`

신규 통합 병렬: `STT → [Gate || Classify || Extract(union) || RAG] all parallel → conditionally LLM`

핵심 결정:
- **Gate + Classify + Extract + RAG 모두 eager** — wall time max(...) ≈ 1s
- **Classify/Extract/RAG 결과는 게이트 라우팅에 따라 conditionally 사용** — eager 실행한 게 낭비될 수 있지만 wall time 절약 더 큼
- **LLM 만 sequential** — 사전 시작 시 $ cost 낭비 회피
- **B 최적화**: 게이트=normal 이면 추출 결과 자체 무시 (스킵)
- **Extract union 모드** — Phase 2 결과 기다리지 않으므로 candidate_scam_types 없음. union 라벨이 약간 더 무겁지만 wall time 단축 큼
- **executor.shutdown(wait=False)** — 게이트가 skip 결정한 future 는 background 에서 완료, main thread 는 즉시 진행

## 작업

- [x] `pipeline/runner.py` — Phase 1.5/2/3 세 블록을 단일 통합 병렬 블록으로 리팩토링
- [x] `GATE_NORMAL` import 추가 (`pipeline.config` 에서)
- [x] 통합 병렬 완료 시간 로그 추가 (`Phase 1.5+2+3 통합 병렬 완료: Xms`)

## 검증

- [x] 전체 테스트 322/322 통과 (회귀 0)
- [ ] uvicorn reload 후 실제 영상 분석 — 1분 영상 9-10s 달성 확인

## 예상 효과 (post-STT phases 만 비교)

| 케이스 | 이전 (sequential) | 신규 (parallel) | 단축 |
|--------|------|------|------|
| gate=normal (skip Phase 2/LLM) | Gate 1 + GLiNER 0.5 = 1.5s | max(Gate, Classify-waste, Extract-skip, RAG-waste) = 1s | ~0.5s |
| gate=scam_news_edu (skip Phase 2/LLM) | Gate 1 + Extract 0.5 = 1.5s | max(Gate, Classify-waste, Extract 0.5, RAG-waste) = 1s | ~0.5s |
| gate=scam_attempt (run all) | Gate 1 + Phase 2 1 + LLM 5 = 7s | max(Gate, Classify, Extract, RAG) 1 + LLM 5 = 6s | ~1s |
| gate=undetermined (run all) | 7s | 6s | ~1s |

1분 영상 (STT 8s) 기준:
- 이전: 8 + (1.5 ~ 7) = 9.5 ~ 15s
- 신규: 8 + (1 ~ 6) = 9 ~ 14s
- 일반 케이스 (normal/news_edu) 에서 1분 영상 ~9s 달성 가능

## 의도적으로 안 한 것

- **LLM speculative parallel 실행** — 게이트가 skip 결정 시 $ cost 낭비. Anthropic Haiku $0.001/req 작아 보이지만 50% skip rate 면 누적 비용.
- **Phase 2 후 Extract 재실행 (focused labels)** — union 모드 entity 가 정확도 거의 같으면서 wall time 일관됨. 굳이 두 번 안 함.
- **Phase 0/0.5/0.6 변경** — 영상 분석엔 영향 없음 (URL/APK 케이스)

---

# Next 16 Turbopack 메모리 누수 → Webpack fallback (2026-05-28)

목적: `./scripts/start_stack.sh` 실행 시 WSL freeze 재발. 직전 8GB 한도 의심으로 20GB 증설했으나 stack 안 띄워도 압박 체감 = 메모리 단독 원인 아님. 진짜 root cause 진단 + fix.

## 진단 (`scripts/monitor_resources.sh` 자체 도구로 잡음)

- **첫 freeze (03:04)**: next-server **VSZ 3GB → 22GB (30초 만에 7배)**. WSL swap 4GB 풀 → 호스트 C:\ 디스크 폭주 → 9P 마운트 hang → D-state 좀비 무더기 → load avg 56
- **frontend.log 결정 증거**: `resolve 'tailwindcss' in '.../apps'` (apps/web 아님) — Turbopack root 자동 감지 fail
- **`turbopack.root: path.resolve(__dirname)` 도 ESM 함정**: next.config.ts 가 ESM 으로 컴파일되면 `__dirname=undefined` → fallback cwd 로 잘못된 경로

## 작업

- [x] `apps/web/next.config.ts` — `fileURLToPath(import.meta.url)` 패턴으로 root 결정 (ESM-safe) + 검증 console.log
- [x] `apps/web/package.json` — `"dev": "next dev"` → `"dev": "next dev --webpack"` (Next 16 공식 fallback)
- [x] `.wslconfig` 8GB → 20GB + swap 4GB → 8GB (응급 버퍼, 근본 fix 아님). 백업 `.wslconfig.bak-20260528-031233`
- [x] `scripts/monitor_resources.sh` 신설 — 5초 sampling + 30초 호스트 rsync. D-state + 9P 마운트 + wchan 진단
- [x] `start_stack.sh` 수정 — `sleep 3` → backend `/health` 폴링 + frontend 폴링 + monitor 자동 시작
- [x] `/mnt/c/Users/mpssh/Documents/wsl_logs/` 호스트 미러 디렉토리 — freeze 후에도 외부 접근

## 검증

- [ ] webpack 모드로 frontend 단독 띄워 첫 페이지 컴파일 통과
- [ ] `./scripts/start_stack.sh` 전체 실행 후 freeze 안 나는지 확인
- [ ] resources.log / processes.log / io.log 에서 next-server VSZ < 5GB 안정 유지
- [ ] 호스트 작업관리자에서 디스크 활성 시간 < 20%, vmmemWSL < 5GB

## 의도적으로 안 한 것

- **Turbopack 자체 고치기** — 시간 더 걸리고 근본 해결 안 될 수 있음. webpack fallback 이 검증된 공식 경로
- **`build` 스크립트 변경** — dev 만 webpack 으로. 프로덕션 build 는 별도 결정
- **WSL 메모리 줄이기** — 사용자 진단 ("메모리 단독 원인 아님") 정확. 20GB 유지

## 부수 발견 (사용자 인식과 다른 흔적)

- **Node.js 4월 16일 자동 업데이트**: nvm 에 v24.14.0 (2026-03-24) + v24.15.0 (2026-04-16) 둘 다 있음. 사용자 인식엔 없지만 `nvm install 24` 등이 minor patch 자동 받았을 가능성
- **Next.js 는 처음부터 16.2.1**: apps/web 추가 시점 (2026-04-26 commit `195d486`) 부터 이미 16. 갈아끼움 작업 commit 없음 — Next 16 default 가 Turbopack 이라 자연스럽게 사용 중이었던 것

## Review

(다음 세션에서 stack 띄운 후 작성. freeze 안 나는지 검증 + 호스트 디스크 활성 시간 확인 후.)

## 학습 내용

상세는 [tasks/lessons.md](tasks/lessons.md) 2026-05-28 패턴 참고. 핵심:
- RSS 가 아닌 **VSZ** 봐야 누수 보임
- D-state + `folio_wait_bit_common` = 9P I/O hang
- 메모리 증설은 임시 버퍼, 근본 fix 아님
- Next 16 + Tailwind 4 + Turbopack 조합 위험 (현재 시점)
- ESM 컨텍스트에서 `__dirname` 함정

---

# APK 분석 웹 플랫폼 + 외부 다운로드 경고 UI (2026-06-03)

## 배경 / 현황

- 백엔드 `pipeline/apk_analyzer.py` 의 **Lv1 정적(권한조합·자체서명 인증서·패키지명 위장) + Lv2 바이트코드(SMS자동발송·접근성악용·C2 URL·난독화 등) 는 이미 실제 구현 완료.** Lv3 동적은 인터페이스만.
- 응답 스키마도 완성: `DetectionReport.to_dict()` 가 `apk_static_check`(package_name·permissions·is_self_signed) / `apk_bytecode_check` / `apk_dynamic_check` + `detected_signals[]`(detection_source=static_lv1/lv2/dynamic_lv3, 근거·출처 포함) 노출.
- runner 가 `is_apk_file(source)` 로 자동 라우팅 + Phase 0 VirusTotal 파일 스캔.
- **막힌 곳 3가지**: ① `/api/analyze-upload` 가 APK 를 ffmpeg 로 보내 실패 ② APK 다운로드 URL 받는 경로 없음 ③ 프론트 UI 전무.

## 결정 (사용자 확인 · 2026-06-03 수정)
- APK 입력: **다운로드 URL 만** — 핵심 시나리오가 "받기/설치 *전* 검사" 라 사용자가 APK 파일을 올리는 건 모순(이미 받았다는 뜻). 서버가 URL 대신 받아서(실행 X, 정적 분석만) 검사. → analyze-upload 손댈 필요 없음.
- UI 위치: **별도 전용 페이지 `/apk`**
- 차단 UI: **둘 다** — 위험 감지 시 경고 인터스티셜 + 상시 안내 가이드

## 작업 항목

### 백엔드 배선 (최소)
- [x] 2. 신규 엔드포인트 `POST /api/analyze-apk-url` (api_server_pkg/analyze.py): SSRF 가드(`_assert_safe_download_url`) + 64MB 캡 + ZIP 매직 확인 후 temp `.apk` 저장 → 기존 pipeline. middleware `_REQUIRE_KEY_PATTERNS` 에 추가. 원본 `uploads/{run_id}/source.apk` 보존.
- [x] 3. Next 프록시: `apps/web/src/app/api/analyze-apk-url/route.ts` + backend.ts `isAnalyzePath` 에 경로 추가(내부 API key 첨부).
- [x] **추가**: runner APK fast-path — APK 는 STT/분류/LLM skip, 정적 결과로 직접 보고 (빈 transcript classifier crash 회피). ⚠️ 이건 계획에 없던 latent bug 발견·수정.

### 프론트엔드 `/apk`
- [x] 4. `apps/web/src/app/apk/page.tsx` 신설 (client, URL only).
- [x] 5. 결과 렌더: 메타 카드(패키지명/인증서 배지/권한 수) + 권한 목록(위험권한 빨강) + 탐지 신호(근거/출처) + VirusTotal. 점수·등급 노출 X.

### 외부 다운로드 경고 UI (둘 다)
- [x] 6a. 상시 안내 가이드: `/apk` 상단 사이드로딩 체인 ①~⑥ 배너.
- [x] 6b. 감지 시 경고 인터스티셜: `components/install-danger-banner.tsx` (재사용 컴포넌트) — 위험 flag 검출 시 "이 앱은 설치하지 마세요" 빨강 배너.

### 테스트 + 검증
- [x] 7. `tests/test_apk_url_download.py` (11개): SSRF(non-http·loopback·사설/링크로컬 IP) + 크기 캡 + Content-Length + 빈 파일 + 정상 다운로드.
- [x] 8. 합성 APK end-to-end (`apk_static_check` 노출 확인) + `tsc --noEmit` + `eslint` 통과 + `pytest 333 passed`. (`npm run build` 는 Turbopack freeze 위험으로 미실행 — tsc+eslint 로 대체, P1 참고)

### 동적 분석 escalation (2026-06-03 추가 — 사용자 요청)
- [x] 9. runner: 정적(Lv1+Lv2) 신호 0건일 때만 `analyze_apk_dynamic` escalation (이미 잡았으면 skip). 격리 VM 있으면 실제 실행, 없으면 status=disabled/not_configured.
- [x] 10. `/apk` `DynamicEscalationCard`: 정적 깨끗 시 동적 상태 표시 — completed(행동 없음=초록/행동 있음=빨강) / 미구성=amber "동적 분석 권장" / error.
- [x] 11. `tests/test_apk_dynamic_escalation.py` (4개): 정적 깨끗→호출 / 정적 신호→skip / Lv1+Lv2 합산 게이트.
- **실제 에뮬레이터 VM 은 미구현** — escalation 배선 + UI 상태만. 로컬 실행 HARD BLOCK 유지.

### 무해한 테스트 APK 픽스처 (2026-06-03 추가 — 사용자 요청, EICAR 식)
- [x] 12. `tests/fixtures/fake_phishing_app/` — 실제 해 0 인 더미 앱 소스 (위험 코드는 전부 미호출 메서드, C2 IP 는 RFC5737 문서화 대역). manifest(위험권한 5종+접근성+device admin) + MalBehavior(SmsManager·Telephony·DevicePolicy + C2/사칭 문자열) + AccessibilityService 상속 + 200개 짧은 클래스(난독화).
- [x] 13. `build.sh` — aapt2→javac→d8→zipalign→apksigner. SDK(`~/Android/Sdk`) + portable JDK(`~/jdk21`) 자동 탐색. (이 환경엔 JRE만 있어 Temurin 21 JDK 별도 설치함.)
- [x] 14. 빌드+검증: `tests/fixtures/fake_phishing.apk` (16KB) → 탐지기가 **10개 신호 전부 발동** (Lv1 3 + Lv2 7). 전체 파이프라인 fast-path + escalation skip + 각 신호 근거/출처 확인.
- [x] 15. `tests/test_apk_fixture_signals.py` (4개): 픽스처 Lv1/Lv2/전체 파이프라인 회귀 (픽스처 없으면 skipif).

### 실제 엔드포인트 구동 데모 (2026-06-03)
- [x] 16. SSRF 가드에 dev 전용 `APK_URL_ALLOW_LOCAL=1` (기본 0) 추가 — 로컬 픽스처 테스트용. production OFF.
- [x] 17. uvicorn(VT 비활성) + `python -m http.server` 로 fake_phishing.apk 서빙 → 실제 `POST /api/analyze-apk-url` 호출 → **HTTP 200, detected_signals 10개, apk_static_check 전부 채워짐, escalation skip** 확인. (= /apk 페이지가 받는 JSON)
- [x] 18. 데모 후 서버·임시파일·데모 DB 정리 (temp 다운로드는 endpoint finally 가 자동 정리 확인).
- **발견**: VT 키가 `.env` 에 있으면 Phase 0 가 fake APK 를 업로드→악성 판정→fast-path 로 정적분석 preempt. (실제로 VT 엔진들이 우리 EICAR식 APK 를 flag 함 — 의도된 동작이지만 정적층 데모하려면 VT 끔.) ⚠️ fake APK 가 VT 에 업로드됨.

## 범위 밖 (이번 X)
- **Lv3 실제 동적분석 VM** (Android 에뮬레이터+Frida+MobSF, 별도 인프라 5~7주) — escalation 배선만 완료, 실행 stack 은 future work
- 메인 `page.tsx` 일반 분석 결과에 다운로드 경고 배너 삽입 — 컴포넌트는 재사용 가능하게 만들되 메인 통합은 후속

## Review (2026-06-03)

완료. 백엔드 분석 엔진(Lv1/Lv2 + 응답 스키마)은 이미 있었고, 막힌 건 웹 진입·UI 였음.

**변경 파일**:
- `api_server_pkg/analyze.py` — `_assert_safe_download_url`/`_download_apk` 헬퍼 + `POST /api/analyze-apk-url`
- `api_server_pkg/models.py` — `AnalyzeApkUrlRequest`
- `platform_layer/middleware.py` — require-key 패턴에 신규 경로
- `pipeline/runner.py` — APK fast-path (STT/분류/LLM skip)
- `apps/web/src/app/apk/page.tsx` (신규), `components/install-danger-banner.tsx` (신규), `api/analyze-apk-url/route.ts` (신규), `api/_lib/backend.ts` (isAnalyzePath)
- `tests/test_apk_url_download.py` (신규 11개), CLAUDE.md, lessons.md

**검증**: pytest 333 passed / tsc 0 / eslint 0 / 합성 APK end-to-end OK.

**미검증·후속**:
- 진짜 악성 APK 로 실측 (현재는 합성 ZIP 만). 실제 보이스피싱 APK 샘플로 권한·인증서·바이트코드 신호 정확도 확인 필요.
- `npm run build` 실제 통과 (Turbopack freeze 위험으로 미실행).
- 다운로드 후 androguard 파싱 자체 안전성 — 정적 분석은 실행 X 지만, androguard 가 악성 zip 에 대해 안전한지(zip bomb 등) 추가 점검 여지.

---

# V3 동적 분석 VM 구축 계획 — redroid + Frida + mitmproxy (2026-06-03)

## 결정 (사용자 확인)
- 에뮬레이터: **redroid** (Android-in-Docker)
- 범위: 런타임 flag **5종 전부**
- 네트워크: **mitmproxy 경유** (트래픽 기록 + 위험 목적지 선택 차단)
- 호스트: **Multipass Ubuntu VM** (아래 실측 근거)

## WSL2 Docker 가능성 — 실측 (2026-06-03)
- `/dev/binder` 없음 · `CONFIG_ANDROID_BINDER_IPC is not set` · binder_linux 모듈 없음 · docker 미설치
- redroid = 컨테이너 Android (KVM 불필요) 지만 **host 커널 binder/ashmem 필수** → WSL2 기본 커널은 binder OFF → **불가**
- 함정 2개: (1) 커널 — 켜려면 커스텀 WSL2 커널 빌드+.wslconfig (P1 freeze 환경, 비권장) (2) 격리 — dev WSL2에서 실제 악성코드 = repo·.env·/mnt/c 노출 (HARD BLOCK 위반)
- → **Multipass Ubuntu VM**: 자체 커널(binder 모듈 apt 제공) + /mnt/c 없음 → dev·real 둘 다 안전

## 2-tier 안전 정책
- **DEV (지금)**: docker 스택을 VM에 올려 **안전 샘플만**(fake_phishing.apk + DroidBench)으로 5 flag 로직 검증. 악성 0 → 위험 0.
- **REAL (나중)**: 같은 compose에 CICMalDroid/CICAndMal2017(PCAP) 실제 샘플. 같은 격리 VM(dev 데이터 없음) + firewall + 스냅샷 복원.

## 아키텍처 (sandbox_server/ 패턴 미러 — 이미 배선됨)
- production: `analyze_apk_dynamic` → `_analyze_apk_dynamic_remote` → `POST {APK_DYNAMIC_REMOTE_URL}/dynamic-analyze` (files=apk, Bearer) → `{detected_flags[], observations{}}`. 서버가 flag를 DETECTED_FLAGS로 검증. (호출부 완성, 서버만 만들면 됨)
- 신규 `apk_dynamic_server/`:
  - `app.py` — FastAPI: `POST /dynamic-analyze`(APK→redroid 설치→시나리오→Frida+mitmproxy 수집→5 flag 매핑→JSON) + `GET /health`. Bearer. stateless(분석 후 APK 삭제 + 스냅샷 복원).
  - `docker-compose.yml` — redroid + analyzer + mitmproxy
  - `README.md` — Multipass VM 구축(binder 모듈 포함) + 배포

## Docker 스택 (compose 3 컨테이너)
1. **redroid** (`redroid/redroid:13.0.0-latest`, x86_64) — ADB 노출. VM에서 `modprobe binder_linux ashmem_linux`.
2. **analyzer** — Python: adb-client + frida-tools + 시나리오 드라이버 + FastAPI(app.py). frida-server를 redroid에 push.
3. **mitmproxy** — redroid 트래픽 경유 + CA를 /system store 설치(redroid는 rw /system). flow 로그 → C2 탐지.

## 5개 flag 구현 매핑
| flag | 탐지 방법 | 자극(stimulation) |
|---|---|---|
| apk_runtime_c2_network_call | mitmproxy flow → IP직접/무료TLD/비표준포트/known-bad + Frida(OkHttp/Socket/URLConnection) | 앱 실행 후 대기 |
| apk_runtime_sms_intercepted | Frida: SmsManager.sendTextMessage + SMS_RECEIVED receiver abort/forward | `adb emu sms send` |
| apk_runtime_overlay_attack | Frida: WindowManager.addView TYPE_APPLICATION_OVERLAY | 다른 앱 포그라운드 시뮬 |
| apk_runtime_credential_exfiltration | Frida taint: getDeviceId/AccountManager/clipboard → network sink (mitmproxy 상관) | 가짜 자격증명 입력 |
| apk_runtime_persistence_install | Frida: BOOT_COMPLETED 등록 + DevicePolicyManager.setActiveAdmin | `adb reboot` 시뮬 |

## 시나리오 드라이버
install → grant/deny perms → launch → (SMS 주입 / call state / 가짜 자격증명 입력 / reboot 시뮬) → 수집 대기 → uninstall → 스냅샷 복원

## 격리·안전 컨트롤
- VM: /mnt/c 마운트 X · production DB/키 X · inbound는 production IP만(firewall) · 분석 후 APK 삭제 · redroid 스냅샷 매 분석 복원
- mitmproxy egress: 기록 + 위험 목적지 선택 차단 (REAL 단계는 통제 egress 필수)
- production은 `APK_DYNAMIC_BACKEND=remote` + REMOTE_URL/TOKEN 있을 때만 호출 (로컬 HARD BLOCK 유지)

## 단계별 빌드
- [x] Phase 0 (2026-06-03 완료): Multipass VM `sg-sandbox`(22.04, 4cpu/6G/30G) + `linux-modules-extra-5.15.0-179-generic` → binderfs(`/dev/binderfs/{binder,hwbinder,vndbinder}`) + ashmem 로드, fstab/modules-load 영속화 + Docker(get.docker.com). `redroid/redroid:13.0.0-latest` 단독 부팅 → `adb connect localhost:5555` → `sys.boot_completed=1`, abi `x86_64`, `adb shell` 진입 확인. 컨테이너명 `redroid`, 720×1280.
- [x] Phase 1 (2026-06-03): frida-tools 17.10.1 설치 + 버전 일치 frida-server x86_64 push → `adb root` → frida-server 기동 → `frida-ps -U` 가 redroid 안 앱 목록 검출 = 런타임 후킹 검증 완료.
- [x] Phase 2~4 코드 작성 (2026-06-03, VM 검증 대기): `apk_dynamic_server/` 신설 —
      `app.py`(FastAPI: Bearer + multipart `/dynamic-analyze` + `/health`, stateless),
      `analyzer.py`(adb install -g → frida spawn+hooks → 관찰 → uninstall, 패키지 diff/pyaxmlparser fallback),
      `frida_hooks.js`(5 flag 후킹: SMS·overlay·persistence·식별자 taint·Socket/URL 네트워크 sink),
      `requirements.txt`, `README.md`(VM 부트스트랩+배포+검증). production 계약 그대로
      `{detected_flags[], observations}` 반환, VALID_FLAGS(5종)로 검증.
      **설계 변경**: 기존 `fake_phishing.apk` 는 dead-code(정적 전용) → 동적은 0 flag. 그래서
      행동을 실제 실행하는 **active fixture** 신설 — `tests/fixtures/dynamic_active_app/`
      (MainActivity 가 launch 시 RFC5737 비라우팅 IP로 C2 소켓·식별자→유출·SMS·오버레이·persistence 5행동 실행).
      `dynamic_active_app/build.sh` 로 `dynamic_active.apk` 빌드 (fake_phishing 툴체인 동일).
      mitmproxy egress 캡처는 REAL 단계로 이관(README) — DEV 는 frida 소켓 후킹으로 C2 검출.
- [x] Phase 2~4 **VM 검증 완료 (2026-06-03)**: VM에 `apk_dynamic_server/` 배포 → `python3 app.py` →
      active fixture `/dynamic-analyze` → **detected_flags 5종 전부 검출** (c2_network_call·
      credential_exfiltration·overlay_attack·persistence_install·sms_intercepted), HTTP 200.
      fake_phishing.apk(dead-code) → `[]` 음성 대조 확인. frida_mode=attach, event_count 정상.
      **디버깅 4건** (lessons.md 패턴 9~12 + 아래 Review):
      ① frida 17 은 내장 `Java` 브리지 제거 → 16.x 핀 (CLI 는 자동주입돼 함정).
      ② `device.spawn(pkg)` 문자열로 (리스트는 네이티브 argv).
      ③ redroid spawn 게이팅 타임아웃 → `am start`+attach fallback + 루프 fixture.
      ④ frida hook 에서 서브클래스 필드는 `Java.cast` 필요 (`addView` 의 ViewGroup.LayoutParams→WindowManager.LayoutParams).
- [ ] Phase 5: production `_analyze_apk_dynamic_remote` 확정 + tests + escalation E2E(정적 깨끗→동적→UI 표시).
- [ ] Phase 6: 격리 하드닝 + REAL 샘플(CICMalDroid 신청) 검증.

## 리스크/미정
- Ubuntu 커널 binder 모듈: `linux-modules-extra-$(uname -r)` 설치 필요할 수 있음.
- redroid x86 이미지 ↔ ARM-only 네이티브 lib 악성코드 호환(houdini ARM translation 필요할 수 있음 — REAL 단계).
- Frida-server 버전 ↔ redroid Android 버전 매칭.
- mitmproxy system CA 설치 (Android 7+ user CA 무시 → /system 필요, redroid OK).
- REAL egress 정책 — 실제 C2 통신 통제 필수.

## 범위/규모
- DEV(Phase 0~5): 안전 샘플로 5 flag 로직 — 2~3주 추정.
- REAL(Phase 6): 데이터셋 신청+격리 하드닝 별도. 전체 5~7주(CLAUDE.md future work 추정과 일치).

## Review — Phase 0~4 (2026-06-03, DEV stack 동작 검증 완료)

**무엇**: WSL2 binder 부재 → Multipass VM(`sg-sandbox`, Ubuntu 22.04) → redroid 13 →
frida 16.x → `apk_dynamic_server/`(FastAPI+analyzer+frida_hooks) 로 5개 런타임 flag 를
실제 후킹으로 검출하는 동적 분석 stack 을 처음부터 끝까지 동작시킴.

**검증** (VM `sg-sandbox`):
- active fixture(`dynamic_active.apk`, RFC5737 비라우팅 행동 5종 실행) → `/dynamic-analyze`
  → `detected_flags` 5종 전부, HTTP 200, frida_mode=attach.
- fake_phishing.apk(정적 dead-code) → `detected_flags: []` (음성 대조 — 행동 없으면 깨끗).

**디버깅 여정** (각 단계 자가진단 마커를 응답에 실어 원인 특정):
1. spawn 리스트 인자 → 엉뚱한 프로세스 spawn, Java 안 올라옴 → 문자열로 수정.
2. frida 17 `Java` 미정의(ReferenceError) → 17 이 코어 브리지 제거 → 16.x 핀(server+python).
3. redroid spawn 게이팅 TimedOutError → `am start`+attach fallback + 루프 fixture(늦은 attach 대비).
4. overlay 만 누락 → hook 은 설치됐으나 `addView(View, ViewGroup.LayoutParams)` 의 params 에
   `.type` 직접 접근 실패 → `Java.cast(params, WindowManager$LayoutParams)` 로 해결.

**남은 것 (Phase 5~6)**:
- [ ] Phase 5: production `_analyze_apk_dynamic_remote` 확정(현재 stub) + `.env`에 REMOTE_URL/TOKEN
      → runner escalation(정적 0건→동적) E2E + UI(`DynamicEscalationCard`) 표시 + tests.
- [ ] Phase 5(속도): spawn-first 가 redroid 에서 항상 ~20s 타임아웃 후 attach fallback → 매 분석
      20s 낭비. attach-first 로 뒤집거나 spawn 타임아웃 단축 검토.
- [ ] Phase 6: mitmproxy egress 통합(REAL C2 캡처/차단) + 스냅샷 복원 + 격리 하드닝 + CICMalDroid 실샘플.

## 환경 정리 계획 (Phase 5 전 — 2026-06-03)

지금은 손으로 쌓은 임시 상태(포그라운드 프로세스 + 수동 명령 + dev 토큰). 재부팅 생존 +
production 호출 가능한 재현 가능 배포로 전환. 5 버킷:

1. **VM 서비스화 (재부팅 생존)**
   - [ ] redroid `--restart unless-stopped` 로 재생성 (binderfs/모듈은 fstab/modules-load 로 이미 영속)
   - [ ] `apk-frida.service` — redroid 부팅 후 frida-server push+실행 (setsid 대체)
   - [ ] `apk-dynamic.service` — `python3 app.py`, `Restart=always`, 토큰은 `EnvironmentFile`
   - [ ] 산출물: `apk_dynamic_server/deploy/` (systemd 유닛 2개 + 설치 스크립트)
2. **네트워크 (production WSL → VM) — 가장 까다로움**
   - WSL2 는 Multipass 내부망에 직접 못 닿음 → Windows 호스트를 다리로 netsh portproxy
     `netsh interface portproxy add v4tov4 listenport=8002 connectaddress=<VM-IP> connectport=8002`
   - [ ] production 은 `http://<Windows호스트IP>:8002` 로 도달 (WSL `ip route` 게이트웨이)
   - ⚠️ portproxy 는 WSL 재시작·VM IP 변동마다 깨질 수 있음 — Phase 5 의 주 변수
3. **시크릿** — `dev-secret-123` 폐기. `secrets.token_urlsafe(32)` → VM `EnvironmentFile` +
   production `.env` 같은 값. git X, `.env.example` 엔 placeholder
4. **production .env (repo)** — `APK_DYNAMIC_ENABLED=1`/`BACKEND=remote`/`REMOTE_URL`/`REMOTE_TOKEN`
   4줄 + `.env.example`/CLAUDE.md 환경변수표 갱신
5. **cruft 정리 + 재현성** — VM frida-server `.xz` 중복 삭제, 스테이징 폴더 정리,
   `apk_dynamic_server/bootstrap.sh`(README 수동단계 자동화) + `deploy.sh`(코드만 transfer)

**권고**: 1·3·4·5 는 일회성 깔끔. 2(네트워크)가 변수 → Phase 5 를 풀로(production→VM 실호출)
갈지, 일단 1+5(서비스화+재현)만 하고 네트워크 안정 시 연결할지 선택.
