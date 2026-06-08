import Link from "next/link";
import { redirect } from "next/navigation";

import { auth, signIn, signOut } from "../../../auth";

type SearchParams = Promise<{ next?: string; error?: string }>;

export default async function AdminLoginPage(props: { searchParams: SearchParams }) {
  const { next, error } = await props.searchParams;
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  const role = session?.user?.role;
  const dest = next && next.startsWith("/admin") ? next : "/admin";
  // admin 역할만 어드민으로 진입. (일반 user 로그인 상태면 아래 "권한 없음" 안내)
  if (role === "admin") {
    redirect(dest);
  }

  // 로그인은 됐지만 관리자 권한이 없는 계정 (일반 user) — 위에서 admin 은 redirect 됨
  if (email) {
    return (
      <main className="mx-auto flex min-h-screen max-w-md items-center justify-center px-6">
        <div className="w-full rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
          <h1 className="text-xl font-semibold text-slate-900">관리자 권한 없음</h1>
          <p className="mt-2 rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-700">
            <strong>{email}</strong> 계정은 관리자 권한이 없습니다. 로그인 시도로 승인 요청이
            접수되었으니, 마스터 승인 후 다시 로그인해주세요.
          </p>
          <div className="mt-6 flex gap-2">
            <Link
              href="/"
              className="flex-1 rounded-lg border border-slate-300 bg-white px-4 py-2 text-center text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              홈으로
            </Link>
            <form
              className="flex-1"
              action={async () => {
                "use server";
                await signOut({ redirectTo: "/" });
              }}
            >
              <button
                type="submit"
                className="w-full rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
              >
                다른 계정으로 로그인
              </button>
            </form>
          </div>
        </div>
      </main>
    );
  }

  const failed = error && error !== "AccessDenied";

  return (
    <main className="mx-auto flex min-h-screen max-w-md items-center justify-center px-6">
      <div className="w-full rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-xl font-semibold text-slate-900">어드민 로그인</h1>
        <p className="mt-1 text-sm text-slate-500">
          승인된 Google 계정만 어드민에 접근할 수 있습니다.
        </p>
        {failed ? (
          <p className="mt-4 rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700">
            로그인 실패: {error}
          </p>
        ) : null}
        <form
          className="mt-6"
          action={async () => {
            "use server";
            await signIn("google", { redirectTo: dest });
          }}
        >
          <button
            type="submit"
            className="flex w-full items-center justify-center gap-2 rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            <svg className="h-4 w-4" viewBox="0 0 48 48" aria-hidden>
              <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.8 1.1 7.9 3l5.7-5.7C34.1 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
              <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.6 16 18.9 13 24 13c3 0 5.8 1.1 7.9 3l5.7-5.7C34.1 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
              <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.5-5.2l-6.2-5.3C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-8L6.1 33C9.5 39.7 16.2 44 24 44z" />
              <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.3 4.3-4.2 5.6l6.2 5.3C40.7 35.6 44 30.3 44 24c0-1.3-.1-2.4-.4-3.5z" />
            </svg>
            Google 로 로그인
          </button>
        </form>
      </div>
    </main>
  );
}
