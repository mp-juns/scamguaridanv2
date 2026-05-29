import Link from "next/link";
import LiveVoiceUpload from "./LiveVoiceUpload";

export const metadata = {
  title: "LIVE VOICE — 통화 중 실시간 사기 탐지",
  description:
    "사기 후가 아닌 사기 중 차단 — 본인 발화 실시간 분석으로 의심 신호 발견 시 가족 SMS · TTS 음성 · 풀스크린 경보로 통화를 끊을 시간을 만듭니다.",
};

const SIGNALS = [
  {
    label: "메타인식 표현",
    examples: ["이거 사기 같은데", "이상한데", "진짜인가요?"],
    weight: "강",
  },
  {
    label: "민감 정보 누설",
    examples: ["주민번호는…", "OTP는…", "비밀번호는…", "계좌번호 X"],
    weight: "매우 강",
  },
  {
    label: "송금 동의",
    examples: ["이체했어요", "보낼게요", "얼마 보내요"],
    weight: "결정적",
  },
  {
    label: "권위 굴복 누적",
    examples: ["네 알겠습니다 반복", "검찰청이 진짜인가요? + 곧 동의"],
    weight: "중 (윈도우)",
  },
  {
    label: "긴박감 휩쓸림",
    examples: ["지금 바로요?", "빨리…", "혼란·말더듬"],
    weight: "약-중",
  },
];

const ALERT_TIERS = [
  {
    tier: "L1 약함",
    trigger: "민감 키워드 1개",
    channels: ["화면 하단 노란 배너"],
    tone: "border-amber-400/30 bg-amber-500/5 text-amber-100",
  },
  {
    tier: "L2 중간",
    trigger: "메타인식 + 키워드 누적",
    channels: ["빨간 배너", "진동", "가족 SMS 1차"],
    tone: "border-orange-400/40 bg-orange-500/10 text-orange-100",
  },
  {
    tier: "L3 강함",
    trigger: "송금 동의 / 명시적 사기 신호",
    channels: [
      "풀스크린 빨간 깜빡임",
      "알람음",
      "TTS 강제 차단음 — 사기범도 듣게 됨",
      "가족 SMS 2차 (콜백 요청)",
      "사전 등록 지인 알림",
    ],
    tone: "border-rose-400/50 bg-rose-500/15 text-rose-100",
  },
];

export default function LiveVoicePage() {
  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,#3b0a18_0%,#1e0a14_45%,#020617_100%)] px-6 py-10 text-slate-100">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-8">
        <section className="rounded-3xl border border-rose-400/20 bg-white/5 p-8 shadow-2xl shadow-rose-950/30 backdrop-blur">
          <div className="mb-6 flex flex-wrap items-center gap-3">
            <span className="rounded-full bg-rose-400/15 px-3 py-1 text-xs font-semibold tracking-[0.2em] text-rose-200 uppercase">
              ScamGuardian · v4
            </span>
            <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-slate-300">
              🎙️ Live Voice
            </span>
            <span className="rounded-full border border-amber-300/30 bg-amber-400/5 px-3 py-1 text-xs text-amber-200">
              개발 중 (Coming soon)
            </span>
            <Link
              href="/"
              className="rounded-full border border-white/10 px-3 py-1 text-xs text-slate-300 transition hover:bg-white/5"
            >
              ← 분석 대시보드
            </Link>
          </div>

          <h1 className="text-4xl font-semibold tracking-tight text-white">
            사기 <span className="text-rose-300">후</span>가 아닌 사기{" "}
            <span className="text-rose-300">중</span>에 차단합니다.
          </h1>
          <p className="mt-4 max-w-2xl text-sm leading-7 text-slate-300">
            보이스피싱 의심 통화 중, 본인 발화를 실시간 분석해 사기 신호가
            누적되면 <strong className="text-rose-200">사기범도 듣게 되는
            TTS 차단음</strong>과 <strong className="text-rose-200">가족 SMS
            콜백 요청</strong>으로 전화를 끊을 시간을 만듭니다. 통신비밀보호법
            우회를 위해 <em>사용자 본인 발화만</em> 캡처합니다.
          </p>
        </section>

        <LiveVoiceUpload />

        <section className="rounded-3xl border border-white/10 bg-white/5 p-8 backdrop-blur">
          <h2 className="text-xl font-semibold text-white">검출 신호</h2>
          <p className="mt-1 text-xs text-slate-400">
            기존 보이스피싱 연구는 사기범 발화 분석이 주류 — 본 시스템은{" "}
            <em>피해자 측 compliance signal</em>을 잡습니다 (Cialdini 영향력
            원리가 피해자 발화에서 어떻게 드러나는지).
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {SIGNALS.map((s) => (
              <div
                key={s.label}
                className="rounded-2xl border border-white/10 bg-slate-950/40 p-4"
              >
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold text-slate-100">
                    {s.label}
                  </h3>
                  <span className="rounded-full bg-rose-500/15 px-2 py-0.5 text-[10px] font-medium text-rose-200">
                    {s.weight}
                  </span>
                </div>
                <ul className="mt-2 space-y-1 text-xs text-slate-400">
                  {s.examples.map((e) => (
                    <li key={e}>· {e}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-3xl border border-white/10 bg-white/5 p-8 backdrop-blur">
          <h2 className="text-xl font-semibold text-white">계단식 경보</h2>
          <p className="mt-1 text-xs text-slate-400">
            어르신 타겟 — 카카오톡 의존 X. 가족 SMS 콜백 + TTS 음성 + 풀스크린이
            주력 채널.
          </p>
          <div className="mt-4 grid gap-3 md:grid-cols-3">
            {ALERT_TIERS.map((t) => (
              <div
                key={t.tier}
                className={`rounded-2xl border p-4 ${t.tone}`}
              >
                <div className="text-sm font-semibold">{t.tier}</div>
                <div className="mt-1 text-xs opacity-80">{t.trigger}</div>
                <ul className="mt-3 space-y-1 text-xs">
                  {t.channels.map((c) => (
                    <li key={c}>• {c}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-3xl border border-white/10 bg-white/5 p-8 backdrop-blur">
          <h2 className="text-xl font-semibold text-white">기술 스택 (계획)</h2>
          <dl className="mt-4 grid gap-4 sm:grid-cols-2">
            <div>
              <dt className="text-xs font-semibold tracking-wide text-rose-200 uppercase">
                마이크 캡처
              </dt>
              <dd className="mt-1 text-sm text-slate-300">
                WebRTC <code>getUserMedia</code> · AudioWorklet 16kHz mono PCM
              </dd>
            </div>
            <div>
              <dt className="text-xs font-semibold tracking-wide text-rose-200 uppercase">
                실시간 STT
              </dt>
              <dd className="mt-1 text-sm text-slate-300">
                OpenAI Whisper API · 5초 chunk 누적
              </dd>
            </div>
            <div>
              <dt className="text-xs font-semibold tracking-wide text-rose-200 uppercase">
                신호 검출
              </dt>
              <dd className="mt-1 text-sm text-slate-300">
                정규식 fast-path + Claude Haiku 한 줄 분류기 (메타인식·송금동의·민감정보)
              </dd>
            </div>
            <div>
              <dt className="text-xs font-semibold tracking-wide text-rose-200 uppercase">
                전송
              </dt>
              <dd className="mt-1 text-sm text-slate-300">
                FastAPI WebSocket 양방향 · 경보 push
              </dd>
            </div>
            <div>
              <dt className="text-xs font-semibold tracking-wide text-rose-200 uppercase">
                알림 채널
              </dt>
              <dd className="mt-1 text-sm text-slate-300">
                Web Audio (알람) · Web Speech (TTS) · Vibration API · 국내 SMS
                provider (가족 콜백)
              </dd>
            </div>
            <div>
              <dt className="text-xs font-semibold tracking-wide text-rose-200 uppercase">
                트리거
              </dt>
              <dd className="mt-1 text-sm text-slate-300">
                자녀가 부모 폰에 PWA 설치 · 의심 시 원격 활성화 또는 KISA
                의심번호 DB 연동 자동 발동
              </dd>
            </div>
          </dl>
        </section>

        <section className="rounded-3xl border border-amber-400/20 bg-amber-500/5 p-6 text-sm text-amber-100">
          <strong className="text-amber-200">현재 상태:</strong> 디자인 확정 ·
          feasibility 실험 대기 중. 들어가기 전 검증해야 할 두 가지 — (1) 한국어
          5초 chunk Whisper 스피커폰 환경 정확도 80%+, (2) iOS Safari 백그라운드
          마이크 제약. 둘 다 통과해야 v4.0 MVP 진입.
        </section>
      </div>
    </main>
  );
}
