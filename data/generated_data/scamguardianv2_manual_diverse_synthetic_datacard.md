# ScamGuardian v2 manual diverse synthetic dataset

생성일: 2026-05-27

## 파일

- `scamguardianv2_manual_diverse_synthetic_2026-05-27.jsonl`: 총 282개
- `scamguardianv2_manual_diverse_synthetic_nodup_2026-05-27.jsonl`: 총 171개, 문자 3-gram 유사도 기준으로 근접 중복 제거

## 목적

ScamGuardian v2의 `training/data.py` 외부 JSONL 스키마에 맞춘 연구·학습용 데이터입니다.

- 실제 기업명, 실제 URL, 실제 전화번호, 실제 계좌번호를 포함하지 않습니다.
- `[URL_MASKED]`, `[PHONE_MASKED]`, `[ACCOUNT_MASKED]`, `[APP_LINK_MASKED]` 같은 슬롯을 사용합니다.
- 모든 샘플의 `augmentation.non_deployable`은 `true`입니다.
- `scam_attempt`는 `sample_kind=synthetic_scam_message`로 저장했습니다.
- `normal`은 hard negative 성격의 정상 안내/일상 메시지입니다.
- `scam_news_edu`는 사기 수법을 설명하는 교육성 문장입니다.

## 권장 사용

학습 전 통계 확인:

```bash
python -m training.dataset_summary \
  --extra-jsonl data/processed/scamguardianv2_manual_diverse_synthetic_nodup_2026-05-27.jsonl
```

게이트와 scam_type 분류기 학습:

```bash
SESSION_ID=$(date +%s)

python -m training.train_classifier \
  --extra-jsonl data/processed/scamguardianv2_manual_diverse_synthetic_nodup_2026-05-27.jsonl \
  --output-dir ".scamguardian/training_sessions/${SESSION_ID}/output" \
  --epochs 3 \
  --batch-size 8
```

## 주의

테스트셋에는 합성 샘플을 섞지 말고, 실제 검수 샘플을 hold-out으로 분리하는 편이 좋습니다.
합성 샘플은 gate/classifier의 초기 일반화 보강 용도로 사용하세요.
