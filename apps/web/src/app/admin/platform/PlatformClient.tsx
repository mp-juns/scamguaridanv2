"use client";

import { useCallback, useEffect, useState } from "react";
import dynamic from "next/dynamic";

// recharts 는 무거운 클라이언트 청크 → lazy-load (초기 admin 진입 JS 에서 제외)
const DailyCostArea = dynamic(
  () => import("../charts").then((m) => m.DailyCostArea),
  { ssr: false },
);
const ProviderBar = dynamic(
  () => import("../charts").then((m) => m.ProviderBar),
  { ssr: false },
);

type ApiKey = {
  id: string;
  label: string;
  created_at: string;
  last_used_at: string | null;
  monthly_quota: number;
  rpm_limit: number;
  monthly_usd_quota?: number;
  status: string;
  usage_total: number;
  usage_month: number;
  usage_month_at: string | null;
};

type ObservabilityResponse = {
  summary: {
    total: number;
    errors: number;
    error_rate: number;
    p50_ms: number;
    p95_ms: number;
    by_path: { path: string; n: number; avg_ms: number }[];
    since_hours: number;
  };
  recent: {
    id: number;
    created_at: string;
    request_id: string;
    api_key_id: string | null;
    method: string;
    path: string;
    status: number;
    latency_ms: number;
    error: string | null;
  }[];
};

type CostResponse = {
  total: { calls: number; usd: number };
  by_provider: { provider: string; calls: number; units: number; usd: number }[];
  by_key: { api_key_id: string | null; label: string | null; calls: number; usd: number }[];
  daily: { day: string; usd: number; calls: number }[];
  since: string;
};

type AbuseBlock = {
  user_id: string;
  block_remaining_sec: number;
  violations: number;
};

type AbuseBlocksResponse = {
  blocks: AbuseBlock[];
};

// 프로바이더별 시각 색상 — 4종 + 기타 fallback
const PROVIDER_COLOR: Record<string, string> = {
  anthropic: "#a78bfa",      // violet (Claude)
  openai: "#34d399",         // emerald (Whisper)
  serper: "#f472b6",         // pink
  virustotal: "#fbbf24",     // amber
};

function providerColor(name: string): string {
  return PROVIDER_COLOR[name.toLowerCase()] ?? "#94a3b8";
}

function fmtDay(iso: string): string {
  // "2026-04-29" → "4/29"
  const parts = iso.split("-");
  if (parts.length === 3) return `${Number(parts[1])}/${Number(parts[2])}`;
  return iso;
}

function fmtRemaining(sec: number): string {
  if (sec <= 0) return "expired";
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  if (m >= 60) return `${Math.floor(m / 60)}h ${m % 60}m`;
  if (m >= 1) return `${m}m ${s}s`;
  return `${s}s`;
}

function fmtMoney(usd: number): string {
  if (usd === 0) return "$0";
  if (usd < 0.01) return `$${usd.toFixed(4)}`;
  if (usd < 1) return `$${usd.toFixed(3)}`;
  return `$${usd.toFixed(2)}`;
}

function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "-";
  return new Date(iso).toLocaleString("ko-KR", { hour12: false });
}

export default function PlatformClient() {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [obs, setObs] = useState<ObservabilityResponse | null>(null);
  const [cost, setCost] = useState<CostResponse | null>(null);
  const [blocks, setBlocks] = useState<AbuseBlock[]>([]);
  const [error, setError] = useState("");
  const [issuedPlaintext, setIssuedPlaintext] = useState<string | null>(null);
  const [form, setForm] = useState({ label: "", monthly_quota: 1000, rpm_limit: 30, monthly_usd_quota: 5 });
  const [submitting, setSubmitting] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const [k, o, c, b] = await Promise.all([
        fetch("/api/admin/api-keys", { cache: "no-store" }),
        fetch("/api/admin/observability", { cache: "no-store" }),
        fetch("/api/admin/cost", { cache: "no-store" }),
        fetch("/api/admin/abuse-blocks", { cache: "no-store" }),
      ]);
      if (k.ok) setKeys(((await k.json()) as { keys: ApiKey[] }).keys ?? []);
      if (o.ok) setObs((await o.json()) as ObservabilityResponse);
      if (c.ok) setCost((await c.json()) as CostResponse);
      if (b.ok) setBlocks(((await b.json()) as AbuseBlocksResponse).blocks ?? []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "load 실패");
    }
  }, []);

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), 10000);
    return () => clearInterval(id);
  }, [refresh]);

  async function issue() {
    if (!form.label.trim()) return;
    setSubmitting(true);
    setError("");
    setIssuedPlaintext(null);
    try {
      const resp = await fetch("/api/admin/api-keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(form),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail ?? "발급 실패");
      setIssuedPlaintext(data.plaintext);
      setForm({ label: "", monthly_quota: 1000, rpm_limit: 30, monthly_usd_quota: 5 });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "발급 실패");
    } finally {
      setSubmitting(false);
    }
  }

  async function revoke(keyId: string) {
    if (!confirm("이 API key 를 revoke 할까요?")) return;
    const r = await fetch(`/api/admin/api-keys/${keyId}/revoke`, { method: "POST" });
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      setError(d.detail ?? "revoke 실패");
    }
    await refresh();
  }

  async function unblockUser(userId: string) {
    if (!confirm(`이 사용자(${userId.slice(0, 12)}…) 차단을 해제할까요?`)) return;
    const r = await fetch(
      `/api/admin/abuse-blocks/${encodeURIComponent(userId)}/unblock`,
      { method: "POST" },
    );
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      setError(d.detail ?? "차단 해제 실패");
    }
    await refresh();
  }

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-2xl border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
          {error}
        </div>
      )}

      {/* === 비용 대시보드 === */}
      {cost && (
        <section className="rounded-2xl border border-white/10 bg-white/5 p-6">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="text-lg font-semibold">💰 외부 API 비용 (최근 30일)</h2>
            <div className="text-2xl font-bold text-emerald-300">
              {fmtMoney(cost.total.usd)}
              <span className="ml-2 text-sm font-normal text-slate-400">
                · {cost.total.calls}회 호출
              </span>
            </div>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {cost.by_provider.map((p) => (
              <div key={p.provider} className="rounded-xl border border-white/10 bg-slate-950/40 p-3">
                <div className="flex items-center gap-2">
                  <span
                    className="inline-block h-2 w-2 rounded-full"
                    style={{ backgroundColor: providerColor(p.provider) }}
                  />
                  <span className="text-xs uppercase tracking-widest text-slate-400">{p.provider}</span>
                </div>
                <div className="mt-1 text-lg font-semibold">{fmtMoney(p.usd)}</div>
                <div className="text-xs text-slate-500">{p.calls}회 / {p.units.toFixed(0)} units</div>
              </div>
            ))}
          </div>

          {/* 일별 비용 추이 — area chart */}
          {cost.daily.length > 0 && (
            <div className="mt-5 rounded-xl border border-white/10 bg-slate-950/40 p-4">
              <div className="mb-3 flex items-baseline justify-between">
                <h3 className="text-sm font-semibold text-slate-200">📈 일별 USD 추이</h3>
                <span className="text-xs text-slate-500">
                  최근 {cost.daily.length}일 · 평균{" "}
                  {fmtMoney(cost.total.usd / Math.max(1, cost.daily.length))}/일
                </span>
              </div>
              <DailyCostArea
                data={cost.daily.map((d) => ({ ...d, label: fmtDay(d.day) }))}
                fmtMoney={fmtMoney}
              />
            </div>
          )}

          {/* 프로바이더 비교 — horizontal bar */}
          {cost.by_provider.length > 0 && (
            <div className="mt-3 rounded-xl border border-white/10 bg-slate-950/40 p-4">
              <h3 className="mb-3 text-sm font-semibold text-slate-200">🔍 프로바이더 USD 비중</h3>
              <ProviderBar
                data={cost.by_provider}
                fmtMoney={fmtMoney}
                colorOf={providerColor}
              />
            </div>
          )}
          {cost.by_key.length > 0 && (
            <div className="mt-4 overflow-x-auto rounded-xl border border-white/10">
              <table className="w-full text-sm">
                <thead className="bg-slate-800/60 text-xs uppercase tracking-wider text-slate-400">
                  <tr>
                    <th className="px-3 py-2 text-left">API key</th>
                    <th className="px-3 py-2 text-right">호출</th>
                    <th className="px-3 py-2 text-right">USD</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {cost.by_key.map((k, i) => (
                    <tr key={`${k.api_key_id}-${i}`}>
                      <td className="px-3 py-2 text-slate-200">{k.label ?? <span className="text-slate-500">(인증 없음)</span>}</td>
                      <td className="px-3 py-2 text-right font-mono">{k.calls}</td>
                      <td className="px-3 py-2 text-right font-mono text-emerald-300">{fmtMoney(k.usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}

      {/* === Observability === */}
      {obs && (
        <section className="rounded-2xl border border-white/10 bg-white/5 p-6">
          <h2 className="mb-3 text-lg font-semibold">📡 Observability (최근 {obs.summary.since_hours}h)</h2>
          <div className="grid gap-3 sm:grid-cols-4">
            <Stat label="총 요청" value={obs.summary.total.toString()} />
            <Stat
              label="에러 (5xx)"
              value={`${obs.summary.errors} (${(obs.summary.error_rate * 100).toFixed(1)}%)`}
              tone={obs.summary.error_rate > 0.05 ? "warn" : "ok"}
            />
            <Stat label="p50 latency" value={`${obs.summary.p50_ms}ms`} />
            <Stat label="p95 latency" value={`${obs.summary.p95_ms}ms`} />
          </div>
          {obs.summary.by_path.length > 0 && (
            <div className="mt-4 overflow-x-auto rounded-xl border border-white/10">
              <table className="w-full text-sm">
                <thead className="bg-slate-800/60 text-xs uppercase tracking-wider text-slate-400">
                  <tr>
                    <th className="px-3 py-2 text-left">경로</th>
                    <th className="px-3 py-2 text-right">요청</th>
                    <th className="px-3 py-2 text-right">평균 ms</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/5">
                  {obs.summary.by_path.slice(0, 12).map((p) => (
                    <tr key={p.path}>
                      <td className="px-3 py-2 font-mono text-xs text-slate-200">{p.path}</td>
                      <td className="px-3 py-2 text-right font-mono">{p.n}</td>
                      <td className="px-3 py-2 text-right font-mono text-slate-300">
                        {Math.round(p.avg_ms)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <details className="mt-3">
            <summary className="cursor-pointer text-xs text-slate-400 hover:text-slate-200">
              최근 {obs.recent.length}개 요청 상세
            </summary>
            <div className="mt-2 max-h-72 overflow-auto rounded-xl border border-white/10 bg-slate-950/40 p-2 font-mono text-xs">
              {obs.recent.map((r) => (
                <div
                  key={r.id}
                  className={`grid grid-cols-[80px_60px_60px_1fr_60px] gap-2 border-b border-slate-800/50 py-1 ${
                    r.status >= 500 ? "text-rose-300" : r.status >= 400 ? "text-amber-300" : "text-slate-300"
                  }`}
                >
                  <span className="text-slate-500">{r.created_at.slice(11, 19)}</span>
                  <span>{r.method}</span>
                  <span>{r.status}</span>
                  <span className="truncate">{r.path}</span>
                  <span className="text-right">{r.latency_ms}ms</span>
                </div>
              ))}
            </div>
          </details>
        </section>
      )}

      {/* === 어뷰즈 차단 관리 === */}
      <section className="rounded-2xl border border-white/10 bg-white/5 p-6">
        <div className="mb-3 flex items-baseline justify-between">
          <h2 className="text-lg font-semibold">🛑 어뷰즈 차단</h2>
          <span className="text-xs text-slate-400">
            짧은 메시지 누적 자동 차단 (1시간). 테스트 중 잘못 걸린 경우 수동 해제.
          </span>
        </div>
        <div className="overflow-x-auto rounded-xl border border-white/10">
          <table className="w-full text-sm">
            <thead className="bg-slate-800/60 text-xs uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-3 py-2 text-left">user_id</th>
                <th className="px-3 py-2 text-right">위반 누적</th>
                <th className="px-3 py-2 text-right">남은 시간</th>
                <th className="px-3 py-2 text-right">액션</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {blocks.length === 0 && (
                <tr>
                  <td className="px-3 py-4 text-center text-sm text-slate-500" colSpan={4}>
                    현재 차단된 사용자가 없습니다.
                  </td>
                </tr>
              )}
              {blocks.map((b) => (
                <tr key={b.user_id}>
                  <td className="px-3 py-2 font-mono text-xs text-slate-200">
                    {b.user_id}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs">{b.violations}</td>
                  <td className="px-3 py-2 text-right font-mono text-xs text-amber-300">
                    {fmtRemaining(b.block_remaining_sec)}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <button
                      onClick={() => void unblockUser(b.user_id)}
                      className="rounded-lg border border-emerald-400/30 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-200 hover:bg-emerald-500/20"
                    >
                      차단 해제
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* === API key 관리 === */}
      <section className="rounded-2xl border border-white/10 bg-white/5 p-6">
        <h2 className="mb-3 text-lg font-semibold">🔑 API key 관리</h2>

        <div className="mb-4 grid gap-3 sm:grid-cols-5">
          <input
            placeholder="라벨 (예: mobile-app, partner-acme)"
            value={form.label}
            onChange={(e) => setForm({ ...form, label: e.target.value })}
            className="rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 text-sm sm:col-span-2"
          />
          <input
            type="number"
            min={1}
            value={form.monthly_quota}
            onChange={(e) => setForm({ ...form, monthly_quota: Number(e.target.value) })}
            className="rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 text-sm"
            placeholder="monthly calls"
          />
          <input
            type="number"
            min={1}
            value={form.rpm_limit}
            onChange={(e) => setForm({ ...form, rpm_limit: Number(e.target.value) })}
            className="rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 text-sm"
            placeholder="rpm"
          />
          <input
            type="number"
            min={0}
            step={0.5}
            value={form.monthly_usd_quota}
            onChange={(e) => setForm({ ...form, monthly_usd_quota: Number(e.target.value) })}
            className="rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 text-sm"
            placeholder="monthly USD ($)"
          />
        </div>
        <button
          onClick={() => void issue()}
          disabled={submitting || !form.label.trim()}
          className="rounded-xl bg-cyan-300 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:opacity-50"
        >
          {submitting ? "발급 중..." : "발급"}
        </button>

        {issuedPlaintext && (
          <div className="mt-4 rounded-xl border border-emerald-400/30 bg-emerald-500/10 p-3">
            <div className="text-xs font-semibold text-emerald-200">
              ⚠️ 이 키는 다시 표시되지 않습니다. 안전한 곳에 저장하세요.
            </div>
            <div className="mt-2 break-all rounded bg-slate-950/60 px-3 py-2 font-mono text-xs text-emerald-100">
              {issuedPlaintext}
            </div>
            <button
              onClick={() => navigator.clipboard.writeText(issuedPlaintext)}
              className="mt-2 text-xs text-emerald-300 hover:text-emerald-200"
            >
              복사하기
            </button>
          </div>
        )}

        <div className="mt-5 overflow-x-auto rounded-xl border border-white/10">
          <table className="w-full text-sm">
            <thead className="bg-slate-800/60 text-xs uppercase tracking-wider text-slate-400">
              <tr>
                <th className="px-3 py-2 text-left">라벨</th>
                <th className="px-3 py-2 text-left">상태</th>
                <th className="px-3 py-2 text-right">월 호출</th>
                <th className="px-3 py-2 text-right">월 USD cap</th>
                <th className="px-3 py-2 text-right">RPM</th>
                <th className="px-3 py-2 text-left">최근 사용</th>
                <th className="px-3 py-2 text-right">액션</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/5">
              {keys.length === 0 && (
                <tr>
                  <td className="px-3 py-4 text-center text-sm text-slate-500" colSpan={7}>
                    아직 발급된 키가 없습니다.
                  </td>
                </tr>
              )}
              {keys.map((k) => (
                <tr key={k.id}>
                  <td className="px-3 py-2 text-slate-200">{k.label}</td>
                  <td className="px-3 py-2">
                    <span
                      className={
                        k.status === "active"
                          ? "rounded-full border border-emerald-400/30 bg-emerald-500/10 px-2 py-0.5 text-xs text-emerald-200"
                          : "rounded-full border border-slate-400/30 bg-slate-500/10 px-2 py-0.5 text-xs text-slate-400"
                      }
                    >
                      {k.status}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs">
                    {k.usage_month} / {k.monthly_quota}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs text-emerald-300">
                    ${(k.monthly_usd_quota ?? 0).toFixed(2)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-xs">{k.rpm_limit}</td>
                  <td className="px-3 py-2 text-xs text-slate-400">{fmtTime(k.last_used_at)}</td>
                  <td className="px-3 py-2 text-right">
                    {k.status === "active" && (
                      <button
                        onClick={() => void revoke(k.id)}
                        className="rounded-lg border border-rose-400/30 bg-rose-500/10 px-3 py-1 text-xs text-rose-200 hover:bg-rose-500/20"
                      >
                        revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}

function Stat({ label, value, tone }: { label: string; value: string; tone?: "ok" | "warn" }) {
  const cls =
    tone === "warn"
      ? "border-amber-400/30 bg-amber-500/10 text-amber-100"
      : "border-white/10 bg-slate-950/40 text-slate-100";
  return (
    <div className={`rounded-xl border px-3 py-2 ${cls}`}>
      <div className="text-xs text-slate-400">{label}</div>
      <div className="mt-1 font-mono text-base">{value}</div>
    </div>
  );
}
