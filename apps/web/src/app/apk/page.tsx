import Link from "next/link";

import ApkClient from "./ApkClient";

export const metadata = {
  title: "APK 분석 — 악성 안드로이드 앱 신호 검출",
  description:
    "의심스러운 안드로이드 설치 파일(.apk)을 격리 VM 으로 분석해 위험 신호를 검출 — Lv1 정적(manifest) · Lv2 bytecode · Lv3 동적 실행 3단계.",
};

export default function ApkPage() {
  return (
    <main className="min-h-screen bg-[#f2f4f6] px-6 py-10 text-[#191f28]">
      <div className="mx-auto flex w-full max-w-3xl flex-col gap-8">
        <section className="rounded-3xl border border-[#e5e8eb] bg-white p-8 shadow-[0_2px_12px_rgba(0,0,0,0.05)]">
          <div className="mb-6 flex flex-wrap items-center gap-3">
            <span className="rounded-full bg-[#e8f3ff] px-3 py-1 text-xs font-bold tracking-[0.08em] text-[#3182f6]">
              ScamGuardian
            </span>
            <span className="rounded-full bg-[#f2f4f6] px-3 py-1 text-xs text-[#4e5968]">
              📱 APK 분석
            </span>
            <Link
              href="/"
              className="rounded-full border border-[#e5e8eb] px-3 py-1 text-xs text-[#4e5968] transition hover:bg-[#f2f4f6]"
            >
              ← 분석 대시보드
            </Link>
          </div>

          <h1 className="text-3xl font-bold leading-snug tracking-tight text-[#191f28] sm:text-[2.6rem]">
            <span className="text-[#3182f6]">악성 앱 신호</span>를 3단계로 검출합니다.
          </h1>
          <p className="mt-4 max-w-2xl text-sm leading-7 text-[#4e5968]">
            한국 보이스피싱은 미끼 SMS → URL → <strong>악성 APK 설치</strong>로 이어집니다.
            VirusTotal 시그니처가 놓치는 zero-day·변형 악성앱을 정적·동적 분석으로 보완해
            검출 신호만 투명하게 보고합니다 — 판정은 통합 기업의 몫입니다.
          </p>
          <div className="mt-4 flex flex-wrap gap-2 text-xs text-[#8b95a1]">
            <span className="rounded-full bg-[#f2f4f6] px-3 py-1">검출만 — 판정은 본인이</span>
            <span className="rounded-full bg-[#f2f4f6] px-3 py-1">격리 VM 으로만 실행</span>
          </div>
        </section>

        <ApkClient />
      </div>
    </main>
  );
}
