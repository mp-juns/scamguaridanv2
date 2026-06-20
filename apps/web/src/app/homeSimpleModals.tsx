import { signIn } from "next-auth/react";

import { GUEST_DAILY_LIMIT } from "./guestLimit";

type SimpleModalProps = {
  open: boolean;
  onClose: () => void;
};

export function InjectionBlockedModal({ open, onClose }: SimpleModalProps) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[90] flex items-center justify-center overflow-y-auto bg-[#191f28]/60 p-4 sm:p-6"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div className="my-auto flex w-full max-w-sm flex-col" onClick={(event) => event.stopPropagation()}>
        <section className="relative rounded-3xl border border-[#fecaca] bg-white p-7 text-center shadow-[0_8px_30px_rgba(0,0,0,0.12)]">
          <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[#fff1f0] text-3xl">
            🚫
          </span>
          <h2 className="mt-4 text-lg font-bold text-[#191f28]">접근이 제한되었습니다</h2>
          <p className="mt-2 text-sm leading-6 text-[#4e5968]">
            프롬프트 우회(인젝션) 시도가 감지되어 분석 이용이 일시 제한되었습니다.
            정상적인 분석 요청만 이용해 주세요.
          </p>
          <button
            type="button"
            onClick={onClose}
            className="mt-6 inline-flex w-full items-center justify-center rounded-2xl bg-[#191f28] px-5 py-3 text-sm font-semibold text-white transition hover:bg-black"
          >
            확인
          </button>
        </section>
      </div>
    </div>
  );
}

export function LimitBlockModal({ open, onClose }: SimpleModalProps) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[80] flex items-center justify-center overflow-y-auto bg-[#191f28]/50 p-4 sm:p-6"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div className="my-auto flex w-full max-w-sm flex-col" onClick={(event) => event.stopPropagation()}>
        <section className="relative rounded-3xl border border-[#e5e8eb] bg-white p-7 text-center shadow-[0_8px_30px_rgba(0,0,0,0.12)]">
          <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[#fff1f0] text-3xl">
            ⛔
          </span>
          <h2 className="mt-4 text-lg font-bold text-[#191f28]">오늘 비회원 분석 한도를 모두 썼어요</h2>
          <p className="mt-2 text-sm leading-6 text-[#4e5968]">
            비회원은 하루 {GUEST_DAILY_LIMIT}회까지 분석할 수 있어요(라이브 음성 포함).
            로그인하면 이어서 계속 이용할 수 있어요.
          </p>

          <div className="mt-6 space-y-2">
            <GoogleLoginButton />
            <button
              type="button"
              onClick={onClose}
              className="inline-flex w-full items-center justify-center rounded-2xl px-5 py-3 text-sm font-semibold text-[#8b95a1] transition hover:bg-[#f2f4f6]"
            >
              닫기
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}

type LoginPromptModalProps = SimpleModalProps & {
  onContinueAsGuest: () => void;
};

export function LoginPromptModal({
  open,
  onClose,
  onContinueAsGuest,
}: LoginPromptModalProps) {
  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-[70] flex items-center justify-center overflow-y-auto bg-[#191f28]/40 p-4 sm:p-6"
      onClick={onContinueAsGuest}
      role="dialog"
      aria-modal="true"
    >
      <div className="my-auto flex w-full max-w-sm flex-col" onClick={(event) => event.stopPropagation()}>
        <section className="relative rounded-3xl border border-[#e5e8eb] bg-white p-7 text-center shadow-[0_8px_30px_rgba(0,0,0,0.12)]">
          <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[#e8f3ff] text-3xl">
            🔒
          </span>
          <h2 className="mt-4 text-lg font-bold text-[#191f28]">로그인하고 계속 이용해 보세요</h2>
          <p className="mt-2 text-sm leading-6 text-[#4e5968]">
            비회원으로 여러 번 분석하셨어요. 로그인하면 분석 결과를 안전하게
            이어서 이용할 수 있어요.
          </p>

          <div className="mt-6 space-y-2">
            <GoogleLoginButton />
            <button
              type="button"
              onClick={onContinueAsGuest}
              className="inline-flex w-full items-center justify-center rounded-2xl px-5 py-3 text-sm font-semibold text-[#8b95a1] transition hover:bg-[#f2f4f6]"
            >
              비회원으로 결과 보기
            </button>
            <button type="button" className="sr-only" onClick={onClose}>
              닫기
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}

function GoogleLoginButton() {
  return (
    <button
      type="button"
      onClick={() => signIn("google", { callbackUrl: "/" })}
      className="flex w-full items-center justify-center gap-2 rounded-2xl bg-[#3182f6] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#1b64da]"
    >
      <svg className="h-4 w-4" viewBox="0 0 48 48" aria-hidden>
        <path fill="#fff" d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.8 1.1 7.9 3l5.7-5.7C34.1 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
      </svg>
      Google 로 로그인
    </button>
  );
}
