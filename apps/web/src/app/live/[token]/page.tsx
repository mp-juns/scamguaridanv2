import Link from "next/link";

import { auth } from "../../../auth";
import LiveVoiceUpload from "../LiveVoiceUpload";

export const dynamic = "force-dynamic";
export const metadata = {
  title: "ScamGuardian Live Session",
  description: "카카오 1회용 라이브 보이스피싱 전용 세션",
};

const API_BASE_URL = process.env.SCAMGUARDIAN_API_URL ?? "http://127.0.0.1:8000";

type PageProps = {
  params: Promise<{ token: string }>;
};

async function checkLiveSession(token: string): Promise<{ ok: true } | { ok: false; detail: string }> {
  try {
    const resp = await fetch(
      `${API_BASE_URL}/api/live-session/${encodeURIComponent(token)}?consume=false`,
      { cache: "no-store" },
    );
    if (!resp.ok) {
      const body = (await resp.json().catch(() => ({}))) as { detail?: string };
      return {
        ok: false,
        detail: body.detail ?? "세션이 만료되었거나 유효하지 않습니다.",
      };
    }
    return { ok: true };
  } catch {
    return { ok: false, detail: "라이브 세션 검증 중 네트워크 오류가 발생했습니다." };
  }
}

export default async function LiveTokenPage({ params }: PageProps) {
  const { token } = await params;
  const session = await auth();
  const isGuest = !session?.user?.email;
  const validity = await checkLiveSession(token);

  if (!validity.ok) {
    return (
      <main className="min-h-screen bg-[#e7f6ec] px-6 py-10 text-[#191f28]">
        <div className="mx-auto max-w-3xl rounded-3xl border border-rose-300 bg-white p-8">
          <h1 className="text-2xl font-bold text-rose-700">라이브 세션에 입장할 수 없습니다</h1>
          <p className="mt-3 text-sm leading-6 text-[#4e5968]">{validity.detail}</p>
          <p className="mt-2 text-sm leading-6 text-[#4e5968]">
            카카오 챗봇에서 <code>라이브 보이스피싱</code> 버튼을 다시 눌러 새 링크를 발급받아 주세요.
          </p>
          <Link
            href="/live"
            className="mt-6 inline-flex rounded-2xl border border-[#e5e8eb] px-4 py-2 text-sm text-[#4e5968] hover:bg-[#f2f4f6]"
          >
            기본 라이브 페이지로 이동
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-[#e7f6ec] px-6 py-10 text-[#191f28]">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-8">
        <section className="rounded-3xl border border-[#bbf7d0] bg-white p-8 shadow-[0_2px_12px_rgba(0,0,0,0.05)]">
          <div className="mb-6 flex flex-wrap items-center gap-3">
            <span className="rounded-full bg-[#dcfce7] px-3 py-1 text-xs font-semibold tracking-[0.2em] text-[#15803d] uppercase">
              ScamGuardian · Live Session
            </span>
            <span className="rounded-full bg-[#f2f4f6] px-3 py-1 text-xs text-[#4e5968]">
              1회용 링크
            </span>
          </div>
          <h1 className="text-3xl font-semibold tracking-tight text-[#191f28]">
            보이스피싱 실시간 전용 세션
          </h1>
          <p className="mt-3 text-sm leading-6 text-[#4e5968]">
            이 링크는 카카오에서 발급된 1회용 세션입니다. 세션이 시작되면 동일 링크는 다시 사용할 수 없습니다.
          </p>
        </section>
        <LiveVoiceUpload isGuest={isGuest} liveSessionToken={token} liveOnly />
      </div>
    </main>
  );
}
