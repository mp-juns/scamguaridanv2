# changes.md

milestone 단위 변경 로그. 누적 append, 최신이 위.

---

## 2026-06-08 — 어드민 상단 하얀 바 제거 + 프롬프트 인젝션 즉시 차단

**무엇 (1) 하얀 바 제거**:
- `app/admin/layout.tsx` — 상단 `bg-slate-50` 이메일·로그아웃 바 삭제(전역 AccountNav pill 이
  로그아웃 제공해 중복이었음). 레이아웃은 `<>{children}</>` 로 단순화.

**무엇 (2) 프롬프트 인젝션(우회) 즉시 접근 제한**:
- `platform_layer/abuse_guard.py` — `detect_prompt_injection(text)` (AI/시스템 프롬프트·역할
  조작 패턴만, 일반 "무시"는 오탐 회피) + `force_block(user_id)` 추가.
- `api_server_pkg/analyze.py` — resolve_source 결과(=웹 source 텍스트 포함)에 대해 인젝션
  검사. 감지 시 `force_block`(user_id 있으면) + **423 INJECTION**. (웹은 텍스트를 source 로
  보내 기존 text-only 가드를 우회하던 갭도 메움.)
- `app/injectionGuard.ts` 신규 — 백엔드와 동일 패턴 거울. `looksLikeInjection()` +
  localStorage 1시간 접근 제한(`sg_injection_block_until`).
- `app/HomeClient.tsx` — handleSubmit 시작 시 ① 기존 제한 상태면 차단 ② 인젝션 감지 시
  `blockForInjection()` + 차단(분석 미실행). 🚫 "접근이 제한되었습니다" 모달(z-[90]).

**왜**: 사용자 요청 — "기존 프롬프트 무시" 류 우회 내용이 섞이면 바로 접근 제한.

**검증**: detect_prompt_injection 단위(8케이스, 실제 사기 "이전 문자는 무시하고…"는 오탐 X)
PASS. pytest abuse_guard 18 passed. 라이브: 인젝션 source→423 INJECTION / 사기 텍스트→200 /
`/admin/login` 200 · `/admin` 307. 프론트 tsc·eslint 에러 0.

**범위 메모**: 인젝션 차단은 *타이핑 텍스트* 벡터(홈 입력 + /api/analyze)에 적용. 라이브
음성 transcript·업로드 파일 transcript 의 인젝션은 후속(드문 벡터).

## 2026-06-08 — 비회원 일일 분석 한도 5회 (홈+라이브 합산) 하드 차단

**무엇**:
- `app/guestLimit.ts` 신규 — 공유 일일 카운터(`sg_guest_daily_{YYYY-MM-DD}` localStorage,
  로컬 날짜 기준). `GUEST_DAILY_LIMIT=5`, `guestOverDailyLimit()`, `bumpGuestDaily()`.
- `app/HomeClient.tsx` — handleSubmit 시작 시 `isGuest && guestOverDailyLimit()` 면 분석 자체
  차단(한도 모달). 성공 시 `bumpGuestDaily()`. 한도 모달(⛔, z-[80]) + ESC 처리.
- `app/live/page.tsx` — server 컴포넌트 async 화, `auth()` → `isGuest` 를 `LiveVoiceUpload` 에 전달.
- `app/live/LiveVoiceUpload.tsx` — prop `isGuest`. 업로드(`handleSubmit`)·실시간(`startLive`)
  두 진입 모두 시작 시 한도 가드 + 시작 시 `bumpGuestDaily()`. 동일 ⛔ 차단 모달.

**왜**: 사용자 요청 — 비회원은 하루 5회 이상 분석하면 결과를 볼 수 없게(라이브 음성 포함 합산).
홈/라이브가 **같은 일일 카운터** 공유. 5회까지 허용, 6회째부터 차단(quota=5).

**검증** (Funnel 라이브): `/live` 200 · 비회원 홈 200 · frontend.log 에러 0. `tsc` 변경파일
에러 0, `eslint` 변경파일 에러 0(잔여 6건은 무관한 LiveVoiceUpload 기존 따옴표 이슈, 행번호만
밀림). (카운트→차단 동작은 브라우저 localStorage 필요 — 코드/타입 검증.)

**⚠️ 한계**: client localStorage 기반 → 시크릿창·스토리지 삭제로 우회 가능(데모 수준 마찰).
엄격 강제는 unique guest id 쿠키 + 백엔드 일일 카운팅 필요(후속 과제).

## 2026-06-08 — 비회원 분석 3회 이상 시 로그인 권유 모달

**무엇**:
- `app/page.tsx` — `HomeClient` 에 `isGuest={!session?.user?.email}` 전달.
- `app/HomeClient.tsx` — prop `isGuest`. 분석 성공 시 비회원이면 `localStorage`
  (`sg_guest_analysis_count`) 누적, **3회(`GUEST_PROMPT_THRESHOLD`) 이상이면 결과 모달 대신
  로그인 권유 모달** 먼저 표시. 권유 모달 버튼: "Google 로 로그인"(client `signIn` from
  next-auth/react, callbackUrl `/`) / "비회원으로 결과 보기"(닫고 결과 모달 표시). ESC·배경
  클릭 = 결과 보기. z-[70] 로 최상단.

**왜**: 사용자 요청 — 비회원이 분석 3회 이상부터 로그인 권유 창. "권하도록"이라 강제 차단 X,
dismiss 가능(비회원으로 계속 결과 확인 가능).

**동작 메모**: 3회째부터 매 분석마다 권유(dismiss 가능). 로그인하면 isGuest=false 라 더 안 뜸.

**검증**: 비회원 랜딩 200 + frontend.log 에러 0. `tsc`·`eslint` 에러 0.
(카운트→모달 동작은 브라우저 localStorage+클릭 필요 — 코드/타입 검증, 실브라우저 미검증.)

## 2026-06-08 — 홈 첫 진입 선택 게이트 (비회원 / 로그인)

**무엇**: 홈(`/`) 첫 진입 시 랜딩 전에 선택 게이트를 띄움.
- `app/page.tsx` — server 게이트로 전환. `auth()` 세션 + 비회원 쿠키 검사 → 둘 다 없으면
  `<EntryGate />`, 있으면 기존 랜딩(`<HomeClient />`).
- `app/HomeClient.tsx` — 기존 랜딩 client 컴포넌트 (구 `page.tsx` 를 `git mv` + `Home`→`HomeClient`).
- `app/EntryGate.tsx` 신규 — 2버튼: "비회원으로 둘러보기"(server action 으로 `sg_entry=guest`
  httpOnly 쿠키 30일 set 후 redirect) / "Google 로 로그인"(권한 따라 회원·관리자 자동).
- `app/guest.ts` 신규 — `GUEST_COOKIE`/`GUEST_VALUE`/`GUEST_MAX_AGE` 공유 상수.
- `app/AccountNav.tsx` — 게이트 화면(미진입)에선 위젯 숨김. 비회원의 "로그인"은
  `/admin/login`(어드민 페이지) 아닌 **일반 Google signIn** 으로 직행(회원 로그인 시 "권한 없음"
  오인 방지).

**왜**: 사용자 요청 — 홈 첫 화면에서 비회원/회원/관리자를 로그인으로 분기. 회원·관리자는
allowlist 로 자동 구분되므로 버튼은 비회원/로그인 2개 (사용자 선택). 비회원은 쿠키로 기억해
다음 방문부터 게이트 생략.

**검증** (Funnel 라이브): 쿠키 없는 새 방문 → 게이트("어떻게 이용하시겠어요"·"비회원으로
둘러보기" 노출, "보이스피싱" 0) / `sg_entry=guest` 쿠키 → 랜딩("보이스피싱" 노출, 게이트 0).
`tsc`·`eslint` 변경파일 에러 0. (Google 로그인 후 상태는 OAuth 필요 — 코드/타입 검증.)

## 2026-06-08 — 로그인 세션 역할 구분 (admin / user) — ChatGPT 방식

**무엇** (위 pill 작업을 역할 기반으로 확장):
- `auth.ts` — `signIn` 이 **모든 Google 계정 로그인 허용**으로 변경(기존: allowlist 만 통과).
  `jwt` 콜백이 최초 로그인 시 `backendAllows(email)` 조회 → `token.role = admin|user` 고정.
  `session` 콜백이 `session.user.role` 노출. `authorized` fallback 도 `role==="admin"` 으로.
- `proxy.ts` — `/admin` 게이트를 **세션 존재 → `role==="admin"`** 으로 강화 (보안 핵심:
  이제 일반 user 도 세션을 가지므로 role 검사 없으면 user 가 /admin 통과해버림).
- `app/admin/login/page.tsx` — admin 만 redirect. 로그인했지만 user 면 "관리자 권한 없음"
  카드(홈으로 / 다른 계정 로그인). admin 의 /admin/login↔/admin redirect 루프 차단.
- `app/AccountNav.tsx` 신규 (구 `AdminEntry.tsx` 대체) — 우측 상단 역할별 위젯:
  익명→"로그인", user→로그아웃만, admin→"🛠️ 관리자" pill + 로그아웃.
- `types/next-auth.d.ts` 신규 — Session.user.role / JWT.role 타입 보강.

**왜**: 사용자 요청 — "관리자가 로그인하면 어드민 pill 노출, 사용자가 로그인하면 미노출".
즉 로그인 창구 하나(Google) + 역할로 노출 분기 (ChatGPT 방식).

**검증** (Funnel 라이브, 익명): `/` 200 + "로그인" pill 1회 + "관리자" 0회 / `/admin` →307
`/admin/login` / `/admin/login` 200. `tsc`·`eslint` 변경파일 에러 0.
(admin·user 로그인 상태는 OAuth 세션 필요 — 코드/타입 검증, 실로그인 미검증.)

**⚠️ 주의**: 기존 admin JWT(역할 없는 토큰)는 `role ?? "user"` 로 떨어져 **한 번 로그아웃→
재로그인 해야 admin 복구**됨. jwt 콜백이 최초 로그인 때만 role 을 박기 때문.

## 2026-06-08 — 메인 페이지에 관리자 전용 진입 pill

**무엇**:
- `apps/web/src/app/AdminEntry.tsx` 신규 — server 컴포넌트, `auth()` 세션 있으면(관리자)만
  우측 상단 작은 pill("🛠️ 관리자") 렌더, 없으면 null.
- `apps/web/src/app/layout.tsx` — 루트 `<body>` 에 `<AdminEntry />` 삽입 (전 페이지 노출).

**왜**: 일반 사용자는 어드민 진입점을 안 보이게, 관리자는 메인에서 바로 `/admin` 진입.

**`/admin` 접근 차단은 이미 존재**: Next 16 은 middleware 를 `proxy.ts` 로 개명 →
`apps/web/src/proxy.ts` 가 이미 `/admin/*` 세션 게이트(미인증 시 `/admin/login` redirect)를
완비하고 있었음. (작업 초기에 `middleware.ts` 를 새로 만들었다가 `proxy.ts` 와 충돌해
앱 전체 404 발생 → `middleware.ts` 삭제로 해결. AGENTS.md 경고대로 Next 16 ≠ 기존 Next.)

**검증** (Tailscale Funnel 라이브): `/` 200 · `/admin/login` 200 · `/admin` → 307
redirect `/admin/login?next=%2Fadmin` (게이트 작동) · 익명 `/` HTML 에 "관리자" 0회 (pill 숨김).

## 2026-05-26 — main ← origin/main-kyy 머지 + Tailscale Funnel 보존 백업 + README 갱신

**무엇**: `origin/main-kyy` (kyy 영상 latency 단축 + cloudflared quick tunnel) 를 main 에
merge. 머지 전에 `scripts/start_stack.sh` 의 Tailscale Funnel 블록을 백업해두고, 머지 후
원래 위치에 그대로 살아있는지 확인.

**왜**: kyy 브랜치는 phh 의 카카오 웹훅(Tailscale Funnel + ngrok, 포트 8000/3100) 을
보호하기 위해 별도 포트(8001/3101) + cloudflared quick tunnel 로 분리한 `start_kyy.sh`
신설. 머지 시 phh 의 funnel 설정이 덮어써질 가능성을 사전 차단해야 함.

**검증 결과**:
- `main-kyy` 의 `scripts/start_stack.sh` 는 main 과 **byte-identical** — Tailscale Funnel
  블록(line 84-88: `tailscale funnel --bg "http://127.0.0.1:${FRONTEND_PORT}"`) 그대로
- `scripts/start_kyy.sh` 는 *추가* 파일, 헤더 주석에 "phh 포트 8000/3100/4040 은 절대
  건드리지 않음" 명시. `tailscale funnel + ngrok 모두 비활성` (phh 보호 의도)
- `git merge-tree` dry-run: 공통 변경 파일 0개 → conflict 없이 auto-merge
- 현재 시스템 상태: `https://scamguardian.tail7e5dfc.ts.net` → `:3100` Funnel on (정상)

**백업 (스크립트 파일 → changes.md 로 이관, 파일 삭제)**:

```bash
# scripts/start_stack.sh:25 (환경변수)
ENABLE_FUNNEL="${ENABLE_FUNNEL:-true}"

# scripts/start_stack.sh:84-88 (frontend 기동 후 funnel 활성화)
if [[ "$ENABLE_FUNNEL" == "true" ]] && command -v tailscale >/dev/null 2>&1; then
  echo "[start] enabling tailscale funnel (frontend:$FRONTEND_PORT)..."
  tailscale funnel --bg "http://127.0.0.1:${FRONTEND_PORT}" || true
  tailscale funnel status 2>/dev/null || true
fi

# scripts/start_stack.sh:89 (주석)
# 카카오 오픈빌더는 .ts.net 도메인을 거부하므로 ngrok 으로 보조 터널 제공
```

참고 URL (CLAUDE.md 기록): `https://scamguardian.tail7e5dfc.ts.net/webhook/kakao` —
카카오 오픈빌더에서 `.ts.net` 접속 불안정 → 카카오 웹훅은 ngrok 권장.

**README 갱신**: hh.md(3단계 캐스케이드) + kyy.md(영상 latency 단축) 작업 요약 추가
("브랜치별 작업 정리" 섹션). `tasks/todo.md` 참조 링크 포함.

**머지된 kyy 변경 요약**:
- `pipeline/stt.py` +107 — STT 병렬 chunking (45s 초과 시 ffmpeg segment + ThreadPoolExecutor(4))
- `pipeline/runner.py` +192 — Phase 1.5+2+3 통합 병렬화 (STT → [Gate ‖ Classify ‖ Extract ‖ RAG] → LLM)
- `pipeline/gate.py` +97 — 프롬프트 트림 + 뉴스 narration heuristic fast-path
- `api_server_pkg/result_token.py` +36 — `get_public_base_url()` 에 cloudflared 로그
  우선순위 추가 (ngrok 4040 API 와 공존, log mtime 무효화 캐시)
- `apps/web/src/app/page.tsx` — `is_uncertain || confidence < 0.3` 시 "정상" 표시
- 신규: `scripts/start_kyy.sh`, `kyy.md`, `tests/test_gate.py`, `tests/test_stt_chunked.py`

**성과** (kyy 실측): baseline 14.5s → **9.2s** (78% 10s 이내, 최단 7.8s, 322 테스트 통과).

---

## 2026-05-20 — 학습·평가 파이프라인 (dataset summary + gate/scam_type/signals 평가 + baseline 비교)

**무엇**: 3단계 캐스케이드 + content_label 재구조화의 *정량 비교*를 위한 평가 스크립트.

- `training/splits.py` 신설 — `group_train_val_test_split()` (default 70/15/15).
  같은 `source_ref` 샘플은 한 fold 로 묶임 → **leakage 방지**. content_label 분포는
  best-effort 균형 (그리디 결손 기반 배정).
- `training/dataset_summary.py` 신설 — `summarize_dataset()`. content_label /
  sample_kind / scam_type(scam_attempt 만) / 출처 / 학습 제외 카운트.
- `training/eval_gate.py` 신설 — `evaluate_gate()`. 3-class (normal/scam_attempt/
  scam_news_edu) 한정, suspicious/undetermined 자동 제외. accuracy + per-class
  P/R/F1 + macro/weighted F1 + confusion matrix.
- `training/eval_scam_type.py` 신설 — `evaluate_scam_type()`. content_label ==
  scam_attempt 만, top-1/top-3 accuracy + macro/weighted F1 + per-class.
- `training/eval_signals.py` 신설 — 3-mode:
    - `evaluate_flags()`: 세부 flag P/R/F1 (per-flag + micro).
    - `evaluate_groups()`: flag_groups 단위 P/R/F1.
    - `compare_label_coverage()`: **baseline vs current** 추출 라벨셋 커버리지 비교.
      Stage 2 의 COMMON_RISK_LABELS + top-N 합집합이 실제로 개인정보 항목·악성 URL
      커버리지를 끌어올리는지 정량화. 핵심 라벨별·전체 Δ 출력.

**검증**: pytest **282개 통과** (training_eval 21 신규, 회귀 0). leakage·제외 정책
모두 테스트로 강제.

**샘플 출력**: 데모 코퍼스에서 baseline 0% → current 100% (개인정보 항목·악성 URL).

---

## 2026-05-20 — Stage 3 검출 신호 그룹핑 레이어 (3단계 캐스케이드 3/3)

**무엇**: 51개 세부 flag 를 11개 그룹으로 묶는 **표시 레이어** 추가. 세부 flag·
rationale 매핑은 *완전히 그대로 유지* — Stage 3 는 보조 view 일 뿐, 내부 검출이나
학술 근거 매핑을 대체하지 않는다.

**왜**: 51개 flag 가 UI 에서 평탄하게 나오면 사용자가 패턴을 못 읽는다. ~11개
의미 그룹("사칭", "개인정보 요구", "금전 요구" 등)으로 묶어 보여주되, 그룹 아래의
세부 flag·근거는 그대로 노출.

- `pipeline/flag_groups.py` 신설 — `FLAG_GROUPS`(11종) + `group_detected_flags()`.
  매핑 안 된 flag 는 `other_signals` 그룹으로 누락 없이 보존.
- `pipeline/signal_detector.py` — `DetectionReport.signal_groups` 필드 추가
  (default `[]`, optional). `detect()` 가 자동으로 populate. `to_dict()` 에 포함.

**보존**: `DETECTED_FLAGS`(51), `FLAG_RATIONALE`, `FLAG_LABELS_KO` 전부 그대로.
기존 `detected_signals` 응답 구조 불변 — `signal_groups` 는 *추가* 필드, optional.
기존 소비자는 무시해도 동작 보장 (default `[]`).

**출력 예시**:
```json
{
  "group_id": "personal_sensitive_request",
  "label_ko": "개인정보·민감정보 요구",
  "description": "주민번호·비밀번호·OTP·자격증명 등 민감 정보 요구",
  "summary": "개인정보 또는 자격증명 제공을 요구하는 신호",
  "count": 2,
  "flags": ["personal_info_request", "sandbox_password_form_detected"]
}
```

**결과**: pytest 261개 통과 (flag_groups 22 신규, 회귀 0). end-to-end 스모크로
실제 응답에 `signal_groups` 정상 노출 확인.

---

## 2026-05-20 — Stage 2 multi-label 추출 라우팅 (3단계 캐스케이드 2/3)

**무엇**: scam_type 단일 강제 분류로 복합 스캠의 한쪽 엔티티를 놓치던 문제를 해결.
`all_scores` 상위 N개 후보 유형의 LABEL_SET 을 합집합으로 추출 대상에 넣는다.

**왜**: top-1 이 "투자 사기" 면 투자 사기 LABEL_SET 만 추출 → 같은 메시지의 "주민번호
요구"(개인정보 항목)를 통째로 놓침. = 검출 누락(recall 손실).

- `pipeline/config.py` — `STAGE2_CANDIDATE_TOP_N`(3) / `STAGE2_DOMINANCE_GAP`(0.30) /
  `COMMON_RISK_LABELS`(개인정보 항목·계좌번호·악성 URL).
- `pipeline/classifier.py` — `candidate_scam_types(all_scores)`. top1-top2 차가
  dominance_gap 이상이면 top-1 단독, 아니면 top-N. all_scores 없으면 [].
- `pipeline/runner.py` — Phase 2 후 candidate 생성. extractor 라벨 = COMMON_RISK_LABELS
  + top-N 후보 LABEL_SET 합집합. all_scores 없으면 기존 top-1 라우팅 fallback.
- `api_server_pkg/common.py` — candidate_scam_types 를 내부 metadata 에만 저장.

**불변**: `scam_type` 필드는 top-1 문자열 그대로 (list 로 안 바꿈). candidate_scam_types
는 외부 응답 schema(`to_dict`)에 노출 안 함 — 추출 라우팅 + 내부 metadata 전용.

**결과**: pytest 239개 통과 (stage2 12 신규, 회귀 0). end-to-end 스모크 — top-1 투자
사기 입력에서 `개인정보 항목`("주민번호") 추출 확인 (Stage 2 이전엔 누락).

---

## 2026-05-20 — Admin 라벨링 UI content_label 반영

**무엇**: `AdminRunEditor.tsx` 에 content_label 데이터 구조를 반영.

- content_label select 를 scam_type 보다 **먼저** 배치 (기준 라벨).
- scam_type select 는 `content_label == scam_attempt` 일 때만 활성 (그 외 disabled).
  저장 시 scam_attempt 가 아니면 `scam_type_gt=""` 전송 — API validator 와 일치.
- sample_kind select(5종) + source_ref 입력 필드 추가.
- `scam_news_edu` 선택 시 정답 플래그 섹션에 "보도/교육에서 언급된 위험 신호"
  안내 배너 표시.
- 기존 annotation 에 content_label 없으면 `resolveContentLabel` fallback (백엔드와 동일).
- 저장 payload 에 content_label/sample_kind/source_ref 포함.

**검증**: AdminRunEditor.tsx tsc·eslint 통과 (clean). 백엔드 pytest 227개 통과.

---

## 2026-05-20 — 학습/라벨링 데이터 content_label 재구조화

**무엇**: 학습 데이터를 "유튜브 뉴스 단순 라벨링" 중심에서 **content_label(콘텐츠
성격) + sample_kind(샘플 출처)** 구조로 재정의. scam_attempt / scam_news_edu /
normal 을 명확히 분리.

**왜**: 뉴스 원문은 "사기에 대한 설명"이지 "사기 유도"가 아님. 뉴스를 scam_attempt
로 학습하면 "사기·피해·경찰" 단어만 보고 오탐. scam_type 분류기는 사기 시도
샘플만 학습해야 함.

- `pipeline/config.py` — `CONTENT_LABELS`(=GATE_BUCKETS) / `SAMPLE_KINDS` /
  학습 정책 상수.
- `db/sqlite_repository.py`·`db/repository.py` — `human_annotations` 에
  `content_label`/`sample_kind`/`source_ref` 컬럼 + 마이그레이션 (sqlite ALTER
  try/except, postgres ADD COLUMN IF NOT EXISTS). 기존 필드 전부 유지.
- `training/data.py` — content_label 중심 로더 재설계:
  `load_classifier_dataset`(scam_attempt 만), `load_content_gate_dataset`
  (normal/scam_attempt/scam_news_edu), `load_review_queue`(suspicious/undetermined).
  content_label 없는 구 데이터는 fallback (scam_type 명확→scam_attempt, 아니면
  undetermined).
- `api_server_pkg/models.py` — `HumanAnnotationRequest` 에 content_label/sample_kind/
  source_ref. scam_type_gt 는 scam_attempt 일 때만 필수 (조건부 validator).
- `docs/labeling_guide.md` 신설 — 뉴스 처리 규칙 + synthetic 샘플 구조 + JSONL 스키마.
- `data/labeling_samples.example.jsonl` — 예시 5종.

**호환성**: 외부 API 응답 schema 불변. 기존 scam_type_gt/entities_gt/triggered_flags_gt
전부 유지. Admin UI 변경은 다음 패스.

**결과**: pytest 227개 통과 (training_data 19 신규, 회귀 0).

---

## 2026-05-20 — Stage 1 콘텐츠 게이트 (3단계 캐스케이드 1/3)

**무엇**: 12개 사기유형 단일 강제 분류 앞단에 콘텐츠 게이트를 추가. 입력을 5 bucket
(`정상`/`사기 시도`/`사기 뉴스·교육`/`의심되지만 불충분`/`판단 불가`)으로 분류해
파이프라인 실행 강도를 라우팅한다.

**왜**: (1) 정상·뉴스/교육 콘텐츠가 12개 중 하나로 강제 분류돼 오탐 → 게이트가 먼저
거름. (2) 비싼 단계(Serper·LLM)를 bucket 별로 조절해 헛수고 절감.

- `pipeline/gate.py` 신설 — `classify_gate()`. Claude Haiku 1회 + 짧은 입력 fast-path
  + 호출 실패 시 `undetermined` fallback (게이트는 죽지 않음).
- `pipeline/config.py` — `GATE_BUCKETS` / `GATE_EXECUTION_PROFILE` (bucket→실행 강도).
- `pipeline/verifier.py` — 룰 기반 신호검출(`detect_rule_signals`)을 Serper 검증
  (`verify`)과 분리. 룰 검출은 모든 gate bucket 에서 항상 실행.
- `pipeline/runner.py` — Phase 1.5 게이트 단계. profile 은 호출자 인자를 상한선으로만
  적용. 분류 skip 시 extractor 는 전체 라벨셋 합집합 사용.
- `api_server_pkg/common.py` — 게이트 결과를 내부 DB metadata 에만 기록.

**Identity Boundary**: 게이트 결과는 외부 응답 schema(`detected_signals`/`scam_type`)에
노출하지 않는다 — 검출(detection)이 아니라 내부 라우팅 신호.

**결과**: pytest 208개 통과 (gate 18 + verifier 6 신규, 회귀 0). end-to-end 스모크 확인.

---

## 2026-05-05 — APK 검출 4-tier 구현 (정적 Lv1 + Lv2 + 동적 Lv3 인터페이스)

**무엇**: VirusTotal (Tier 1) 단독 → 4-tier APK 검출 architecture. zero-day 보이스피싱 APK 대응.

**Tier 1 (이미 있음)**: VirusTotal 70+ 백신 시그니처 매칭

**Tier 2 — 정적 분석 Lv 1** (`pipeline/apk_analyzer.analyze_apk_static`):
- `androguard.core.apk.APK` 기반 manifest 분석
- 위험 권한 4종 이상 동시 → `apk_dangerous_permissions_combo`
- subject == issuer 휴리스틱 → `apk_self_signed`
- 정상 한국 앱 (kakao/naver/은행 등) typo-squatting → `apk_suspicious_package_name`

**Tier 3 — 심화 정적 분석 Lv 2** (`pipeline/apk_analyzer.analyze_apk_bytecode`):
- `androguard.misc.AnalyzeAPK` — dex disassemble + xref (코드 *읽기만*, 실행 X)
- 7 종 신호: `apk_sms_auto_send_code`, `apk_call_state_listener`, `apk_accessibility_abuse`,
  `apk_impersonation_keywords`, `apk_hardcoded_c2_url`, `apk_string_obfuscation`,
  `apk_device_admin_lock`

**Tier 4 — 동적 분석 Lv 3 인터페이스만** (`pipeline/apk_analyzer.analyze_apk_dynamic`):
- ⚠️ 로컬 실행 절대 금지 (HARD BLOCK 정책) — 호스트 멀웨어 감염 위험
- `APK_DYNAMIC_ENABLED=0` 기본 비활성, `backend=local` 어떤 env 조합으로도 풀리지 않음
- `backend=remote` + REMOTE_URL+TOKEN 둘 다 있을 때만 별도 VM 호출
- 5 종 candidate flag: `apk_runtime_c2_network_call`, `apk_runtime_sms_intercepted`,
  `apk_runtime_overlay_attack`, `apk_runtime_credential_exfiltration`,
  `apk_runtime_persistence_install`
- 실제 remote VM (Android 에뮬레이터 + Frida + MobSF stack) 구축은 future work
  — 5-7주 작업 + 별도 인프라 + 격리 정책 검증

**Phase 0.6 통합** (`pipeline/runner.py`):
- 입력이 APK 파일 (`.apk` 확장자 또는 ZIP magic) 일 때만 호출
- Lv 1 → Lv 2 → Lv 3 순차 실행, 각각 try/except graceful (실패 시 무시)
- StepLog 에 lv1/lv2/lv3 신호 개수 기록

**검출 신호 카탈로그 (총 15 종, 모두 학술/법적 근거 동반)**:
- 출처: S2W TALON 보고서 (SecretCalls·SecretCrow·KrBanker·MoqHao) / KISA / 안랩
- 학술: Cialdini (2021), Stajano & Wilson (2011), Allix et al. (2016) AndroZoo,
  Wei et al. (2018), Mavroeidis & Bromander (2017)
- 법령: 정보통신망법 제48조, 통신사기피해환급법 제2조 제2호, 형법 제283조
- API/표준: Android Documentation, OWASP Mobile Top 10, Frida

**산출물**:
- `pipeline/apk_analyzer.py` (~500 줄, Lv1 + Lv2 + Lv3)
- `pipeline/config.py` — DETECTED_FLAGS / FLAG_LABELS_KO / FLAG_RATIONALE 에 15 종 추가
- `pipeline/signal_detector.py` — `apk_static_result` / `apk_bytecode_result` /
  `apk_dynamic_result` 인자 + DetectionReport 의 3 종 check 필드
- `pipeline/runner.py` — Phase 0.6 통합 (APK 파일 자동 감지)
- `tests/test_apk_analyzer.py` (~470 줄, 70 테스트):
  - Lv 1: helper 단위 + 매핑 검증
  - Lv 2: signal_detector 통합 + 환각 차단
  - Lv 3: 안전 정책 회귀 가드 (기본 비활성 / local HARD BLOCK / auto 결정 / remote 환각 차단)
- `requirements.txt` — `androguard>=4.1.0`

**검증**:
- `pytest -q` → 184 passed (직전 114 → +70)
- 184 = baseline 85 (점수 reframe 전) + signal_detection 8 + detection_report_schema 13
  + APK Lv1 (12) + APK Lv2 (8) + Lv3 (15) + LV3 매핑 (5) + 기타
- `from api_server import app` boot OK
- Forbidden Actions: 0 위반 (점수·등급·"100% 차단"·"production-grade" 신규 0건)
- "동적 분석" vs "심화 정적 분석" 학술 용어 정확히 구분 (CLAUDE.md / README / lessons.md)

**Identity Boundary 일관**:
- ❌ 단일 신호로 "사기다" 단정 X — 누적 + 조합 시점에서만 강함 명시 (apk_analyzer.py docstring + FLAG_RATIONALE 본문 + lessons.md 패턴 6)
- ❌ 진짜 동적 분석 (에뮬레이터 실행) 하지 않음 — Lv 3 는 인터페이스 + 카탈로그만
- ❌ 로컬 실행 절대 금지 (3중 안전망: ENABLED=0 / local HARD BLOCK / remote URL+TOKEN 강제)
- ✅ 모든 신호에 학술/법적 근거 + 출처 동반 (false positive 한계도 함께 명시)

---

## 2026-05-05 — Identity reframe: 점수·등급 시스템 → 신호 검출 시스템 (Stage 1·2·3)

**무엇**: ScamGuardian 의 정체성을 "사기 판정 시스템" 에서 "사기 신호 검출 reference
implementation" 으로 reframe. VirusTotal 모델 채택 — 검출 보고만, 판정은 통합 기업이.

**왜**:
- 학부 reference 단계에서 점수의 정확한 숫자 (왜 25 점? 24 점 아니고?) 를 정당화 불가
- 등급 결정 (안전/주의/위험/매우 위험) 도 자체 RCT 없이 임계 정당화 불가
- 판정 책임을 통합 기업으로 명시적 위임 → 보안 도구의 표준 분리 모델 (VT, OWASP ZAP)
- FLAG_RATIONALE 의 학술/법적 근거가 점수 숫자보다 *훨씬* 더 무거운 자산임을 인정

**Stage 1 (narrative reframe — docs only)**:
- `CLAUDE.md` — Identity / What ScamGuardian Does NOT Do / Forbidden Actions 섹션 신설
- `README.md` — 첫 단락 교체 (사기 탐지 AI → 신호 검출 reference implementation)

**Stage 2 (코어 코드 reframe)**:
- `pipeline/signal_detector.py` 신설 — `DetectedSignal` + `DetectionReport` + `detect()`
- `pipeline/scorer.py` 삭제 (Option A 채택)
- `pipeline/config.py` — `SCORING_RULES`(dict) → `DETECTED_FLAGS`(list), `RISK_LEVELS`·
  `get_risk_level`·`LLM_FLAG_SCORE_RATIO` 폐기, `LLM_FLAG_SCORE_THRESHOLD` →
  `LLM_FLAG_DETECTION_CONFIDENCE_THRESHOLD` (env 호환 유지)
- `pipeline/runner.py` — `analyze()` 가 `DetectionReport` 반환
- `api_server_pkg/analyze.py` — description 전체 재작성 + Identity Boundary 명시
- 부수 1줄 rename: `common.py`, `health.py`, `llm_assessor.py`, `claude_labeler.py`
- **FLAG_RATIONALE 0 줄 변경** — 학술/법적 근거 그대로 보존

**Stage 3 (마무리)**:
- `pipeline/kakao_formatter.py` — 점수·등급 출력 → detected_signals 카드 + disclaimer
- `api_server_pkg/kakao/tasks.py`, `result_token.py` — log 필드 신호 개수로
- `api_server_pkg/v4_stream.py` — draft schema 도 `cumulative_signal_count` 로
- `api_server_pkg/app.py` — FastAPI title "ScamGuardian Signal Detection API"
- `tests/test_safety_scoring.py` (4) + `tests/test_sandbox_parser.py` (4) — signal_detector 로 reframe
- `tests/test_signal_detection.py` 신설 (8 테스트) — flag 검출 정확성 + LLM 환각 차단
- `tests/test_detection_report_schema.py` 신설 (13 테스트) — schema contract + 회귀 가드 (`total_score`/`risk_level` 등 폐기 필드 재도입 즉시 실패)
- `apps/web/src/app/result/[token]/page.tsx` — 점수 산정 + 위험 등급 테이블 제거 → detected_signals 카드 + 학술 근거 + disclaimer
- `apps/web/src/app/admin/{page,[runId]/AdminRunEditor,stats/page}.tsx` — 점수 표시 → 검출 신호 개수, 위험 등급 chart 제거
- `docs/INTEGRATION_GUIDE.md` — Public API 응답 schema 갱신, "Signal Detection API" rebrand
- `db/repository.py` 컬럼명은 호환 유지 (`total_score_predicted` → 신호 개수, `risk_level_predicted` → "")

**검증**:
- `pytest -q` → **114 passed, 0 failed** (회귀 0)
- `python -c "from api_server import app"` → boot OK
- `grep -rn "total_score\|risk_level" --include="*.py"` 사용처: 모두 *호환 컬럼명* 또는 *test 의 회귀 가드 (응답에 *없어야* 한다고 명시)*
- `/api/methodology` 응답: `flags[]` 의 각 항목에 `score_delta` 없음, `risk_bands` 사라짐
- `/api/analyze` description: "DetectionReport / detected_signals / Identity Boundary" 포함, "total_score / risk_level" 없음
- 카카오 카드: "🚨 위험 신호 N개 검출" + 신호별 학술 근거 + disclaimer

**Identity Boundary (CLAUDE.md Forbidden Actions 준수)**:
- ❌ 응답·UI·docstring 어디서도 "위험 점수 X점" 신규 추가 0
- ❌ "안전/의심/위험" 등급 매기기 신규 추가 0
- ❌ "이 콘텐츠는 사기입니다" 단정 신규 추가 0
- ✅ "위험 신호 N개 검출되었습니다, 자세한 근거는 detected_signals 참고" 형식만 사용
- ✅ FLAG_RATIONALE 0 줄 변경 — 학술/법적 근거 (Cialdini, Whitty, Stajano & Wilson, FBI IC3, KISA 등) 그대로

---

## 2026-05-04 — v4 Whisper 5초 chunk 한국어 정확도 측정 ⚠️ FAIL (그러나 valuable)

**무엇**: 5개 한국어 시나리오 (검찰사칭/금융사칭/메타인식/송금동의/대조군) 를 edge-tts 합성, OpenAI Whisper API 5초 chunk 로 transcribe, WER 측정.

**결과**: 평균 WER **0.307** (임계 0.20 → FAIL). 5/2 PASS. chunk 평균 latency 1985ms.

**왜 valuable**:
- v4 직진 못 한다는 명확한 시그널 — 30분 검증의 본 목적이 "들어가기 전 break point 찾기"
- 실패 원인 3가지가 모두 알려진 패턴 → 처방 가능

**핵심 발견 (3종 실패 패턴)**:
1. **침묵 chunk 환각** (s1_prosecutor) — 발화 종료 후 침묵 5초 chunk 에 Whisper 가 "MBC 뉴스 이덕영입니다" 환각. Whisper 학습 데이터의 뉴스 종영 멘트 bias. → **VAD pre-filter** 필요.
2. **Chunk 경계 단어 절단** (s3, s4, s5) — 5초 경계가 단어 중간에 떨어져서 양쪽 chunk 모두 부정확. 예: "되는 건가요" → "되는 겁니까? | 건가요?". → **overlapping window (2초 hop) + dedupe** 필요.
3. **한국어 숫자/신조어 표기** (s5) — "두 시쯤" → "2시쯤" 의미 동일하지만 token WER 잡힘. → **CER 또는 의미 기반 metric** 검토.

**산출물**:
- `experiments/v4_whisper/synthetic_samples.jsonl` (5개 발화 정의)
- `experiments/v4_whisper/audio/*.mp3 + *.txt` (TTS + reference)
- `experiments/v4_whisper/generate_synthetic.py` (edge-tts 합성, --speakerphone 옵션)
- `experiments/v4_whisper/batch_eval.py` (5샘플 batch + WER aggregation)
- `experiments/v4_whisper/results.md` (per-sample 결과 + 핵심 발견 + 처방)

**의존성 추가**: `edge-tts` (개발 전용, requirements.txt 미포함).

**v4 설계 결정**:
- 5초 고정 chunk 단순 chunker 는 production 부적합
- chunker v2 = VAD pre-filter + overlapping window + dedupe → 재측정 후 평균 WER < 0.15 또는 CER < 0.10 통과해야 v4.0 진입
- 또는 Deepgram 한국어 (정확도 ↑, 비용 5×) 비교 검증 후 결정

다음: api_server.py 분리 + v4 검증 종합 커밋 → 사용자 확인 후 chunker v2 또는 다른 방향 선택.

---

## 2026-05-04 — api_server.py 라우터 분리 완료 ✅

**무엇**: `api_server.py` (2368 LOC 모놀리스) → `api_server.py` (41 LOC entry) + `api_server_pkg/` (10개 모듈, 2437 LOC).

분리 단위:
| 모듈 | LOC | 역할 |
|---|---|---|
| `state.py` | 42 | 모듈 전역 상태 (`pending_jobs`, `result_tokens`, `jobs_lock`, `bg_tasks`, `public_url_cache`) + 타임아웃 상수 + `spawn_bg` |
| `models.py` | 61 | Pydantic 요청 모델 7종 (AnalyzeRequest 등) |
| `common.py` | 155 | `persist_run`, `run_pipeline`, `resolve_source`, `options_payload`, `require_db` |
| `health.py` | 58 | `/health`, `/api/methodology` |
| `result_token.py` | 145 | `/api/result/{token}` + `issue_result_token` + `get_public_base_url` (60s 캐시) |
| `kakao.py` | 1187 | `/webhook/kakao` + 모든 `_kakao_*` + 멀티턴 컨텍스트 흐름 |
| `analyze.py` | 187 | `/api/analyze`, `/api/analyze-upload` |
| `admin_runs.py` | 301 | runs/metrics/stats/ai-draft/media/scam-types |
| `admin_platform.py` | 108 | login/api-keys/observability/cost/abuse-blocks |
| `admin_training.py` | 109 | training/* 세션 관리 |
| `app.py` | 76 | FastAPI 인스턴스 + middleware + include_router + startup |

**왜**: 단일 파일 2368 LOC 가 (1) 한 파일 안에 컨텍스트 수집·웹훅·라벨링·플랫폼이 다 섞여 한 화면에 안 잡힘 (2) git blame/diff 노이즈 (3) 새 기능 (v4 Live Call Guard) 도 같은 파일에 들어가면 더 비대해질 예정. 라우터 단위 분리로 모듈 응집도 ↑.

**구현 노트**:
- 외부 import 호환성 100% — 테스트가 `from api_server import _kakao_detect_input` / `_resolve_admin_media_path` / `_is_system_command` / `_wrap_with_soft_warning` / `app` 직접 가져옴 → 모두 re-export
- 모듈 전역 상태는 `api_server_pkg.state` 한 곳에 모음 (`_pending_jobs` → `state.pending_jobs` 등). 여러 모듈이 같은 dict 인스턴스 공유.
- 라우터 패턴: 각 모듈에 `router = APIRouter()`, `app.py` 에서 `include_router(...)` 일괄 등록.
- `importlib.reload(api_server)` 호환 — `api_server.py` 가 thin entry 라 reload 시 `create_app()` 재실행됨.

**결과**: ✅ pytest 93/93 통과 (6.51s, baseline 6.95s 보다 살짝 빠름). TestClient 로 `/health`, `/api/methodology` 검증 — 36 routes (admin 26개) 정상.

다음: v4 Whisper 5초 chunk 한국어 정확도 측정 (TTS 합성 음성 5~6개).

---

## 2026-05-04 — pytest baseline 확인 (refactor 시작 전)

**무엇**: `pytest -q` 실행, 13개 파일 / 93 테스트 통과 (6.95s).

**왜**: api_server.py (2368 LOC) 라우터별 분리 리팩토링 들어가기 전, baseline 확인. 분리 후 동일하게 93/93 통과해야 통과 판정.

**결과**: ✅ 93 passed. 분리 작업 시작 가능.

다음: api_server/ 패키지 골격 + helpers + health 분리.

---

## 2026-06-04 — APK 동적분석 VM 'API server' 회색불 + AndroZoo 벤치마크 오류 디버깅

**무엇**:
1. `api_server_pkg/androzoo_client.py` — AndroZoo 리스트/다운로드 요청에 브라우저 User-Agent(`_HEADERS`) 추가 + HTML 응답 가드.
2. `scripts/apk_dynamic_vm_ctl.sh` — `start_server` 를 nohup → **systemd 서비스(sg-apkdyn)** 로 교체 (Restart=always + WantedBy=multi-user.target). `logs`/`status` 도 journald 기준으로 갱신.

**왜**:
- 벤치마크 `Not a gzipped file (b'<h')`: AndroZoo 앞단 WAF 가 `python-requests` 기본 UA 를 "Request Rejected" HTML 로 차단 → gunzip 실패. (키 문제 아님 — 리스트는 공개.)
- 카드 'API server' 회색: VM 안 `apk_dynamic_server/app.py` 가 supervision 없는 맨 nohup 프로세스라, ① 03:55 단발 SIGTERM, ② VM 재부팅(24h 내 3회) 한 번에 영구 다운. redroid/frida 는 docker/Android 측이라 생존, app.py 만 죽음.

**결과**: ✅
- AndroZoo: Python 클라이언트로 실제 gzip row 스트리밍 검증.
- systemd: is-enabled=enabled / SIGTERM 후 자동 부활(MainPID 교체) / status-json server_up=true 검증. 디버깅 중 self-killing pkill(heredoc 의 'python3 app.py' 가 우리 shell argv 에 박힘)·pipefail+set -e 변수할당 중단 두 버그도 잡음.

다음: 실제 end-to-end 동적분석은 WSL 브릿지(`vm_ctl.sh bridge`/`start`)도 떠야 함 — 카드 불과 별개 레이어.

**후속**: `scripts/start_stack.sh` 에 APK 동적분석 WSL 브릿지 통합 — `ENABLE_APK_BRIDGE=auto`(기본). VM(sg-sandbox) 이 Running 일 때만 브릿지 자동 기동(6GB VM 강제부팅 회피), `true` 면 항상/`false` 면 스킵. stop 섹션·로그 힌트도 갱신. 이제 매번 `vm_ctl.sh bridge` 수동 실행 불필요.
