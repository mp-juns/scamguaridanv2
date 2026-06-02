# Experiments

이 문서는 ScamGenomeGraph 를 실제로 구현하기 전에 검증할 실험 계획이다.

## Experiment 1. Feature Profile Coverage

목표: 현재 synthetic / annotation 데이터가 graph feature 로 얼마나 설명되는지 확인한다.

방법:

1. 각 sample 에서 다음 feature 를 추출한다.
   - `scam_type`
   - `risk_flags` 또는 signal 후보
   - entity labels
   - expression patterns
   - requested actions
2. feature 가 비어 있는 샘플 비율을 계산한다.
3. 유형별 feature coverage 를 비교한다.

성공 기준:

- 대부분 샘플이 최소 2개 이상의 graph feature 를 가진다.
- 특정 유형만 feature 가 비는 현상이 있으면 schema 를 보완한다.

## Experiment 2. Same-Type Cohesion

목표: 같은 scam_type 샘플끼리 relation score 가 높은지 확인한다.

방법:

1. 각 sample 의 top-k related samples 를 계산한다.
2. top-k 중 같은 scam_type 비율을 측정한다.
3. embedding-only 와 graph-combined score 를 비교한다.

지표:

- same-type@5
- same-type@10
- mean relation score by scam_type

기대:

- graph-combined score 가 embedding-only 보다 유형 응집도를 높인다.

## Experiment 3. Boundary Mining

목표: 다른 scam_type 이지만 relation score 가 높은 pair 를 찾아 hard negative 후보로 만든다.

방법:

1. `different type, high relation` pair 를 수집한다.
2. 유형 조합별 빈도를 본다.
3. 사람이 일부 샘플을 검수한다.

관찰 후보:

- 투자 사기 vs 코인 사기
- 스미싱 vs 기관 사칭
- 로맨스 스캠 vs 투자 사기
- 대출 사기 vs 기관 사칭

활용:

- classifier fine-tuning hard negative set
- compare-analysis smoke set
- 라벨링 가이드 보강

## Experiment 4. Label Error Candidate Detection

목표: 같은 유형 안에서 너무 멀리 떨어진 샘플을 라벨 오류 후보로 찾는다.

방법:

1. 같은 scam_type 내 평균 relation score 를 계산한다.
2. 하위 percentile 샘플을 뽑는다.
3. 사람이 라벨/본문을 확인한다.

가능한 결과:

- 진짜 라벨 오류
- 정상 subtype
- feature extractor 부족
- synthetic template 이상

## Experiment 5. RAG Re-ranking

목표: RAG 검색에서 단순 semantic similarity 보다 graph relation score 를 섞으면 참조 품질이 좋아지는지 본다.

방법:

1. 입력 문장에 대해 embedding top-k 를 뽑는다.
2. 각 후보에 graph relation score 를 계산한다.
3. 다음 식으로 재정렬한다.

```text
rag_score =
  0.65 * embedding_similarity
+ 0.35 * graph_relation_score
```

평가:

- 같은 scam_type 참조 비율
- 같은 signal 참조 비율
- 사람이 보기에 설명에 도움되는 참조 비율

## Experiment 6. Classifier Spike Explanation

목표: 학습 중 loss spike 를 graph feature 로 설명할 수 있는지 본다.

방법:

1. `loss_spikes.jsonl` 의 hard samples 를 읽는다.
2. 각 sample 의 graph feature profile 을 만든다.
3. spike sample 이 특정 feature 조합에 몰리는지 확인한다.

확인할 것:

- 특정 scam_type boundary 에서 튀는가?
- 특정 signal 조합에서 튀는가?
- synthetic source 또는 template 에 몰리는가?
- 긴 문장 / 짧은 문장 / entity 과밀 샘플에서 튀는가?

## Minimal Report

처음 구현 후 생성할 리포트:

```text
research/scam_genome_graph/reports/
  feature_coverage.json
  same_type_cohesion.json
  boundary_pairs.jsonl
  label_error_candidates.jsonl
  rag_rerank_examples.jsonl
  loss_spike_explanations.jsonl
```
