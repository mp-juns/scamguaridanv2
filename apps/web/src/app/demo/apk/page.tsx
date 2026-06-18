import Link from "next/link";

import ApkClient from "../../apk/ApkClient";
import DemoImplementationSection from "../DemoImplementationSection";

export const metadata = {
  title: "시연 · APK 분석",
  description: "APK 악성 신호 검출 데모 + 구현 구조 설명",
};

export default function DemoApkPage() {
  return (
    <main className="min-h-screen bg-[#f2f4f6] px-6 py-10 text-[#191f28]">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-8">
        <section className="rounded-3xl border border-[#e5e8eb] bg-white p-8 shadow-[0_2px_12px_rgba(0,0,0,0.05)]">
          <div className="mb-6 flex flex-wrap items-center gap-3">
            <span className="rounded-full bg-[#e8f3ff] px-3 py-1 text-xs font-bold tracking-[0.08em] text-[#3182f6]">
              시연 모드
            </span>
            <span className="rounded-full bg-[#f2f4f6] px-3 py-1 text-xs text-[#4e5968]">
              📱 APK 분석
            </span>
            <Link
              href="/demo"
              className="rounded-full border border-[#e5e8eb] px-3 py-1 text-xs text-[#4e5968] transition hover:bg-[#f2f4f6]"
            >
              ← 시연 허브
            </Link>
          </div>

          <h1 className="text-3xl font-bold leading-snug tracking-tight text-[#191f28] sm:text-[2.6rem]">
            <span className="text-[#3182f6]">악성 앱 신호</span>를 3단계로 검출합니다.
          </h1>
          <p className="mt-4 max-w-2xl text-sm leading-7 text-[#4e5968]">
            VirusTotal 시그니처가 놓치는 zero-day·변형 악성앱을 정적·동적 분석으로 보완해
            검출 신호만 투명하게 보고합니다.
          </p>
        </section>

        <ApkClient />

        <DemoImplementationSection mode="apk" />
      </div>
    </main>
  );
}
