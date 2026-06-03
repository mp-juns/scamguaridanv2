"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

type Variant = {
  id: string;
  filename: string;
  size: number;
  default_filename: string;
  title: string;
  family: string;
  tier: string;
  impersonates: string;
  expected_signals: string[];
};

type LinkInfo = {
  token: string;
  variant_id: string;
  filename: string;
  download_path: string;
  download_url: string | null;
  expires_at: number;
  created_at?: number;
};

function fmtTime(ts: number | undefined): string {
  if (!ts) return "-";
  return new Date(ts * 1000).toLocaleString("ko-KR", { hour12: false });
}

export default function DummyClient() {
  const [variants, setVariants] = useState<Variant[]>([]);
  const [links, setLinks] = useState<LinkInfo[]>([]);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [c, l] = await Promise.all([
        fetch("/api/admin/apk-dynamic/dummy/catalog", { cache: "no-store" }),
        fetch("/api/admin/apk-dynamic/dummy/links", { cache: "no-store" }),
      ]);
      if (c.ok) setVariants(((await c.json()).variants ?? []) as Variant[]);
      if (l.ok) setLinks(((await l.json()).links ?? []) as LinkInfo[]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "로드 실패");
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function generate(variantId: string) {
    setBusy(variantId);
    setError("");
    try {
      const r = await fetch("/api/admin/apk-dynamic/dummy/link", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ variant_id: variantId }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail ?? "링크 생성 실패");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "링크 생성 실패");
    } finally {
      setBusy(null);
    }
  }

  async function copy(text: string, token: string) {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(token);
      setTimeout(() => setCopied(null), 1500);
    } catch {
      /* noop */
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
        ⚠️ 여기 더미는 <strong>무해한 테스트 fixture</strong>입니다(dead-code, 비라우팅 URL). 실제 단말에 설치하지 마세요 — 분석기 검증·시연 전용.
      </div>

      {error && (
        <div className="rounded-xl border border-rose-400/30 bg-rose-500/10 px-4 py-2 text-sm text-rose-200">{error}</div>
      )}

      {/* 카탈로그 */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-white">더미 카탈로그</h2>
        <div className="grid gap-4 md:grid-cols-2">
          {variants.map((v) => (
            <div key={v.id} className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
              <div className="mb-2 flex items-start justify-between gap-2">
                <div>
                  <div className="text-sm font-semibold text-white">{v.title}</div>
                  <div className="mt-0.5 font-mono text-xs text-slate-500">{v.filename} · {(v.size / 1024).toFixed(1)}KB</div>
                </div>
                <span
                  className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${
                    v.tier === "dynamic"
                      ? "border border-violet-400/30 bg-violet-500/10 text-violet-200"
                      : "border border-cyan-400/30 bg-cyan-500/10 text-cyan-200"
                  }`}
                >
                  {v.tier === "dynamic" ? "동적 Lv3" : "정적 Lv1/2"}
                </span>
              </div>
              <div className="mb-2 text-xs text-slate-400">사칭: {v.impersonates}</div>
              <div className="mb-3 flex flex-wrap gap-1">
                {v.expected_signals.map((s) => (
                  <span key={s} className="rounded bg-white/5 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                    {s}
                  </span>
                ))}
              </div>
              <button
                onClick={() => void generate(v.id)}
                disabled={busy === v.id}
                className="rounded-xl border border-emerald-400/30 bg-emerald-500/10 px-4 py-2 text-sm font-semibold text-emerald-200 transition hover:bg-emerald-500/20 disabled:opacity-50"
              >
                {busy === v.id ? "생성 중..." : "🔗 다운로드 링크 생성"}
              </button>
            </div>
          ))}
        </div>
      </section>

      {/* 활성 링크 */}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold text-white">발급된 링크 ({links.length})</h2>
        {links.length === 0 && <p className="text-sm text-slate-500">아직 발급된 링크가 없습니다.</p>}
        <div className="space-y-2">
          {links.map((l) => {
            const shown = l.download_url ?? l.download_path;
            return (
              <div key={l.token} className="rounded-xl border border-white/10 bg-slate-950/40 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-cyan-500/10 px-1.5 py-0.5 text-xs text-cyan-200">{l.variant_id}</span>
                    <span className="text-xs text-slate-400">{l.filename}</span>
                  </div>
                  <span className="text-xs text-slate-500">만료 {fmtTime(l.expires_at)}</span>
                </div>
                <div className="mt-2 flex items-center gap-2">
                  <code className="flex-1 overflow-x-auto rounded bg-black/40 px-2 py-1.5 font-mono text-xs text-slate-300">
                    {shown}
                  </code>
                  <button
                    onClick={() => void copy(shown, l.token)}
                    className="shrink-0 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-slate-200 hover:bg-white/5"
                  >
                    {copied === l.token ? "복사됨 ✓" : "복사"}
                  </button>
                </div>
                {!l.download_url && (
                  <p className="mt-1 text-[11px] text-amber-300/80">
                    SCAMGUARDIAN_PUBLIC_URL 미설정 — 외부 배포처로 쓰려면 공개 URL 베이스 필요. 로컬은 백엔드 호스트 기준 경로로 동작.
                  </p>
                )}
              </div>
            );
          })}
        </div>
      </section>

      <section className="rounded-2xl border border-white/10 bg-white/5 p-4 text-sm text-slate-300">
        <h3 className="mb-2 font-semibold text-white">사용법</h3>
        <ol className="list-inside list-decimal space-y-1 text-slate-400">
          <li>카탈로그에서 더미를 골라 <strong className="text-slate-200">링크 생성</strong>.</li>
          <li>발급된 URL 을 <strong className="text-slate-200">메인 분석 입력창 / 카카오 챗봇</strong>에 붙여넣어 e2e 검출 확인.</li>
          <li>또는 URL 을 브라우저로 받아 <Link href="/admin/apk-dynamic" className="text-cyan-300 hover:text-cyan-200">동적 분석 콘솔</Link>에 업로드(동적 더미는 VM 기동 필요).</li>
        </ol>
      </section>
    </div>
  );
}
