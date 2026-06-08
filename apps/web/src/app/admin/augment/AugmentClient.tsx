"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";

// recharts 는 무거운 클라이언트 청크 → lazy-load (초기 admin 진입 JS 에서 제외)
const CoverageBar = dynamic(
  () => import("../charts").then((m) => m.CoverageBar),
  { ssr: false },
);
const AugmentProgressLine = dynamic(
  () => import("../charts").then((m) => m.AugmentProgressLine),
  { ssr: false },
);

type SeedStats = {
  scam_types: string[];
  by_scam_type: Record<string, number>;
  starved: string[];
  starved_threshold: number;
  total: number;
};

type Seed = {
  idx: number;
  text: string;
  scam_type: string;
  content_label: string;
};

type SessionParams = {
  seed_file?: string;
  variants?: number;
  rounds?: number;
  model?: string;
  concurrency?: number;
  limit?: number;
  scam_type?: string | null;
};

type SessionInfo = {
  session_id: string;
  model: string;
  status: string;
  started_at: number;
  ended_at: number | null;
  params: SessionParams;
  output_file?: string;
  last_metrics?: Record<string, unknown> | null;
};

type Metric = {
  kind?: string;
  done?: number;
  total?: number;
  generated?: number;
  total_generated?: number;
  scam_type?: string;
  ts?: number;
};

type Detail = {
  session: SessionInfo;
  metrics: Metric[];
  log_tail: string;
};

const CONTENT_LABELS = ["scam_attempt", "normal", "scam_news_edu"];

function statusColor(status: string): string {
  if (status === "running") return "border-cyan-400/30 bg-cyan-500/10 text-cyan-200";
  if (status === "completed") return "border-emerald-400/30 bg-emerald-500/10 text-emerald-200";
  if (status === "cancelled") return "border-amber-400/30 bg-amber-500/10 text-amber-200";
  return "border-rose-400/30 bg-rose-500/10 text-rose-200";
}

export default function AugmentClient() {
  const [stats, setStats] = useState<SeedStats | null>(null);
  const [seeds, setSeeds] = useState<Seed[]>([]);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [error, setError] = useState("");
  const logRef = useRef<HTMLPreElement | null>(null);

  // 씨앗 작성 폼
  const [seedForm, setSeedForm] = useState({
    scam_type: "",
    content_label: "scam_attempt",
    text: "",
  });
  const [seedSubmitting, setSeedSubmitting] = useState(false);

  // 증강 시작 폼
  const [augForm, setAugForm] = useState({
    variants: 5,
    rounds: 1,
    model: "claude-sonnet-4-6",
    concurrency: 8,
    limit: 0,
    scam_type: "",
  });
  const [augSubmitting, setAugSubmitting] = useState(false);

  const refreshStats = useCallback(async () => {
    try {
      const [s1, s2, s3] = await Promise.all([
        fetch("/api/admin/augment/seed-stats", { cache: "no-store" }),
        fetch("/api/admin/augment/seeds", { cache: "no-store" }),
        fetch("/api/admin/augment/sessions", { cache: "no-store" }),
      ]);
      if (s1.ok) {
        const data = (await s1.json()) as SeedStats;
        setStats(data);
        setSeedForm((f) => ({ ...f, scam_type: f.scam_type || data.scam_types[0] || "" }));
      }
      if (s2.ok) setSeeds(((await s2.json()).seeds ?? []) as Seed[]);
      if (s3.ok) setSessions(((await s3.json()).sessions ?? []) as SessionInfo[]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "로드 실패");
    }
  }, []);

  useEffect(() => {
    void refreshStats();
  }, [refreshStats]);

  // running 세션 있으면 5초 폴링
  useEffect(() => {
    const hasRunning = sessions.some((s) => s.status === "running");
    if (!hasRunning) return;
    const id = setInterval(() => {
      void refreshStats();
      if (selectedId) void loadDetail(selectedId);
    }, 5000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessions, selectedId, refreshStats]);

  const loadDetail = useCallback(async (sessionId: string) => {
    try {
      const r = await fetch(`/api/admin/augment/sessions/${sessionId}`, { cache: "no-store" });
      if (r.ok) setDetail((await r.json()) as Detail);
    } catch {
      /* noop */
    }
  }, []);

  useEffect(() => {
    if (selectedId) void loadDetail(selectedId);
  }, [selectedId, loadDetail]);

  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [detail?.log_tail]);

  async function submitSeed() {
    if (!seedForm.text.trim()) {
      setError("씨앗 텍스트를 입력하세요.");
      return;
    }
    setSeedSubmitting(true);
    setError("");
    try {
      const r = await fetch("/api/admin/augment/seeds", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(seedForm),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail ?? "씨앗 추가 실패");
      setSeedForm((f) => ({ ...f, text: "" }));
      await refreshStats();
    } catch (err) {
      setError(err instanceof Error ? err.message : "씨앗 추가 실패");
    } finally {
      setSeedSubmitting(false);
    }
  }

  async function deleteSeed(idx: number) {
    try {
      const r = await fetch(`/api/admin/augment/seeds/${idx}`, { method: "DELETE" });
      if (r.ok) await refreshStats();
    } catch {
      /* noop */
    }
  }

  async function startAugment() {
    setAugSubmitting(true);
    setError("");
    try {
      const r = await fetch("/api/admin/augment/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          variants: augForm.variants,
          rounds: augForm.rounds,
          model: augForm.model,
          concurrency: augForm.concurrency,
          limit: augForm.limit,
          scam_type: augForm.scam_type || null,
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail ?? "증강 시작 실패");
      await refreshStats();
      setSelectedId(data.session_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "증강 시작 실패");
    } finally {
      setAugSubmitting(false);
    }
  }

  async function cancelSession(sessionId: string) {
    try {
      await fetch(`/api/admin/augment/sessions/${sessionId}/cancel`, { method: "POST" });
      await refreshStats();
    } catch {
      /* noop */
    }
  }

  async function promoteSession(sessionId: string) {
    setError("");
    try {
      const r = await fetch(`/api/admin/augment/sessions/${sessionId}/promote`, { method: "POST" });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail ?? "내보내기 실패");
      setError(`✅ ${data.added}건 추가 → ${data.path} (training extra_jsonl 로 사용 가능)`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "내보내기 실패");
    }
  }

  const coverageData = useMemo(() => {
    if (!stats) return [];
    return stats.scam_types.map((t) => ({
      type: t,
      count: stats.by_scam_type[t] ?? 0,
      starved: stats.starved.includes(t),
    }));
  }, [stats]);

  const progressData = useMemo(() => {
    if (!detail) return [];
    return detail.metrics
      .filter((m) => m.kind === "augment" && typeof m.done === "number")
      .map((m) => ({ done: m.done, generated: m.generated ?? 0 }));
  }, [detail]);

  const selectedDone = detail?.metrics.filter((m) => m.kind === "augment").slice(-1)[0];

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-xl border border-rose-400/30 bg-rose-500/10 px-4 py-2 text-sm text-rose-200">
          {error}
        </div>
      )}

      {/* 씨앗 커버리지 */}
      <section className="rounded-2xl border border-white/10 bg-slate-950/40 p-5">
        <div className="mb-3 flex items-end justify-between">
          <h2 className="text-lg font-semibold text-white">씨앗 유형별 커버리지</h2>
          <p className="text-xs text-slate-400">
            총 {stats?.total ?? 0}개 · 굶은 유형(≤{stats?.starved_threshold ?? 3}) {stats?.starved.length ?? 0}개
          </p>
        </div>
        <CoverageBar data={coverageData} />
        <p className="mt-1 text-xs text-slate-500">빨강 = 굶은 유형 (씨앗 부족 → 학습 F1 낮음)</p>
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* 씨앗 작성 */}
        <section className="rounded-2xl border border-white/10 bg-slate-950/40 p-5">
          <h2 className="mb-3 text-lg font-semibold text-white">씨앗 작성</h2>
          <div className="space-y-3">
            <div className="flex gap-2">
              <select
                value={seedForm.scam_type}
                onChange={(e) => setSeedForm((f) => ({ ...f, scam_type: e.target.value }))}
                className="flex-1 rounded-lg border border-white/10 bg-slate-900/80 px-3 py-2 text-sm text-slate-100"
              >
                {(stats?.scam_types ?? []).map((t) => (
                  <option key={t} value={t}>
                    {t}
                    {stats?.starved.includes(t) ? " ⚠️굶음" : ""}
                  </option>
                ))}
              </select>
              <select
                value={seedForm.content_label}
                onChange={(e) => setSeedForm((f) => ({ ...f, content_label: e.target.value }))}
                className="rounded-lg border border-white/10 bg-slate-900/80 px-3 py-2 text-sm text-slate-100"
              >
                {CONTENT_LABELS.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            </div>
            <textarea
              value={seedForm.text}
              onChange={(e) => setSeedForm((f) => ({ ...f, text: e.target.value }))}
              placeholder="진짜같은 사기 메시지 씨앗을 입력하세요..."
              rows={4}
              className="w-full rounded-lg border border-white/10 bg-slate-900/80 px-3 py-2 text-sm text-slate-100"
            />
            <button
              onClick={() => void submitSeed()}
              disabled={seedSubmitting}
              className="rounded-xl border border-emerald-400/30 bg-emerald-500/10 px-4 py-2 text-sm font-semibold text-emerald-200 transition hover:bg-emerald-500/20 disabled:opacity-50"
            >
              {seedSubmitting ? "추가 중..." : "씨앗 추가"}
            </button>
          </div>
          <div className="mt-4 max-h-56 space-y-1 overflow-auto">
            {seeds.length === 0 && <p className="text-xs text-slate-500">작성된 씨앗 없음</p>}
            {seeds.map((s) => (
              <div key={s.idx} className="flex items-start gap-2 rounded-lg border border-white/5 bg-white/5 px-3 py-2 text-xs">
                <span className="shrink-0 rounded bg-cyan-500/10 px-1.5 py-0.5 text-cyan-200">{s.scam_type}</span>
                <span className="flex-1 text-slate-300">{s.text}</span>
                <button onClick={() => void deleteSeed(s.idx)} className="shrink-0 text-rose-300 hover:text-rose-200">
                  삭제
                </button>
              </div>
            ))}
          </div>
        </section>

        {/* 증강 시작 */}
        <section className="rounded-2xl border border-white/10 bg-slate-950/40 p-5">
          <h2 className="mb-3 text-lg font-semibold text-white">증강 실행</h2>
          <div className="grid grid-cols-2 gap-3 text-sm">
            <label className="space-y-1">
              <span className="text-xs text-slate-400">변형 수 (씨앗당)</span>
              <input
                type="number"
                min={1}
                value={augForm.variants}
                onChange={(e) => setAugForm((f) => ({ ...f, variants: Number(e.target.value) }))}
                className="w-full rounded-lg border border-white/10 bg-slate-900/80 px-3 py-2 text-slate-100"
              />
            </label>
            <label className="space-y-1">
              <span className="text-xs text-slate-400">라운드</span>
              <input
                type="number"
                min={1}
                value={augForm.rounds}
                onChange={(e) => setAugForm((f) => ({ ...f, rounds: Number(e.target.value) }))}
                className="w-full rounded-lg border border-white/10 bg-slate-900/80 px-3 py-2 text-slate-100"
              />
            </label>
            <label className="space-y-1">
              <span className="text-xs text-slate-400">동시성 (병렬)</span>
              <input
                type="number"
                min={1}
                max={16}
                value={augForm.concurrency}
                onChange={(e) => setAugForm((f) => ({ ...f, concurrency: Number(e.target.value) }))}
                className="w-full rounded-lg border border-white/10 bg-slate-900/80 px-3 py-2 text-slate-100"
              />
            </label>
            <label className="space-y-1">
              <span className="text-xs text-slate-400">씨앗 한도 (0=전체)</span>
              <input
                type="number"
                min={0}
                value={augForm.limit}
                onChange={(e) => setAugForm((f) => ({ ...f, limit: Number(e.target.value) }))}
                className="w-full rounded-lg border border-white/10 bg-slate-900/80 px-3 py-2 text-slate-100"
              />
            </label>
            <label className="col-span-2 space-y-1">
              <span className="text-xs text-slate-400">씨앗 소스 유형 (비우면 전체)</span>
              <select
                value={augForm.scam_type}
                onChange={(e) => setAugForm((f) => ({ ...f, scam_type: e.target.value }))}
                className="w-full rounded-lg border border-white/10 bg-slate-900/80 px-3 py-2 text-slate-100"
              >
                <option value="">전체 유형</option>
                {(stats?.scam_types ?? []).map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <button
            onClick={() => void startAugment()}
            disabled={augSubmitting}
            className="mt-3 w-full rounded-xl border border-cyan-400/30 bg-cyan-500/10 px-4 py-2 text-sm font-semibold text-cyan-200 transition hover:bg-cyan-500/20 disabled:opacity-50"
          >
            {augSubmitting ? "시작 중..." : "증강 세션 시작"}
          </button>
          <p className="mt-2 text-xs text-slate-500">
            씨앗 소스: <code className="text-slate-400">data/processed/admin_seeds.jsonl</code> (작성한 씨앗)
          </p>
        </section>
      </div>

      {/* 세션 리스트 + 상세 */}
      <section className="grid gap-4 lg:grid-cols-[260px_1fr]">
        <div className="space-y-2">
          <h2 className="text-sm font-semibold text-slate-300">세션</h2>
          <div className="max-h-[480px] space-y-2 overflow-auto">
            {sessions.length === 0 && <p className="text-xs text-slate-500">세션 없음</p>}
            {sessions.map((s) => (
              <button
                key={s.session_id}
                onClick={() => setSelectedId(s.session_id)}
                className={`w-full rounded-xl border px-3 py-2 text-left text-xs transition ${
                  selectedId === s.session_id ? "border-cyan-400/50 bg-cyan-500/10" : "border-white/10 bg-white/5 hover:bg-white/10"
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-slate-300">{s.session_id}</span>
                  <span className={`rounded px-1.5 py-0.5 ${statusColor(s.status)}`}>{s.status}</span>
                </div>
                <div className="mt-1 text-slate-500">
                  {s.params?.scam_type || "전체"} · 변형 {s.params?.variants} · 동시성 {s.params?.concurrency}
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-5">
          {!detail ? (
            <p className="text-sm text-slate-500">세션을 선택하면 진행 상황이 표시됩니다.</p>
          ) : (
            <div className="space-y-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <p className="font-mono text-sm text-slate-300">{detail.session.session_id}</p>
                  <span className={`mt-1 inline-block rounded px-2 py-0.5 text-xs ${statusColor(detail.session.status)}`}>
                    {detail.session.status}
                  </span>
                </div>
                <div className="flex gap-2">
                  {detail.session.status === "running" && (
                    <button
                      onClick={() => void cancelSession(detail.session.session_id)}
                      className="rounded-lg border border-rose-400/30 bg-rose-500/10 px-3 py-1.5 text-xs font-semibold text-rose-200 hover:bg-rose-500/20"
                    >
                      취소
                    </button>
                  )}
                  {detail.session.status === "completed" && (
                    <button
                      onClick={() => void promoteSession(detail.session.session_id)}
                      className="rounded-lg border border-emerald-400/30 bg-emerald-500/10 px-3 py-1.5 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/20"
                    >
                      training 데이터로 내보내기
                    </button>
                  )}
                </div>
              </div>

              {selectedDone && (
                <div>
                  <div className="mb-1 flex justify-between text-xs text-slate-400">
                    <span>
                      진행 {selectedDone.done}/{selectedDone.total}
                    </span>
                    <span>생성 누적 {selectedDone.generated ?? 0}건</span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-white/10">
                    <div
                      className="h-full bg-cyan-400 transition-all"
                      style={{ width: `${((selectedDone.done ?? 0) / (selectedDone.total || 1)) * 100}%` }}
                    />
                  </div>
                </div>
              )}

              {progressData.length > 1 && (
                <AugmentProgressLine data={progressData} />
              )}

              <pre
                ref={logRef}
                className="h-60 overflow-auto whitespace-pre-wrap break-words rounded-xl border border-white/10 bg-black/30 p-3 font-mono text-xs leading-relaxed text-slate-300"
              >
                {detail.log_tail || "아직 출력 없음"}
              </pre>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
