import Link from "next/link";

import AugmentClient from "./AugmentClient";

export const dynamic = "force-dynamic";

export default function AugmentPage() {
  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,#111827_0%,#020617_60%,#000000_100%)] px-4 py-8 text-slate-100 sm:px-6">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-sm text-slate-400">ScamGuardian Admin</p>
            <h1 className="text-3xl font-semibold text-white">🧬 데이터 증강</h1>
            <p className="mt-2 text-sm text-slate-400">
              굶은 scam 유형에 씨앗을 직접 작성하고, Claude 로 병렬 패러프레이즈해 학습 데이터를 늘립니다.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link
              href="/admin/augment/about"
              className="rounded-2xl border border-fuchsia-400/30 bg-fuchsia-500/10 px-4 py-2 text-sm font-semibold text-fuchsia-200 transition hover:bg-fuchsia-500/20"
            >
              📖 설명 보기
            </Link>
            <Link
              href="/admin/training"
              className="rounded-2xl border border-cyan-400/30 bg-cyan-500/10 px-4 py-2 text-sm font-semibold text-cyan-200 transition hover:bg-cyan-500/20"
            >
              Fine-tuning →
            </Link>
            <Link
              href="/admin"
              className="rounded-2xl border border-white/10 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/5"
            >
              어드민 홈
            </Link>
          </div>
        </header>
        <AugmentClient />
      </div>
    </main>
  );
}
