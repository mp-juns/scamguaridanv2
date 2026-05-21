# Training Workflow — 분석 run → 라벨 → 학습 → 활성화

ScamGuardian 의 scam_type 분류기 (mDeBERTa) / content gate / GLiNER 추출기를 도메인
데이터로 fine-tune 하는 end-to-end 흐름. 라벨 데이터는 DB(`human_annotations`) + 외부
JSONL 둘 다 합쳐서 학습된다.

자세한 라벨 스키마는 [labeling_guide.md](labeling_guide.md) 참고.

---

## 0. 전제

- 이미 웹/카카오로 분석된 `analysis_runs` 가 DB 에 쌓여 있음 (`SCAMGUARDIAN_PERSIST_RUNS` 등)
- conda env `capstone` 활성 (또는 학습 deps 가 설치된 venv)

```bash
pip install -r requirements.txt
pip install -r training/requirements-train.txt
```

---

## 1. DB run → JSONL 초안 export

이미 분석된 run 들의 transcript·예측 결과를 JSONL 초안으로 뽑는다. 사람은 이후
`content_label` / `scam_type` / `sample_kind` 만 빠르게 검수하면 됨.

```bash
# 전체 run → data/run_drafts.jsonl
python -m scripts.export_runs_to_jsonl_draft

# 옵션
python -m scripts.export_runs_to_jsonl_draft \
    --output data/run_drafts.jsonl \
    --only-unlabeled \
    --scam-type "대출 사기" \
    --limit 100
```

**한 줄 schema** (`scripts/export_runs_to_jsonl_draft.py` 의 `build_draft`):

```json
{
  "run_id": "e7e3441a-963e-4ba5-bc0f-91027ea51397",
  "text": "여보세요? NH농협은행 대출 상담사 ...",
  "content_label": "undetermined",
  "sample_kind": "review_needed",
  "scam_type": "대출 사기",
  "entities": [{"text": "주민번호", "label": "개인정보 항목"}],
  "risk_flags": [{"flag": "personal_info_request"}],
  "source_ref": "https://youtube.com/watch?v=xx",
  "notes": "needs_human_review"
}
```

초안 규칙 (자동 추정):

| 필드 | 자동 채움 |
|---|---|
| `text` | `transcript_corrected_text` 우선, 없으면 `transcript_text` |
| `content_label` | gate.bucket == `scam_news_edu` 면 그 값, 그 외 `undetermined` (검수 강제) |
| `sample_kind` | 항상 `review_needed` |
| `scam_type` | classifier 예측값 그대로 |
| `entities` | `entities_predicted` 의 `{text, label}` 만 |
| `risk_flags` | `DETECTED_FLAGS` 화이트리스트 통과한 flag 만 + 중복 제거 |
| `source_ref` | `input_source` 가 `http(s)://` 면 그 URL, 아니면 `null` |
| `notes` | `"needs_human_review"` (배치 detection 용) |

---

## 2. 사람이 검수 (가장 시간 많이 듬)

JSONL 한 줄씩 열어서:

1. `content_label` 을 정정 — 명백한 사기 시도면 `scam_attempt`, 뉴스면
   `scam_news_edu`, 정상이면 `normal`, 모호하면 `undetermined` 또는
   `suspicious_insufficient`.
2. `scam_type` 예측이 맞는지 확인 — 틀리면 정정 (12개 + "기타 사기" 중 하나).
3. `sample_kind` 를 정정 — 실제 사기 통화·문자면 `real_scam_message`, 뉴스 기반 합성
   메시지면 `synthetic_scam_message`, 뉴스 본문이면 `scam_news_education`, 정상
   대화면 `normal_content`.
4. (선택) `entities` / `risk_flags` 정정·추가.
5. `notes` 의 `"needs_human_review"` 는 검수 완료 시 빈 문자열로.

검수 끝난 JSONL 은 `data/run_drafts.reviewed.jsonl` 식으로 저장 (덮어쓰기 추천 X).

---

## 3. 통계 확인 (학습 전 마지막 점검)

```bash
python -m training.dataset_summary --extra-jsonl data/run_drafts.reviewed.jsonl
```

기대 분포 (보통):

```
[content_label 별]
   45  scam_attempt
   12  scam_news_edu
    8  normal
    3  undetermined

[scam_type 별 — content_label == scam_attempt 만]
   15  대출 사기
   10  메신저 피싱
    8  투자 사기
    ...
```

`scam_news_edu` 가 너무 적으면 학습 후 뉴스 → 사기 오탐 위험 — 비율 보강 권장
(전체의 10~20% 정도).

---

## 4. 학습

### scam_type 분류기 (mDeBERTa)

```bash
SESSION_ID=$(date +%s)
mkdir -p ".scamguardian/training_sessions/${SESSION_ID}/output"

python -m training.train_classifier \
    --extra-jsonl data/run_drafts.reviewed.jsonl \
    --output-dir ".scamguardian/training_sessions/${SESSION_ID}/output" \
    --epochs 3 \
    --batch-size 8
```

또는 웹 UI: `/admin/training` → `extra_jsonl` 필드에 경로 입력 → 시작 클릭 →
진행률·log 실시간 확인.

### GLiNER 추출기

```bash
python -m training.train_gliner \
    --extra-jsonl data/run_drafts.reviewed.jsonl \
    --output-dir ".scamguardian/training_sessions/${SESSION_ID}/gliner_output"
```

---

## 5. 평가 (학습 전/후 정량 비교)

```bash
# scam_type 분류 평가 (scam_attempt 만 자동 필터링)
python -m training.eval_scam_type --records eval_records.jsonl

# content gate 평가 (normal / scam_attempt / scam_news_edu)
python -m training.eval_gate --records eval_records.jsonl

# 신호 평가 + baseline vs current 라벨 커버리지 비교
python -m training.eval_signals --records eval_records.jsonl --mode coverage
```

`eval_records.jsonl` 은 hold-out test split — `training.splits.group_train_val_test_split`
가 같은 `source_ref` 끼리 한 fold 로 묶어 leakage 방지.

---

## 6. 활성화 — 파이프라인에 swap

`/admin/training` 에서 학습 끝난 세션의 **"파이프라인 적용"** 클릭 →
`.scamguardian/active_models.json` 갱신 → 60초 TTL 안에 다음 분석부터 fine-tuned
모델 자동 사용 (`pipeline/active_models.py` 의 `invalidate()` 가 즉시 무효화).

수동 swap:

```bash
cat > .scamguardian/active_models.json <<EOF
{
  "classifier": ".scamguardian/training_sessions/${SESSION_ID}/output",
  "gliner": ".scamguardian/training_sessions/${SESSION_ID}/gliner_output"
}
EOF
```

검증:

```bash
# 같은 영상 다시 분석 → 신뢰도 % 가 22% → 70~90% 로 올라오는지 확인
python run_analysis.py "https://youtube.com/watch?v=..."
```

---

## 7. 자주 쓰는 한 줄 명령 모음

```bash
# DB → 초안 export (검수자 작업 큐)
python -m scripts.export_runs_to_jsonl_draft --only-unlabeled --output data/$(date +%Y%m%d)_drafts.jsonl

# 통계
python -m training.dataset_summary --extra-jsonl data/20260521_drafts.reviewed.jsonl

# 학습 + 자동 세션 디렉토리
SESSION_ID=$(date +%s) python -m training.train_classifier \
    --extra-jsonl data/20260521_drafts.reviewed.jsonl \
    --output-dir ".scamguardian/training_sessions/${SESSION_ID}/output"

# baseline vs current 효과 비교 (개인정보·악성 URL 커버리지)
python -m training.eval_signals --records data/eval_test.jsonl --mode coverage
```
