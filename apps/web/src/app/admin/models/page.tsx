import Link from "next/link";

import ModelsClient from "./ModelsClient";

export const dynamic = "force-dynamic";

export default function AdminModelsPage() {
  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,#111827_0%,#020617_60%,#000000_100%)] px-4 py-8 text-slate-100 sm:px-6">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-sm text-slate-400">ScamGuardian Admin</p>
            <h1 className="text-3xl font-semibold text-white">🧠 모델 관리</h1>
            <p className="mt-2 text-sm text-slate-400">
              게이트·분류기·추출기(GLiNER)의 fine-tuned 체크포인트를 확인하고 파이프라인에 적용합니다.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Link
              href="/admin/training"
              className="rounded-2xl border border-emerald-400/30 bg-emerald-500/10 px-4 py-2 text-sm font-semibold text-emerald-200 transition hover:bg-emerald-500/20"
            >
              🧪 Fine-tuning →
            </Link>
            <Link
              href="/admin/training/compare"
              className="rounded-2xl border border-violet-400/30 bg-violet-500/10 px-4 py-2 text-sm font-semibold text-violet-200 transition hover:bg-violet-500/20"
            >
              모델 비교 →
            </Link>
            <Link
              href="/admin"
              className="rounded-2xl border border-white/10 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/5"
            >
              어드민 홈
            </Link>
          </div>
        </header>
        <ModelsClient />
      </div>
    </main>
  );
}
