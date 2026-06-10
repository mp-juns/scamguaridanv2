# TODO — 게이트(content_label) 학습·증강·시각화 웹 연결 (2026-06-10)

## 목표
게이트 파트가 웹에서 컨트롤이 안 됨 → **기존 코드를 웹에 배선만** 한다.
**절대 새 학습/증강 알고리즘 코드를 만들지 않는다** — 기존 `content_label_gate.py`,
`run_augment_session.py`/`_augment_seed` 를 그대로 호출하고, 필터/통계/UI/시각화만 추가.

3가지: (1) 게이트 모델 학습을 파인튜닝 세션에서 시작 가능하게 (2) 게이트 전용
content_label 데이터 증강을 증강 섹션에 (3) 게이트 전용 데이터+모델 시각화.

## 발견한 갭 (근거)
- `sessions.py` `ALLOWED_MODELS=(classifier,gliner)` → 게이트 시작 경로 없음.
  `content_label_gate.py --train` CLI 전용, 끝나면 `record_gate_session` 자가 등록만.
- `_watch_process`(sessions.py:535) 가 종료 시 `last_metrics` 를 슬림 `gate_eval` 행으로
  덮어씀 → confusion/per_class **유실** (시각화 불가). gate 가드 필요.
- `admin_augment._compute_seed_stats`(L54) 는 `content_label==scam_attempt` 만 집계 →
  normal/scam_news_edu HN 안 보임. `_append_seed`(L106) scam_type 필수 → normal 추가 불가.
- `run_augment_session._load_seeds`(L44) scam_type 필터만 → content_label 타깃 증강 불가.

## Part A — 게이트 학습을 파인튜닝 세션에 연결
- [x] A1. `sessions.py` `start_session` 에 `model=="gate"` 분기 (content_label_gate.py --train
      --session-id/--epochs/--val-ratio/--seed/--input 호출, kind="gate" 기록).
- [x] A1b. `_watch_process`: 기존 `kind=="gate"` 면 `last_metrics` 덮어쓰지 않음(가드).
- [x] A2. `admin_training.py` `POST /sessions` 에서 `model=="gate"` 단일 세션 허용.
- [x] A3. `TrainingClient.tsx` "게이트 학습" 전용 패널(epochs/val_ratio/input + 시작 버튼).

## Part B — 게이트 전용 데이터 증강 (content_label)
- [x] B1. `run_augment_session._load_seeds` 에 `--content-label` 필터 추가(scam_type 필터 미러).
- [x] B2. `augment_sessions.AugmentParams` 에 `content_label` + 인자 전달.
- [x] B3. `models.py`: `AugmentStartRequest.content_label` 추가, `SeedCreateRequest.scam_type` 옵션화.
- [x] B4. `admin_augment.py`: augment_start content_label 전달 / `_append_seed` normal 허용 /
      `_compute_seed_stats` `by_content_label` 추가.
- [x] B5. `AugmentClient.tsx`: 씨앗 폼 scam_type 옵션화 + 증강 폼 content_label 필터.

## Part C — 게이트 전용 시각화
- [x] C1. augment 페이지: content_label 3-class 커버리지 바.
- [x] C2. training 페이지(gate 세션): confusion 히트맵 + per-class P/R/F1 + watch_cells 콜아웃.
- [x] C3. `charts.tsx`: ConfusionMatrix / GatePerClassBar 컴포넌트.

## 검증
- [x] V1. `SCAMGUARDIAN_AUGMENT_FAKE=1` content_label 필터 증강(비용 0).
- [x] V2. 웹에서 게이트 학습 시작 → 완료 후 confusion 보존(가드).
- [x] V3. `npm run lint`+`build`, 영향 `pytest`.
- [x] V4. classifier/gliner/scam_type 증강 회귀 없음.

## Review (완료 2026-06-10)

**기존 코드 배선만 — 새 학습/증강 알고리즘 0줄.** 변경 파일:

Backend
- `training/sessions.py` — `start_session` gate 분기(content_label_gate.py --train 호출),
  ALLOWED 에 gate, `_watch_process` 가드(kind==gate 면 last_metrics 보존).
- `api_server_pkg/admin_training.py` — POST /sessions 문서에 gate 명시(핸들러는 제네릭해서 그대로 동작).
- `scripts/run_augment_session.py` — `_load_seeds` 에 `--content-label` 필터(scam_type 필터 미러).
- `training/augment_sessions.py` — `AugmentParams.content_label` + 인자 전달.
- `api_server_pkg/models.py` — `AugmentStartRequest.content_label`, `SeedCreateRequest.scam_type` 옵션화.
- `api_server_pkg/admin_augment.py` — content_label 전달 / normal 씨앗 허용 / `by_content_label` 통계.

Frontend
- `apps/web/.../admin/charts.tsx` — `GatePerClassBar` 추가.
- `apps/web/.../training/TrainingClient.tsx` — 게이트 학습 패널(+게이트/분류기/추출기 역할 카드),
  `GateMetricsPanel`(confusion 히트맵 + per-class 막대 + watch_cells 콜아웃).
- `apps/web/.../augment/AugmentClient.tsx` — content_label 커버리지 바 + 게이트 클래스 필터 + normal 씨앗 폼.

검증: lint OK / build OK / pytest 398 passed / FAKE 증강 normal 144건 필터 OK /
gate 세션 wiring+가드 PASS(confusion·macro_f1·watch_cells 보존).

미실행(무거움): 실제 게이트 학습 1회(웹에서 시작 → GPU 수분). 배선·데이터 흐름은 검증 완료.

---

# 6-class scam_category 실험 (증강·summary 후 진행) — 2026-06-08

## 매핑 (12 scam_type → 6 scam_category)
- 링크·문자 유도형 ← 스미싱
- 기관·금융 사칭형 ← 기관 사칭, 대출 사기
- 투자·가상자산형 ← 투자 사기, 코인 사기
- 관계·지인 사칭형 ← 로맨스 스캠, 메신저 피싱
- 거래·취업형 ← 중고거래 사기, 취업·알바 사기
- 기타·특수형 ← 부동산 사기, 건강식품 사기, 납치·협박형

## 설계 결정 (공정 비교)
- **별도 변환 데이터셋** `data/generated/user_samples_augmented.category.jsonl` 생성 (원본 그대로 유지).
- 비교는 **동일 데이터·동일 분할(seed17,val0.1)·동일 hparam(mDeBERTa LoRA ep10 bs7)** 로 12-class vs 6-class, 라벨 granularity만 차이.
- ⚠️ DB(25건, 12-class 라벨) 혼입 시 6-class 라벨공간 오염 → 실험은 **jsonl-only 통제** (양쪽 동일 조건). 기타·특수형은 jsonl 에 0건일 수 있음(부동산/건강식품/납치는 DB만) → 실제론 5-class 분포 가능. 보고 시 명시.
- 산출물 세션: `.scamguardian/training_sessions/cat6_exp_*`, `.../cls12_jsononly_*` (active_models 미적용).

## Plan
- [ ] 1. 증강(bp0uecatf) 완료 + dataset_summary 보고 (선행)
- [ ] 2. `scripts/make_category_dataset.py` — scam_type→category 변환 jsonl
- [ ] 3. 통제 실험 하네스 — jsonl-only, 12-class & 6-class 동일조건 학습
- [ ] 4. `eval_classifier` 확장 — acc/macro_f1/per-label P·R·F1/confusion (양쪽)
- [ ] 5. 비교 보고 + (6-class 더 안정적이면) UI 제안: scam_category 주표시 + scam_type 세부후보
- [ ] active_models 미변경 / push 금지

## Review (6-class 실험)
- 변환셋 `user_samples_augmented.category.jsonl` 생성(0.29s, LLM 0). 원본 보존.
- jsonl-only 통제(빈 DB) 12-class vs 6-class 동일조건 학습:
  - 12-class(9라벨): acc 0.899 / macro_f1 **0.895** (최저 투자 0.773, 투자↔코인 혼동)
  - 6-class(5라벨): acc 0.962 / macro_f1 **0.962** (전 카테고리 F1≥0.93)
- ⚠️ seed-level 누수(변형 단위 split) → 수치 낙관적. 진짜 일반화는 seed-group split 필요.
- ⚠️ 기타·특수형 0건(DB만) → 실제 5-class.
- UI 제안: scam_category 주표시 + scam_type(scam_type_detail 보존) 세부 후보. 12-class 모델 옵션 유지.
- active_models 미변경, push 없음.

## Review (증강 병렬화)
- `scripts/augment_seeds_concurrent.py` 신규 — concurrency(기본4,최대8) 병렬 생성 → worker는 파일 직접 안 씀(메모리/temp) → 일괄 스키마검증+text dedup → **단일 append** → 실패 seed retry(기본2). deficit-aware 유지.
- FAKE 검증: 49 seed 병렬 +245 단일 append, 원본 불변, 스키마/중복 0. ✓
- 미실행(실데이터): 현재 52 seed 모두 20 충족이라 신규 증강 대상 없음 — 차기 seed 배치용.

---

# synthetic seed 반영 + 증강 (학습 대기) — 2026-06-07

## Plan
- [ ] 1. draft 검증 → `pending_admin_draft_seeds.jsonl`(32) → `admin_seeds.jsonl` append (신규 생성).
- [ ] 2. append 전후 검증: JSON 파싱 / 중복 text / 중복 source_ref / scam_type 유효성.
- [ ] 3. `scripts/augment_seeds.py` — 신규 32 seed만 × 20변형 (batch5/max_tokens8192, 기존 출력과 dedup).
- [ ] 4. `user_samples_augmented.jsonl` 에 append (덮어쓰기 금지). 2280 → ~2920 예상.
- [ ] 5. `python -m training.dataset_summary --extra-jsonl ...` → content_label/sample_kind/scam_type 분포 보고.
- [ ] 6. 학습 미실행 (분포 확인 후 대기). active_models 변경·push 금지.

## Review
(작업 후)

---

# Classifier(mDeBERTa) 재학습 — top-up 데이터 — 2026-06-07

## 배경·조건
- 대상: `data/generated/user_samples_augmented.jsonl` (2280건). classifier 는 `content_label==scam_attempt` 1340건(9유형)만 사용.
- 비교 대상 `110256ac407a`: **같은 파일의 top-up 이전(2188)** 으로 학습됨. 기록치 eval_acc **0.435** / macro_f1 **0.177** (메모리의 그 0.177).
- top-up 이 classifier 클래스에 추가한 것: **로맨스 +20, 취업·알바 +5** 뿐 (나머지 67건 normal=미사용). **코인·투자는 +0** → 개선 기대 못 함(정직하게 보고).
- 조건: classifier(mDeBERTa)만 / GLiNER X / active_models.json 미적용 / per-label P·R·F1 + confusion matrix 보고 / 110256ac407a 비교 / push X / 로컬.

## Plan
- [x] 1. 동일 설정 재학습 (GPU RTX 5070 Ti, early stopping@epoch2). 출력 `.scamguardian/training_sessions/topup_retrain_20260607/output`. active_models 미적용(classifier 현재 disabled 상태 유지).
- [x] 2. `scripts/eval_classifier.py` — 동일 분할 재현 + per-label + confusion + LoRA 로드.
- [x] 3. 신모델 own-val: acc 0.4403 / macro_f1 0.2705 (val 134건).
- [x] 4. 110256ac407a 비교 — 기록 own-val acc0.435/mf1 0.177 / 동일 NEW-val 재평가 acc0.448/mf1 0.265(부분 누수).
- [x] 5. 취업·알바/코인/투자 확인.

## Review
- 신모델 own-val macro_f1 **0.2705** vs baseline 기록 **0.177**. 단 **동일 val(134건) 직접비교는 0.2705 vs 0.2648 — 사실상 동률**(옛 모델은 부분 누수로 과대평가됨). → top-up 으로 의미 있는 개선 없음.
- 원인: top-up 이 classifier 클래스에 추가한 건 로맨스 +20·취업 +5뿐, **코인·투자 +0**. 두 모델 모두 **코인 F1 0.000(val 4건)·투자 F1 0.000(val 6건)** — 소수 클래스가 스미싱(44)·기관사칭(24)으로 붕괴.
- 취업·알바 F1 0.667 이지만 **val 2건** — 통계적으로 무의미.
- 학습 매우 불안정(loss 149→20→4, epoch별 macro_f1 0.07→0.27→0.20→0.23) — LoRA+lr2e-5+심한 불균형. per-label 차이(로맨스 NEW0.0 vs OLD0.47 등)는 대부분 노이즈.
- 신규: `scripts/eval_classifier.py`, `scripts/topup_augment.py`. active_models 미변경, push 안 함.
- 권고: ① 코인·투자·중고·로맨스 **실물 시드 자체를 늘려** 증강(같은 시드 패러프레이즈는 다양성 한계) ② class weight / focal loss / 오버샘플링 ③ val_ratio↑ 또는 k-fold (현재 소수 클래스 val 2~6건은 평가 신뢰 불가).

---

# user_samples_augmented 미달 씨앗 top-up — 2026-06-07

## 배경
- `data/generated/user_samples_augmented.jsonl` (2188건, 고유 씨앗 114개) 증강이 불균등하게 중단됨.
- 씨앗 파일(`data/processed/admin_seeds.jsonl`)은 이 base 워크스페이스에 없음 — 출력의 `seed_text`로 복원.
- 목표: **미달 씨앗만 20변형까지** 채움 (18개 씨앗 / +92건). 균등 씨앗(20변형)은 건드리지 않음.

## Plan
- [x] 1. `scripts/topup_augment.py` — 기존 `_augment_seed`/`_get_client` 재사용. 출력에서 씨앗 복원 + per-seed deficit(목표-현재) 계산 → 부족분만 생성. 기존 텍스트 dedup 후 --append. FAKE 모드 지원.
- [x] 2. FAKE 모드 복사본 검증 — 18씨앗 +92건, 전부 20도달 / 중복 0 / 스키마 일치 확인.
- [x] 3. 실제 Claude 호출로 `user_samples_augmented.jsonl` 에 append (2188→2280).
- [x] 4. 최종 검증 — 114씨앗 전부 20변형, 총 2280건, 중복 0, 스키마 누락 0.

## Review
- `scripts/topup_augment.py` 신규 + `scripts/augment_user_samples.py` 의 `_augment_seed` 에 `max_tokens` 파라미터 추가(기본 4096 하위호환).
- 결과: `data/generated/user_samples_augmented.jsonl` 2188 → **2280건**, 고유 씨앗 114개 전부 20변형 도달.
- **버그 발견·수정**: 긴 씨앗(채용공고·뉴스·교육문)에 변형을 한 번에 多 요청하니 출력이 `max_tokens=4096` 초과로 JSON 잘려 `variants=0` → 5개 씨앗이 계속 +0. 원인은 `stop_reason=max_tokens`. 호출당 배치 5로 제한 + max_tokens 8192 로 해소.
- 라벨 분포: scam_attempt 1340 / normal 620 / scam_news_edu 320. scam_type 은 스미싱 440·기관사칭 240·대출 200·로맨스 140·메신저 100·중고거래 100·투자 60·코인 40·취업 20 (normal+scam_news_edu 940건은 유형 없음 — 정상).
- 균등 씨앗(이미 20변형)은 건드리지 않음. 재실행 idempotent (deficit 재계산).

---

# 어드민 확장 2건 (augment + apk-dummy) — 2026-06-04 완료

## 1) 데이터 증강 어드민 `/admin/augment`
씨앗 작성 + Claude 병렬 증강 + 모니터링. training 세션 패턴 미러링.
- 신규: `training/augment_sessions.py`, `scripts/run_augment_session.py`, `api_server_pkg/admin_augment.py`, `tests/test_augment_session.py`(3), 프론트 `admin/augment/{page,AugmentClient}` + `about/`, 프록시 7개
- 설명 위키: `/admin/augment/about`
- 검증: pytest 그린, 내 프론트 lint+build OK(증강 작업 시점)

## 2) 더미 피싱앱 다운로드 링크 `/admin/apk-dynamic/dummy`
prebuilt 무해 더미(data_examples/apk 5종)를 만료 공개 토큰 URL 로 발급 → kakao/analyze e2e 테스트.
- 신규: `api_server_pkg/apk_dummy.py`, `tests/test_apk_dummy.py`(6), 프론트 `admin/apk-dynamic/dummy/{page,DummyClient}`, 프록시 3개
- 수정: `state.py`, `models.py`, `middleware.py`(/api/apk-dummy/ skip), `app.py`
- 검증: pytest **345 passed**, 내 프론트 4파일 eslint exit 0 + tsc 0
- ⚠️ `npm run build` 는 머지로 들어온 `live/LiveVoiceUpload.tsx` 의 unescaped-quote 6건에서 실패(내 코드 아님). kyy todo(아래)는 빌드 통과로 기록 — 머지 트리 불일치. 사용자 확인 후 따옴표 escape 로 해소 가능.

---

# 실시간 마이크 스트리밍 보이스피싱 탐지 포팅 (kyy uncommitted) — 2026-06-04

## 배경
- kyy 워크스페이스에 **커밋 안 된** 실시간 버전 존재 — 3812846(업로드 /live) 위에 얹힘.
- POST `/api/live-analyze` 청크 스트리밍(MediaRecorder 주기 POST), WebSocket 아님.
- 신규: `live_stream.py`, `stt_correct.py`, `live-analyze/route.ts`, 테스트4(clova_roles/stream_alert_tier/stream_window/stt_correct)
- 교체(main==3812846): `stream_analyze.py`(+384), `transcribe.py`(+25), `stt.py`(+198), `LiveVoiceUpload.tsx`(+514)
- surgical: app.py(live_stream 라우터), middleware.py(/api/live-analyze 패턴), globals.css(danger-flash +20)
- 새 의존성 없음(전부 stdlib). 제외: start_kyy.sh, todo-kyy.md.

## 결과
- [x] kyy 작업트리 → main 복사(교체4 + 신규3 + 테스트4)
- [x] surgical 3 (app.py / middleware.py / globals.css)
- [x] 백엔드: create_app OK, /api/live-analyze 등록, pytest **384 passed** (새 테스트 4개 포함)
- [x] 프론트 빌드 exit 0 — `/api/live-analyze`, `/live`(실시간 버전) 컴파일
- [x] Review

## Review
- 실시간 마이크 스트리밍 보이스피싱 탐지가 main 워크스페이스에 들어옴. `/live` 가 업로드→실시간 버전으로 업그레이드.
- 흐름: 브라우저 MediaRecorder → 청크 주기적 POST `/api/live-analyze` → STT(diarize/stt_correct) → 누적 윈도우 위험신호 → danger-flash 풀스크린 경보.
- 새 의존성 없음. CLOVA Speech 옵션 백엔드 + stt_correct(Claude 텍스트 교정) 전부 stdlib.
- 검증: pytest 384 passed(새 테스트 clova_roles/stream_alert_tier/stream_window/stt_correct 포함), npm build exit 0.
- 미커밋. 학습포팅 + 라이브보이스(업로드) + 실시간 3건이 작업트리에 누적 — 파일셋 대체로 disjoint(공유: app.py/middleware.py/page.tsx/globals.css는 additive). 경로별 커밋 분리 가능.
- 미반영(제외): kyy의 start_kyy.sh, todo-kyy.md, sg-tui 스크립트, db 백업.

---

# 라이브 보이스(Live Call Guard) 코드단위 포팅 — 2026-06-04

## 배경
- 라이브 보이스가 `origin/main-kyy`(HEAD `3812846`)에만 있고 main 미머지. main엔 stub `v4_stream.py`만.
- 사용자 결정: 파일 통째가 아니라 **코드 체리픽** — 파이프라인은 합치고, 프론트는 `/live` 관련 코드만. 무관(train_classifier 충돌, README, todo, 스크립트) 제외.
- 학습 포팅과 파일셋 disjoint → 같은 작업트리에서 경로별 커밋 분리 가능.

## Plan / 결과
- [x] 신규 파일 wholesale: `pipeline/diarize.py`, `api_server_pkg/{stream_analyze,transcribe}.py`, `apps/web/src/app/live/*`, `api/{analyze-stream,transcribe-upload}/route.ts`
- [x] `pipeline/stt.py` wholesale (main 미변경 → 안전, 화자분리/스트리밍 지원)
- [x] surgical 6: `app.py`(라우터2), `analyze.py`(ffmpeg VAD), `page.tsx`(LIVE 링크), `pricing.py`(clova), `cost.py`(record_clova), `middleware.py`(키패턴2)
- [x] 백엔드: create_app OK, 라우트 등록(/api/transcribe-upload, /api/analyze-stream), import OK, pytest 339 passed
- [x] 프론트 빌드 exit 0 — `/live`, `/api/analyze-stream`, `/api/transcribe-upload` 컴파일
- [x] 제외 확정: train_classifier.py, README, kyy.md, tasks/*, start_*.sh, live_stream.py(미등록)

## Review
- 코드단위 포팅 완료. 라이브 보이스 본체(STT 정확도+화자분리+스트리밍+/live UI)가 main 워크스페이스에 들어옴.
- diarize는 pyannote 등 무거운 오디오모델 아님 → Claude 텍스트 기반 화자분리, **새 pip 의존성 없음**. requirements.txt 미변경.
- CLOVA Speech 비용추적 추가(optional, `CLOVA_SPEECH_PER_MIN_USD` env override). stt.py가 CLOVA 백엔드 옵션 사용 가능.
- 미커밋. 학습포팅(feat/training-compare-sequential)과 파일셋 disjoint — 경로별 커밋 분리 가능.
- 미검증: 실제 런타임(WebRTC 마이크 스트리밍 /live 동작)은 브라우저 필요 — 빌드/라우트/import 까지만 정적 검증.

---

# 더미 피싱앱 다운로드 링크 생성 (/admin/apk-dynamic/dummy) — 2026-06-04

## 배경
APK 검출 e2e 테스트엔 "외부 배포처처럼 받아지는 APK URL"이 필요. prebuilt 무해 더미(data_examples/apk/ 5종)를
만료 공개 토큰 URL 로 발급 → kakao/analyze 에 먹여 탐지 tier 검증. plan: ~/.claude/plans/cuddly-frolicking-lecun.md

## Plan
- [ ] 1. `state.py` — apk_dummy_tokens 저장소 + TTL
- [ ] 2. `models.py` — DummyLinkRequest
- [ ] 3. `apk_dummy.py` — catalog/link/links(admin) + 공개 다운로드(/api/apk-dummy/{token}) + 보안(경로 가드)
- [ ] 4. `middleware.py` — /api/apk-dummy/ 공개 패턴 명시
- [ ] 5. `app.py` — 라우터 include + 태그
- [ ] 6. `tests/test_apk_dummy.py` + pytest 그린
- [ ] 7. Next 프록시 3개 `api/admin/apk-dynamic/dummy/**`
- [ ] 8. 프론트 `admin/apk-dynamic/dummy/{page,DummyClient}` + apk-dynamic nav 링크
- [ ] 9. lint + build

---

# 데이터 증강 어드민 (/admin/augment) 구축 — 2026-06-04

## 배경
씨앗 유형 커버리지 갭(67개가 9유형 편중, 건강식품·부동산·납치 0개)이 macro_f1 0.177 의 근본 원인.
공개 데이터셋은 라벨 체계 불일치로 부적합 → 관리자가 굶은 유형에 씨앗 직접 작성 + Claude 병렬 증강을
웹 어드민으로 빼낸다. training 세션 인프라 미러링. plan: ~/.claude/plans/cuddly-frolicking-lecun.md

## Plan
- [x] 1. `training/augment_sessions.py` — 세션 매니저(start/list/get/cancel/read_metrics/read_log_tail/emit/promote)
- [x] 2. `scripts/run_augment_session.py` — 병렬 러너(ThreadPoolExecutor) + FAKE dry-run hook
- [x] 3. `api_server_pkg/models.py` — AugmentStartRequest, SeedCreateRequest
- [x] 4. `api_server_pkg/admin_augment.py` — seed-stats/seeds/sessions/promote 라우터(7개)
- [x] 5. `api_server_pkg/app.py` — 라우터 include + OPENAPI 태그
- [x] 6. `tests/test_augment_session.py`(3) + pytest 339 passed
- [x] 7. Next.js 프록시 7개 `apps/web/src/app/api/admin/augment/**`
- [x] 8. 프론트 `admin/augment/{page.tsx,AugmentClient.tsx}` + `/admin` 네비 링크
- [x] 9. lint clean + build 성공 + runner/TestClient 스모크 통과

## Review
- **백엔드**: training 세션 패턴 미러링. 증강 세션은 체크포인트 대신 `output.jsonl` 산출, `activate` 대신 `promote_output`(data/generated 병합·중복제거). 병렬은 러너의 ThreadPoolExecutor(동시성 ≤16, write_lock). `SCAMGUARDIAN_AUGMENT_FAKE=1` 로 API 비용 0 테스트.
- **인증**: `/api/admin/*` 미들웨어가 자동 게이팅 → 추가 코드 0.
- **검증**: pytest 339 passed(신규 3 — FAKE 러너/subprocess 라이프사이클/promote/missing-seed). lint clean, next build 성공(7 API + /admin/augment 페이지). TestClient 로 seed-stats/CRUD/validation(400) 확인. FAKE 러너 라이브 스모크 3행 생성.
- **알려진 제약**: 이 base 워크스페이스엔 실물 씨앗 0 → seed-stats 가 12유형 전부 "굶음" 표시(정상·정직). 실제 67 씨앗은 phh 워크스페이스에 있음. UI 에서 씨앗 작성하거나 phh 파일 복사 시 실수치 반영.
- **미적용(의도)**: 실제 Claude 증강 E2E(API 키+서버 필요)는 수동 검증 영역으로 남김 — 플럼빙은 FAKE 로 전부 검증됨.

---

# 순차학습 + 모델 비교 페이지 복원 (feat 브랜치 포팅) — 2026-06-04

## 배경
- 요청: (1) raw Claude vs 파인튜닝 비교 페이지, (2) classifier→gliner 순차학습 기본 + 개별 설정.
- 기능은 `feat/training-compare-synthetic`(tip 04f1c25)에 완성. PR #2 는 분기점(d3ae9da)까지만 머지 → 순차학습/compare 프론트 미반영.
- compare-analysis **백엔드는 이미 main 에 존재**(admin_training.py:742). main 은 분기 이후 해당 파일 미변경 → feat superset, 충돌 없이 포팅 가능. v4 스트리밍 링크 없음 확인.

## Plan
- [x] 1. PR용 브랜치 `feat/training-compare-sequential`
- [x] 2. 프론트 신규 dir 포팅: `compare/`, `models/`
- [x] 3. `training/page.tsx` (nav 링크)
- [x] 4. `TrainingClient.tsx` (순차 체크박스, 둘 선택 시 "순차 학습 시작")
- [x] 5. 백엔드: `sessions.py`(start_sequential_sessions), `models.py`(models:list), `admin_training.py`(sequential dispatch)
  - ⚠️ feat tip 불일치 버그 발견: `admin_training.py`가 `payload.models`/`early_stopping_*` 참조하는데 feat `models.py`엔 없음 → `StartTrainingRequest`에 `models: list[str]|None`, `early_stopping_patience:int=2`, `early_stopping_threshold:float=0.0` 보강 (SessionParams 기본값과 일치).
- [x] 6a. pytest 336 passed
- [x] 6b. 라우트 패리티 확인 (프론트 fetch ↔ FastAPI route ↔ Next proxy 핸들러 전부 존재)
- [x] 6c. `npm run build` exit 0 — `/admin/training/compare`, `/admin/training/models` 컴파일 성공
- [x] 7. dispatch 런타임 시뮬 + Review

## Review
- 브랜치 `feat/training-compare-sequential` 에 포팅 완료. 변경:
  - 신규 프론트: `compare/{page,CompareClient}.tsx` (Claude raw vs 파인튜닝 vs active 3관점 + agreement), `models/{page,ModelsClient}.tsx` (체크포인트 활성화).
  - `training/page.tsx` — 모델관리/모델비교 nav 링크.
  - `TrainingClient.tsx` — 모델 체크박스(기본 둘 다 체크 → "순차 학습 시작", 하나만 → "학습 시작").
  - 백엔드: `sessions.py start_sequential_sessions` (cooldown 사이 순차 spawn), `admin_training.py` dispatch.
- **수정 1 (feat tip 버그)**: `admin_training.py`가 `payload.models`/`early_stopping_*` 참조하나 feat `models.py`에 필드 부재 → `StartTrainingRequest`에 `models/early_stopping_patience/early_stopping_threshold` 추가 (SessionParams 기본값 일치). feat tip 자체는 학습 시작 시 AttributeError 났을 것.
- **수정 2 (사용자 spec)**: feat 순서가 `gliner→classifier`였으나 요청은 classifier 먼저 → `ordered_models = ["classifier", "gliner"]` 로 변경.
- 검증: pytest 336 + 40 passed / npm build exit 0 / 라우트 패리티(프론트 fetch ↔ FastAPI ↔ Next proxy) 전수 확인 / dispatch 런타임 시뮬(classifier→gliner, 단일=start_session) OK.
- v4 스트리밍(`live_stream/stream_analyze/transcribe`)은 의도적으로 미포함.
- 미커밋 상태 — 사용자 확인 후 commit/PR 예정. (무관 변경 `tests/fixtures/fake_phishing.apk`는 제외)

---

# Admin 사용자 관리 — 마스터 + 승인요청 시스템 (2026-06-04)

목적: admin 허용을 정적 `ADMIN_EMAILS` env(4곳 체크)에서 → **마스터 + DB 승인요청** 모델로.
모르는 Google 계정 로그인 시 pending 적재 → 마스터가 `/admin/users`에서 승인. 계획서: `~/.claude/plans/glittery-growing-flute.md`.

- [x] DB: `admin_users` 테이블 + `upsert_access_request`/`get_admin_user`/`list_admin_users`/`set_admin_user_status` + facade + kimjunsung5 approved seed
- [x] 백엔드 `api_server_pkg/admin_users.py` — `/access/check`(unauth) + `/users` + approve/deny/revoke(master-only via X-Admin-Email) + app mount + 미들웨어 public 패턴
- [x] 프론트 게이트 전환: `auth.ts` signIn → 백엔드 `/access/check` 위임(단일 게이트), `proxy.ts`/`backend.ts` 세션 존재만 신뢰 + `X-Admin-Email` forward
- [x] 마스터 UI `/admin/users` + 프록시 4라우트 + admin 탭 + login 페이지 pending 안내
- [x] root `.env` `SCAMGUARDIAN_MASTER_EMAILS=minecrsft64@gmail.com`

## Review
- **모델**: master=env(항상 허용, 락아웃 방지), 그 외=`admin_users` DB(pending/approved/denied). signIn 콜백이 백엔드 `/access/check`를 호출해 단일 게이트 — 비승인자는 세션 자체가 안 생기므로 proxy/backend는 세션만 신뢰.
- **검증**: pytest 336 passed (admin_users 7 신규), tsc/eslint 클린. 재시작 후 E2E — minecrsft64→master, kimjunsung5→admin(seed), 모르는 계정→pending, `/api/admin/users` 무세션 401, `/admin/users` 307→login, 메인/APK 다운로드 200(공개 유지).
- **잔여**: revoke는 기존 JWT(30d) 만료 전까지 유효(v1 한계). Funnel 로그인하려면 Google OAuth 콜백 `https://scamguardian.tail7e5dfc.ts.net/api/auth/callback/google` 등록 필요.

---

# APK Lv3 동적 분석 — API 기반 VM 제어 + 웹 콘솔 (2026-06-03)

목적: APK Lv3 동적 분석이 "VM 이 이미 떠 있다" 가정에 의존하던 것을, **VM 라이프사이클(기동/상태/정지)
+ APK 분석을 API 로 통제하고 전용 admin 웹 콘솔에 노출**. 분석 자체는 그대로 실제 격리 VM(redroid+Frida)
에서 수행. 계획서: `~/.claude/plans/glittery-growing-flute.md`.

- [x] `scripts/apk_dynamic_vm_ctl.sh` — `stop`(VM 정지 + bridge kill), `status-json`(머신리더블, VM 안 켬) 추가
- [x] `pipeline/apk_analyzer.configure_remote()` — 런타임 모듈 상수 주입 (서버 재시작 없이 remote 활성)
- [x] `api_server_pkg/apk_dynamic_control.py` — vm_ctl.sh 래핑, op 백그라운드+로그, status 캐시, 분석 잡 레지스트리
- [x] `api_server_pkg/apk_dynamic.py` — `/api/admin/apk-dynamic/` 6 엔드포인트 + `app.py` 마운트
- [x] 프론트: 프록시 6 라우트 + `/admin/apk-dynamic` 콘솔(VM 배지·기동/정지·APK 업로드·폴링·tier 결과) + admin 탭
- [x] `result/[token]` detection_source 태그에 static_lv1/lv2/dynamic_lv3 보완 (page.tsx 는 이미 완비)
- [x] `tests/test_apk_dynamic_control.py` (7) + 전체 329 통과 / tsc·eslint 클린 / bash -n

## Review

**백엔드**:
- `apk_dynamic_control.py` — `vm_ctl.sh` subprocess 래핑. VM op(start/stop)은 전역 `_op_lock`(동시 1개)
  + 백그라운드 스레드 + `.scamguardian/apk_dynamic/ops/{id}.log`. status 는 `status-json` 파싱 + 8s 캐시
  (VM 을 켜지 않음). start 성공 시 `apk_analyzer.configure_remote(enabled=True)`, stop 시 enabled=False.
  분석 잡은 in-memory 레지스트리; `force_dynamic`이면 `analyze_apk_dynamic` 직접, 아니면 전체 파이프라인.
- 모듈 상수 주입 방식 채택 이유: `analyze_apk_dynamic` 이 모듈 레벨 상수를 읽고 테스트도 `monkeypatch.setattr`
  로 그 상수를 패치 → os.getenv 리팩토링은 70개 테스트 회귀. `configure_remote` 가 동일 메커니즘.
- 라우터 `/api/admin/apk-dynamic/` 6개 → `^/api/admin/` 패턴으로 admin 토큰 강제(기존 미들웨어). 검증:
  ADMIN_AUTH_DISABLED=false 에서 no-token 401 / with-token 200.

**프론트**:
- `proxyGet`/`proxyJsonRequest`/`proxyRaw`(multipart) 기존 헬퍼 재사용. Next 16 route 는 `params: Promise<>`.
- 콘솔: VM 배지(emerald/회색) + 기동/정지 + op 로그 tail + APK 업로드(.apk) + 동적 강제 토글 + 5s 폴링.
  결과는 Lv1/Lv2/Lv3 tier 카드 + observations JSON + (전체 모드) detected_signals 한국어 라벨.
- VM 꺼짐 + 동적 강제 시 "먼저 기동" 배너 (수동 기동 정책).

**보안**: 로컬 실행 HARD BLOCK 유지 — 컨트롤러는 host 에서 APK 실행 안 함, 항상 격리 VM 위임.

**검증**: pytest 329 passed (322+7), `bash -n`/py_compile OK, `tsc --noEmit`/eslint 클린,
TestClient 로 라우팅+admin 게이팅 확인.

**남은 것 (실제 VM 필요 — 자동화 불가)**: `/admin/apk-dynamic` 에서 "VM 기동" → 배지 green →
`tests/fixtures/dynamic_active.apk` 업로드 + 동적 강제 → 5개 런타임 flag E2E (Multipass sg-sandbox 가용 시).

---

# APK Dynamic Main-Server Integration (2026-06-03)

목적: WSL 메인 ScamGuardian 서버에서 별도 VM/redroid/Frida APK 동적 분석 서버를 안정적으로 호출하도록
연결 경로를 정리하고, 리뷰에서 찾은 실행 버그를 함께 수정한다.

- [x] 사용자 정정 반영 및 통합 목표 재설정
- [x] 현재 main server 원격 호출/env/startup 흐름 확인
- [x] Frida hook 재귀 위험 및 dynamic server import 문제 수정
- [x] 정적 분석 결과가 있을 때 동적 호출 gating 정책 정렬
- [x] WSL main server 연결 검증 helper/docs/test 보강
- [x] py_compile/pytest 등 targeted 검증
- [x] Review 결과 기록

## Review

**수정**:
- `scripts/apk_dynamic_vm_ctl.sh` 추가.
  - WSL 에서 Windows `multipass.exe` 를 호출해 VM 시작/상태 확인을 수행한다.
  - `sync`: `apk_dynamic_server/` 와 APK fixture 를 VM 의 `/home/ubuntu/sg-apkdyn` 으로 복사한다.
  - `bootstrap`: binder/ashmem, adb, Docker, frida 16.x 계열 의존성을 VM 에 설치한다.
  - `redroid`: redroid 컨테이너를 만들거나 시작하고 `sys.boot_completed=1` 까지 대기한다.
  - `frida`: frida python package 와 버전 일치 frida-server 를 준비하고 Android 안에서 기동한다.
  - `server`: VM 안에서 `apk_dynamic_server/app.py` 를 token 포함 FastAPI 서버로 기동한다.
  - `bridge`: WSL 로컬 FastAPI bridge 를 `127.0.0.1:18002` 에 띄워 Multipass VM 으로 전달한다.
  - `start`: 위 흐름을 한 번에 실행하고 `.env.apk-dynamic.local` 을 생성한 뒤 `/health` 를 확인한다.
  - `apply-env`: `.env` 백업 후 메인 ScamGuardian 이 읽을 `APK_DYNAMIC_*` 값을 반영한다.
- `scripts/apk_dynamic_wsl_bridge.py` 추가.
  - WSL 메인 서버가 `127.0.0.1:18002` 로 호출하면 bridge 가 `multipass transfer/exec` 로
    VM 내부 `127.0.0.1:8002` 동적 분석 서버에 전달한다.
  - WSL 에서 Multipass NAT IP(`172.20.x.x`) 로 직접 라우팅되지 않는 문제를 우회한다.
- `scripts/check_apk_dynamic_remote.py` 추가.
  - WSL 메인 서버 관점에서 remote `/health` 와 선택적 APK POST 를 점검한다.
- `scripts/apk_dynamic_windows_relay.ps1` 추가.
  - Windows TCP relay fallback. 현재 환경에서는 WSL→Windows gateway inbound 가 timeout 되어
    기본 경로는 WSL bridge 로 전환했다.
- `apk_dynamic_server/frida_hooks.js`
  - replacement 내부에서 같은 Java 메서드를 다시 호출하던 부분을 overload 원본 호출 패턴으로 수정했다.
- `apk_dynamic_server/app.py`
  - package import 와 `cd apk_dynamic_server && python3 app.py` 실행을 둘 다 지원하게 했다.
- `pipeline/runner.py`
  - Lv1/Lv2 정적 분석에서 이미 신호가 있으면 remote VM 동적 분석을 생략한다.
- `.env.example`, `apk_dynamic_server/README.md`, `sg-apk.md`
  - WSL 컨트롤러 기반 운영 흐름을 추가했다.
- `README.md`
  - APK Lv3 를 더 이상 future-work-only 로 적지 않고, WSL bridge 기반 수동 활성화 절차를 추가했다.
  - `start_stack.sh` 기본 자동 기동은 피하고, 필요 시 수동 또는 별도 옵션으로 켜는 정책을 기록했다.

**검증**:
- `bash -n scripts/apk_dynamic_vm_ctl.sh`
- `scripts/apk_dynamic_vm_ctl.sh --help`
- `python3 -m py_compile scripts/check_apk_dynamic_remote.py apk_dynamic_server/app.py apk_dynamic_server/analyzer.py pipeline/apk_analyzer.py pipeline/runner.py`
- `conda run --no-capture-output -n capstone python - <<PY import apk_dynamic_server.app ... PY`
- `conda run --no-capture-output -n capstone python -m pytest tests/test_apk_analyzer.py -q` → 70 passed
- `conda run --no-capture-output -n capstone python -m pytest tests/test_detection_report_schema.py tests/test_flag_groups.py -q`
  → 35 passed
- `git diff --check`
- 실제 기동:
  - VM `sg-sandbox` running, redroid booted, frida-server running.
  - VM 내부 `apk_dynamic_server` 는 `0.0.0.0:8002` 에서 uvicorn listening.
  - WSL bridge `127.0.0.1:18002` health 성공:
    `{"status":"ok","redroid_booted":true,"auth":true,"bridge":"wsl-multipass"}`.
  - `scripts/check_apk_dynamic_remote.py --apk tests/fixtures/dynamic_active.apk --timeout 30`
    → HTTP 200, 5개 런타임 flag 전부 검출.

**잔여 리스크**:
- Windows relay fallback 은 현재 WSL→Windows gateway timeout 으로 직접 사용하지 않는다.
- `.env` 에 dev token(`dev-secret-123`) 이 들어간 상태다. 운영용으로는 반드시 긴 랜덤 토큰으로 교체한다.

---

# APK Dynamic Analysis Review (2026-06-03)

목적: 최신 커밋 `04f1c25 feat(apk-dynamic)` 의 redroid+Frida APK 동적 분석 서버와 active fixture를
코드 리뷰 관점으로 점검한다.

- [x] 리뷰 범위 재설정 및 누락 lesson 기록
- [x] APK 동적 분석 서버/API/analyzer/hook/fixture diff 확인
- [x] 보안 경계·실행 가능성·테스트 연결성 점검
- [x] 가능한 정적/스모크 검증 실행
- [x] 발견사항과 잔여 리스크 정리

## Review

**검토 범위**:
- 최신 ahead 커밋 `04f1c25 feat(apk-dynamic): redroid+Frida APK 동적 분석 서버 + active fixture`
- `apk_dynamic_server/app.py`, `apk_dynamic_server/analyzer.py`, `apk_dynamic_server/frida_hooks.js`
- `tests/fixtures/dynamic_active_app/*`, `tests/fixtures/dynamic_active.apk`
- 기존 연동부: `pipeline/apk_analyzer.py`, `pipeline/runner.py`, `pipeline/signal_detector.py`,
  `tests/test_apk_analyzer.py`

**발견사항**:
- `frida_hooks.js` 일부 hook 이 replacement 내부에서 같은 Java 메서드를 다시 호출한다.
  `WindowManagerImpl.addView`, `WindowManagerGlobal.addView`, `BroadcastReceiver.abortBroadcast` 등은
  `ov.apply(...)`/overload `.call(...)` 로 원본을 호출해야 한다. 현재 형태는 재귀/스택오버플로우로
  overlay/SMS 계열 이벤트 수집을 불안정하게 만들 수 있다.
- `apk_dynamic_server/app.py` 는 `import analyzer` 절대 import 를 사용한다. README 방식처럼
  `cd apk_dynamic_server && python3 app.py` 는 동작하지만, repo root 에서
  `uvicorn apk_dynamic_server.app:app` / package import 는 `ModuleNotFoundError: analyzer` 로 실패한다.
- README 는 "정적 분석(Lv1/Lv2)이 0 신호일 때만 runner 가 동적 서버를 호출"한다고 설명하지만,
  실제 `pipeline/runner.py` 는 APK 입력이면 Lv1/Lv2 결과와 무관하게 `analyze_apk_dynamic()` 을 호출한다.
  운영에서 enabled+remote 설정 시 문서보다 더 많은 VM 호출/지연이 발생할 수 있다.

**검증**:
- `python3 -m py_compile apk_dynamic_server/app.py apk_dynamic_server/analyzer.py`
- `conda run --no-capture-output -n capstone python -m pytest tests/test_apk_analyzer.py -q` → 70 passed
- `conda run --no-capture-output -n capstone python -m pytest tests/test_detection_report_schema.py tests/test_flag_groups.py -q`
  → 35 passed
- `conda run --no-capture-output -n capstone python - <<PY import apk_dynamic_server.app ... PY`
  → `ModuleNotFoundError: No module named 'analyzer'`
- `cd apk_dynamic_server && conda run --no-capture-output -n capstone python - <<PY import app ... PY`
  → OK
- `git diff --check`

**잔여 리스크**:
- redroid/Frida VM 실제 동적 실행은 현재 환경에서 수행하지 못했다. 따라서 active fixture 의 5개 런타임
  flag 실검출은 코드/문서/테스트 계약 기준 리뷰이며, VM smoke 는 별도 필요하다.

---

# Changed Files Review (2026-06-03)

목적: 최근 변경된 `api_server_pkg/app.py` 와 신규 TUI 스크립트를 코드 리뷰 관점으로 점검한다.

- [x] 현재 작업트리와 기존 lessons 확인
- [x] 변경 diff 및 주변 호출 경로 확인
- [x] 가능한 정적/스모크 검증 실행
- [x] 발견사항과 잔여 리스크 정리

## Review

**검토 범위**:
- 추적 변경: `api_server_pkg/app.py`
- 미추적 신규: `scripts/sg_tui.py`, `scripts/sg-tui.sh`
- 미추적 기타: `.scamguardian/scamguardian.sqlite3.broken-selflink-20260602-235057`

**발견사항**:
- TUI 기본 시작 경로가 `scripts/start_stack.sh` 를 호출하고, 이 스크립트는 Next 16 dev 서버를
  `--webpack` 없이 실행한다. 기존 lessons 의 Turbopack/WSL freeze 회귀 위험이 있다.
- TUI의 detached 학습 실행은 `subprocess.run(...)` 반환 코드를 확인하지 않아, 학습 프로세스를
  띄우지 못해도 즉시 `tail -F` 로 넘어갈 수 있다.

**검증**:
- `python3 -m py_compile api_server_pkg/app.py scripts/sg_tui.py`
- `bash -n scripts/sg-tui.sh scripts/start_stack.sh scripts/start_kyy.sh`
- `git diff --check`
- `conda run --no-capture-output -n capstone python - <<PY ... create_app() ... PY`

**주의**:
- 일반 `python3` 는 `fastapi` 가 없어 앱 import 검증이 실패했다. 프로젝트 검증은 `capstone`
  conda env 기준으로 해야 한다.
# Training Status False Failure (2026-06-01)

목적: 학습 로그와 metrics 는 갱신 중인데 status.json 이 `failed` 로 먼저 바뀌어 UI가
실행 중인 학습을 실패로 표시하는 문제를 수정한다.

- [x] 최신 학습 세션 로그/status/metrics 확인
- [x] 최근 로그 활동이 있으면 failed 전환을 유예하도록 세션 상태 보정
- [x] py_compile smoke 검증
- [x] Review 섹션에 결과 기록

## Review

**확인 결과**:
- 최신 세션 `79e87597a8a2` 는 `batch_size=1`, `epochs=10` 설정이라 전체 step 이
  `108250` 으로 커졌다. 이전 성공 세션 `382515ce0381` 의 `batch_size=5`, `epochs=5`,
  `10825` step 대비 정확히 10배 규모다.
- 로그의 처리 속도는 대략 10-13 it/s 로 GPU 학습 자체가 멈춘 상황은 아니다.
- `status.json` 은 `failed` 로 바뀌었지만 `metrics.jsonl` 과 `train.log` 는 그 이후에도
  계속 갱신되어 상태 추적 false failure 가 있었다.

**수정**:
- `training/sessions.py`
  - metrics/log 파일이 최근 120초 안에 갱신됐으면 pid liveness 확인이 애매해도 바로
    `failed` 로 전환하지 않는다.
  - 이미 `failed` 로 표시됐더라도 `ended_at` 이후 새 로그 활동이 있으면 `running` 으로
    복구하고 최신 metric 을 `last_metrics` 로 반영한다.

**검증**:
- `python -m py_compile training/sessions.py` 통과.
- `sessions.get_session("79e87597a8a2")` 결과가 `running` 으로 복구되고 latest step 이
  `10360`, epoch `0.957` 로 반영되는 것을 확인했다.

---

# Classifier Early Stopping (2026-06-01)

목적: synthetic classifier fine-tuning 에 early stopping 을 추가해 validation metric 이 더 이상
개선되지 않을 때 불필요한 epoch 를 멈추고 best checkpoint 를 사용하게 한다.

- [x] `training/train_classifier.py` Trainer 설정 확인
- [x] early stopping CLI 옵션과 callback 추가
- [x] training session params/API/UI 에 patience 옵션 연결
- [x] lint/type/py_compile smoke 검증
- [x] Review 섹션에 결과 기록

## Review

**구현**:
- `training/train_classifier.py`
  - `--early-stopping-patience` 추가. 기본값 2, 0 이하면 비활성.
  - `--early-stopping-threshold` 추가. 기본값 0.0.
  - `EarlyStoppingCallback` 연결.
  - 기준 metric 은 기존 best model 설정과 동일한 `eval_macro_f1`.
  - `load_best_model_at_end=True` 유지라 early stop 후 best checkpoint 를 사용.
- `training/sessions.py`
  - `SessionParams` 에 `early_stopping_patience`, `early_stopping_threshold` 추가.
  - classifier 세션 시작 시 CLI 로 early stopping 옵션 전달.
- `api_server_pkg/models.py`, `api_server_pkg/admin_training.py`
  - training session API payload 에 early stopping 옵션 연결.
- `/admin/training`
  - 새 학습 세션 폼에 `early stop` 숫자 input 추가.
  - classifier 에서만 활성, 기본값 2.
  - Live Training Console 실행 설정에 patience 표시.

**검증**:
- `python -m py_compile training/train_classifier.py training/sessions.py api_server_pkg/models.py api_server_pkg/admin_training.py`
- `python -m training.train_classifier --help` 에 early stopping 옵션 노출 확인.
- `npm run lint` 통과.
- `npx tsc --noEmit` 통과.
- `git diff --check` 통과.
- `SessionParams(... early_stopping_patience=2).to_dict()` smoke 확인.

---

# Model Comparison Analysis Session (2026-06-01)

목적: 초기 분석 화면처럼 사용자가 텍스트나 링크를 입력하면, 같은 입력에 대해
기존 ScamGuardian 분석, Claude/LLM 분석, fine-tuned classifier 분석을 나란히 비교하는
별도 세션을 만든다. 단순 checkpoint smoke test 가 아니라 실제 입력 기반 분석 비교로
`/admin/training` 에 연결한다.

- [x] 기존 `/api/analyze` 입력/파이프라인/LLM 분석 구조 확인
- [x] 비교 세션 backend API 설계 및 구현
- [x] Next.js proxy route 추가
- [x] `/admin/training` 에 입력 폼과 비교 결과 UI 연결
- [x] py_compile/lint/type smoke 검증
- [x] Review 섹션에 결과 기록

## Review

**구현한 비교 세션**:
- Backend: `POST /api/admin/training/compare-analysis`
  - 입력: `text` 또는 `source`, 선택 `session_id`.
  - `source` 가 링크/파일이면 `pipeline.stt.transcribe()` 로 transcript 를 만든 뒤 같은 텍스트를 비교한다.
  - 비교 관점:
    - `existing`: raw zero-shot classifier + keyword boost.
    - `claude`: `llm_assessor.analyze_unified()` 기반 LLM 재판정/근거 후보.
    - `fine_tuned`: 완료된 classifier 세션 checkpoint 직접 로드.
  - session_id 미지정 시 최신 완료 classifier checkpoint 를 자동 선택한다.
- Next proxy: `POST /api/admin/training/compare-analysis`.
- UI: `/admin/training` 에 `모델 비교 분석 세션` 섹션 추가.
  - 분석 문구 textarea + URL/파일 경로 input.
  - 현재 선택된 완료 classifier 세션 또는 최신 완료 classifier 를 fine-tuned 기준으로 사용.
  - 기존/Claude/fine-tuned 결과 카드, 일치 여부, Claude 신호/엔티티 후보, transcript 접기 영역 표시.

**검증**:
- `python -m py_compile api_server_pkg/admin_training.py` 통과.
- `npm run lint` 통과.
- `npx tsc --noEmit` 통과.
- `git diff --check` 통과.
- API smoke:
  - session: `382515ce0381`
  - existing: `기관 사칭`
  - fine_tuned: `대출 사기`
  - Claude: 현재 실행 환경에 `anthropic` Python module 이 없어 `No module named 'anthropic'` 오류를
    결과 카드에 표시하는 fallback 확인.

---

# Raw vs Fine-tuned Classifier Comparison (2026-06-01)

목적: `/admin/training` 에 raw 기본 classifier 와 fine-tuned classifier 를 같은 smoke 문장 세트로
비교하는 별도 분석 세션을 추가한다. 학습 결과를 단순 metric 이 아니라 "기본 모델 대비
어떤 유형 예측이 개선/악화됐는지"로 현재 fine-tuning 페이지에 연결해 보여준다.

- [x] classifier 로딩/세션 구조 확인
- [x] raw vs fine-tuned 비교용 smoke set 과 backend API 추가
- [x] `/admin/training` 에 비교 실행/결과 UI 연결
- [ ] py_compile/lint/type/API smoke 검증
- [ ] Review 섹션에 결과 기록

## Review

진행 중.

---

# Training Start Live Feedback (2026-06-01)

목적: `/admin/training` 에서 학습 시작 버튼을 누르면 새 세션의 상태, 실행 파라미터,
로그 tail, metric 흐름이 즉시 보이게 한다. 사용자가 별도 세션을 찾아 누르지 않아도
"지금 학습이 실제로 돌고 있다"를 확인할 수 있게 한다.

- [x] 현재 세션 시작/상세 폴링 흐름 확인
- [x] 시작 직후 selected session/detail/log 가 바로 보이도록 UI 상태 개선
- [x] 실행 중 요약 패널과 로그 자동 스크롤 추가
- [x] lint/type 검증
- [x] Review 섹션에 결과 기록

## Review

**수정 내용**:
- 학습 시작 성공 직후 새 `session_id` 를 자동 선택하고 상세 정보를 즉시 fetch 하도록 변경.
- 새 학습 세션 폼 아래에 `Live Training Console` 패널 추가.
- 패널에서 상태, 시작 시각, 경과 시간, PID, 마지막 step, 실행 설정, output dir 을 표시.
- 마지막 metric snapshot 을 `loss`, `eval loss`, `macro F1`, `accuracy` 로 표시.
- `train.log` tail 8KB 를 실시간 로그 영역에 표시하고, 새 로그가 오면 자동으로 아래로 스크롤.
- 기존 5초 폴링은 유지해서 running session 동안 목록/상세/로그가 계속 갱신된다.

**검증**:
- `npm run lint` 통과.
- `npx tsc --noEmit` 통과.
- `git diff --check` 통과.
- `curl -sS http://127.0.0.1:3001/admin/training` HTML 응답 확인.
- `curl -sS http://127.0.0.1:8000/health` 응답 확인.

---

# Training Data Count Clarification (2026-06-01)

목적: `/admin/training` 에서 기본 DB 라벨 25건과 synthetic extra JSONL 포함 12025건이
서로 다른 통계인데 같은 "학습 데이터"처럼 보여 혼동되는 문제를 바로잡는다.

- [x] 원인 확인: data-stats 기본 DB vs synthetic summary extra JSONL
- [x] UI 카드 문구와 표시값을 전체 학습 후보 기준으로 조정
- [x] 새 학습 세션의 extra JSONL 기본값을 최신 synthetic corpus 로 채우기
- [x] lessons.md 에 혼동 방지 규칙 기록
- [x] lint/type smoke 검증
- [x] Review 섹션에 결과 기록

## Review

**원인**:
- `GET /api/admin/training/data-stats` 는 기본 DB 라벨만 읽어서 25건을 표시했다.
- `GET /api/admin/training/synthetic-summary` 와 실제 학습 명령의 `--extra-jsonl` 경로는
  `data/generated/scamguardian_synthetic_12000.jsonl` 을 포함해 12025건을 읽는다.

**수정**:
- `/admin/training` 의 카드 제목을 `분류기 학습 데이터` 에서 `현재 학습 후보 전체` 로 변경.
- 값은 synthetic summary 가 있으면 12025건 기준으로 표시.
- 보조 문구에 `기본 검수 라벨 25건 + synthetic <path>` 를 표시해 source scope 를 분리.
- 새 학습 세션 폼의 `extra JSONL` 기본값을 최신 synthetic corpus 경로로 자동 채움.
- `tasks/lessons.md` 에 source/scope 를 분리해서 표시하라는 규칙 추가.

**검증**:
- `npm run lint` 통과.
- `npx tsc --noEmit` 통과.

---

# Synthetic Knowledge Graph Visualization (2026-06-01)

목적: `/admin/training` 에 합성 데이터의 유형·시나리오·사례·검출 신호 연결 구조를
네트워크 그래프 형태로 시각화한다. 비전공자가 "데이터가 서로 어떻게 연결되어 학습 재료가
되는지"를 한눈에 볼 수 있게 하되, ScamGuardian identity boundary 에 맞춰 판정/점수 표현은
추가하지 않는다.

- [x] synthetic summary API 에 graph nodes/links payload 추가
- [x] 캔버스 기반 네트워크 그래프 컴포넌트 구현
- [x] `/admin/training` 상단 시각화 패널에 그래프 배치
- [x] lint/type/API smoke 검증
- [x] Review 섹션에 결과 기록

## Review

**추가한 API 데이터**:
- `GET /api/admin/training/synthetic-summary` 응답에 `graph.nodes[]`, `graph.links[]` 추가.
- graph 는 최신 synthetic corpus 에서 다음 연결을 구성한다:
  - 전체 코퍼스 → 12개 scam_type
  - scam_type → 60개 scenario/template
  - scenario → sampled synthetic case
  - scam_type/scenario/case → flag_group, flag, entity_label

**그래프 규모**:
- 기준 corpus: `data/generated/scamguardian_synthetic_12000.jsonl`.
- graph nodes: 555.
- graph links: 1774.

**UI 구현**:
- `/admin/training` synthetic panel 에 `데이터 연결망` 캔버스 추가.
- 어두운 배경, 얇은 파란 edge, 흰색 사례/시나리오 node, 보라색 신호/엔티티 node 로 구성.
- hover 시 node label, node kind, 연결 가중치를 표시.
- runtime 확인 중 HMR 에서 component reference 오류가 한 번 떠서 wrapper component 를 상단에 두도록 보강했다.

**검증**:
- `python -m py_compile api_server_pkg/admin_training.py` 통과.
- `npm run lint` 통과.
- `npx tsc --noEmit` 통과.
- `_synthetic_graph()` local smoke 통과: 555 nodes / 1774 links.
- Next dev log 에서 `/admin/training`, `/api/admin/training/synthetic-summary`,
  `/api/admin/training/data-stats`, `/api/admin/training/sessions` 200 응답 확인.

---

# Synthetic Corpus Expansion 12000 (2026-06-01)

목적: 기존 3000건 synthetic corpus 를 보존하면서 12개 사기 유형별 균형을 유지한
대형 학습용 corpus 를 추가 생성한다. 생성 후 span/schema/loader 검증까지 끝내
다음 학습 또는 RAG 재인덱싱에 바로 사용할 수 있게 한다.

- [x] 생성기 옵션과 기존 분포 확인
- [x] 12000건 synthetic JSONL 별도 생성
- [x] schema/entity span/유형 분포 검증
- [x] training loader 호환성 확인
- [x] 필요 시 admin training summary 가 새 corpus 를 인식하도록 조정
- [x] Review 섹션에 결과 기록

## Review

**산출물**:
- `data/generated/scamguardian_synthetic_12000.jsonl`
  - 12개 scam_type × 1000건 = 총 12000건.
  - 기존 `data/generated/scamguardian_synthetic_3000.jsonl` 은 보존.
  - seed `20260602` 로 생성해 기존 3000건과 다른 값 조합을 사용.

**분포/품질 검증**:
- JSONL line count: 12000.
- 유형 분포: 12개 유형 모두 1000건.
- template families: 60개, family 당 200건.
- unique text: 10610건.
- entity span mismatch: 0건.
- invalid flag / flag group mismatch: 0건.
- 평균 relation 수: 16.45개/row.
- 평균 slot value 수: 3.31개/row.

**학습 로더 호환**:
- `python -m training.data --extra-jsonl data/generated/scamguardian_synthetic_12000.jsonl`
  - content gate examples: 12025.
  - scam_type classifier examples: 12025.
  - GLiNER examples: 12019.
  - 평균 엔티티/문서: 3.3.

**웹 요약 API 조정**:
- `api_server_pkg/admin_training.py` 의 synthetic summary 가
  `data/generated/scamguardian_synthetic_*.jsonl` 중 가장 큰 corpus 를 자동 선택하게 변경.
- Next proxy `GET /api/admin/training/synthetic-summary` 에서
  `data/generated/scamguardian_synthetic_12000.jsonl`, total 12025 로 표시 확인.

**검증**:
- `python -m py_compile api_server_pkg/admin_training.py` 통과.
- `git diff --check` 통과.
- `curl -sS http://127.0.0.1:8000/health` 응답 확인.
- `curl -sS http://127.0.0.1:3001/api/admin/training/synthetic-summary` 응답 확인.

---

# Training Visualization for Beginners (2026-06-01)

목적: synthetic classifier 학습 결과를 비전공자도 이해할 수 있게 `/admin/training` 에
카드·막대·타임라인 형태로 시각화한다. 단순 metric 숫자 대신 "데이터", "학습 안정성",
"검증 결과", "왜 아직 자동 적용 보류인지"를 단계별로 보여준다.

- [x] 백엔드에서 로컬 synthetic 학습 산출물 요약 API 제공
- [x] Next.js proxy route 추가
- [x] `/admin/training` 에 초심자용 시각화 패널 추가
- [x] lint/type/build 수준 검증
- [x] Review 섹션에 결과 기록

## Review

**추가한 화면**:
- `/admin/training` 상단에 "이번 합성 데이터 학습 한눈에 보기" 패널 추가.
- 비전공자도 이해할 수 있게 `공부한 문장`, `유형 수`, `최고 연습 점수`, `자동 적용 보류 이유`,
  `다음 단계`를 문장형 카드로 표시한다.
- 데이터 균형은 유형별 bar chart 로, 학습 시도별 개선은 F1/accuracy line chart 로 표시한다.

**추가한 API**:
- `GET /api/admin/training/synthetic-summary`
  - `data/generated/scamguardian_synthetic_3000.jsonl` 기준 학습 데이터 분포 요약.
  - `.scamguardian/training_sessions/synthetic_classifier_*` 산출물의 checkpoint trainer_state 를 읽어
    시도별 eval metric 을 반환.
- Next proxy route:
  - `apps/web/src/app/api/admin/training/synthetic-summary/route.ts`

**UI 설계 판단**:
- 높은 validation 값만 보여주면 비전공자는 "왜 적용 안 하지?"로 오해하기 쉬워서,
  패널에 `학습/재로드 성공` 과 `실전형 smoke set 전 자동 적용 보류`를 같이 보여준다.
- ScamGuardian identity boundary 에 맞게 사기 판정/위험 점수 표현은 추가하지 않았다.

**검증**:
- `python -m py_compile api_server_pkg/admin_training.py`
- synthetic summary 함수 smoke:
  - dataset 3025건, 12개 유형, 학습 시도 4개 감지.
  - best: `synthetic_classifier_20260601_1605_lora_head_lr5e6`.
- `npm run lint` 통과.
- `npx tsc --noEmit` 통과.
- `git diff --check` 통과.
- `npm run build` 는 sandbox 안 Turbopack 이 process 생성 중 port bind 권한 문제
  (`Operation not permitted`) 로 실패했다. 타입 검사는 별도로 통과했고, escalation 으로
  `npm run dev` 실행 후 `/admin/training` 과 `/api/admin/training/synthetic-summary` 응답을 확인했다.

---

# Synthetic Classifier Fine-Tuning (2026-06-01)

목적: `data/generated/scamguardian_synthetic_3000.jsonl` 를 추가 학습 데이터로 사용해
12개 사기 유형 scam_type 분류기를 fine-tune 한다. 우선 파이프라인 자동 적용 전,
세션 산출물과 평가 지표를 확인 가능한 상태로 남긴다.

- [x] 데이터 dry-run / 라벨 분포 확인
- [x] synthetic JSONL 기반 classifier 학습 실행
- [x] 3 epoch 본학습 실행
- [x] 1 epoch smoke 학습 산출물/평가 지표 확인
- [x] 필요 시 active model 적용 여부 판단
- [x] Review 섹션에 결과 기록

## Review

**CUDA 확인**:
- WSL sandbox 안에서는 `torch.cuda.is_available() == False` 로 보였지만, escalation 환경에서
  `LD_LIBRARY_PATH=/usr/lib/wsl/lib` 를 지정하자 `NVIDIA GeForce RTX 5070 Ti`, BF16 지원 확인.
- `tasks/lessons.md` 에 WSL CUDA 판정 시 sandbox/device 노출을 분리해서 확인하라는 교훈을 추가했다.

**코드 수정**:
- `training/train_classifier.py`
  - Transformers 최신 API 호환: `Trainer(tokenizer=...)` → `processing_class=...`.
  - mixed precision 옵션 추가: `--fp16`, `--bf16`.
  - LoRA adapter 저장 시 classifier head/pooler 도 보존하도록 `modules_to_save` 설정.
- `pipeline/classifier.py`
  - 활성 classifier checkpoint 가 PEFT/LoRA adapter 인 경우 base model + adapter 로 로드.
  - `label2id.json` 을 읽어 `id2label`/`label2id` 를 복원.

**학습 결과**:
- 1 epoch smoke: `.scamguardian/training_sessions/synthetic_classifier_20260601_1542/output`
  - eval accuracy 0.23, macro-F1 0.1677.
- 3 epoch LoRA without saved classifier head:
  `.scamguardian/training_sessions/synthetic_classifier_20260601_1549_e3/output`
  - eval accuracy 0.52, macro-F1 0.4857.
  - adapter reload 시 classifier head 가 안정적으로 복원되지 않아 활성화 부적합.
- 3 epoch LoRA with classifier head, LR 2e-5:
  `.scamguardian/training_sessions/synthetic_classifier_20260601_1553_lora_head/output`
  - eval accuracy 0.42, macro-F1 0.4053.
  - 초반 gradient/loss 불안정, 스모크 예측 불량.
- 3 epoch LoRA with classifier head, LR 5e-6:
  `.scamguardian/training_sessions/synthetic_classifier_20260601_1605_lora_head_lr5e6/output`
  - eval loss 0.6475, accuracy 0.84, macro-F1 0.8396, macro precision 0.8508, macro recall 0.84.
  - 재로드 후 validation sample 24건 중 23건 정답.

**활성화 판단**:
- `.scamguardian/active_models.json` 은 수정하지 않았다.
- 이유: synthetic validation 은 좋지만, 수동 smoke 문장(예: "검찰청 안전계좌", "대한통운 주소 오류",
  "삼성 이재용 특별 투자")에서 일반화가 아직 약했다. 실서비스 자동 swap 전에는 별도 held-out
  hard smoke set 또는 실제 라벨 데이터 기반 평가가 필요하다.

---

# Synthetic Multi-View RAG Index (2026-06-01)

목적: `rag_texts.case/scenario/pattern/entity_pattern/evidence_terms` 를 각각 embedding view 로
인덱싱해, 단순 문장 유사도뿐 아니라 scenario·flag 조합·entity 구조 기반 검색도 가능하게 한다.

- [x] index artifact 형식 결정 (`metadata.jsonl` + `embeddings.npz`)
- [x] build/query 겸용 스크립트 추가
- [x] 3000건 synthetic corpus 로 multi-view index 생성
- [x] smoke query 로 검색 결과 검증
- [x] Review 섹션에 결과 기록

## Review

**산출물**:
- `scripts/build_synthetic_rag_index.py` — synthetic JSONL 의 `rag_texts` 를 multi-view embedding index 로
  build/query 하는 CLI.
- `data/generated/rag_index/synthetic_multiview_embeddings.npz` — float32 normalized embeddings.
- `data/generated/rag_index/synthetic_multiview_metadata.jsonl` — view 별 검색 metadata.
- `data/generated/rag_index/synthetic_multiview_manifest.json` — 모델명/차원/분포 manifest.

**인덱스 구조**:
- view 5종: `case`, `scenario`, `pattern`, `entity_pattern`, `evidence_terms`.
- 각 synthetic row 가 5개 view 로 확장되어 3000건 → 15000 vectors.
- embedding dimension 384, scam_type 12종 각각 1250 vectors.
- query 는 cosine 기반 dot product + view weight + 가벼운 lexical boost 를 사용하고,
  같은 `synthetic_id` 중복 결과를 제거한다.

**구현 메모**:
- `pipeline/rag.py` 의 로컬 Hugging Face snapshot 탐색 경로에 프로젝트 `.cache/huggingface`
  루트와 사용자 `~/.cache/huggingface` 루트를 추가해, 기존 로컬 캐시를 쓰고 네트워크 fallback 을 피하게 했다.

**검증**:
- build 성공: rows 3000, vectors 15000, dimension 384.
- smoke query:
  - "검찰/안전계좌/5000만원" → top 3 모두 `기관 사칭`.
  - "인스타그램/해외 군인/통관 수수료" → top 2 `로맨스 스캠`, top 3 `메신저 피싱`.
  - "택배 주소 오류 링크/신분증 사진" → top 2 `스미싱`.

---

# Synthetic Corpus v2 — RAG/관계형 메타데이터 확장 (2026-06-01)

목적: 3000건 synthetic_scam_message 를 classifier/GLiNER 학습뿐 아니라 multi-view RAG 에도
쓸 수 있게 `scenario_id`, `scenario_ko`, `slots`, `relations`, `rag_texts`, `flag_groups`
필드를 추가한다.

- [x] 생성기 렌더 단계에서 slot value 보존
- [x] flag group / relation / rag_texts 생성 로직 추가
- [x] 3000건 JSONL 재생성
- [x] 스키마·span·flag group·loader 검증
- [x] Review 섹션에 결과 기록

## Review

**산출물**:
- `scripts/generate_synthetic_training_data.py` 확장.
- `data/generated/scamguardian_synthetic_3000.jsonl` 재생성.

**추가 필드**:
- `scenario_id`: 템플릿 ID. 예: `smishing_tax_refund`.
- `scenario_ko`: scam_type 별 한국어 scenario 설명 + 템플릿 ID.
- `slots`: 렌더링에 사용된 slot value dict. 같은 slot 이 여러 번 나오면 list 로 보존.
- `flag_groups`: `pipeline.flag_groups.group_of()` 기준 risk_flags 의 그룹 ID list.
- `relations`: lightweight triples. `flag supports scam_type`, `group groups_signal_for scam_type`,
  `entity typed_as label`, `entity evidence_candidate_for flag`.
- `rag_texts`: `case`, `scenario`, `pattern`, `entity_pattern`, `evidence_terms` multi-view 검색 텍스트.

**검증**:
- 생성 로그: 3000 rows, 12개 유형 각 250건, template families 60개.
- 커스텀 검증: 필수 v2 필드 누락 0, entity span mismatch 0, invalid flag/label 0,
  flag_groups mismatch 0.
- v2 통계: 평균 relations 16.37개/row, 평균 slots 3.27개/row.
- `python -m training.data --extra-jsonl data/generated/scamguardian_synthetic_3000.jsonl`
  기존 로더 호환 확인.

---

# Synthetic Training Data 3000 — scam_attempt 증강 (2026-06-01)

목적: 실제 도메인 데이터 부족을 보완하기 위해 12개 사기 유형별 균형 synthetic_scam_message
3000건을 생성한다. 본문은 `[사람이름]` 같은 마스킹 토큰이 아니라 자연스러운 가상값을 사용하고,
엔티티는 `entities[]` span 라벨로 제공한다.

- [x] 기존 학습 스키마/라벨/flag 확인
- [x] 12개 유형별 템플릿과 슬롯 사전 기반 생성기 추가
- [x] 3000건 JSONL 생성 (`data/generated/scamguardian_synthetic_3000.jsonl`)
- [x] 분포/스키마/GLiNER 로더 검증
- [x] Review 섹션에 결과 기록

## Review

**산출물**:
- `scripts/generate_synthetic_training_data.py` — deterministic generator. 기본 `--total 3000`,
  `--seed 20260601`, 출력 `data/generated/scamguardian_synthetic_3000.jsonl`.
- `data/generated/scamguardian_synthetic_3000.jsonl` — 12개 scam_type × 250건 = 총 3000건.

**설계**:
- 본문은 `[사람이름]` 같은 placeholder 노출 없이 가상 이름·기관·금액·URL 등 자연 문자열 사용.
- `entities[]` 에 `text`, `label`, `start`, `end` span 포함 — GLiNER loader 가 바로 사용 가능.
- `risk_flags[]` 는 `pipeline.config.DETECTED_FLAGS` 안의 기존 flag 만 사용.
- `source_ref=synthetic_template/<scam_type>/<template_id>` 로 템플릿 family 를 묶어
  `training/splits.py` 의 group split 이 train/val leakage 를 피할 수 있게 함.

**검증**:
- 생성 로그: 3000 rows, 12개 유형 각 250건, template families 60개, family 당 50건.
- 커스텀 검증: content_label/scam_type/risk_flags/entity label/span mismatch 모두 0건.
- `python -m training.data --extra-jsonl data/generated/scamguardian_synthetic_3000.jsonl`
  - content gate examples: 3025 (`scam_attempt` 3025)
  - scam_type classifier examples: 3025
  - GLiNER examples: 3019, 평균 엔티티/문서 3.4

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

---

# 🚨 공유 — Next 16 Turbopack 메모리 누수 → Webpack fallback (2026-05-28, phh 워크스페이스 발견)

> **환경 공통 이슈**. 모든 워크스페이스 작업자가 알아야. phh 에서 4시간 디버깅 후 root cause 확정.

## 증상

- `./scripts/start_stack.sh` 실행 → WSL 무한 프리징 + 원격(SSH/VSCode) 연결 끊김
- WSL 메모리 8GB → 20GB 증설 후에도 재발
- stack 안 띄웠을 때도 호스트 측 압박 체감 (작업관리자 디스크 활성 시간 50%+)

## 진단

- **첫 freeze (03:04)**: next-server **VSZ 3GB → 22GB (30초 만에 7배)**. RSS 1.2GB 만 보면 못 봄
- **frontend.log 결정 증거**: `resolve 'tailwindcss' in '.../apps'` (apps/web 아님)
- = **Turbopack root 자동 감지가 monorepo 패턴으로 잘못 추론** → tailwindcss resolve 무한 시도 → JS heap 누적 → swap thrashing → 9P 마운트 hang → D-state 좀비 → WSL freeze 악순환

## 적용된 fix (phh 에서 적용 끝)

- `apps/web/next.config.ts` — `fileURLToPath(import.meta.url)` 패턴 (`__dirname` ESM 함정 회피)
- `apps/web/package.json` — `"dev": "next dev --webpack"` (Next 16 공식 webpack fallback)
- `.wslconfig` 메모리 20GB + swap 8GB (응급 버퍼)
- `scripts/monitor_resources.sh` 신설 — D-state + 9P + wchan 진단
- `/mnt/c/Users/mpssh/Documents/wsl_logs/` 호스트 미러 — freeze 후에도 외부 진단

## 다른 워크스페이스가 주의할 것

- **Next 버전 올리지 말 것** (16.2.1 유지)
- **Tailwind 큰 버전 변경 시 재발 가능** (현재 4 사용)
- **`apps/web` 구조 변경 시 turbopack root 재검증 필수**
- **freeze 진단 시 RSS 가 아닌 VSZ + D-state wchan 봐야**

## 상세 기록

- 작업 항목 + Review: [tasks/todo-phh.md](tasks/todo-phh.md) 의 2026-05-28 섹션
- 학습 패턴: [tasks/lessons.md](tasks/lessons.md) 의 2026-05-28 패턴
