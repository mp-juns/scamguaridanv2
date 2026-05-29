# Project Analysis Refresh — 2026-05-29

목적: 현재 워크트리 기준으로 ScamGuardian 의 구조, 진행 중 변경, 실행/로그 상태, 우선 리스크를 다시 진단한다.

- [x] 저장소 구조와 기존 교훈/작업 기록 확인
- [x] 백엔드/API 진입점과 파이프라인 현재 흐름 확인
- [x] 프론트엔드/API proxy 및 새 live/stream 경로 확인
- [x] 현재 로그에서 실행 상태와 대표 오류 확인
- [x] 테스트/빌드/문서 정합성 확인
- [x] 주요 강점, 리스크, 다음 개선 우선순위 정리

## Review

**요약**: `api_server.py` 는 여전히 얇은 FastAPI entrypoint 이고, 실제 앱 조립은
`api_server_pkg.app.create_app()` 에서 라우터 단위로 관리된다. 핵심 검출 흐름은
`pipeline.runner.ScamGuardianPipeline` 이 Phase 0/0.5/0.6/1/1.5~5 를 오케스트레이션하며,
외부 응답은 `DetectionReport.detected_signals[]` 중심으로 점수·등급 없는 schema 를 유지한다.
최근 작업의 중심은 CLOVA STT + audio diarization, `/api/transcribe-upload`, `/api/analyze-stream`,
Next `/live` 페이지다.

**현재 워크트리**:
- 기존 수정/추가 파일이 많다. 주요 축: `pipeline/stt.py` CLOVA 백엔드/환각 완화,
  `api_server_pkg/transcribe.py` STT-only endpoint, `api_server_pkg/stream_analyze.py`
  청크 NDJSON 분석, `apps/web/src/app/live/*` 라이브 업로드 UI.
- `tasks/todo.md` 는 이번 분석 기록 때문에 추가 수정됨. 그 외 변경은 기존 작업분으로 보이며 건드리지 않았다.

**로그 관찰**:
- `.scamguardian/logs/clova-kyy.log` 기준 CLOVA 는 60초 청크를 약 3.6~4.1초에 처리했고,
  `segments` 와 `turns` 를 정상 생성했다.
- `.scamguardian/logs/backend.log` 는 13:26 전후까지 admin/training API 200 응답이 반복되어
  backend 가 정상 처리한 흔적이 있다.
- `.scamguardian/logs/backend-kyy.log` 는 8001 서버가 워밍업 후 shutdown 된 기록이 있어
  kyy 전용 stack 은 재확인이 필요하다. sandbox 제한으로 현재 host process/port 는 직접 확인하지 못했다.
- `cloudflared-kyy.log` 는 quick tunnel 생성 성공. 단 quick tunnel 은 uptime 보장이 없으므로 시연용으로만 적합.

**검증**:
- `timeout 60s pytest tests/test_detection_report_schema.py tests/test_result_content_type.py tests/test_gate.py tests/test_stage2_routing.py -q`
  → 59 passed.
- `npm run lint` (`apps/web`) → 실패. `react/no-unescaped-entities` 14 errors
  (`admin/training/about/page.tsx`, `live/LiveVoiceUpload.tsx`) + unused warning 2개
  (`admin/stats/page.tsx`).

**리스크**:
- Identity Boundary 위반 잔여: `apps/web/src/app/methodology/page.tsx` 는 아직 점수·등급 산정 방식 페이지이고,
  `apps/web/src/app/live/page.tsx`, `pipeline/kakao_formatter.py`, 일부 metadata 는 "차단/위험도/점수" 표현이 남아 있다.
- `/live` 는 클라이언트 regex alert 를 쓰며 `level`/경보 표현을 노출한다. 제품 의도상 실시간 경고는 필요하지만,
  "판정" 이 아니라 "검출된 통화 신호" 로 문구를 정렬해야 한다.
- `SCAMGUARDIAN_INTERNAL_API_KEY` 가 없으면 Next proxy 의 `/api/transcribe-upload`,
  `/api/analyze-stream`, `/api/analyze-upload` 는 백엔드 `PlatformMiddleware` 에서 401 이 난다.
- README 의 `pytest # 114 passed` 는 현재 테스트 수와 맞지 않는다.

**다음 우선순위**:
1. 프론트 lint 14 errors 를 먼저 정리해 build gate 를 회복.
2. `/methodology` 를 점수 산정 페이지에서 신호 근거 페이지로 전환하거나 route 를 숨김.
3. `/live` 와 카카오 문구를 "위험 신호 검출" 언어로 재정렬하고 `score_delta`/`triggered_flags` compatibility 타입을 단계적으로 걷어냄.
4. kyy stack 재기동 스크립트로 backend/frontend/cloudflared 실제 포트 상태를 검증.

---

# Project Analysis — 2026-05-28

목적: 현재 ScamGuardian 코드베이스의 구조, 핵심 흐름, 실행 가능성, 리스크를 빠르게 진단한다.

- [x] 저장소 구조와 기존 교훈/작업 기록 확인
- [x] 백엔드/API 진입점과 파이프라인 흐름 확인
- [x] 프론트엔드/API proxy 구조 확인
- [x] 테스트/빌드/의존성 상태 확인
- [x] 주요 강점, 리스크, 다음 개선 우선순위 정리

## Review

**요약**: FastAPI 진입점은 `api_server.py` → `api_server_pkg.app.create_app()` 로 잘 분리되어 있고,
핵심 분석은 `pipeline.runner.ScamGuardianPipeline` 이 Phase 0/0.5/0.6/1/1.5~5 를 오케스트레이션한다.
외부 응답은 `pipeline.signal_detector.DetectionReport` 중심으로 점수·등급 없이 `detected_signals[]` 를 노출하는
Identity Boundary 를 대체로 잘 지킨다. Next.js 는 `apps/web/src/app/api/_lib/backend.ts` 의 thin proxy 구조다.

**검증**:
- `timeout 45s pytest tests/test_detection_report_schema.py tests/test_gate.py tests/test_stage2_routing.py tests/test_signal_detection.py -q`
  → 57 passed.
- `npm run lint` (`apps/web`) → 실패. `react/no-unescaped-entities` 14 errors, unused warnings 2개.
- 전체 `pytest -q` 는 322개 수집 후 `tests/test_admin_auth.py` 구간에서 출력 없이 장시간 대기해 중단 판단. 별도 원인 확인 필요.

**리스크**:
- 프론트 lint 가 깨져 CI/build gate 로 쓰기 어렵다.
- README 의 테스트 수(114 passed) 와 현재 수집 수(322 items)가 맞지 않아 문서 갱신 필요.
- 작업 트리에 기존 수정/추가 파일이 많아 변경 전 소유권 확인이 필요하다.

---

# PHH Data Fine-Tuning Check — 2026-05-29

목적: 상위 폴더 `scamguardian-v2-phh/data` 에 기존 학습 데이터/파인튜닝 산출물이 있는지 확인하고,
현재 kyy 프로젝트의 training 파이프라인으로 재사용 가능한지 검증한다.

- [x] sibling `scamguardian-v2-phh/data` 구조와 JSONL/checkpoint/metric 파일 확인
- [x] 현재 training 로더가 읽을 수 있는 포맷인지 dry-run/stat 으로 검증
- [x] 데이터가 충분하고 의존성이 준비되어 있으면 classifier LoRA fine-tuning 실행
- [x] 기존 fine-tuned/benchmark 산출물 존재 여부와 실행 결과 정리

## Review

- PHH `data` 에서 `generated_data/scamguardianv2_manual_diverse_synthetic_nodup_2026-05-27.jsonl`, `processed/user_samples_2026-05-26.jsonl`, `run_drafts.reviewed.jsonl` 확인.
- 세 JSONL을 `.scamguardian/phh_training/phh_combined_classifier_20260529.jsonl` 로 병합: 310 rows, dedupe skip 1.
- training 로더 기준 전체 content gate 335 examples, scam_type classifier 182 examples. `min_per_class=5` 적용 후 9개 유형 172 examples 사용.
- PHH 기존 `checkpoints/classifier-v1` 는 LoRA adapter 형태이며 `active_models.json` 에 호환성 오류로 비활성화 기록 있음.
- 학습 중 발견한 호환성 수정:
  - `Trainer(tokenizer=...)` → `Trainer(processing_class=...)`
  - LoRA+FP16 gradient unscale 오류 회피를 위해 `fp16=False`
  - LoRA 산출물은 adapter와 merged full model을 함께 저장하도록 수정
- 최종 산출물: `.scamguardian/phh_training/classifier-lora-merged-20260529`
  - train=158, val=14, epochs=3, LoRA trainable params 2,685,705 / total 281,501,970 (0.9541%)
  - eval_accuracy=0.142857, eval_macro_f1=0.040404
  - `AutoModelForSequenceClassification` 로 9개 한국어 scam_type label 로드 확인
  - 품질이 낮아 운영 활성화는 보류 권장

---

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

**다음**: Stage 2 (multi-label 라우팅) / Stage 3 (신호 그룹핑).

## Stage 2 — 사기 유형 multi-label 라우팅

- [ ] `runner.py` — extractor 에 단일 `scam_type` 대신 임계값 넘는 **상위 N개 유형의 라벨셋 합집합** 전달
      (`classifier.classify()` 는 `all_scores` 이미 반환 / `extractor.extract()` 는 `labels` 인자 이미 있음)
- [ ] 표면 `scam_type` 은 top-1 유지 (context 용, 노출 schema 불변)
- [ ] `config.py` — "기타 사기" 유형 + 라벨셋 추가

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
- [ ] 합성 발화로 게이트 5-bucket 정확도 (특히 사기 뉴스/교육 vs 사기 시도 혼동률)
- [ ] 복합 스캠 텍스트로 multi-label 합집합 → 엔티티 recall 개선 측정
- [ ] `tests/test_gate.py` 신설 + 기존 pytest 93개 회귀 없음

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
