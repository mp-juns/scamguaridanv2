"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type SampleResult = {
  sha256: string;
  pkg_name: string;
  package_name?: string;
  vt_detection: number | string | null;
  apk_size?: string;
  static_flags: string[];
  bytecode_flags: string[];
  all_flags?: string[];
  detected?: boolean;
  strong_detected?: boolean;
  error?: string | null;
};

type Summary = {
  analyzed: number;
  detected: number;
  strong_detected: number;
  detection_rate: number;
  strong_detection_rate: number;
  flag_frequency: Record<string, number>;
};

type Benchmark = {
  benchmark_id: string;
  status: "running" | "done" | "error";
  phase: string;
  message: string;
  total: number;
  done: number;
  results: SampleResult[];
  summary: Summary | null;
};

const WEAK = new Set(["apk_self_signed"]);

export default function AndrozooClient() {
  const [count, setCount] = useState(5);
  const [minVt, setMinVt] = useState(10);
  const [pkgGrep, setPkgGrep] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [bench, setBench] = useState<Benchmark | null>(null);
  const idRef = useRef<string | null>(null);

  const poll = useCallback(async (id: string) => {
    const r = await fetch(`/api/admin/apk-dynamic/androzoo/benchmark/${id}`, { cache: "no-store" });
    if (!r.ok) return;
    const data = (await r.json()) as Benchmark;
    setBench(data);
    if (data.status === "running") {
      setTimeout(() => poll(id), 1500);
    } else {
      setBusy(false);
    }
  }, []);

  useEffect(() => {
    if (idRef.current) poll(idRef.current);
  }, [poll]);

  async function start() {
    setBusy(true);
    setNotice(null);
    setBench(null);
    try {
      const r = await fetch("/api/admin/apk-dynamic/androzoo/benchmark", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ count, min_vt: minVt, pkg_grep: pkgGrep.trim() || null }),
      });
      const data = await r.json();
      if (!r.ok) {
        setNotice(data?.detail ?? "벤치마크 시작 실패");
        setBusy(false);
        return;
      }
      idRef.current = data.benchmark_id;
      poll(data.benchmark_id);
    } catch (e) {
      setNotice(String(e));
      setBusy(false);
    }
  }

  async function cancel() {
    try {
      await fetch("/api/admin/apk-dynamic/androzoo/benchmark/cancel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
    } finally {
      setBusy(false);
    }
  }

  const s = bench?.summary;

  return (
    <div className="space-y-6">
      {/* 폼 */}
      <section className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
        <h2 className="text-lg font-semibold text-white">무작위 악성 샘플 벤치마크</h2>
        <p className="mt-1 text-sm text-slate-400">
          <code>vt_detection ≥ 임계</code> 인 실제 악성 APK 를 받아 우리 검출 신호와 비교합니다. 실제 멀웨어를
          내려받으니 데모/연구 용도로만 사용하세요.
        </p>
        <div className="mt-4 grid gap-4 sm:grid-cols-[120px_140px_1fr_auto]">
          <label className="text-sm text-slate-300">
            샘플 수
            <input
              type="number" min={1} max={30} value={count}
              onChange={(e) => setCount(Number(e.target.value))}
              className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-slate-100"
            />
          </label>
          <label className="text-sm text-slate-300">
            min vt_detection
            <input
              type="number" min={0} max={70} value={minVt}
              onChange={(e) => setMinVt(Number(e.target.value))}
              className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-slate-100"
            />
          </label>
          <label className="text-sm text-slate-300">
            패키지명 필터 (콤마, 선택)
            <input
              type="text" value={pkgGrep} placeholder="bank,kakao,gov …"
              onChange={(e) => setPkgGrep(e.target.value)}
              className="mt-1 w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-slate-100 placeholder:text-slate-500"
            />
          </label>
          <div className="mt-auto flex gap-2">
            <button
              onClick={start}
              disabled={busy}
              className="rounded-2xl bg-cyan-300 px-5 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:opacity-40"
            >
              {busy ? "실행 중…" : "벤치마크 시작"}
            </button>
            {busy ? (
              <button
                onClick={cancel}
                className="rounded-2xl border border-rose-400/40 px-4 py-2 text-sm text-rose-200 transition hover:bg-rose-500/10"
              >
                중단
              </button>
            ) : null}
          </div>
        </div>
        <p className="mt-2 text-xs text-slate-500">
          멈춘 것처럼 보이면 다시 <strong>벤치마크 시작</strong>을 누르면 이전 잡을 취소하고 새로 시작합니다.
          패키지 필터가 좁으면 매칭이 드물어 스캔이 길어집니다(최대 100만 행).
        </p>
        {notice ? (
          <div className="mt-3 rounded-2xl border border-rose-400/30 bg-rose-500/10 px-4 py-2 text-sm text-rose-100">
            {notice}
          </div>
        ) : null}
        {bench ? (
          <div className="mt-3 text-sm text-slate-400">
            {bench.phase} · {bench.message} {bench.total ? `(${bench.done}/${bench.total})` : ""}
          </div>
        ) : null}
      </section>

      {/* 요약 */}
      {s ? (
        <section className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
          <h2 className="text-lg font-semibold text-white">검출 요약</h2>
          <div className="mt-3 flex flex-wrap gap-4">
            <Stat label="분석" value={`${s.analyzed}`} />
            <Stat label="신호 1개+ 검출" value={`${s.detected} (${Math.round(s.detection_rate * 100)}%)`} />
            <Stat label="강한 신호(self-signed 외)" value={`${s.strong_detected} (${Math.round(s.strong_detection_rate * 100)}%)`} accent />
          </div>
          {Object.keys(s.flag_frequency).length ? (
            <div className="mt-4 flex flex-wrap gap-2">
              {Object.entries(s.flag_frequency).map(([f, c]) => (
                <span key={f} className={`rounded-full border px-3 py-1 text-xs ${WEAK.has(f) ? "border-white/10 text-slate-400" : "border-amber-400/40 text-amber-200"}`}>
                  {f} · {c}
                </span>
              ))}
            </div>
          ) : null}
          <p className="mt-3 text-xs text-slate-500">
            ScamGuardian 은 검출만 보고합니다 — vt_detection 은 VirusTotal 70개 백신 합의이고, 우리 신호는 한국 보이스피싱
            패밀리 패턴에 튜닝돼 있어 일반 멀웨어는 self-signed 만 뜰 수 있습니다 (판정은 통합 기업).
          </p>
        </section>
      ) : null}

      {/* 결과 테이블 */}
      {bench?.results?.length ? (
        <section className="overflow-x-auto rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
          <table className="w-full text-sm">
            <thead className="text-left text-xs uppercase tracking-widest text-slate-400">
              <tr>
                <th className="pb-2">패키지 / SHA256</th>
                <th className="pb-2">vt</th>
                <th className="pb-2">우리 검출 신호</th>
              </tr>
            </thead>
            <tbody>
              {bench.results.map((r) => (
                <tr key={r.sha256} className="border-t border-white/5 align-top">
                  <td className="py-2 pr-4">
                    <div className="text-slate-100">{r.package_name || r.pkg_name || "(unknown)"}</div>
                    <div className="font-mono text-[11px] text-slate-500">{r.sha256.slice(0, 24)}…</div>
                  </td>
                  <td className="py-2 pr-4">
                    <span className="rounded-full bg-rose-500/15 px-2 py-0.5 text-rose-200">{String(r.vt_detection)}</span>
                  </td>
                  <td className="py-2">
                    {r.error ? (
                      <span className="text-rose-300">{r.error}</span>
                    ) : r.all_flags?.length ? (
                      <div className="flex flex-wrap gap-1.5">
                        {r.all_flags.map((f) => (
                          <span key={f} className={`rounded-full border px-2 py-0.5 text-xs ${WEAK.has(f) ? "border-white/10 text-slate-400" : "border-amber-400/40 text-amber-200"}`}>
                            {f}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-slate-500">검출 신호 없음</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      ) : null}
    </div>
  );
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-black/20 px-4 py-3">
      <div className="text-xs uppercase tracking-widest text-slate-400">{label}</div>
      <div className={`mt-1 text-xl font-semibold ${accent ? "text-amber-200" : "text-white"}`}>{value}</div>
    </div>
  );
}
