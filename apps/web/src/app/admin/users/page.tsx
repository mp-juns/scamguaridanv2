import Link from "next/link";

import AdminUsersClient from "./AdminUsersClient";

export const dynamic = "force-dynamic";

export default function AdminUsersPage() {
  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,#111827_0%,#020617_60%,#000000_100%)] px-4 py-8 text-slate-100 sm:px-6">
      <div className="mx-auto w-full max-w-4xl space-y-6">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-sm text-slate-400">ScamGuardian Admin</p>
            <h1 className="text-3xl font-semibold text-white">👥 사용자 관리</h1>
            <p className="mt-2 text-sm text-slate-400">
              마스터 계정이 승인 요청(pending)을 승인/거부합니다. 승인되면 재시작 없이 로그인 가능합니다.
            </p>
          </div>
          <Link
            href="/admin"
            className="rounded-2xl border border-white/10 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/5"
          >
            ← 어드민
          </Link>
        </header>
        <AdminUsersClient />
      </div>
    </main>
  );
}
