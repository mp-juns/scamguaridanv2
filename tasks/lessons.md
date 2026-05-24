# Lessons — 패턴 모음

작업 중 발견한 패턴·교정 기록. 같은 실수를 반복하지 않으려는 self-improvement loop 의 누적 자산.
최신이 위.

---

## 2026-05-24 — LLM max_tokens 단축은 라우팅 결정에 *대규모* 회귀

**관찰**: gate.py 의 `max_tokens 120 → 60` 으로 줄여 ~0.5s latency 절약 시도 → Haiku 출력 JSON 이 60 토큰에서 잘림 → 파서 실패 → fallback bucket = `undetermined` → 라우팅이 보수 모드로 Phase 2 + Phase 3 LLM 전체 실행 → **분석 시간 12s → 33-40s 폭증** (2배 이상 악화). 14:34, 14:40 두 분석 모두 동일 transcript 에 동일 fallback.

**근본 원인**: Haiku JSON 응답이 한국어 reason 필드 (~30-40 토큰) 포함하면 정확히 60 토큰 근처에서 잘림. 파서는 빈 dict 반환 → bucket 무효 → fallback. fallback bucket 이 `undetermined` 였기 때문에 *최악의 라우팅 결정* (보수 = 전체 실행) 으로 이어짐.

**처방**:
1. **LLM output token 캡은 *디버깅 마진의 2-3 배* 로 설정** — 예상 출력 길이 측정 후 그 ~2배 (60 토큰 예상 → 120 cap). 0.5s 의 latency 가치는 fallback 시 20+초 잃는 위험 대비 무가치.
2. **파서 fallback bucket 선택이 라우팅 비용을 좌우** — gate fallback 이 `undetermined` (보수 = 모든 단계 실행) 가 아니라 `normal` (모든 단계 skip) 이었다면 정반대 회귀가 났을 것. 라우팅 cost matrix 를 보고 fallback 결정해야.
3. **출력 schema 압축은 응답 길이 가변성을 사전 측정** — `reason` 같은 자유 형식 필드는 길이 보장 X. 캡 강제하려면 프롬프트에 "≤N자" 추가 + max_tokens 안전 마진 함께.

**증거 패턴**: `metadata.gate.source == "fallback"` + `metadata.gate.reason` 이 "bucket 무효" 메시지를 담고 있으면 즉시 parser failure 의심. 게이트 응답 의도와 routing 결과를 분리해서 검증해야.

**적용 시점**: LLM 호출의 output token 캡을 줄이거나, fallback 정책을 바꾸거나, JSON 응답 schema 를 손볼 때마다 (1) 실제 출력 길이 측정, (2) fallback bucket 의 라우팅 비용 확인, (3) 회귀 케이스 (정상 input → fallback) 시뮬레이션.

---

## 2026-05-05 — APK 검출 3-tier (Stage 2/3): 학술 표준과 false positive boundary

**상황**: ScamGuardian 의 APK 처리 — VirusTotal 단독에서 시그니처(VT) + 정적 분석(권한·서명) + 심화 정적 분석(bytecode 패턴) 의 3-tier 로 확장.

### 패턴 5 — 한국 보이스피싱 APK 검출은 시그니처+정적+심화정적 3-tier 가 학술적 표준

**관찰**: 학술 문헌 (Allix et al. 2016 AndroZoo / Wei et al. 2018 / S2W TALON 위협 인텔리전스) 에서 안드로이드 멀웨어 검출의 표준 architecture 는 다음 3 layer:

1. **시그니처 매칭** (VirusTotal 등) — 알려진 hash. 빠르지만 zero-day 못 잡음
2. **정적 분석 Lv 1** (manifest·권한·서명) — androguard 기반. 파일 *읽기*. 60-80% 검출률
3. **심화 정적 분석 Lv 2** (bytecode 패턴) — dex disassemble. 코드 *읽기만*, 실행 X

진짜 동적 분석 (Android 에뮬레이터 안에서 *실제 실행* 후 behavior 모니터링) 은 4-tier 라기보단 *완전히 다른 영역* — 호스트 위험 + 5-7 주 작업.

**처방**: 학부·prototype reference 에서 동적 분석 시도하지 말 것. 3-tier 까지가 학술적 정직 + 실현 가능 영역. 동적 분석은 future work 으로 명시 (CLAUDE.md `미구현 / future work` 섹션).

### 패턴 6 — bytecode 패턴은 단독 신호로 약함, 누적+조합으로만 강함

**관찰**: Stage 3 의 7 종 신호 중 거의 모두 false positive 가능:
- `apk_sms_auto_send_code` — 정상 메신저 앱도 인증 SMS 발송
- `apk_call_state_listener` — 통화 녹음 앱도 사용
- `apk_accessibility_abuse` — 장애인 보조 앱 정상 사용
- `apk_impersonation_keywords` — 뉴스 앱도 "검찰" 키워드 가짐
- `apk_string_obfuscation` — 정상 앱도 ProGuard 사용

**처방 — design principle**:
- 단일 패턴 매칭 → "사기다" 단정 X
- 권한 조합 + 서명 + 패키지명 + bytecode 패턴이 *누적* 시점에서만 강한 신호
- ScamGuardian 의 Identity (검출만, 판정 X) 와 정확히 fit — 누적 상태를 보고만 하고 판정은 통합 기업 몫
- 코드 주석 + FLAG_RATIONALE 양쪽에 false positive 한계 명시 필수

**적용 시점**: 다음 stage 에서 새 검출 신호 추가할 때 *먼저 false positive 시나리오부터 적어보라*. 정상 앱이 어떻게 똑같은 패턴 가질 수 있는지. 답이 안 나오면 그 신호는 단독 신호로 약하다 — 다른 신호와 조합해서만 의미 있다고 명시해야 한다.

### 패턴 7 — "동적 분석" vs "심화 정적 분석" 학술 용어 정확히 구분

**관찰**: bytecode 패턴 매칭을 "동적 분석" 이라고 부르면 *틀림*. 정확한 용어:
- **정적 분석 (static analysis)**: 코드를 *읽기만*. 실행 X
- **심화 정적 분석 (advanced static analysis / bytecode pattern matching)**: dex 를 disassemble 해서 *읽기*. 여전히 실행 X
- **동적 분석 (dynamic analysis)**: 에뮬레이터·sandbox 에서 *실제 실행* 후 behavior 모니터링

bytecode 분석은 disassemble 한다고 해서 동적 분석이 아니다 — 여전히 코드 읽기.

**처방**: 학부 발표·논문·문서에서 정확한 용어 사용. "동적 분석" 라고 잘못 쓰면 평가자가 "그럼 에뮬레이터 어디서 돌리는데?" 즉시 반박. CLAUDE.md / README / INTEGRATION_GUIDE / apk_analyzer.py 모두 일관되게 *심화 정적 분석* / *bytecode pattern matching* 으로 표기.

### 패턴 9 — 동적 분석은 인터페이스 먼저, 실행은 *기본 비활성* + 별도 VM 강제

**관찰**: APK 동적 분석을 학부 reference 에 추가할 때 *기능 자체* 는 만들고 싶지만
*로컬 실행* 은 위험 (멀웨어가 호스트 감염). 그래서 v3.5 sandbox.py 패턴 그대로:

1. `analyze_apk_dynamic()` 함수 + `APKDynamicReport` dataclass 까지 인터페이스 박음
2. `APK_DYNAMIC_ENABLED=0` (기본) → 즉시 `status=DISABLED` 반환, 호스트 0 건드림
3. `backend=local` → **HARD BLOCK** (어떤 env 조합으로도 풀리지 않음). `BLOCKED_LOCAL` 반환
4. `backend=remote` 만 실제 동작 — 별도 VM 의 Android 에뮬레이터 stack 호출
5. flag 카탈로그 5 종 + FLAG_RATIONALE 미리 박음 — remote VM 구현 시 자동 흘러감

**처방**:
- 위험한 기능은 *3 단 안전망*: 기본 비활성 / 로컬 영구 차단 / remote 만 허용
- 인터페이스 + 데이터 모델 먼저 박으면 실제 구현 시 통합 표면 없음
- 테스트로 안전 정책 *회귀 가드*: `test_dynamic_local_backend_hard_blocked` 같이 "어떤 env 조합으로도 local 활성 X" 검증 박아 두기

**적용 시점**: 학부·프로토타입에서 위험한 기능 (실행·네트워크 변형·파일 시스템 변경 등) 추가 시 이 패턴. *코드는 있지만 실행은 별도 호스트* 가 보안 + 학술 정직 + 점진 개선의 교집합.

### 패턴 8 — androguard LGPL 라이선스 호환성

**관찰**: androguard 는 LGPL — 동적 링크 (Python `pip install androguard` import) OK. 정적 링크나 fork 는 라이선스 의무 발생.

**처방**: ScamGuardian 처럼 `requirements.txt` 의존으로 import 만 쓰면 라이선스 자유. fork/embed 는 LGPL 의무 (소스 공개·라이선스 명시) 발생.

**적용 시점**: OSS 의존성 추가 시 LGPL/GPL/AGPL/BSD/MIT 차이 *반드시* 확인. LGPL = 동적 링크 OK / GPL = 모두 GPL 전염 / AGPL = 네트워크 사용도 GPL 전염 / BSD·MIT = 거의 자유.

---

## 2026-05-05 — Identity reframe: 학부 reference 의 정직성

**상황**: ScamGuardian 의 점수·등급 시스템을 검출 시스템으로 reframe (Stage 1·2·3).

### 패턴 1 — 점수 정당화는 학부에서 거의 항상 어렵다

**관찰**: SCORING_RULES 의 27 종 flag 에 부여된 점수 (15·20·25·50·75·80) 의 정확한 숫자를 자체 RCT 없이 정당화 불가능. "왜 abnormal_return_rate 가 15 점? 14 점도 아니고 16 점도 아니고?" 답이 없음. 등급 임계 (20·40·70) 도 동일.

**처방 — 정직한 reference implementation 의 형태**:
- 점수·등급은 **응답 표면에서 제거** — `DetectionReport` 에 `total_score`/`risk_level` 필드 없음
- 검출 사실 + 학술/법적 근거만 노출
- 판정 logic 은 통합한 기업 (자체 RCT 가능한 도메인 전문가) 의 책임 영역으로 위임

**적용 시점**: 학부·연구·prototype 단계 reference implementation 을 만들 때 점수 산정 부분을 만들고 싶다면, **먼저 정당화 가능한지 자문**. 임계 결정에 자체 데이터/실험 없이 "감각" 으로 정한 숫자라면, 점수 표면화 대신 검출 보고만 하는 모델 (VirusTotal, OWASP ZAP) 이 더 정직하다.

### 패턴 2 — VirusTotal 모델이 보안 reference 의 표준

**관찰**: 실제 운영되는 보안 도구 (VirusTotal·OWASP ZAP·Snyk 등) 가 모두 **검출 결과 보고만 하고 최종 판정은 사용자에게** 위임하는 모델을 채택. 이는 우연이 아니라 *책임 분리* 의 표준.

**처방 — reference 자격에 fit 한 모델**:
- 검출기 (detector): 의심 신호 + 근거 보고
- 판정자 (judge): 통합 클라이언트 (통신사·은행·메신저 앱 등) — 자기 risk tolerance 에 따라 판정 logic 구현

**적용 시점**: "이 콘텐츠는 X 다" 단정 응답이 필요한 상황을 의심하라. 보안·금융·법률 도메인은 거의 항상 *판정 분리* 가 정답.

### 패턴 3 — FLAG_RATIONALE 같은 transparent 학술 근거가 점수보다 더 무거운 자산

**관찰**: `FLAG_RATIONALE` (27 종 flag × 학술 근거 + 출처 기관) 는 점수 시스템 폐기 후에도 *그대로* 가치. 오히려 점수 없이 근거만 노출하니 의미가 더 명확.

```
- abnormal_return_rate
  rationale: "연 20% 이상 수익 보장은 자본시장법상 불법 권유 신호 ..."
  source: "금융감독원 보이스수신 감독사례집 / SEC Investor Bulletin: Affinity Fraud"
```

**처방 — 자산 가치 보존 우선순위**:
- 학술/법적 근거 (정당화 가능): **최우선 보존**, 0 줄 변경
- 검출 가능 flag list (관측 가능): 보존, dict→list 전환만
- 점수 매핑 (정당화 어려움): 폐기
- 등급 임계 (정당화 어려움): 폐기

**적용 시점**: 시스템에서 "정당화 가능" vs "정당화 어려움" 을 구분하라. 정당화 가능한 부분 (학술 근거·법적 출처·관측 가능 신호) 은 보존, 정당화 어려운 부분 (가중치·임계값·등급) 은 외부에 위임 가능한지 검토.

### 패턴 4 — Stage 단위 분할 + Forbidden Actions 회귀 가드

**관찰**: Identity 변경같은 큰 reframe 은 한 번에 하면 회귀가 폭발. Stage 1 (narrative) → Stage 2 (core) → Stage 3 (마무리) 분할 + 각 Stage 끝에 회귀 가드 테스트 박는 패턴이 효과적.

**Stage 3 의 핵심 가드**:
- `tests/test_detection_report_schema.py::test_to_dict_does_not_expose_score_or_grade_fields` — `parametrize` 로 `total_score`/`risk_level`/`is_scam` 등 7 종 폐기 필드 모두 회귀 가드
- `tests/test_detection_report_schema.py::test_pipeline_config_has_no_deprecated_symbols` — `RISK_LEVELS`/`get_risk_level`/`SCORING_RULES`/`LLM_FLAG_SCORE_RATIO` 재도입 즉시 실패

**처방**:
- 정체성·약속 (예: Forbidden Actions, Identity Boundary) 은 *문서* 만으로 부족 — *실행 가능한 회귀 가드 테스트* 로 박아야 한다
- 실수로 cherry-pick 으로 되돌려도 CI 가 즉시 fail → 자동 enforcement
- "테스트는 contract 의 살아있는 spec" 원칙

**적용 시점**: 다음번에도 정체성 변경·필드 폐기·token name rename 같은 큰 일이 있을 때 *반드시* 회귀 가드 테스트 동반.

---
