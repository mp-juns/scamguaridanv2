import Link from "next/link";

import ApkDynamicClient from "./ApkDynamicClient";

export const dynamic = "force-dynamic";

export default function ApkDynamicPage() {
  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,#111827_0%,#020617_60%,#000000_100%)] px-4 py-8 text-slate-100 sm:px-6">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-sm text-slate-400">ScamGuardian Admin</p>
            <h1 className="text-3xl font-semibold text-white">🧪 APK 동적 분석 (Lv3)</h1>
            <p className="mt-2 text-sm text-slate-400">
              격리 VM(redroid + Frida)을 기동·정지하고, APK 를 올려 실제 실행 기반 런타임 신호를 검출합니다.
              로컬 호스트에서는 APK 를 실행하지 않습니다 — 분석은 항상 격리 VM 으로 위임됩니다.
            </p>
          </div>
          <Link
            href="/admin"
            className="rounded-2xl border border-white/10 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/5"
          >
            ← 어드민
          </Link>
        </header>
        <ApkDynamicClient />
      </div>
    </main>
  );
}
