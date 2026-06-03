# ScamGuardian Fine-tuning 가이드

ScamGuardian 의 검출 파이프라인에서 **학습 가능한 두 모델**(스캠 유형 분류기 · 엔티티 추출기)을
도메인 특화로 fine-tune 하는 전 과정을 다룹니다. 데이터 준비 → 합성 데이터 생성 → 학습 →
평가 → 파이프라인 적용까지 *재현 가능한 절차*로 정리했습니다.

> ⚠️ **Identity Boundary**: 본 문서가 다루는 `macro_f1`, `scam_type`, `content_label`,
> `risk_flags` 는 모두 **내부 학습/검출 지표**입니다. 외부 응답·UI 에 점수·등급으로 노출하지
> 않습니다 (`CLAUDE.md` Forbidden Actions 참조).

---

## 0. 한눈에 보기

```
[데이터 소스]                          [학습 대상]                 [파이프라인 위치]
 ├ 사람 라벨링 (human_annotations) ┐
 ├ 외부 JSONL (--extra-jsonl)      ├─→ training/data.py ─→ ① mDeBERTa 분류기   → Phase 2 (classifier.py)
 └ 합성 데이터 (generate_*.py)     ┘    (정규화·split)    └→ ② GLiNER 엔티티     → Phase 3 (extractor.py)

[보조 산출물] 합성 → build_synthetic_rag_index.py → 멀티뷰 RAG 인덱스 (Phase 3 rag.py 실험)
```

| 모델 | base | 역할 | 학습 스크립트 | 추론 위치 |
|---|---|---|---|---|
| **① 스캠 유형 분류기** | `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli` | scam_type 12종 multi-class | `training/train_classifier.py` | `pipeline/classifier.py` |
| **② 엔티티 추출기** | `taeminlee/gliner_ko` | 스캠 엔티티 NER | `training/train_gliner.py` | `pipeline/extractor.py` |

학습된 체크포인트는 `.scamguardian/active_models.json` 에 등록되면 파이프라인이 **자동 swap**
합니다 (60초 TTL 캐시, [pipeline/active_models.py](../pipeline/active_models.py)). 등록 전까지는
base zero-shot 모델로 동작하므로, 학습이 망가져도 서비스는 안전합니다.

---

## 1. 설치

```bash
pip install -r requirements.txt                  # 공통 (transformers/torch/gliner)
pip install -r training/requirements-train.txt   # 학습 전용: peft / datasets / evaluate / accelerate / seqeval / scikit-learn
```

---

## 2. 데이터 준비

학습 데이터는 **세 소스**를 동시에 받습니다. 모두 [training/data.py](data.py) 에서 동일한
`ClassifierExample` / `GlinerExample` 로 정규화됩니다.

### 2.1 소스 1 — 사람 라벨링 (`human_annotations` 테이블)

`/admin` 라벨링 큐에서 검수자가 확정한 정답이 자동으로 학습셋에 들어옵니다.
`db.repository.fetch_annotated_pairs()` 가 반환하며, `transcript_corrected_text` →
`transcript_text` 순으로 본문을 고릅니다.

### 2.2 소스 2 — 외부 JSONL (`--extra-jsonl path.jsonl`)

AI Hub 등 외부 데이터를 변환해 한 줄당 한 샘플로 넣습니다. **신규 스키마**(권장):

```jsonc
{
  "text": "...",                      // 필수
  "content_label": "scam_attempt",    // normal / scam_attempt / scam_news_edu / ...
  "scam_type": "투자 사기",            // scam_attempt 일 때 학습 타깃
  "sample_kind": "synthetic_scam_message",
  "source_ref": "synthetic_template/투자 사기/investment_vip_room",  // leakage 방지 split 키
  "entities": [{"text": "연 30%", "label": "수익 퍼센트", "start": 12, "end": 17}],
  "risk_flags": ["abnormal_return_rate", "urgent_transfer_demand"]
}
```

구 스키마(`{"text": "...", "label": "투자 사기"}`)도 호환됩니다 — `label` 을 `scam_type` 으로
간주하고 `content_label` 은 fallback 추정합니다.

> **왜 `content_label` 을 분리하나**: 뉴스 원문(`scam_news_edu`)을 `scam_attempt` 로 학습시키면
> "사기·피해·경찰" 같은 단어만 보고 오탐합니다. Stage 1 게이트가 정상/뉴스를 먼저 거르므로,
> scam_type 분류기는 *사기 시도로 확인된 콘텐츠 안에서 유형만* 배웁니다.

### 2.3 소스 3 — 합성 데이터 ([scripts/generate_synthetic_training_data.py](../scripts/generate_synthetic_training_data.py))

희귀 유형(코인·로맨스·납치협박·부동산 등)은 실데이터가 부족해 클래스 불균형이 심합니다.
이를 **템플릿 기반 합성**으로 메웁니다. 실데이터가 아니라 *허구의 자연스러운 값*으로 채운
메시지형 샘플입니다 (`[사람이름]` 같은 리터럴 placeholder 를 본문에 남기지 않음 — 값은 채우고
엔티티 라벨은 `entities[]` 에 별도 기록).

**구조 (12 scam_type × 5 템플릿 패밀리 = 60 템플릿):**

- **슬롯 채우기**: 템플릿의 `{slot:엔티티라벨}` 자리를 슬롯 사전(사람·회사·기관·금액·계좌·URL
  등)에서 뽑아 렌더. 금액·전화·계좌·URL·지갑주소 등은 난수 생성기로 만듭니다.
- **엔티티 span 자동 기록**: 문자열 검색이 아니라 *치환 위치*에서 `(start, end)` 를 따므로
  중복 값이 있어도 정확합니다 (`validate()` 가 `text[start:end] == entity.text` 로 전수 검증).
- **risk_flags + flag_groups**: scam_type 별 후보 플래그에서 2~4개를 뽑고,
  [pipeline/flag_groups.py](../pipeline/flag_groups.py) `group_of()` 로 의미 그룹을 함께 기록.
- **relations / rag_texts**: 그래프·RAG 용 보조 구조 (flag→scam_type `supports`,
  entity→label `typed_as`, 5뷰 `case/scenario/pattern/entity_pattern/evidence_terms`).
- **재현성**: 고정 `--seed` 로 동일 산출물. `source_ref` 가 *템플릿 패밀리 단위*라
  group-aware split 이 같은 템플릿 변형을 한 fold 에 묶어 **train/val leakage** 를 막습니다.

```bash
# 3000건 (유형별 균등 분배) — 기본
python scripts/generate_synthetic_training_data.py \
    --output data/generated/scamguardian_synthetic_3000.jsonl \
    --total 3000 --seed 20260601

# 12000건 (대량)
python scripts/generate_synthetic_training_data.py \
    --output data/generated/scamguardian_synthetic_12000.jsonl \
    --total 12000 --seed 20260601
```

출력 끝에 scam_type 별 건수 · 템플릿 패밀리 수 · 패밀리당 행 수가 찍힙니다.

> `data/generated/` 는 `.gitignore` 대상입니다 (스크립트로 재생성 가능 + 대용량). 커밋하지 않습니다.

### 2.4 보조 산출물 — 멀티뷰 RAG 인덱스 ([scripts/build_synthetic_rag_index.py](../scripts/build_synthetic_rag_index.py))

합성 샘플 한 건이 `rag_texts` 의 5뷰(case·scenario·pattern·entity_pattern·evidence_terms)로
펼쳐져 각각 SBERT 임베딩됩니다 (뷰별 가중치 + lexical boost). Phase 3 RAG 검색 실험용입니다.

```bash
python scripts/build_synthetic_rag_index.py build \
    --input data/generated/scamguardian_synthetic_3000.jsonl
python scripts/build_synthetic_rag_index.py query "검찰 안전계좌로 이체하라는 전화" --top-k 5
```

산출물: `data/generated/rag_index/` (`*_embeddings.npz`, `*_metadata.jsonl`, `*_manifest.json`).

### 2.5 데이터 통계만 점검 (학습 X)

```bash
python -m training.data                                                  # DB 라벨만
python -m training.data --extra-jsonl data/generated/scamguardian_synthetic_3000.jsonl
```

게이트/scam_type/리뷰큐/GLiNER 4개 로더의 라벨 분포를 출력합니다.

---

## 3. 모델 ① — mDeBERTa 스캠 유형 분류기

[training/train_classifier.py](train_classifier.py) — zero-shot NLI 분류기를 task-specific
multi-class 로 SFT. LoRA·early stopping·mixed precision 지원.

### 3.1 데이터 흐름 (스크립트 내부)

1. `load_classifier_dataset()` → `content_label == scam_attempt` & `scam_type` 있는 샘플만
2. `_ensure_min_per_class(min=5)` → 라벨당 5건 미만 클래스 제외 (학습 안정성)
3. `stratified_split(val_ratio=0.1)` → 라벨별 균형 분할 (희소 클래스 val 누락 방지)
4. 라벨 인코딩 → `label2id.json` 저장 (추론 시 필수)

### 3.2 학습 명령

```bash
# 데이터 통계만 (빠른 점검)
python -m training.train_classifier --dry-run \
    --extra-jsonl data/generated/scamguardian_synthetic_3000.jsonl

# LoRA fine-tune (메모리 절약, 권장)
python -m training.train_classifier \
    --output-dir checkpoints/classifier-v1 \
    --extra-jsonl data/generated/scamguardian_synthetic_3000.jsonl \
    --epochs 3 --batch-size 8 --lr 2e-5 \
    --lora --bf16 \
    --early-stopping-patience 2
```

### 3.3 주요 옵션

| 옵션 | 기본 | 설명 |
|---|---|---|
| `--lora` | off | PEFT/LoRA 어댑터 학습 (target: `query/value/key_proj`, `dense` + `modules_to_save=[classifier, pooler]`) |
| `--lora-r` / `--lora-alpha` / `--lora-dropout` | 16 / 32 / 0.1 | LoRA 하이퍼파라미터 |
| `--fp16` / `--bf16` | off | CUDA mixed precision. LoRA 는 `--bf16` 권장 (fp16 NaN 회피) |
| `--early-stopping-patience` | 2 | `eval_macro_f1` 개선 없는 epoch 허용 횟수. `0` 이면 비활성 |
| `--early-stopping-threshold` | 0.0 | 개선으로 인정할 최소 증가폭 |
| `--min-per-class` | 5 | 라벨당 최소 샘플 수 |
| `--base-model` | mDeBERTa-v3 | base 모델 교체 (ablation 용) |

`metric_for_best_model="macro_f1"` + `load_best_model_at_end=True` 로 **best epoch** 를 저장합니다.

### 3.4 산출물 + PEFT 로딩

```
checkpoints/classifier-v1/
├── label2id.json                  # 추론 라벨 매핑 (필수)
├── adapter_model.safetensors      # LoRA 어댑터 (--lora 시) 또는
├── model.safetensors              # 풀 모델 (--lora 미사용 시)
└── adapter_config.json            # base_model_name_or_path 등
```

[pipeline/classifier.py](../pipeline/classifier.py) `_load_finetuned_model()` 가 체크포인트를 보고
자동 분기합니다 — `adapter_config.json` 이 있으면 **base 모델 + PeftModel** 로 어댑터를 얹고,
없으면 풀 시퀀스 분류기를 그대로 로드합니다. `label2id.json` 으로 라벨 head 크기를 맞춥니다.

---

## 4. 모델 ② — GLiNER 엔티티 추출기

[training/train_gliner.py](train_gliner.py) — `taeminlee/gliner_ko` 를 스캠 엔티티 라벨로 fine-tune.

```bash
python -m training.train_gliner --output-dir checkpoints/gliner-v1 --epochs 5
```

산출물: `train.json` / `val.json` (GLiNER 표준 `tokenized_text + ner`), `labels.json`.

> GLiNER 버전마다 학습 API 가 다릅니다. 본 스크립트는 `model.fit()` 이 있으면 자동 학습,
> 없으면 JSON 만 저장합니다 — 그 경우 [공식 fine-tune 가이드](https://github.com/urchade/GLiNER#fine-tune-on-your-own-data)
> 의 trainer 를 같은 JSON 으로 돌립니다. char→token span 변환은 `training/data.py` 가 처리합니다.

---

## 5. 웹 UI 로 학습 (`/admin/training`)

[training/sessions.py](sessions.py) 가 학습을 **백그라운드 subprocess** 로 띄우고 파일 기반으로
상태를 관리합니다 (`.scamguardian/training_sessions/{id}/{status.json, metrics.jsonl, train.log}`).

- **진행률**: `MetricsEmitCallback` 이 매 log/eval/epoch 마다 `metrics.jsonl` 에 한 줄씩 기록 →
  UI 가 폴링하며 recharts 그래프로 표시.
- **상태 보정** (2026-06-01): `_refresh_status()` 가 ① 산출물(`label2id.json` +
  `*.safetensors`)이 있으면 watcher 가 clean exit 을 놓쳐도 `completed` 로 승격,
  ② 최근 120초 내 활동이 있으면 죽은 PID 오판으로 `failed` 처리하지 않음 → **"가짜 실패"** 제거.
- **early stopping 파라미터**가 세션 요청(`StartTrainingRequest`)에서 학습 CLI 인자로 전달됩니다.

### 모델 활성화 (파이프라인 swap)

`/admin/training` 의 **"파이프라인 적용"** → `.scamguardian/active_models.json` 갱신 →
`active_models.invalidate()` 즉시 반영. 경로가 무효면 base 모델로 자동 fallback.

---

## 6. 원본 ↔ Fine-tuned 비교 분석 (2026-06-01 신규)

학습 결과가 실제로 나아졌는지 **나란히 비교**하는 도구를 `/admin/training` 에 추가했습니다
([api_server_pkg/admin_training.py](../api_server_pkg/admin_training.py)).

| 엔드포인트 | 용도 |
|---|---|
| `GET /api/admin/training/synthetic-summary` | 합성 코퍼스 통계 + 지식그래프(scam_type↔flag_group↔entity) 데이터 |
| `POST /api/admin/training/sessions/{id}/compare` | 스모크셋으로 zero-shot ↔ 체크포인트 분류 결과 대조 |
| `POST /api/admin/training/compare-analysis` | 임의 입력(text/URL)을 원본·학습 모델 양쪽으로 분석해 예측·일치 여부 표시 |

UI([TrainingClient.tsx](../apps/web/src/app/admin/training/TrainingClient.tsx)): `ClassifierComparisonPanel`,
`ModelComparePanel`, Canvas 기반 `KnowledgeGraphCanvas`(합성 데이터 관계 시각화), 초보자용 학습
단계 설명을 포함합니다.

---

## 7. 권장 학습 분량

| | 최소 | 권장 |
|---|---|---|
| 분류기 (라벨당) | 5건 | 50건+ |
| GLiNER (라벨당) | 30건 | 200건+ |

라벨이 부족할 때:
- 사람 라벨링 큐(`/admin`) 진행
- **합성 데이터 생성**(§2.3)으로 희귀 유형 즉시 보강
- AI Hub `dataset 98`(금융보험 정상) → negative 보강, `dataset 71768`(119 신고) → 협박/위급 발화 보강

---

## 8. 명령어 빠른 참조

```bash
# 1) 합성 데이터 생성
python scripts/generate_synthetic_training_data.py --total 3000 --seed 20260601
# 2) (옵션) RAG 인덱스
python scripts/build_synthetic_rag_index.py build
# 3) 데이터 통계 점검
python -m training.train_classifier --dry-run --extra-jsonl data/generated/scamguardian_synthetic_3000.jsonl
# 4) 분류기 학습 (LoRA + early stopping)
python -m training.train_classifier --output-dir checkpoints/classifier-v1 \
    --extra-jsonl data/generated/scamguardian_synthetic_3000.jsonl --epochs 3 --lora --bf16
# 5) /admin/training 에서 "파이프라인 적용" → active_models.json 등록 → 자동 swap
```
