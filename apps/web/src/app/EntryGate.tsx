import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { signIn } from "../auth";
import { GUEST_COOKIE, GUEST_MAX_AGE, GUEST_VALUE } from "./guest";
import { GUEST_DAILY_LIMIT, GUEST_DAILY_LIMIT_ENABLED } from "./guestLimit";

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
    <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center bg-[#f2f4f6] px-6 text-[#191f28]">
      <section className="w-full rounded-3xl border border-[#e5e8eb] bg-white p-8 text-center shadow-[0_2px_12px_rgba(0,0,0,0.05)]">
        <span className="inline-block rounded-full bg-[#e8f3ff] px-4 py-2 text-base font-bold tracking-[0.08em] text-[#3182f6]">
          ScamGuardian
        </span>
        <h1 className="mt-6 text-[22px] font-bold leading-[1.4] text-[#191f28]">
          로그인하고
          <br />
          ScamGuardian 을 시작하세요
        </h1>
        <p className="mt-3 text-sm leading-7 text-[#4e5968]">
          영상·텍스트·통화 속 사기 위험 신호를 검출해 드려요. 최종 판단은 언제나 본인이.
        </p>

        <div className="mt-7 flex flex-col gap-2.5">
          <form action={loginWithGoogle}>
            <button
              type="submit"
              className="flex w-full items-center justify-center gap-2 rounded-2xl bg-[#3182f6] px-4 py-3.5 text-[15px] font-semibold text-white shadow-[0_6px_20px_rgba(49,130,246,0.28)] transition hover:bg-[#1b64da]"
            >
              <svg className="h-[18px] w-[18px]" viewBox="0 0 48 48" aria-hidden>
                <path fill="#fff" d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.8 1.1 7.9 3l5.7-5.7C34.1 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
              </svg>
              Google 로 로그인
            </button>
          </form>

          <form action={continueAsGuest}>
            <button
              type="submit"
              className="w-full rounded-2xl border border-[#e5e8eb] bg-white px-4 py-3.5 text-[15px] font-semibold text-[#4e5968] transition hover:bg-[#f2f4f6]"
            >
              비회원으로 시작하기
            </button>
          </form>
        </div>

        <p className="mt-5 text-xs leading-6 text-[#8b95a1]">
          {GUEST_DAILY_LIMIT_ENABLED
            ? `비회원은 하루 ${GUEST_DAILY_LIMIT}회까지 분석할 수 있어요. 로그인 시 권한에 따라 회원 / 관리자가 자동으로 구분됩니다.`
            : "현재 비회원 일일 사용 한도는 임시 비활성화 상태입니다. 로그인 시 권한에 따라 회원 / 관리자가 자동으로 구분됩니다."}
        </p>
      </section>
    </main>
  );
}
