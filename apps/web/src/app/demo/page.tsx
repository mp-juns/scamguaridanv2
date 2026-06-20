import Link from "next/link";

import DemoHubCards from "./DemoHubCards";

export const metadata = {
  title: "시연 모드 — ScamGuardian 구현 구조",
  description:
    "통화·콘텐츠·APK 분석 데모와 함께 각 기능의 파이프라인·ML 구현 구조를 확인합니다.",
};

export default function DemoHubPage() {
  return (
    <main className="min-h-screen bg-[#f2f4f6] px-6 py-10 text-[#191f28]">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
        <section className="rounded-3xl border border-[#e5e8eb] bg-white p-8 shadow-[0_2px_12px_rgba(0,0,0,0.05)]">
          <div className="mb-7 flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-[#e8f3ff] px-3 py-1 text-xs font-bold tracking-[0.08em] text-[#3182f6]">
              시연 모드
            </span>
            <Link
              href="/"
              className="rounded-full border border-[#e5e8eb] px-3 py-1 text-xs text-[#4e5968] transition hover:bg-[#f2f4f6]"
            >
              ← 일반 분석으로
            </Link>
            <Link
              href="/evidence"
              className="rounded-full border border-[#e5e8eb] px-3 py-1 text-xs text-[#4e5968] transition hover:bg-[#f2f4f6]"
            >
              📚 근거
            </Link>
          </div>

          <div className="mb-6">
            <h1 className="text-2xl font-bold tracking-tight text-[#191f28]">
              무엇을 시연할까요?
            </h1>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-[#4e5968]">
              분석 화면은 기존과 동일하게 동작합니다. 각 화면 맨 아래에서 해당 기능의
              파이프라인·파일·ML 상태를 자세히 볼 수 있어요.
            </p>
          </div>

          <DemoHubCards />
        </section>
      </div>
    </main>
  );
}
