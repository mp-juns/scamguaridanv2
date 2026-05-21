# 라벨링 가이드 — content_label 중심 학습 데이터

ScamGuardian 3단계 캐스케이드(게이트 → 유형 → 신호)를 위한 라벨링 기준 문서입니다.
학습 데이터는 "유튜브 뉴스 단순 라벨링"이 아니라 **콘텐츠 성격(content_label) + 실제
사기 시도 샘플 + 뉴스/교육 오탐 방지 샘플** 구조로 구성합니다.

---

## 1. content_label — 콘텐츠 성격 (필수 기준 라벨)

모든 샘플은 `content_label` 을 가집니다. Stage 1 게이트 분류기의 출력 공간
(`pipeline/config.py` 의 `GATE_BUCKETS`)과 **동일한 어휘**입니다.

| content_label | 의미 |
|---|---|
| `normal` | 사기와 무관한 일상적·정상적 콘텐츠 |
| `scam_attempt` | 콘텐츠 자체가 수신자를 속이려는 실제 사기 시도 |
| `scam_news_edu` | 사기를 *소재로 다루는* 뉴스·예방·교육 콘텐츠 |
| `suspicious_insufficient` | 사기 의심되나 단정할 신호 부족 |
| `undetermined` | 입력이 너무 짧거나 깨져 판단 불가 |

> 코드·JSONL 어디서나 `scam_news_edu` 를 씁니다 (게이트 어휘와 통일).

---

## 2. 학습 정책 — content_label 별 사용처

| content_label | scam_type 분류기 | content 게이트 분류기 | 비고 |
|---|---|---|---|
| `scam_attempt` | ✅ (label = scam_type) | ✅ (label = content_label) | scam_type 학습의 유일 소스 |
| `normal` | ❌ | ✅ | |
| `scam_news_edu` | ❌ | ✅ | 오탐 방지용 |
| `suspicious_insufficient` | ❌ | ❌ | review queue |
| `undetermined` | ❌ | ❌ | review queue |

- **scam_type 분류기**는 `content_label == scam_attempt` 인 샘플만 학습합니다 —
  뉴스·정상 콘텐츠를 유형 분류에 넣으면 "사기·피해·경찰" 단어만 보고 오탐합니다.
- `suspicious_insufficient` / `undetermined` 는 기본 학습셋에서 제외하고
  `load_review_queue()` 로 분리합니다.

---

## 3. sample_kind — 샘플의 출처·성격

| sample_kind | 의미 |
|---|---|
| `real_scam_message` | 실제 사기 문자/대화/통화 스크립트 |
| `synthetic_scam_message` | 뉴스/사례 기반으로 재구성한 실제 메시지형 샘플 |
| `scam_news_education` | 뉴스/예방/교육 콘텐츠 |
| `normal_content` | 정상 콘텐츠 |
| `review_needed` | 판단 보류 |

미지정 시 학습 로더가 `content_label` 로부터 추정합니다.

---

## 4. 유튜브 뉴스 처리 규칙 (중요)

- 유튜브 **뉴스·보도·예방 영상은 기본적으로 `scam_news_edu`** 후보입니다.
- 영상 안에 사기 문구가 *인용*되어 있어도, 전체 콘텐츠 목적이 보도·예방이면
  `scam_news_edu` 입니다.
- **단**, 영상 자체가 시청자에게 투자·송금·가입·링크 클릭·앱 설치·개인정보 제출을
  유도하면 `scam_attempt` 입니다.
- 핵심 판별: *"수신자를 속이려는 의도가 있는가"* — 있으면 `scam_attempt`,
  사기를 설명·경고하면 `scam_news_edu`.

---

## 5. synthetic 샘플 — 뉴스 수법을 메시지형으로 재구성

뉴스 원문을 그대로 `scam_attempt` 로 넣지 **않습니다**. 뉴스에서 확인된 수법을
바탕으로 *실제 메시지 형태*의 샘플을 따로 만들어 `sample_kind=synthetic_scam_message`
로 저장하고, `source_ref` 에 원본 뉴스 URL 을 연결합니다.

```
뉴스 원문 (scam_news_edu):
  "고수익을 미끼로 투자금을 요구한 사기 피해가 발생했다."
        │  수법 추출 → 메시지형 재구성
        ▼
synthetic_scam_message (scam_attempt):
  "원금 보장됩니다. 오늘 입금하시면 월 30% 수익 지급 가능합니다."
  source_ref = "https://news.example.com/article/123"
```

---

## 6. JSONL 스키마 (외부 학습 데이터)

학습 로더(`training/data.py`)의 `extra_jsonl` 인자로 받는 한 줄당 한 샘플:

```json
{
  "text": "원금 보장됩니다. 오늘 입금하시면 월 30% 수익...",
  "content_label": "scam_attempt",
  "scam_type": "투자 사기",
  "sample_kind": "synthetic_scam_message",
  "source_ref": "https://news.example.com/article/123",
  "entities": [{"text": "월 30%", "label": "수익 퍼센트"}],
  "risk_flags": ["abnormal_return_rate", "urgent_transfer_demand"]
}
```

- `scam_type` 은 `content_label == scam_attempt` 일 때만 학습 타깃으로 쓰입니다.
- 구 스키마(`{"text", "label"}`, label=scam_type) 도 하위호환 — `content_label`
  없으면 fallback: scam_type 명확 → `scam_attempt`, 아니면 `undetermined`.

예시 파일: `data/labeling_samples.example.jsonl`

---

## 7. risk_flags 의 의미 구분

`risk_flags`(=triggered_flags) 는 모든 content_label 에서 기록 가능합니다. 단 의미가
다릅니다:

- `scam_attempt` 의 risk_flags = **현재 입력에서 실행 중인 사기 신호**
- `scam_news_edu` 의 risk_flags = **보도된(언급된) 위험 신호** — 현재 입력의 사기
  실행 신호가 아님

라벨링·학습 시 이 둘을 혼동하지 않습니다.
