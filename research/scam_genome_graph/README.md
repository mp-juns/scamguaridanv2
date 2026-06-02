# ScamGenomeGraph

ScamGenomeGraph 는 사기 데이터를 단순한 `text -> scam_type` 학습 샘플로만 보지 않고,
사기 유형, 위험 신호, 엔티티, 표현 패턴, 요구 행동 사이의 관계 구조로 해석하려는 연구 노트다.

목표는 시각화 자체가 아니다. 핵심은 데이터 간 연결성과 특징 간 연결성을 정의해서
fine-tuning, RAG, 라벨 검수, hard negative mining 에 활용하는 것이다.

## Research Question

사기 탐지 데이터셋에서 텍스트 임베딩 기반 유사도와 위험 신호 기반 구조 유사도를 결합하면,
단순 분류 학습보다 라벨 검수, hard negative mining, RAG 검색 품질을 개선할 수 있는가?

## Why

현재 classifier 는 전체 문맥을 보고 `scam_type` 을 예측한다. 하지만 모델 내부가 어떤 특징을
얼마나 근거로 삼았는지는 완전히 투명하지 않다.

대신 데이터 바깥에 별도의 관계 지도를 만들 수 있다.

```text
sample
  -> scam_type
  -> signal
  -> entity_label
  -> expression_pattern
  -> requested_action
  -> similar_sample
```

이 구조를 만들면 다음 질문을 던질 수 있다.

- 같은 유형인데 관계 구조가 지나치게 먼 샘플은 라벨 오류인가?
- 다른 유형인데 관계 구조가 매우 가까운 샘플은 hard negative 인가?
- RAG 가 단순히 비슷한 문장이 아니라 같은 위험 신호 구조를 가진 사례를 찾는가?
- 분류기가 틀리는 샘플은 어떤 신호/표현/행동 조합에서 많이 발생하는가?

## Files

- `classifier_behavior.md`  
  현재 classifier 가 입력 문장을 어떻게 처리하고 분류하는지 설명한다.

- `graph_schema.md`  
  ScamGenomeGraph 의 node, edge, relation score 초안이다.

- `experiments.md`  
  구현 전 검증 가능한 실험 계획이다.

- `schema.example.json`  
  샘플 1개를 관계 구조로 표현한 예시다.

## First Implementation Target

처음부터 GNN 이나 복잡한 시각화로 가지 않는다.

1. synthetic JSONL 을 읽는다.
2. sample 별 feature profile 을 만든다.
3. pairwise relation score 를 계산한다.
4. 각 sample 에 대해 top-k related samples 를 뽑는다.
5. 같은 유형 top-k, 다른 유형 top-k, 라벨 오류 후보를 리포트한다.

이후 필요하면 RAG ranking 에 relation score 를 추가하거나, graph embedding / GraphSAGE / GAT 로 확장한다.
