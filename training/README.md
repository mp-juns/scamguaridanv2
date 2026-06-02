# training/ — fine-tuning 골격

ScamGuardian 라벨 데이터(+AI Hub 등 외부)로 분류기·NER 모델을 도메인 특화 학습합니다.

## 설치

```bash
pip install -r training/requirements-train.txt
```

기본 `requirements.txt` 의 transformers/torch/gliner 위에 `peft / datasets / evaluate / accelerate / seqeval / scikit-learn` 만 추가됩니다.

## 데이터

소스는 두 가지를 동시에 받을 수 있습니다.

1. **사람 라벨링** (`human_annotations` 테이블) — `db.repository.fetch_annotated_pairs()` 가 정답 데이터를 반환. Admin UI 에서 라벨링한 결과가 자동으로 들어옵니다.
2. **외부 JSONL** (`--extra-jsonl path.jsonl`) — AI Hub 등에서 변환한 데이터. 각 라인:
   - 분류용: `{"text": "...", "label": "투자 사기"}` (label 비우면 정상 대화)
   - NER 용: `{"text": "...", "ner": [[start, end, "라벨"], ...]}` 또는 `{"text": "...", "entities": [{"text": "..", "label": ".."}]}`

먼저 통계만 점검:

```bash
python -m training.data
python -m training.data --extra-jsonl data/processed/aihub_calls.jsonl
```

## 모델 1 — mDeBERTa 분류기 (스캠 유형 12종 + 정상)

`pipeline/classifier.py` 가 사용하는 zero-shot mDeBERTa NLI 를 task-specific multi-class 분류기로 SFT.

```bash
# 빠른 점검
python -m training.train_classifier --dry-run

# 전체 학습 (LoRA 어댑터 적용 — 메모리 절약)
python -m training.train_classifier \
    --output-dir checkpoints/classifier-v1 \
    --epochs 3 --batch-size 8 --lora

# AI Hub 정상 콜센터 데이터 추가 (negative 보강)
python -m training.train_classifier \
    --output-dir checkpoints/classifier-v2 \
    --extra-jsonl data/processed/aihub_callcenter.jsonl \
    --epochs 3 --lora
```

산출물:
- `checkpoints/<name>/` — HuggingFace 모델 가중치 + tokenizer
- `checkpoints/<name>/label2id.json` — 추론 시 라벨 매핑

## 모델 2 — GLiNER (27개 스캠 엔티티)

`pipeline/extractor.py` 가 사용하는 `taeminlee/gliner_ko` 를 스캠 엔티티 라벨로 fine-tune.

```bash
python -m training.train_gliner \
    --output-dir checkpoints/gliner-v1 \
    --epochs 5
```

산출물:
- `checkpoints/<name>/train.json` / `val.json` — GLiNER 표준 포맷 (tokenized_text + ner)
- `checkpoints/<name>/labels.json` — 학습된 라벨 목록

> GLiNER 버전마다 학습 API 가 다릅니다. 본 스크립트는 0.2.x 에서 `model.fit()` 이 있으면 자동 학습, 없으면 JSON 만 저장합니다. 그 경우 [공식 fine-tune 가이드](https://github.com/urchade/GLiNER#fine-tune-on-your-own-data) 의 trainer 스크립트를 같은 JSON 으로 돌리면 됩니다.

## 권장 학습 분량

|  | 최소 | 권장 |
|---|---|---|
| 분류기 (라벨당) | 5건 | 50건+ |
| GLiNER (라벨당) | 30건 | 200건+ |

라벨이 부족할 때는:
- 사람 라벨링 큐(`/admin`) 진행
- AI Hub `dataset 98` 금융보험(정상) → negative 분류 보강
- AI Hub `dataset 71768` 119 신고 → 협박/위급 발화 보강
- Claude 합성 → 희귀 유형(코인·로맨스·납치협박) 채우기

## 학습된 모델 파이프라인 적용

`pipeline/classifier.py` 와 `pipeline/extractor.py` 의 모델 경로를 환경변수로 오버라이드하도록 추후 패치 예정. 현재는 `pipeline/config.py:MODELS` 에서 직접 교체합니다.
