# Graph Schema

ScamGenomeGraph 는 heterogeneous graph 로 설계한다. 즉 모든 노드가 같은 종류가 아니다.

## Node Types

### Sample

개별 학습 데이터 또는 분석 사례.

필드:

- `sample_id`
- `text`
- `source`
- `source_ref`
- `content_label`
- `scam_type`
- `sample_kind`

### ScamType

사기 유형.

예:

- `기관 사칭`
- `투자 사기`
- `스미싱`
- `로맨스 스캠`
- `코인 사기`

### Signal

위험 신호 또는 판단 근거 후보.

예:

- `권위자 사칭`
- `긴급성`
- `금전 요구`
- `비밀 유지 요구`
- `외부 링크 유도`
- `수익 보장`
- `선입금 요구`

### EntityLabel

추출 대상 엔티티의 라벨.

예:

- `기관명`
- `사람이름`
- `금액`
- `계좌번호`
- `URL`
- `직함`
- `가상자산명`

### ExpressionPattern

반복적으로 나타나는 표현 패턴.

예:

- `안전계좌`
- `본인 명의가 도용`
- `오늘 안에`
- `원금 보장`
- `출금 한도 해제`
- `인증번호`

### RequestedAction

피해자에게 요구하는 행동.

예:

- `이체`
- `입금`
- `링크 클릭`
- `앱 설치`
- `인증번호 전달`
- `개인정보 제출`
- `대화 지속`

## Edge Types

### Sample -> ScamType

`HAS_TYPE`

샘플의 라벨.

### Sample -> Signal

`HAS_SIGNAL`

샘플에 나타난 위험 신호.

### Sample -> EntityLabel

`HAS_ENTITY_LABEL`

샘플 안에 등장한 엔티티 라벨.

### Sample -> ExpressionPattern

`USES_PATTERN`

샘플에 쓰인 반복 표현.

### Sample -> RequestedAction

`REQUESTS_ACTION`

샘플이 요구하는 행동.

### Sample -> Sample

`RELATED_TO`

두 샘플 사이의 관계. 단순 텍스트 유사도만 쓰지 않고 구조 유사도를 같이 쓴다.

## Relation Score

초기 relation score 는 해석 가능한 weighted sum 으로 시작한다.

```text
relation_score(a, b) =
  0.35 * embedding_similarity(a.text, b.text)
+ 0.20 * signal_jaccard(a.signals, b.signals)
+ 0.15 * entity_label_jaccard(a.entity_labels, b.entity_labels)
+ 0.15 * pattern_jaccard(a.patterns, b.patterns)
+ 0.10 * action_match(a.requested_actions, b.requested_actions)
+ 0.05 * scam_type_match(a.scam_type, b.scam_type)
```

이 가중치는 실험값이 아니라 초기 가설이다. 나중에 라벨 오류 탐지나 RAG 성능을 기준으로 조정한다.

## Useful Relation Buckets

### Same Type, Low Relation

같은 `scam_type` 인데 relation score 가 낮은 샘플.

가능한 의미:

- 라벨 오류
- 너무 다양한 subtype
- 유형 정의가 넓음
- synthetic template 이 과하게 벗어남

### Different Type, High Relation

다른 `scam_type` 인데 relation score 가 높은 샘플.

가능한 의미:

- hard negative
- 유형 경계가 겹침
- RAG 에서 주의해야 할 유사 사례

### Same Signal, Different Type

같은 위험 신호가 여러 유형에 걸쳐 나타나는 경우.

가능한 의미:

- 공통 사기 전략
- cross-type feature
- 분류기 혼동 원인

## Identity Boundary

이 그래프는 판정 시스템이 아니다. 그래프는 위험 신호와 데이터 관계를 보고한다.
최종 판정, 점수, 등급은 외부 통합 주체의 정책 영역으로 둔다.
