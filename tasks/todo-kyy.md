# todo-kyy

## 2026-05-29 — 이전 브랜치(main) 대비 변경점 문서화

`main..main-kyy` diff + 미커밋 작업 트리를 기준으로 kyy.md / README.md 갱신 후 푸시.

### 계획
- [x] `main..main-kyy` 커밋 diff 파악 (3단계 캐스케이드 / 학습·평가 / latency 단축 / AGENTS·docs)
- [x] 미커밋 신규 작업 파악 (CLOVA STT / hallucination 강화 / diarize / streaming / Live Voice)
- [x] `kyy.md` — 2026-05-29 신규 작업 섹션 추가 (STT 정확도·CLOVA·화자분리·스트리밍·Live Voice)
- [x] `README.md` — 테스트 수(114→322) / STT 백엔드 env / Live Voice 채널 / 신규 엔드포인트 반영
- [x] 커밋 + main-kyy 푸시 (3812846)

### Review
- 미커밋 기능 코드(CLOVA STT·diarize·stream_analyze·transcribe·Live Voice) + 문서를 한 커밋으로 묶어 푸시.
- sqlite 백업·.bak·phh_training·temp 파일은 명시적으로 제외 (git add -A 대신 경로 지정).
- `from api_server import app` boot OK (42 routes) 확인 후 푸시.
- 후속: `.env.example` 에 STT_BACKEND/CLOVA_* 추가, CLOVA 화자분리 정확도 측정.

## 2026-06-01 — 화자 분리 chunk 경계 문제 해결 (전역 diarization)

`/api/analyze-stream` 이 업로드 파일을 60초 wall-clock 으로 쪼개 chunk마다 CLOVA 를
독립 호출 → (1) turn 중간 절단 (2) CLOVA speaker label 이 요청 단위로만 일관 → chunk
경계에서 상대방/본인 뒤집힘. 파일은 이미 전체가 있으므로 chunk 자체가 자초한 문제.

**방향**: STT/diarization 은 통파일 1회 (전역 일관 turns), "스트리밍" 은 분석 단계로
이동 — 전역 turns 를 ~60초 window 로 묶어 progressive emit. 프론트 이벤트 contract
(start/chunk/done/error) 동일 유지 → 프론트 변경 0.

### 계획
- [x] `_window_turns(turns, window_seconds)` 헬퍼 — 전역 turns 를 ~60초 단위 window 로 묶기
- [x] `analyze_stream` 재작성: ffmpeg segment 분할/chunk loop 삭제 → 통파일 `_stt.transcribe()` 1회
- [x] window 순회하며 `_scan_text` → 기존 `chunk` 이벤트 shape 그대로 emit (turns 전역 timestamp)
- [x] ffmpeg 전처리에서 CLOVA backend 면 `silenceremove` 제거 (경계·timestamp 보존) — stream + transcribe-upload 양쪽
- [x] boot OK (42 routes) + 실제 통화(121s) 분리 정확도 확인 + 단위테스트 추가
- [ ] (조건부) 장문 CLOVA sync 한계 확인 → 필요 시 침묵 분할 fallback (미발생 — 보류)

### Review
- **핵심**: `/api/analyze-stream` 이 60초 wall-clock chunk → CLOVA 독립 호출 (경계 절단 + label 뒤집힘)
  하던 것을, **통파일 1회 STT/diarization → 전역 turns → ~60초 window 로 묶어 progressive emit**
  으로 전환. STT 는 1회, "스트리밍" 은 분석(window) 단계로 이동.
- **프론트 변경 0**: `start`/`chunk`/`done`/`error` 이벤트 contract 유지. `chunk` 가 시간
  슬라이스 → turn window 로 의미만 바뀜 (turns 전역 timestamp, start/end_sec 정확).
- **silenceremove**: CLOVA backend 일 때만 제거 (`_audio_filter()`). CLOVA 는 침묵 환각이
  없어 불필요한데 화자 경계 정적·timestamp 만 망가뜨렸음. non-CLOVA(Whisper) 는 그대로 유지.
  stream_analyze.py + transcribe.py 양쪽 적용.
- **실증** (실제 검찰 사칭 통화 121s): 새 흐름에서 상대방 모놀로그가 45.0–76.2s 연속 1 turn
  으로 유지 — 옛 60초 경계를 가로질러도 안 잘림. 상대방/본인 label 전 구간 일관. wav 121s
  그대로 (silenceremove 미적용 → timestamp 원본 일치).
- **코드 감소**: ffmpeg segment 분할, chunk glob, chunks_dir mkdtemp/cleanup, per-chunk
  diarize fallback 제거. non-CLOVA 는 전체 텍스트 1회 Sonnet diarize 로 처리.
- **테스트**: `tests/test_stream_window.py` 6개 신규 (window 분할/turn 보존/filter 분기) +
  전체 322→328 passed.
- **보류**: 10분 초과 장문에서 CLOVA `completion: sync` 단일 호출 한계는 실제로 안 만나
  보류. 만나면 침묵 기준 분할(silencedetect cut) fallback 추가 예정.

## 2026-06-01 — 화자 역할 배정: duration 휴리스틱 → 내용 기반 LLM (A안)

`_clova_to_turns` 가 "발화 시간 총합 가장 긴 화자 = 상대방" duration 휴리스틱으로 역할을
정해, 피해자가 더 많이 말하는 통화에서 상대방/본인이 통째로 뒤집힘. CLOVA 의 음향 기반
segment 분리는 정확하므로, **segment·텍스트는 그대로 두고 label→역할 매핑만 내용 기반**
으로 교체 (다시 쪼개지 않음 → 텍스트 생성 X → 환각 위험 없음).

### 계획
- [x] `_label_durations` / `_label_texts` / `_duration_role_map` 헬퍼 분리
- [x] `_assign_clova_roles(segments)` — Haiku 에게 "둘 중 누가 전화 건 사람?" 만 질의 → {label:역할}
- [x] `_parse_role_map` — JSON 객체 파싱 + 검증 (라벨 1:1, 역할 {상대방,본인}) + "화자 N"/"speaker N" 키 정규화
- [x] `_clova_to_turns` 가 longest_label 대신 `_assign_clova_roles` 결과 사용
- [x] fallback: 파싱 실패·역할 중복·LLM 실패·`CLOVA_ROLE_ASSIGN=duration`·화자수≠2 → duration 휴리스틱
- [x] 단위 테스트 12개 (`tests/test_clova_roles.py`) + 전체 340 passed
- [x] 실증: 합성 통화(피해자가 더 많이 말함)에서 duration=오판 vs LLM=정확 교정 확인

### Review
- **핵심 교체**: [pipeline/stt.py](pipeline/stt.py) `_clova_to_turns` 의 역할 매핑 1줄
  (`longest_label`) → `_assign_clova_roles()`. CLOVA segment/텍스트/timestamp 불변.
- **LLM 작업 범위**: 텍스트 생성 0 — 두 라벨에 역할 딱지만 (출력 토큰 ~20, max_tokens=80).
  `diarize()` 의 환각 가드 불필요. 입력은 화자별 발화 모음 + 발화량(초) 보조단서.
- **안전**: env `CLOVA_ROLE_ASSIGN=llm`(기본)/`duration` 토글. 모든 실패 경로 → duration
  fallback (ANTHROPIC 키 없을 때 graceful, 검증 실패 시 fallback) → 회귀 없음.
- **비용**: Haiku 1콜/통화 (~0.9s, ledger action=`diarize.role_assign`). CLOVA 4~7s 대비 미미.
  통파일 1회 diarization 과 합쳐져 통화당 1콜 (전역 일관).
- **Identity Boundary 무관**: "둘 중 누가 전화 건 쪽인가" 판정 — 사기 판정·점수 아님.
- **실증** (clova-kyy.log):
  - 실제 검찰사칭 통화: `LLM {'1':'상대방','2':'본인'} (duration 일치, 0.9s)`
  - 합성 피해자-다발화 통화: duration `{'1':'본인','2':'상대방'}`(오판) vs LLM `{'1':'상대방','2':'본인'}`(교정)
- **미적용**: 개별 segment 오배정(turn[3]류)은 그룹 단위 역할 배정으론 못 고침 — 필요 시
  segment 단위 교정 패스(B안) 별도. 현재 보류.

## 2026-06-01 — STT 오인식: 전처리 dynaudnorm 제거 (측정 기반)

화자분리 체감 저하의 큰 부분이 STT 텍스트 깨짐("수사관입니다"→"수작을 했다")이었음.
원본이 전화 8kHz 가 아니라 **48kHz 스테레오 고음질**이라 전처리 한계가 아니라 전처리가
오히려 STT 를 망치고 있었음. 실제 통화로 ffmpeg -af A/B 측정:

| 전처리 | 수사관 | 명의로 된 그게 | 발급된 겁니다 |
|--------|--------|----------------|----------------|
| dynaudnorm(현재) | 수작을 했다 ❌ | 명의료된 그량 ❌ | 발급된니다 ❌ |
| **무필터(clean)** | **수사관입니다 ✅** | **명의로 된 그게 ✅** | **발급된 겁니다 ✅** |
| speechnorm / gentle dynaudnorm | 부분만 ✅ | ❌ | ❌ |

→ **어떤 정규화든 CLOVA STT 저하** (단어 사이 노이즈 플로어 pumping). clean 16k downsample 최선.

### 변경
- [x] `_audio_filter()` (stream_analyze.py + transcribe.py): CLOVA 면 빈 문자열 → `_ffmpeg_af_args()`
      가 `-af` 자체 생략. non-CLOVA(Whisper) 는 silenceremove+dynaudnorm 유지.
- [x] 테스트 갱신 (`test_audio_filter_clova_is_clean_downsample`) + 전체 340 passed
- [x] boot OK, clova/whisper 분기 검증

### 남은 STT 오류 (전처리로 안 잡히는 잔여)
"통장이 줄기"(통장이 뭐죠), "죽었다고"(받았다고), "철산 치석"(철산동) 등 — 음향 자체 모호.
다음 레버: **LLM 후처리 교정** → 아래에서 구현.

## 2026-06-01 — STT LLM 후처리 교정 (`pipeline/stt_correct.py`)

깨진 전사("이선호 수작을 했다"→"수사관입니다", "철산 치석"→"철산동 지점")를 LLM 이 맥락으로
교정. **생성 금지** — 명백한 STT 오류만, 내용 추가·요약·의미변경 X.

### 설계
- turn 단위 교정 — speaker / start_sec / end_sec 보존, text 만 교체
- **fabrication 가드 3중**: (1) turn 개수 일치 (2) turn별 길이비율 [0.4,2.5] 이탈 시 해당 turn
  원본 유지 (3) 전체 길이비율 [0.6,1.8] 이탈 시 통째 거부 → 회귀 없음
- 모든 실패(LLM 오류·파싱 실패·키 없음) → 원본 그대로
- env `STT_CORRECT=1`(토글, 기본 0) / `STT_CORRECT_MODEL`(기본 Haiku)
- `stt.transcribe()` 의 `_maybe_correct()` 에서 turns 있을 때만 적용 (CLOVA). text 도 재구성
  → 다운스트림(엔티티·분류·RAG)도 깨끗한 텍스트 사용
- Identity Boundary: 판정·점수 주입 X, 순수 전사 교정만

### 검증 (실제 통화 측정)
- Haiku/Sonnet 둘 다 외과수술식 최소 교정 — 글자단위 diff: `철산 치석→철산동 지점`,
  `본인 통산→본인 통장` 만. **fabrication 0**. 모호한 "통장이 줄기"/"죽었다고"는 안 건드림(규칙3).
- `transcribe()` end-to-end: 역할배정 LLM + 교정 LLM 정상 합성 (철산동✅, 본인통장✅)
- 단위테스트 8개 (`tests/test_stt_correct.py`, 가드·토글·구조보존·fabrication거부) + 전체 348 passed
- `.env` 에 `STT_CORRECT=1` 활성화

### 후속 옵션
- 잔여 음향 모호 케이스("통장이 줄기" 등)는 단일 발화만으론 LLM 도 추측 불가 — 더 큰 맥락
  (전후 turn) 줘도 한계. CLOVA 사용자 사전 등록(고유명사)이 보완 레버.
- 교정 모델 Haiku→Sonnet 시 고유명사 잡는 폭 약간 ↑ (`STT_CORRECT_MODEL`).

## 2026-06-01 — Live Voice 알림 설계: 계층적 에스컬레이션 (시각 중심)

매번 울리면 알람 피로 → "결정적 순간에 한 번 확실히". 사용자 결정: **계층적 에스컬레이션
+ 화면(시각) 중심.**

설계:
- **신호 2분류**: instant(주민번호·OTP·안전계좌·송금동의·즉시송금 → 바로 danger) vs
  cumulative(기관사칭·긴박감·순응 → 슬라이딩 누적 점수 → 임계)
- **3단계 tier**: 🟢watch → 🟠caution(상단 배너+pulse) → 🔴danger(풀스크린+flash+행동+근거+확인)
- **규칙**: instant → 단계 건너뛰고 danger / 누적 임계 / tier 단조증가(내림 flicker 방지) / 쿨다운
- **시각 핵심**: danger 는 정적 빨강 X, **flash(번쩍임)** — 주변시야로도 감지
- **메시지**: "신호 감지 + 행동 안내 + 근거" (Identity Boundary — "사기다" 단정 X)

### 계획
- [x] 백엔드: `_ALERT_PATTERNS` 에 instant/action 추가, `_scan_text` 가 match 에 포함
- [x] 백엔드: window 순회 시 cumulative 점수 + instant → `tier`(0~3, 단조) + `tier_changed` emit
- [x] 백엔드: 단위 테스트 7개 (`tests/test_stream_alert_tier.py`) — instant→3, 누적 임계, 단조성
- [x] 프론트: StreamChunk/StreamMatch 타입 확장(tier/instant/action)
- [x] 프론트: tier state(단조) + dangerDismissed, handleStreamEvent 갱신 (죽은 cumulativeAlert 제거)
- [x] 프론트: CautionBanner(pulse) + DangerOverlay(풀스크린 flash + 확인 + 행동/근거) + 잔류 빨간 바
- [x] globals.css: danger-flash keyframe (+ prefers-reduced-motion fallback)
- [x] 검증: tsc exit 0, /live dev HTTP 200, 백엔드 355 passed

### Review
- **백엔드** ([stream_analyze.py](api_server_pkg/stream_analyze.py)): `_ALERT_PATTERNS` 6-tuple
  (flag,regex,level,label,**instant,action**) 로 확장. instant=돌이킬수없는 신호(주민번호·OTP·
  안전계좌·송금동의·즉시송금). `_compute_tier(cum_score, instant_seen, any_match)` — instant 1개
  또는 누적≥6 → 3(danger), 누적≥3 → 2(caution), 신호 있음 → 1, 없음 → 0. window 순회 시
  tier 단조증가 + `tier_changed` emit. match 에 instant/action 포함.
- **프론트** ([LiveVoiceUpload.tsx](apps/web/src/app/live/LiveVoiceUpload.tsx)): tier state(단조) +
  dangerDismissed. DangerOverlay(풀스크린 `animate-danger-flash` + "지금 전화를 끊으세요" +
  pickAlertAction 으로 행동안내 + 근거 + 확인버튼) / 잔류 빨간 바(재노출) / CautionBanner(amber pulse).
  tier_changed && tier≥3 면 dismissed 리셋해 재경보.
- **시각 핵심**: danger 는 정적 빨강 X → flash 키프레임(주변시야 감지). reduced-motion 정적 fallback.
- **Identity Boundary**: "사기다" 단정 X — "위험 신호 감지 + 행동안내 + 근거 + 판단은 본인" 문구.
- **빌드 메모**: `npm run build` 는 **무관한 기존 페이지 `/methodology`** 의 prerender 버그
  (`data.risk_bands.map` 등 undefined)로 실패 — 내 변경(live/css/backend) 아님. `/live` 는 컴파일
  성공·dev HTTP 200. (methodology prerender 버그는 별도 후속 — 내 스코프 밖.)
- pre-existing eslint `no-unescaped-entities`(`"{m.snippet}"` 3곳)는 빌드 비차단(컴파일 성공) — 미수정.

## 2026-06-01 — 화자별 알림 (#2: 만들어둔 diarization 을 알림에 실제로 사용)

기존 알림은 화자 구분 없이 전체 전사문을 regex 스캔 → "송금하세요"(사기범)와 "송금했어요"
(피해자)를 구분 못 함. 이미 `win["turns"]` 에 화자 라벨이 있으니, **turn 별로 스캔하고
(신호 × 화자)로 심각도 차등.** v4 "피해자 compliance 신호" 가설을 실제 구현.

### 핵심 분류 (같은 키워드, 다른 심각도)
- 본인 발설(주민번호·OTP·비번)·송금 동의("이체했어요") → 🔴 **instant danger**
- 상대방 사칭(검찰청)·요구·압박 → 🟠 **누적 경고**
- 본인 "이거 사기 같은데" → 🟢 보호 신호(낮은 누적)
- transfer_done 은 사기범 발화면 무시(by_scammer=None)

### 변경
- [x] `_SPEAKER_PATTERNS` (flag/regex/label/by_victim/by_scammer) + `_classify`(role None→더 심각)
- [x] `_scan_turns(turns)` 화자별 스캔, window 루프가 turns 있으면 사용(없으면 `_scan_text` fallback)
- [x] match 에 `speaker` 필드 → 프론트 칩·DangerOverlay 에 "🙋 본인 / 🗣️ 상대방" 표시
- [x] 테스트 13개 (화자별 instant 차등, 사기범-only 통화 non-instant) + 전체 361 passed
- [x] tsc exit 0, /live dev HTTP 200, 실제 통화 검증(사칭 4건→상대방 누적8→tier3)

### 오탐 감소 효과
사기범만 떠드는 콘텐츠(뉴스·교육영상)는 본인 compliance 없음 → instant 안 뜸 → danger 직행 X.

### 알려진 후속 (이번 범위 밖)
- 같은 flag 반복이 누적점수 부풀림(실측: 사칭 4회→8점). 윈도우 내 동일 flag 캡/디듀프가 보완 레버.
- transfer_done regex 는 명시적 송금어만 — "네 알겠습니다" 류 일반 compliance 미포착(누적 신호로 별도 모델링 가능).

## 2026-06-01 — Live Voice 실시간 마이크 (스피커폰 양쪽) MVP

사용자 선택: 스피커폰 양쪽 캡처 → 실시간 화자분리 필요. **우회**: 클라이언트가 누적 오디오를
주기적으로 보내고 백엔드가 **통째 재분석**(기존 통파일 diarization·역할배정·화자별 알림 재사용)
→ chunk별 diarization 뒤집힘 회피, 화자분리 품질 유지. stateless(클라이언트가 상태 보유).

### 계획
- [x] 백엔드 `POST /api/live-analyze` ([live_stream.py](api_server_pkg/live_stream.py)): 누적 오디오 →
      ffmpeg(clean) → stt.transcribe → `_scan_turns` → tier → JSON {turns, matches, tier, transcript}. stateless.
- [x] app.py 라우터 등록 + middleware require-key 추가
- [x] Next 프록시 route ([api/live-analyze/route.ts](apps/web/src/app/api/live-analyze/route.ts)) — API key 자동 첨부
- [x] 프론트: 🎤 마이크 모드 — getUserMedia + MediaRecorder(1s timeslice), ~7초마다 누적 blob POST →
      tier 단조 갱신 → 기존 DangerOverlay/CautionBanner/화자칩 재사용. 시작/중지·전사 미리보기.
- [x] 검증: 엔드포인트 실제통화 200(tier3·화자별), 프록시 체인 200, /live dev 컴파일, tsc 0, 361 passed

### Review
- **핵심 우회**: 실시간 chunk별 diarization(뒤집힘) 대신 **누적 오디오 통째 재분석** → 기존
  통파일 diarization·역할배정·화자별 신호(`_scan_turns`)·tier 전부 재사용. stateless(클라가 상태 보유).
- **흐름**: 마이크 → MediaRecorder 누적 → 7초마다 `new Blob(chunks)` POST → 백엔드 CLOVA STT+
  화자분리+역할배정 → 화자별 신호+tier → 프론트 tier 단조 max → 본인 발설/송금동의 시 🔴 풀스크린.
- **재사용**: 알림 UI(DangerOverlay·CautionBanner·잔류바·화자칩) live 모드에 그대로. reset()이 마이크
  정리(트랙 stop·timer clear) 담당 → 모드 전환/초기화 시 캡처 종료.
- **실측 지연**: 121s 누적 분석 ~6.7~8s. 통화 길수록 ↑(누적 재-STT). 데모 OK, production 은
  true streaming STT 필요.
- **정직한 제약(UI에도 명시)**: iOS 통화 중 브라우저 마이크 제한 → 스피커폰+별도기기 권장.
- 후속: 슬라이딩 윈도우(최근 N초만)로 지연·비용 cap / CLOVA 실시간 gRPC 전환 / 동일 flag 누적 캡.

## 2026-06-01 — 라이브 최적화: 슬라이딩 윈도우(최근 N초) + 화자별 dedup tier

기존 라이브는 매 tick 누적 오디오 통째 재-STT → O(n²) (5분 통화 ~21배 중복 처리). 지배적
비용(CLOVA+역할LLM)을 **최근 N초로 bound** → 선형화.

### 설계
- 백엔드 `/api/live-analyze` 에 `window_sec` 추가: >0 이고 길이 초과면 wav 를 **마지막
  window_sec 만 잘라** CLOVA 에 보냄 (webm→wav 로컬 변환은 cheap, CLOVA 호출만 bound).
- 프론트: tick 마다 `window_sec=45` 전송. **중지 시 `window_sec=0`(full)** → 완전한
  전사/화자분리(말풍선·재생용).
- tier 의미 보존: 윈도우면 backend tier 가 윈도우 한정 → **프론트가 누적 match(dedup
  flag+snippet+speaker)로 tier 계산**(instant→3, 누적합 임계). 부수효과로 동일 flag 반복
  부풀림도 해결.

### 계획
- [x] 백엔드 `window_sec` 트림 ([live_stream.py](api_server_pkg/live_stream.py)): >0 이고 길이 초과면
      wav 마지막 window_sec 만 잘라 CLOVA. window_sec=0 이면 full.
- [x] 프론트: tick `window_sec=45` / 중지 `window_sec=0`(full). 누적 dedup match
      (`dedupMergeMatches`) + client tier(`computeTierFromMatches`) + finalizing 게이팅
- [x] 검증: window=45 트림 로그 확인(121s→45s), /live tsc/lint clean, 361 passed

### Review
- **핵심**: 지배 비용(CLOVA STT + 역할LLM)을 매 tick 최근 45초로 bound → O(n²)→선형.
  실측: window=45 가 전체 121s 를 45s 로 트림(turns 8→5, 로그 확인).
- **tier 의미 보존**: 윈도우면 backend tier 가 윈도우 한정 → 프론트가 누적 match(dedup
  flag+snippet+speaker)로 tier 계산. 단조 유지 + **동일 flag 반복 부풀림도 dedup 으로 해결**.
- **중지 시 full**: window_sec=0 으로 전체 1회 분석 → 완전한 전사·화자분리(타임스탬프가 full
  오디오와 정합 → 말풍선 클릭 재생 정확). full 도착 전엔 `liveFinalizing` 로 말풍선 숨김
  (윈도우 turn 의 윈도우-상대 타임스탬프로 잘못 재생되는 것 방지).
- **잔여(정직)**: 프론트가 여전히 누적 webm 을 보냄 → 업로드 대역폭 + 백엔드 webm→wav 로컬
  변환은 O(n) 으로 자라남(둘 다 cheap, 지배 비용 아님). 완전 선형화는 증분 전송(webm 헤더
  surgery) 또는 CLOVA 실시간 gRPC 필요 — 후속.
- 역할 캐싱은 미적용(stateless) — 윈도우 bound 로 역할LLM 도 45s 한정이라 cheap, 후속 옵션.

## 2026-06-01 — 크롬 OS 알림 (탭 안 볼 때 경보, PII·서버 0)

카카오 push 는 전화번호(PII)+사업자등록 필요로 무거움. 브라우저 내장 `Notification` API 로
대체 — 탭이 백그라운드여도 OS 토스트로 경보. 서버·라이브러리·PII 전부 불필요.

### 변경 (프론트 only, [LiveVoiceUpload.tsx](apps/web/src/app/live/LiveVoiceUpload.tsx))
- [x] `startLive` 에서 `Notification.requestPermission()` (시작 버튼 제스처 안)
- [x] `fireDangerNotification(matches)` — danger 진입 1회. tag=중복방지, requireInteraction,
      onclick→window.focus()(탭 복귀). 모바일 SW-필요 브라우저 대비 try/catch
- [x] `notifiedDangerRef` 가드로 danger 진입 시 1회만 (단조), reset 시 해제
- [x] 안내 문구 추가, tsc/lint clean, /live 200
- 제약: 탭 열려있어야(완전 닫으면 Web Push 필요) / iOS 는 PWA 설치해야 / 백그라운드 throttling
  은 마이크 캡처 중 완화 / "차단" 누르면 재요청 불가

## 2026-06-01 — 말풍선 클릭 → 음성 재생 (라이브 모드)

`Conversation` 컴포넌트엔 이미 turn 별 ▶️ 재생(start_sec~end_sec seek) 이 있었음(단일 모드). 라이브
모드에 오디오·turns 를 연결 + **말풍선 전체 클릭**으로도 재생되게.

### 변경
- [x] live state `liveTurns`(화자분리) / `liveAudioUrl`(blob) 추가, `sendLiveCumulative` 가 turns 저장
- [x] `stopLive` 가 캡처 누적 chunks → `Blob` → objectURL (cleanup 전에), reset 시 revoke
- [x] live 섹션에 `<Conversation turns={liveTurns} audioUrl={liveAudioUrl} />` 렌더
      (중지 후 audioUrl 생기면 클릭 재생 가능, 녹음 중엔 말풍선만)
- [x] `Conversation` 말풍선 div 전체 onClick 재생(cursor-pointer) + 내부 ▶️버튼 stopPropagation
      → 단일·라이브 양쪽 적용
- [x] tsc 0, lint clean(신규 0), /live 200

### 정직한 제약
- MediaRecorder WebM 은 duration 메타가 불완전해 `currentTime` seek 이 브라우저별로 부정확할 수
  있음(Chrome 대체로 OK, FF/Safari 변동). 필요 시 서버에서 seekable 포맷 변환이 보완 레버.
