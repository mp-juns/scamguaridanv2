# ScamGuardian 대화 정리

> 학부 졸업 프로젝트 ScamGuardian의 정체성·전략·실행 계획에 대한 멘토링 대화 전체 기록.
> 핵심: 7번의 self-correction을 거치며 "다단계 인터럽트 시스템"에서 "클라이언트-agnostic 검증 엔진 reference implementation"으로 reframe.

---

## Part 1. 첫 진단 — README 비판

처음 너가 GitHub README 링크를 던지면서 "냉정하게 비판해라"고 했다. 일반론으로 다음 약점을 지적했다.

**좋은 점**
- "catch-net" framing (단발 차단 99% vs 다단계 80%×4=99.84%)이 학부생 수준에선 영리함
- Phase 0.5 sandbox 물리 분리 (`--read-only --cap-drop=ALL`) 실무 감각 있음
- 비용 ledger 분리 (Claude/OpenAI/Serper/VT) — 학부에서 자주 빠뜨리는 부분 챙김

**비판**
1. 핵심 가설(다단계 인터럽트가 효과적) 검증 데이터 0 — 학술 인용만 있고 user study 없음
2. Stage 1 (실시간 STT) 미구현인데 catch-net 수학은 4단계 작동 전제
3. 플래그 점수(15/20/50/80) 학술 근거 없는 직관
4. "metacognitive interruption efficacy"가 학술적 새 영역이라는 자기평가 과함
5. 카카오 채널 구조적 한계 (PDF·APK 첨부 차단)
6. 어드민 인증 미완·webhook signature 미구현·인메모리 데이터 등 production 톤과 실제 갭

→ 결론: "잘 만든 엔지니어링 + 영리한 framing"이지만 "다단계 인터럽트 시스템"의 약속을 못 지킴.

---

## Part 2. 학술 근거 + 시장 차별화 리서치

너가 "그럼 왜 굳이 GPT/Gemini/Claude 두고 내 거 써야 하는지 답해야 한다"고 했다. Extended research로 다음 정리:

**학술 근거 (질문 1+2)**
- Loewenstein (1996) visceral influence: hot state에서 판단력 저하
- Mullainathan & Shafir (2013) scarcity tunneling: IQ 13점 떨어짐 (수면 박탈 수준)
- Stajano-Wilson (2009) 7원칙 / Cialdini 6원칙 / Gragg 7트리거 / Whitty SPT 모델
- 한국 KCI 논문: 정고은 (2017), 오세연·송혜진 (2023), 강석구 (2008)
- Tanaka et al. (2020 PMC7378759): self-voice가 self-awareness 유도, cheating 억제 — 동아시아권 실증
- ImmuniFraug (arXiv 2601.06774, 2026): 메타인지 개입 RCT n=846, p=0.026 — 사기 영역 직접 검증
- 자본시장법 제49조 / 통신사기피해환급법 제2조 / 형법 제283조 — 점수 정당화의 법적 근거

**시장 분석 (질문 3)**
- 후후 (4,680만 통화), 더치트 (1,411만 가입자, 누적 1조 6,879억 피해 예방), 시티즌코난 (경찰청 협력, 35,000+ APK 탐지), SKT 스캠뱅가드 (월 19만건 경고), KT 후후 (정확도 97.2%), LG 익시오 (온디바이스 + 안티딥보이스)
- 글로벌 솔루션(Truecaller, Hiya): 한국 진입 거의 실패 (한국어 DB 부족, 통신사·후후 우위)
- 금감원 2023 피해 1,965억 → 2025 1Q 3,116억 (전년 동기 대비 2.2배 급증)

→ **단일 기능 단위로는 ScamGuardian이 모두 진다.** 살길은 4가지 결합 niche.

---

## Part 3. 7번의 Self-Correction (핵심)

이 대화의 진짜 가치는 여기다. 너가 본인 의도를 점진적으로 명확히 하면서 narrative를 7번 reframe했다.

### Self-correction 1: "다단계 인터럽트 시스템" → "Reference Implementation"
- 너 발언: "그냥 길을 연다는 거지 진짜 그걸 하겠다는 게 아냐"
- 깨달음: ScamGuardian은 직접 운영 제품이 아니라 design probe / integration blueprint
- 결과: README의 production 톤을 "reference implementation"으로 재표현 필요

### Self-correction 2: "한국 시장 진입 채널" → "클라이언트-agnostic 백엔드"
- 너 발언: "내가 카톡으로 한 이유는 단 하나야 — 사용자가 쉽게 쓰려고. FastAPI로 JSON 하나만 보내면 되니까"
- 깨달음: 카톡은 데모용 thin client이고, 진짜 product는 JSON in / JSON out 백엔드
- 결과: 디스코드·텔레그램·웹·통신사 앱 등 어느 클라이언트도 같은 endpoint를 호출 가능

### Self-correction 3: "사기 진행 중 hot state 개입" → "Cold state 검증"
- 너 발언: "사용자가 통화 중에 굳이 어 나 사기당하고 있구나 그럼 내 플랫폼 들어가서 음성 권한 부여해야겠다가 더 말이 안 되지 않음?"
- 깨달음: Loewenstein·Mullainathan 학술 근거 자체가 hot state에서 능동 제출 불가능을 말함 — ScamGuardian의 학술 근거가 본인 use case를 무력화
- 결과: 사후 검증 + 가족 대리 + 학습용 — 모두 cold state 가정 use case로 reframe

### Self-correction 4: "verification engine as a service"
- 너 발언: "그냥 음성·영상·APK 다운링크를 너네 플랫폼에서 우리한테 보내주기만 해라. 바이러스 검증·샌드박스·무결성·웹 팩트체크는 우리가 한다 이거니까"
- 깨달음: 가치 명제가 한 줄로 정리됨. 검증 엔진을 SaaS로 분리하고, 사용자 onboarding·UX는 클라이언트 책임
- 결과: 약속의 boundary가 명확해짐 → 책임·SLA·response schema 설계 가능

### Self-correction 5: "Moat는 데이터 라벨링 + Fine-tuning"
- 너 발언: "유일한 우리 플랫폼은 데이터 라벨링이랑 파인튜닝임"
- 깨달음: API 백엔드는 commodity, 누적되는 한국어 멀티모달 사기 라벨 데이터셋 + fine-tuned 모델이 진짜 자산
- 결과: 후후·더치트 등 단일 채널 솔루션은 따라잡을 수 없는 moat 가능성

### Self-correction 6: "GLiNER + SBERT는 로컬, LLM은 클라우드 — Hybrid"
- 너 발언: "그래도 GLiNER랑 BERT 내 컴에서 하잖아"
- 깨달음: 작은 모델(GLiNER, KoSBERT)은 로컬이 빠르고, 큰 모델(LLM)은 클라우드가 한국어 reasoning quality 강함
- 결과: 3-tier hybrid architecture — latency·비용·프라이버시 trade-off 결과로 정당화

### Self-correction 7: "LLM Fine-tuning 대신 Prompt Engineering"
- 너 발언: "원랜 로컬 LLM 파인튜닝 할려 했는데 걍 프롬프트 엔지니어링 최적화로 API 보내고 하는 거지"
- 깨달음: 학부 6주에 LLM fine-tuning은 비현실적 + Claude Sonnet 4.7 + 좋은 prompt 못 이김. 작은 모델은 fine-tune (GLiNER), 큰 모델은 prompt
- 결과: prompt를 "코드처럼" 버전 관리(v1-v5) + 학술 근거를 prompt에 직접 박아 자체 평가셋으로 메트릭 측정 (= prompt as research artifact)

---

## Part 4. 도달한 ScamGuardian 정체성

위 7번의 self-correction이 결합되면 다음 한 줄이 나온다.

> **"ScamGuardian은 cold state 사용자(사후 검증·가족 대리·학습자)가 멀티모달 의심 자료(URL/파일/이미지/PDF/통화 녹음)를 어떤 클라이언트(카톡·디스코드·텔레그램·웹·통신사 앱)에서든 JSON으로 던지면, GLiNER+KoSBERT 로컬 분석 + LLM 클라우드 rationale + VirusTotal+Sandbox 검증을 거쳐 점수·rationale·법조항 매핑된 응답을 돌려주는 클라이언트-agnostic verification engine API의 reference implementation이다. 학술 근거(Loewenstein·Tanaka·ImmuniFraug)와 한국 법조항(자본시장법 제49조·통신사기피해환급법 제2조)을 prompt와 스코어링에 직접 매핑한 design probe로서, 통신사·후후·더치트가 못 다루는 '능동 제출형 멀티모달 검증' 영역의 design space를 작동하는 코드로 보여준다."**

### 차별화 4축 (모두 결합돼야 성립)
1. 멀티모달 단일 진입점
2. 메타인지 trip-wire (본인 행동 거울 메시지)
3. 점수 + rationale + 법조항 매핑 (transparency)
4. 클라이언트-agnostic JSON API

### 약점 인정 (정직성)
- 데이터 우위 0에서 시작
- 사용자 onboarding은 클라이언트 책임이라 ScamGuardian 자체로는 사용자 0
- 메타인지 trip-wire 효과의 자체 RCT 없음 (n=10 user study로 일부 보완 예정)
- 정식 ISMS-P·법무 검토·통신사 공식 자문은 학부 단계 가능 범위 밖 (future work)

---

## Part 5. 졸업 전략 — Path A vs Path B

너 질문: "그냥 될 거라 가정하고 만들었습니다 할지, 아니면 보안 전문가·법 집행기관 자문 받아가며 진짜로 만들지"

**Path A (가정 기반)**: 학술 근거 + 작동하는 코드. weight 가벼움.
**Path B (자문 검증)**: 같은 졸업 일정 + 외부 자문으로 검증된 결과물. weight 무거움. 운영은 안 함.

→ **결론: Path B의 학부생이 받을 수 있는 부분만**.

학부 단계에서 가능한 자문 (응답률 순):
1. ★ **보이스피싱 피해자 인터뷰 1-2명** (본인·가족·지인) — 가장 무거움
2. **지도교수 네트워크 1명** (보안·HCI·법학) — 가장 reliable
3. **보안 엔지니어 (LinkedIn 콜드)** 또는 **사이버수사대 일선 수사관** 중 1명
4. **로스쿨 박사과정** (자본시장법 매핑 검토) — 학교 내 있으면

학부 단계에서 어려운 자문:
- 대형 로펌 (시간당 비용)
- SKT/KT/LG U+ 보이스피싱팀 (NDA, 대기업 단위)
- 금감원·국과수 K-VoM팀 (보안 등급)

→ **6명 다 노리지 말고 3-4명만**. 첫 2주 안에 컨택 폭격 안 하면 두 달이 한 달 됨.

---

## Part 6. 인프라·하드웨어 점검

작업하는 머신:
- AMD Ryzen 5 7500F (Zen 4, AM5)
- MSI PRO B650M-P
- DDR5-4800 32GB (16GB × 2, DIMMA2/B2)
- **RTX 5070 Ti** (16GB GDDR7) — 학부 워크스테이션치고 매우 좋음
- 슬롯 4개, 최대 128GB 지원

**RAM 96GB 업그레이드 검토 결과: 보류 권장.**
- AMD AM5에서 4슬롯 다 채우면 DDR5-4800 → 3600~4000으로 강제 다운클럭 (가장 큰 함정)
- ScamGuardian + GLiNER fine-tune 워크로드는 32GB로 충분
- LLM fine-tuning까지 욕심내면 64GB (32GB × 2 교체) 합리적
- 96GB는 학부 6주 일정 안에서 활용 못 함

**5070 Ti가 의미하는 것:**
- GLiNER LoRA fine-tune 30분~2시간이면 가능 → moat의 첫 prototype 학부 일정 내 가능
- KoSBERT 임베딩 + Whisper faster-whisper 모두 로컬에서 ms 단위 추론
- LLM은 클라우드 가는 것이 정답 (Qwen 7B로 Claude 못 이김)

---

## Part 7. 6주 워크스트림

3개 워크스트림 병렬 + 평가셋 100건이 hub.

### WS1: 데이터 라벨링 + Fine-tuning → 진짜 moat
- Week 1: 100건 시나리오 list 설계
- Week 2-3: 라벨링 (라벨러 2-3명, Cohen κ ≥ 0.6), 사기 50 + 정상 30 + ambiguous 20
- Week 4: GLiNER LoRA fine-tune (5070 Ti)
- Week 5: base vs fine-tuned F1 비교
- Week 6: 발표 자료 통합
- Deliverable: ko-scam labeled dataset, GLiNER fine-tuned checkpoint, F1 비교 표

### WS2: Prompt Engineering + 메타인지 Trip-wire → 학술 차별화
- Week 1: 코드 마스터링 (architecture map 직접 그리기)
- Week 2: prompt v1-v3 (baseline → few-shot → CoT)
- Week 3-4: prompt v4-v5 (학술 근거 직접 매핑 + Tanaka 2020 self-voice mirroring)
- Week 5: 사람평가 n=10 (trip-wire quality 1-5점)
- Week 6: 발표 자료 통합
- Deliverable: prompts/v1~v5 git history, eval metrics 4종, 사람평가 결과

### WS3: API 구조 구체화 → reference implementation 자격
- Week 1: 레포 rename (`scamguaridanv2` → `scamguardian`, 오타 수정)
- Week 2: OpenAPI 3.1 spec
- Week 3: 스코어링 v2 (Sigmoid 정규화 + Combo bonus)
- Week 4: 디스코드 봇 (2번째 클라이언트 — agnostic 주장 증명)
- Week 5: ROC + use case profile (banking/education/general)
- Week 6: 발표 자료 통합
- Deliverable: openapi.yaml, 카톡+디스코드 dual client, 스코어링 v2 + ROC 표

★ **평가셋 100건이 hub** — Week 1-2 안에 set up 안 되면 3 워크스트림 모두 절뚝거림. Critical path.

---

## Part 8. 폐기된 것들 (이전 narrative에서 빠져야 할 것)

self-correction을 거치면서 폐기된 표현·접근:
- ❌ "Catch-net 99.84%" (Stage 1 실시간 인터럽트가 hot state 사용자를 잡는다는 가정)
- ❌ "사기 진행 중 사용자가 능동적으로 ScamGuardian 사이트 접속" use case
- ❌ "통신사 대체" narrative
- ❌ 점수 가중치(15/20/50/80)를 직관으로 정당화
- ❌ VirusTotal 단일 임계값으로 80점 매핑
- ❌ 로컬 LLM (Qwen 7B 등) fine-tuning 시도
- ❌ "production" 톤 README

대체된 표현:
- ✅ "Cold state 사용자 능동 제출형 검증"
- ✅ "통신사가 못 다루는 능동 제출형 멀티모달 채널 보완"
- ✅ "라벨러 합의 + ROC + logistic regression 기반 스코어링"
- ✅ "Maat ML 라벨링으로 보정한 VirusTotal 신호"
- ✅ "GLiNER fine-tune (작은 모델) + LLM prompt engineering (큰 모델)"
- ✅ "Reference implementation / design probe"

---

## Part 9. 졸업 발표·자문·피칭용 모범 답안 (1문단)

> "ScamGuardian은 사기 진행 중 실시간 개입이 아니라, cold state에 있는 사용자(사후 검증·가족 대리·학습자)가 멀티모달 의심 자료(URL/파일/이미지/PDF/통화 녹음)를 어떤 클라이언트에서든 능동 제출하면 점수·rationale·메타인지 거울로 응답하는 클라이언트-agnostic verification engine API의 reference implementation입니다. Loewenstein(1996) visceral influence·Tanaka et al.(2020) self-voice OSA·ImmuniFraug(2026 RCT, n=846, p=0.026) 메타인지 개입 학술 근거와 자본시장법 제49조·통신사기피해환급법 제2조 법조항을 prompt와 스코어링에 직접 매핑했고, 한국어 사기 도메인 라벨 100건으로 GLiNER fine-tuning을 수행해 base 대비 F1 X%p 향상을 확인했습니다. 통신사 통화 인프라 영역과 정면 승부하지 않고, 후후 발신 DB·더치트 계좌 DB·통신사 통화 단일 채널이 못 다루는 '능동 제출형 멀티모달 검증' 영역의 design space를 작동하는 코드로 보여주는 것이 목표입니다. 학부 단계 reference implementation으로서 단일 진실을 약속하지 않으며, 정식 ISMS-P·법무 검토·통신사 공식 자문은 운영 단계의 future work입니다. 본 시스템은 보이스피싱 피해 경험자 N인 인터뷰·KISA 정책팀 통계 검증·사이버수사대 일선 수사관 현장 검증·로스쿨 박사과정 법조항 검토·보안 엔지니어 false positive·sandbox 한계 검증을 거쳤습니다."

---

## Part 10. 다음 액션

### 이번 주말 안에
- [ ] GitHub 레포 rename (`scamguaridanv2` → `scamguardian`)
- [ ] `git reflog`로 옛날 로컬 stack(Whisper + SBERT + LLM 로컬) 흔적 복구 시도
- [ ] 자문 컨택 메일 5건 던지기 (지도교수 / 피해자 가족·지인 / 보안 엔지니어 LinkedIn / 사이버수사대 / 로스쿨)
- [ ] 평가셋 100건 시나리오 list 카테고리별 breakdown 작성

### Week 1 안에
- [ ] 코드 마스터링 — architecture map 손으로 그리기, 모듈 10개 each 3줄 책임 정리, critical path 함수 5-10개 줄 단위 이해
- [ ] `CLAUDE.md` + `tasks/todo.md` + `tasks/lessons.md` 레포 추가

### 졸업 일정 6주 끝까지
- 위 6주 워크스트림(WS1·WS2·WS3) 진행
- 자문 미팅 3-4회 진행 + 결과 narrative 반영

---

## 마지막 한 줄

이 대화의 진짜 가치는 시각화·학술 리서치·시장 분석이 아니라, **너가 본인 프로젝트를 7번 self-correct한 능력**이다. 발표·자문·피칭에서 이 self-correction 과정 자체를 한 슬라이드로 보여주면 — "처음엔 다단계 인터럽트로 시장 점유한다고 생각했지만, 학술 근거 검토하면서 hot state 가정이 무너진다는 걸 깨닫고, 클라이언트-agnostic verification engine으로 reframe했다" — 이게 학부 reference implementation에서 보여줄 수 있는 가장 무거운 narrative다.
