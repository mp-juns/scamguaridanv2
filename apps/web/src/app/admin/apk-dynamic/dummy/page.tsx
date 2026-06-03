import Link from "next/link";

import DummyClient from "./DummyClient";

export const dynamic = "force-dynamic";

export default function ApkDummyPage() {
  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,#111827_0%,#020617_60%,#000000_100%)] px-4 py-8 text-slate-100 sm:px-6">
      <div className="mx-auto w-full max-w-6xl space-y-6">
        <header className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <p className="text-sm text-slate-400">ScamGuardian Admin · APK</p>
            <h1 className="text-3xl font-semibold text-white">🔗 더미 피싱앱 다운로드 링크 생성</h1>
            <p className="mt-2 text-sm text-slate-400">
              무해한 테스트용 더미 APK 를 만료되는 공개 URL 로 발급합니다. 그 링크를 메인 분석·카카오 챗봇에 붙여넣으면
              파이프라인이 외부 배포처처럼 받아 검출 신호(VT·정적·동적)를 발동합니다.
            </p>
          </div>
          <Link
            href="/admin/apk-dynamic"
            className="rounded-2xl border border-white/10 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/5"
          >
            ← APK 동적 분석
          </Link>
        </header>
        <DummyClient />
      </div>
    </main>
  );
}
