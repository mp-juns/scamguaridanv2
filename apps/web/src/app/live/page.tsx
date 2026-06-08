import Link from "next/link";

import { auth } from "../../auth";
import LiveVoiceUpload from "./LiveVoiceUpload";

export const metadata = {
  title: "LIVE VOICE — 통화 중 실시간 사기 탐지",
  description:
    "통화 중 본인 발화를 실시간 분석해 위험 신호를 검출 — 의심 신호 발견 시 가족 SMS · TTS 음성 · 풀스크린 경보로 통화를 끊을 시간을 만듭니다.",
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
    tone: "border-amber-400/30 bg-amber-500/5 text-amber-700",
  },
  {
    tier: "L2 중간",
    trigger: "메타인식 + 키워드 누적",
    channels: ["빨간 배너", "진동", "가족 SMS 1차"],
    tone: "border-orange-400/40 bg-orange-500/10 text-orange-700",
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
    tone: "border-rose-400/50 bg-rose-500/15 text-rose-700",
  },
];

export default async function LiveVoicePage() {
  const session = await auth();
  const isGuest = !session?.user?.email; // 로그인 안 했으면 비회원 — 일일 한도 적용
  return (
    <main className="min-h-screen bg-[#e7f6ec] px-6 py-10 text-[#191f28]">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-8">
        <section className="rounded-3xl border border-[#bbf7d0] bg-white p-8 shadow-[0_2px_12px_rgba(0,0,0,0.05)]">
          <div className="mb-6 flex flex-wrap items-center gap-3">
            <span className="rounded-full bg-[#dcfce7] px-3 py-1 text-xs font-semibold tracking-[0.2em] text-[#15803d] uppercase">
              ScamGuardian · v4
            </span>
            <span className="rounded-full bg-[#f2f4f6] px-3 py-1 text-xs text-[#4e5968]">
              🎙️ Live Voice
            </span>
            <span className="rounded-full border border-amber-300/30 bg-amber-400/5 px-3 py-1 text-xs text-amber-700">
              개발 중 (Coming soon)
            </span>
            <Link
              href="/"
              className="rounded-full border border-[#e5e8eb] px-3 py-1 text-xs text-[#4e5968] transition hover:bg-white"
            >
              ← 분석 대시보드
            </Link>
          </div>

          <h1 className="text-4xl font-semibold tracking-tight text-[#191f28]">
            <span className="text-[#16a34a]">통화 중</span>에 위험 신호를
            잡아냅니다.
          </h1>
          <p className="mt-4 max-w-2xl text-sm leading-7 text-[#4e5968]">
            보이스피싱 의심 통화 중, 본인 발화를 실시간 분석해 사기 신호가
            누적되면 <strong className="text-[#15803d]">사기범도 듣게 되는
            TTS 차단음</strong>과 <strong className="text-[#15803d]">가족 SMS
            콜백 요청</strong>으로 전화를 끊을 시간을 만듭니다. 통신비밀보호법
            우회를 위해 <em>사용자 본인 발화만</em> 캡처합니다.
          </p>
        </section>

        <LiveVoiceUpload isGuest={isGuest} />

        <section className="rounded-3xl border border-[#e5e8eb] bg-white p-8 backdrop-blur">
          <h2 className="text-xl font-semibold text-[#191f28]">검출 신호</h2>
          <p className="mt-1 text-xs text-[#8b95a1]">
            기존 보이스피싱 연구는 사기범 발화 분석이 주류 — 본 시스템은{" "}
            <em>피해자 측 compliance signal</em>을 잡습니다 (Cialdini 영향력
            원리가 피해자 발화에서 어떻게 드러나는지).
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {SIGNALS.map((s) => (
              <div
                key={s.label}
                className="rounded-2xl border border-[#e5e8eb] bg-white p-4"
              >
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold text-[#191f28]">
                    {s.label}
                  </h3>
                  <span className="rounded-full bg-rose-500/15 px-2 py-0.5 text-[10px] font-medium text-rose-700">
                    {s.weight}
                  </span>
                </div>
                <ul className="mt-2 space-y-1 text-xs text-[#8b95a1]">
                  {s.examples.map((e) => (
                    <li key={e}>· {e}</li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </section>

        <section className="rounded-3xl border border-[#e5e8eb] bg-white p-8 backdrop-blur">
          <h2 className="text-xl font-semibold text-[#191f28]">계단식 경보</h2>
          <p className="mt-1 text-xs text-[#8b95a1]">
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

        <section className="rounded-3xl border border-amber-400/20 bg-amber-500/5 p-6 text-sm text-amber-700">
          <strong className="text-amber-700">현재 상태:</strong> 디자인 확정 ·
          feasibility 실험 대기 중. 들어가기 전 검증해야 할 두 가지 — (1) 한국어
          5초 chunk Whisper 스피커폰 환경 정확도 80%+, (2) iOS Safari 백그라운드
          마이크 제약. 둘 다 통과해야 v4.0 MVP 진입.
        </section>
      </div>
    </main>
  );
}
