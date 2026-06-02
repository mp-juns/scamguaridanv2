# Classifier Behavior

## Current Classifier Shape

현재 ScamGuardian 의 classifier 는 mDeBERTa 계열 sequence classification 모델을 사용한다.
학습 시에는 `training/train_classifier.py` 가 텍스트와 `scam_type` 라벨을 받아 multi-class classifier 로 fine-tune 한다.

추론 흐름은 개념적으로 다음과 같다.

```text
input text
  -> tokenizer
  -> subword tokens
  -> transformer encoder
  -> contextual representation
  -> classification head
  -> logits per scam_type
  -> softmax / ranking
```

## Does It Read the Whole Context?

대체로 그렇다.

모델은 `검찰`, `계좌`, `이체` 같은 단어 하나만 독립적으로 보는 것이 아니라, 토큰들이 문장 안에서
서로 어떤 문맥으로 연결되는지 계산한다.

예를 들어 아래 문장은 단어 하나보다 조합이 중요하다.

```text
검찰입니다. 본인 명의 계좌가 사건에 연루되어 안전계좌로 이체가 필요합니다.
```

가능한 신호 조합:

- 권위자 사칭: `검찰`
- 법적 압박: `사건에 연루`
- 금전 요구: `이체`
- 특수 표현: `안전계좌`
- 긴급성 또는 압박 문맥

모델은 이런 조합을 내부 표현으로 압축한 뒤 라벨별 점수를 만든다.

## Why It Is Still Hard to Explain

Transformer 는 각 토큰 간 attention 과 hidden state 를 계산하지만, 최종 분류 이유를 사람이 읽기 쉬운
규칙으로 그대로 내놓지는 않는다. 따라서 "모델이 정확히 이 단어 때문에 분류했다" 고 단정하기 어렵다.

그래도 다음 방식으로 근사적으로 추적할 수 있다.

## Practical Probes

### 1. Ablation Probe

핵심 표현을 하나씩 제거하고 confidence 변화를 본다.

```text
검찰입니다. 본인 명의 계좌가 사건에 연루되어 안전계좌로 이체가 필요합니다.
검찰입니다. 본인 명의 계좌가 사건에 연루되었습니다.
본인 명의 계좌가 사건에 연루되어 안전계좌로 이체가 필요합니다.
```

확인할 것:

- `검찰` 제거 시 기관 사칭 confidence 가 얼마나 줄어드는가?
- `이체` 제거 시 분류가 흔들리는가?
- `안전계좌` 가 있으면 기관 사칭으로 강하게 쏠리는가?

### 2. Counterfactual Probe

의미 구조를 유지한 채 surface token 을 바꾼다.

```text
검찰입니다. 안전계좌로 이체하세요.
금감원입니다. 안전계좌로 이체하세요.
고객센터입니다. 안전계좌로 이체하세요.
친구입니다. 안전계좌로 이체하세요.
```

확인할 것:

- 권위 기관명 변화에 민감한가?
- 같은 행동 요구가 다른 주체와 결합할 때 라벨이 바뀌는가?

### 3. Boundary Probe

비슷하지만 다른 유형을 비교한다.

```text
고수익 리딩방에 초대합니다. 입금하면 수익을 보장합니다.
거래소 VIP 매니저입니다. 보증금을 넣으면 출금 한도를 풀어드립니다.
연인 관계를 믿고 급히 돈을 보내달라고 요청합니다.
```

확인할 것:

- 투자 사기, 코인 사기, 로맨스 스캠의 경계가 어떤 feature 에서 갈리는가?
- hard negative 로 쓸 수 있는 샘플은 무엇인가?

## Link to ScamGenomeGraph

Classifier 의 내부 판단을 완전히 열 수 없다면, 데이터 바깥에 feature graph 를 만든다.

```text
model confidence change
  + feature profile
  + graph relation score
```

이 세 가지를 같이 보면 모델이 어떤 feature cluster 에서 안정적이고, 어디서 흔들리는지 연구할 수 있다.
