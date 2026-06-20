import Link from "next/link";

import { auth } from "../../../auth";
import DemoImplementationSection from "../DemoImplementationSection";
import LiveVoiceUpload from "../../live/LiveVoiceUpload";

export const metadata = {
  title: "시연 · 통화 분석 — Live v4",
  description: "실시간 통화 분석 데모 + 구현 구조 설명",
};

const SIGNALS = [
  { label: "메타인식 표현", examples: ["이거 사기 같은데", "이상한데", "진짜인가요?"], weight: "강" },
  { label: "민감 정보 누설", examples: ["주민번호는…", "OTP는…", "비밀번호는…"], weight: "매우 강" },
  { label: "송금 동의", examples: ["이체했어요", "보낼게요", "얼마 보내요"], weight: "결정적" },
];

export default async function DemoLivePage() {
  const session = await auth();
  const isGuest = !session?.user?.email;

  return (
    <main className="min-h-screen bg-[#e7f6ec] px-6 py-10 text-[#191f28]">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-8">
        <section className="rounded-3xl border border-[#bbf7d0] bg-white p-8 shadow-[0_2px_12px_rgba(0,0,0,0.05)]">
          <div className="mb-6 flex flex-wrap items-center gap-3">
            <span className="rounded-full bg-[#dcfce7] px-3 py-1 text-xs font-semibold tracking-[0.2em] text-[#15803d] uppercase">
              시연 모드
            </span>
            <span className="rounded-full bg-[#f2f4f6] px-3 py-1 text-xs text-[#4e5968]">
              🎙️ Live Voice
            </span>
            <Link
              href="/demo"
              className="rounded-full border border-[#e5e8eb] px-3 py-1 text-xs text-[#4e5968] transition hover:bg-[#f2f4f6]"
            >
              ← 시연 허브
            </Link>
          </div>

          <h1 className="text-4xl font-semibold tracking-tight text-[#191f28]">
            <span className="text-[#16a34a]">통화 중</span>에 위험 신호를 잡아냅니다.
          </h1>
          <p className="mt-4 max-w-2xl text-sm leading-7 text-[#4e5968]">
            보이스피싱 의심 통화 중, 본인 발화를 실시간 분석해 사기 신호가 누적되면 경보를 보냅니다.
            <em> 사용자 본인 발화만</em> 캡처합니다.
          </p>
        </section>

        <LiveVoiceUpload isGuest={isGuest} />

        <section className="rounded-3xl border border-[#e5e8eb] bg-white p-8 backdrop-blur">
          <h2 className="text-xl font-semibold text-[#191f28]">검출 신호</h2>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {SIGNALS.map((s) => (
              <div key={s.label} className="rounded-2xl border border-[#e5e8eb] bg-white p-4">
                <div className="flex items-center justify-between gap-2">
                  <h3 className="text-sm font-semibold text-[#191f28]">{s.label}</h3>
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

        <DemoImplementationSection mode="live" />
      </div>
    </main>
  );
}
