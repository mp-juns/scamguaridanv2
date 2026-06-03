# Lessons — 패턴 모음

작업 중 발견한 패턴·교정 기록. 같은 실수를 반복하지 않으려는 self-improvement loop 의 누적 자산.
최신이 위.

---

## 2026-06-03 — 리뷰 범위는 작업트리뿐 아니라 브랜치/최신 커밋 diff 로 확인

**상황**: 사용자가 "많이 바뀌었다"고 했는데 assistant 가 `git status` 의 미커밋 변경만 보고
`api_server_pkg/app.py` 와 TUI 스크립트만 리뷰했다. 실제 핵심 변경은 최신 커밋
`feat(apk-dynamic)` 안의 APK 동적 분석 서버와 fixture 였다.

**처방**:
- 리뷰 요청을 받으면 먼저 `git status` 와 함께 `git log --oneline -5`,
  `git show --stat HEAD`, `git diff --stat <upstream>...HEAD` 를 확인한다.
- 브랜치가 upstream 보다 ahead 면 미커밋 변경뿐 아니라 ahead 커밋 전체를 리뷰 범위에 포함한다.
- 사용자가 특정 영역을 암시하거나 정정하면 즉시 범위를 재설정하고, 놓친 패턴을 lessons 에 남긴다.

**적용 시점**: "검토해봐", "많이 바뀌었다", "그 전이랑 달라졌다" 같은 코드 리뷰 요청 전부.
## 2026-06-01 — WSL CUDA 판정은 샌드박스/디바이스 노출을 분리해서 확인

**관찰**: `torch.cuda.is_available() == False` 만 보고 "CUDA 없음" 으로 결론내렸지만,
WSL 환경에서는 `/usr/lib/wsl/lib` 드라이버 라이브러리와 `/dev/dxg` 디바이스 노출 여부,
그리고 Codex sandbox 의 device passthrough 여부가 서로 다를 수 있다.

**처방**:
- CUDA 여부를 말하기 전에 `torch.version.cuda`, `/usr/lib/wsl/lib/libcuda.so`,
  `/dev/dxg`, `LD_LIBRARY_PATH=/usr/lib/wsl/lib ... torch.cuda.device_count()` 를 함께 본다.
- sandbox 안에서 디바이스가 안 보이면 host/WSL 자체에 CUDA가 없다는 뜻이 아닐 수 있다.
- 학습 실행 전에는 실제 학습 프로세스가 돌아갈 권한/환경에서 CUDA probe 를 다시 한다.

**적용 시점**: WSL + GPU 학습, nvidia-smi 비정상, Codex sandbox 에서 CUDA probe 할 때.

---

## 2026-05-28 — Next 16 Turbopack 메모리 누수 → WSL freeze 악순환 (4시간 디버깅)

**관찰**: `./scripts/start_stack.sh` 실행 시 WSL 무한 프리징 + 원격 끊김. 메모리 8GB→20GB 증설해도 재발. baseline 만으로도 호스트 측 압박 체감.

**증상 시간 추이 (첫 freeze, 03:04)**:
- next-server **VSZ 3GB → 22GB (30초 만에 7배)** — RSS 1.2GB 만 보면 못 보는 누수
- WSL 안 swap 4GB 풀로 사용 → 호스트 C:\ 디스크 쓰기 폭주 (작업관리자 활성 시간 58%)
- 9P 마운트 (`/mnt/c`) 응답 늦어짐 → WSL 안 D-state 프로세스 무더기
- D-state wchan: `folio_wait_bit_common`, `wait_on_buffer`, `d_alloc_parallel`
- load avg 56 (CPU 6코어 정상치의 9배)
- = WSL freeze 체감 (실은 진짜 hang, OOM kill 흔적 없음)

**근본 원인**: Next 16 Turbopack 의 root 자동 감지가 `apps/web` 가 아닌 `apps/` 를 잘못 잡음 → `tailwindcss` resolve 를 `apps/node_modules` → `/node_modules` 까지 무한 시도 → resolve 캐시가 JS heap 에 누적 → 메모리 폭증. WSL2 의 swap → 호스트 디스크 → 9P hang → D-state 좀비 악순환.

**시너지 원인 — 호스트 백업 SW (Acronis True Image)**: Turbopack 누수 *단독* 으론 freeze 안 났을 가능성. 사용자 의문 "그전까진 잘 쓰다가 왜 갑자기" 의 진짜 답 — **호스트 Acronis True Image 가 디스크 80% I/O 점유** 중이라 WSL 가 남은 20% 만 사용 가능. WSL swap I/O + 9P 마운트가 그 좁은 대역폭 위에서 처리 → 디스크 saturated → 9P hang → D-state 누적. **두 원인 합쳐서 폭발**: Acronis (1차 디스크 점유) × Turbopack 누수 (2차 swap 요구). 어제는 Acronis 비활성 시간대 → 같은 누수 있어도 freeze 안 남. 즉 *호스트 디스크 I/O bandwidth* 와 *WSL 메모리 swap 요구* 의 충돌이 진짜 trigger. 다른 후보: OneDrive 대량 sync, Antivirus full scan, Windows Update 다운로드.

**`turbopack.root` 옵션도 ESM 컴파일 함정**: `next.config.ts` 의 `__dirname` 이 ESM 컨텍스트에서 *undefined*. `path.resolve(undefined)` 는 cwd fallback → 의도와 다른 경로. ESM-safe 패턴 필수:

```ts
import { fileURLToPath } from "node:url";
import path from "node:path";
const __dirname = path.dirname(fileURLToPath(import.meta.url));
```

**처방**:
1. **Next 16 + Tailwind 4 조합에서 Turbopack 위험 (2026-05 기준)** — `next dev --webpack` 으로 fallback. Next 16 공식 옵션. 5-10% 느려지지만 freeze 완전 해소.
2. **WSL freeze 진단은 RSS 가 아닌 VSZ 봐야** — RSS 1.2GB 만 보면 누수 안 보임. **VSZ 22GB** 가 진짜 증거. swap 으로 빠진 부분 합쳐서 봐야.
3. **D-state 프로세스 + 9P 마운트 hang 패턴** — freeze 원인이 메모리 단독이 아닌 *kernel I/O wait 누적*. `ps -eo stat,wchan` 로 D-state 잡고 wchan 확인. `folio_wait_bit_common` = page cache 대기 = 디스크/9P hang.
4. **메모리 증설은 *임시 버퍼*** — Turbopack 누수가 있으면 20GB 도 시간 문제로 차오름. 근본 fix 없이 메모리만 늘리면 freeze 시간만 길어질 뿐. 사용자가 정확히 진단 ("메모리가 단독 원인이면 stack 안 띄웠을 때도 압박 없어야").

**증거 패턴**:
- `frontend.log` 에 `resolve 'tailwindcss' in '.../apps'` (apps/web 아님) = root 자동 감지 fail
- `processes.log` 에 next-server **VSZ > 10GB** = JS heap 누수
- `io.log` 에 D-state wchan `folio_wait_bit_common` = I/O hang
- 호스트 작업관리자에서 디스크 활성 시간 50%+ 와 vmmemWSL 메모리 = 호스트 측 swap 폭주

**적용 시점**: Next 버전 올릴 때 / Tailwind 큰 버전 변경 시 / `apps/web` 같은 sub-디렉토리 구조 변경 시 — *반드시* turbopack root 자동 감지 검증. frontend.log 의 resolve 경로 확인.

**진단 시 추가 체크리스트** (WSL freeze 가 어제까진 안 났는데 갑자기 시작):
- 호스트 작업관리자 → 디스크 활성 시간 > 50% 인지 → Acronis / Norton / OneDrive / Windows Defender full scan / Windows Update 가 점유 중인지
- 호스트 측 백업 SW 가 *최근에 활성화* 됐는지 (예: 자동 백업 스케줄 시작, 새 폴더 sync, 정기 full scan 주기)
- 위 항목이 *예* 면 — 메모리/Turbopack 만 의심하지 말고 *호스트 디스크 점유 SW* 도 root cause 후보로 같이 봐야

**관련 자산** (이번 세션에서 신설):
- `scripts/monitor_resources.sh` — 5초 sampling + 30초 호스트 rsync + D-state 진단
- `/mnt/c/Users/mpssh/Documents/wsl_logs/` — freeze 후에도 외부에서 진단 데이터 접근
- `.wslconfig` 백업 `/mnt/c/Users/mpssh/.wslconfig.bak-20260528-031233` — 8GB 원상복귀용

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
## 2026-06-01 — 학습 세션 상태는 pid 보다 완료 산출물을 우선 확인

**상황**: classifier 학습이 `metrics.jsonl` 에 `kind=done` 을 기록하고 checkpoint 도 저장했는데,
세션 감시 로직이 pid 종료 타이밍만 보고 `failed` 로 보정했다.

**처방**:
- `running`/`failed` 상태를 갱신할 때는 먼저 `metrics.jsonl` 의 `done` 이벤트와 output artifact
  (`label2id.json`, adapter/model weights 등)를 확인한다.
- 성공 산출물이 있으면 pid 상태보다 artifact 를 신뢰해 `completed` 로 복구한다.
- 긴 학습 subprocess 는 서버 reload/HMR/admin polling 과 독립적으로 끝날 수 있으므로,
  상태 판정은 process liveness 단독 판단을 피한다.

**적용 시점**: 백그라운드 작업 상태를 파일 기반으로 추적할 때. 특히 watch thread 가 reload 나
프로세스 재시작과 엇갈릴 수 있는 dev 서버에서는 artifact-first 복구 경로가 필요하다.

---

## 2026-06-01 — 학습 데이터 통계 표시는 source 를 분리해서 보여주기

**상황**: `/admin/training` 의 "분류기 학습 데이터" 카드가 기본 DB 라벨 25건만 보여주면서,
synthetic extra JSONL 포함 학습셋 12025건과 혼동을 만들었다.

**처방**:
- `load_classifier_dataset()` 기본 호출 결과와 `load_classifier_dataset(extra_jsonl=...)` 결과를 같은 이름으로 표시하지 않는다.
- UI 에서는 "기본 검수 라벨" 과 "현재 학습 후보 전체" 를 명확히 분리한다.
- 학습 시작 폼은 최신 synthetic corpus 경로를 기본값으로 채워 실제 학습 명령과 화면 숫자가 같은 기준을 쓰게 한다.

**적용 시점**: DB 라벨 + 외부 JSONL + generated corpus 처럼 여러 source 를 합쳐 학습하는 화면을 만들 때,
항상 표시값 옆에 source/scope 를 함께 적는다.

---

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
