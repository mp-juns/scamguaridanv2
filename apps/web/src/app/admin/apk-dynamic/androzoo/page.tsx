import Link from "next/link";

import AndrozooClient from "./AndrozooClient";

export const dynamic = "force-dynamic";

export default function AndrozooBenchmarkPage() {
  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,#111827_0%,#020617_60%,#000000_100%)] px-4 py-8 text-slate-100 sm:px-6">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-sm text-slate-400">ScamGuardian Admin · APK</p>
            <h1 className="text-3xl font-semibold text-white">🧪 AndroZoo 실제 악성 샘플 비교</h1>
            <p className="mt-2 text-sm text-slate-400">
              AndroZoo(룩셈부르크대 학술 데이터셋)에서 실제 악성 APK 를 무작위로 받아, 우리 정적·bytecode 검출 신호를
              VirusTotal 합의(<code>vt_detection</code>)와 나란히 비교합니다. 호스트 실행 없음 — 정적 분석만.
            </p>
          </div>
          <Link
            href="/admin/apk-dynamic"
            className="rounded-2xl border border-white/10 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/5"
          >
            ← APK 동적 분석
          </Link>
        </header>
        <AndrozooClient />
      </div>
    </main>
  );
}
