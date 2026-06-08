import Link from "next/link";
import { cookies } from "next/headers";

import { auth, signIn, signOut } from "../auth";
import { GUEST_COOKIE, GUEST_VALUE } from "./guest";

// 우측 상단 계정 위젯 — 진입 상태/역할(role)에 따라 노출이 달라짐.
//  · 게이트(미진입) → 숨김 (게이트 자체에 버튼이 있음)
//  · 비회원        → "로그인"
//  · user (로그인)  → 로그아웃만 (어드민 pill 안 보임)
//  · admin         → "🛠️ 관리자" pill + 로그아웃
export default async function AccountNav() {
  const session = await auth();
  const store = await cookies();
  const email = session?.user?.email;
  const isGuest = store.get(GUEST_COOKIE)?.value === GUEST_VALUE;

  const pill =
    "flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-xs font-medium shadow-sm backdrop-blur transition";

  // 게이트 화면(로그인도 비회원도 아님) — 위젯 숨김
  if (!email && !isGuest) return null;

  // 비회원 — Google 로그인 진입 (권한에 따라 회원/관리자 자동)
  if (!email) {
    return (
      <div className="fixed right-4 top-4 z-50">
        <form
          action={async () => {
            "use server";
            await signIn("google", { redirectTo: "/" });
          }}
        >
          <button
            type="submit"
            className={`${pill} border-slate-200 bg-white/90 text-slate-700 hover:border-indigo-300 hover:text-indigo-600`}
          >
            로그인
          </button>
        </form>
      </div>
    );
  }

  const isAdmin = session?.user?.role === "admin";

  return (
    <div className="fixed right-4 top-4 z-50 flex items-center gap-2">
      {isAdmin ? (
        <Link
          href="/admin"
          className={`${pill} border-slate-200 bg-white/90 text-slate-700 hover:border-indigo-300 hover:text-indigo-600`}
        >
          <span aria-hidden>🛠️</span>
          관리자
        </Link>
      ) : null}
      <form
        action={async () => {
          "use server";
          await signOut({ redirectTo: "/" });
        }}
      >
        <button
          type="submit"
          className={`${pill} border-slate-200 bg-white/80 text-slate-500 hover:border-slate-300 hover:text-slate-700`}
        >
          로그아웃
        </button>
      </form>
    </div>
  );
}
