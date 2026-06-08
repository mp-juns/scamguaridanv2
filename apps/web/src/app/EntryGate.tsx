import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { signIn } from "../auth";
import { GUEST_COOKIE, GUEST_MAX_AGE, GUEST_VALUE } from "./guest";

// 홈 첫 진입 시 랜딩 전에 뜨는 선택 게이트.
//  · 비회원으로 둘러보기 → 쿠키 기억 후 랜딩 (익명 사용 경로 보존)
//  · Google 로 로그인     → 권한에 따라 회원/관리자 자동 구분
export default function EntryGate() {
  async function continueAsGuest() {
    "use server";
    const store = await cookies();
    store.set(GUEST_COOKIE, GUEST_VALUE, {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: GUEST_MAX_AGE,
    });
    redirect("/");
  }

  async function loginWithGoogle() {
    "use server";
    await signIn("google", { redirectTo: "/" });
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center px-6">
      <div className="w-full rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <h1 className="text-center text-2xl font-bold text-slate-900">ScamGuardian</h1>
        <p className="mt-2 text-center text-sm text-slate-500">
          어떻게 이용하시겠어요?
        </p>

        <form action={continueAsGuest} className="mt-7">
          <button
            type="submit"
            className="w-full rounded-xl bg-indigo-500 px-4 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-600"
          >
            비회원으로 둘러보기
          </button>
        </form>

        <form action={loginWithGoogle} className="mt-3">
          <button
            type="submit"
            className="flex w-full items-center justify-center gap-2 rounded-xl border border-slate-300 bg-white px-4 py-3 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
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

        <p className="mt-5 text-center text-xs text-slate-400">
          로그인 시 권한에 따라 회원 / 관리자가 자동으로 구분됩니다.
        </p>
      </div>
    </main>
  );
}
