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
