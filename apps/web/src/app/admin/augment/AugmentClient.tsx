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
  content_labels?: string[];
  by_content_label?: Record<string, number>;
  by_content_label_augmented?: Record<string, number>;
  augmented_path?: string;
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

type AugForm = {
  variants: number;
  rounds: number;
  model: string;
  concurrency: number;
  limit: number;
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
const CONTENT_LABEL_KO: Record<string, string> = {
  scam_attempt: "사기 시도",
  normal: "정상",
  scam_news_edu: "사기 예방·뉴스",
};

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

  // 씨앗 작성 폼 (기본 게이트 파트 → normal HN)
  const [seedForm, setSeedForm] = useState({
    scam_type: "",
    content_label: "normal",
    text: "",
  });
  const [seedSubmitting, setSeedSubmitting] = useState(false);

  // 증강 시작 폼
  const [augForm, setAugForm] = useState<AugForm>({
    variants: 5,
    rounds: 1,
    model: "claude-sonnet-4-6",
    concurrency: 8,
    limit: 0,
    scam_type: "",
    content_label: "",
  });
  const [augSubmitting, setAugSubmitting] = useState(false);

  // 두 파트: 게이트(content_label 3-class) vs 분석 분류기·추출기(scam_type 12종)
  const [part, setPart] = useState<"gate" | "analysis">("gate");
  function switchPart(next: "gate" | "analysis") {
    setPart(next);
    setError("");
    if (next === "analysis") {
      // 분석 분류기·추출기는 scam_attempt 만 다룸
      setSeedForm((f) => ({ ...f, content_label: "scam_attempt" }));
      setAugForm((f) => ({ ...f, content_label: "" }));
    } else {
      // 게이트는 정상/예방 hard negative 가 핵심
      setSeedForm((f) => ({ ...f, content_label: f.content_label === "scam_attempt" ? "normal" : f.content_label }));
      setAugForm((f) => ({ ...f, scam_type: "" }));
    }
  }

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
    const isScamAttempt = seedForm.content_label === "scam_attempt";
    if (isScamAttempt && !seedForm.scam_type) {
      setError("사기 시도 데이터는 세부 유형을 선택해야 합니다.");
      return;
    }
    // 정상/사기예방·뉴스는 세부 유형 없음 → scam_type 강제 빈 값
    const payload = {
      ...seedForm,
      scam_type: isScamAttempt ? seedForm.scam_type : "",
    };
    setSeedSubmitting(true);
    setError("");
    try {
      const r = await fetch("/api/admin/augment/seeds", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
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
          // 각 파트에 맞는 필터만 전송
          scam_type: part === "analysis" ? augForm.scam_type || null : null,
          content_label: part === "gate" ? augForm.content_label || null : "scam_attempt",
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

  // 파트별 씨앗 목록 — 게이트는 정상/예방 HN, 분석은 사기 시도
  const partSeeds = useMemo(() => {
    if (part === "analysis") {
      return seeds.filter((s) => (s.content_label ?? "scam_attempt") === "scam_attempt");
    }
    return seeds.filter((s) => ["normal", "scam_news_edu"].includes(s.content_label ?? ""));
  }, [seeds, part]);

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

      {/* 파트 탭 — 게이트 vs 분석 분류기·추출기 */}
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => switchPart("gate")}
          className={`rounded-xl border px-4 py-2 text-sm font-semibold transition ${
            part === "gate"
              ? "border-amber-300/40 bg-amber-500/15 text-amber-100"
              : "border-white/10 bg-white/5 text-slate-300 hover:bg-white/10"
          }`}
        >
          🚪 게이트 데이터 (정상·사기·예방 3-class)
        </button>
        <button
          onClick={() => switchPart("analysis")}
          className={`rounded-xl border px-4 py-2 text-sm font-semibold transition ${
            part === "analysis"
              ? "border-cyan-300/40 bg-cyan-500/15 text-cyan-100"
              : "border-white/10 bg-white/5 text-slate-300 hover:bg-white/10"
          }`}
        >
          🔍 분석 분류기·추출기 (scam_type 12종)
        </button>
      </div>
      <p className="-mt-3 text-xs text-slate-500">
        {part === "gate"
          ? "게이트는 메시지를 정상/사기 시도/사기 예방·뉴스로 거릅니다. 정상·예방 hard negative 를 늘려 오탐(정상→사기)을 줄입니다."
          : "분석 분류기(scam_type 12종)·추출기(entity)는 사기 시도(scam_attempt) 메시지만 학습합니다. 굶은 유형 씨앗을 늘립니다. scam_type 12종은 세부 후보 라벨이며, 대표 유형 분류에는 상위 scam_category(5-class)가 사용됩니다."}
      </p>

      {part === "gate" ? (
        <>
          {/* 게이트 클래스 균형 — seed 후보 vs 실제 학습 데이터 두 기준 나란히 */}
          <section className="rounded-2xl border border-amber-300/20 bg-amber-500/5 p-5">
            <h2 className="text-lg font-semibold text-white">게이트 클래스 균형 (content_label)</h2>
            <p className="mb-4 mt-1 text-xs text-slate-400">
              왼쪽은 증강 전 seed 후보, 오른쪽은 게이트가 실제 학습하는 증강 후 데이터입니다. 두 기준의 균형은 다를 수 있습니다.
            </p>
            <div className="grid gap-4 lg:grid-cols-2">
              <GateBalancePanel
                title="Seed 후보 균형"
                desc="증강 전 원본/후보 seed 기준입니다. pending, draft 파일이 포함될 수 있습니다."
                counts={stats?.by_content_label}
                accent="slate"
              />
              <GateBalancePanel
                title="실제 학습 데이터 균형"
                desc="게이트 학습에 실제 사용되는 증강 후 데이터 기준입니다."
                counts={stats?.by_content_label_augmented}
                accent="amber"
              />
            </div>
          </section>

          <div className="grid gap-6 lg:grid-cols-2">
            {/* 게이트 씨앗 작성 */}
            <section className="rounded-2xl border border-amber-300/20 bg-amber-500/5 p-5">
              <h2 className="mb-3 text-lg font-semibold text-white">게이트 씨앗 작성 (정상·예방 HN)</h2>
              <div className="space-y-3">
                <div className="flex gap-2">
                  <select
                    value={seedForm.content_label}
                    onChange={(e) => {
                      const v = e.target.value;
                      setSeedForm((f) => ({
                        ...f,
                        content_label: v,
                        // 사기 시도만 세부 유형 유지 — 정상/예방은 빈 값으로 강제
                        scam_type: v === "scam_attempt" ? f.scam_type || stats?.scam_types?.[0] || "" : "",
                      }));
                    }}
                    className="rounded-lg border border-amber-300/30 bg-slate-900/80 px-3 py-2 text-sm text-slate-100"
                  >
                    {CONTENT_LABELS.map((c) => (
                      <option key={c} value={c}>
                        {CONTENT_LABEL_KO[c] ?? c}
                      </option>
                    ))}
                  </select>
                  {seedForm.content_label === "scam_attempt" && (
                    <select
                      value={seedForm.scam_type}
                      onChange={(e) => setSeedForm((f) => ({ ...f, scam_type: e.target.value }))}
                      className="flex-1 rounded-lg border border-white/10 bg-slate-900/80 px-3 py-2 text-sm text-slate-100"
                    >
                      {(stats?.scam_types ?? []).map((t) => (
                        <option key={t} value={t}>
                          {t}
                        </option>
                      ))}
                    </select>
                  )}
                </div>
                <p className="text-xs text-slate-500">
                  {seedForm.content_label === "scam_attempt"
                    ? "사기 시도 데이터는 세부 유형을 선택해야 합니다."
                    : seedForm.content_label === "scam_news_edu"
                      ? "사기예방·뉴스 데이터는 세부 사기유형을 선택하지 않습니다."
                      : "정상 데이터는 세부 사기유형을 선택하지 않습니다."}
                </p>
                <textarea
                  value={seedForm.text}
                  onChange={(e) => setSeedForm((f) => ({ ...f, text: e.target.value }))}
                  placeholder="정상 안내문·사기 예방 콘텐츠 씨앗을 입력하세요..."
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
              <SeedList seeds={partSeeds} onDelete={deleteSeed} />
            </section>

            {/* 게이트 증강 */}
            <section className="rounded-2xl border border-amber-300/20 bg-amber-500/5 p-5">
              <h2 className="mb-3 text-lg font-semibold text-white">게이트 데이터 증강</h2>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <AugmentBasicFields augForm={augForm} onChange={(patch) => setAugForm((f) => ({ ...f, ...patch }))} />
                <label className="col-span-2 space-y-1">
                  <span className="text-xs text-amber-300/80">게이트 클래스 (비우면 전체)</span>
                  <select
                    value={augForm.content_label}
                    onChange={(e) => setAugForm((f) => ({ ...f, content_label: e.target.value }))}
                    className="w-full rounded-lg border border-amber-300/30 bg-slate-900/80 px-3 py-2 text-slate-100"
                  >
                    <option value="">전체 클래스</option>
                    {(stats?.content_labels ?? CONTENT_LABELS).map((c) => (
                      <option key={c} value={c}>
                        {CONTENT_LABEL_KO[c] ?? c}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <button
                onClick={() => void startAugment()}
                disabled={augSubmitting}
                className="mt-3 w-full rounded-xl border border-amber-400/30 bg-amber-500/10 px-4 py-2 text-sm font-semibold text-amber-200 transition hover:bg-amber-500/20 disabled:opacity-50"
              >
                {augSubmitting ? "시작 중..." : "게이트 증강 시작"}
              </button>
              <p className="mt-2 text-xs text-slate-500">
                정상/예방 hard negative 만 골라 증강 → promote 후 게이트 학습 입력으로 사용.
              </p>
            </section>
          </div>
        </>
      ) : (
        <>
          {/* scam_type 커버리지 */}
          <section className="rounded-2xl border border-white/10 bg-slate-950/40 p-5">
            <div className="mb-3 flex items-end justify-between">
              <h2 className="text-lg font-semibold text-white">세부 scam_type seed 커버리지</h2>
              <p className="text-xs text-slate-400">
                총 {stats?.total ?? 0}개 · 부족 유형(≤{stats?.starved_threshold ?? 3}) {stats?.starved.length ?? 0}개
              </p>
            </div>
            <CoverageBar data={coverageData} />
            <p className="mt-1 text-xs text-slate-500">빨강 = 부족 유형(seed ≤ {stats?.starved_threshold ?? 3}, 학습 F1 저하 가능)</p>
            <p className="mt-1 text-xs text-amber-300/70">
              seed는 scam_type 기준으로 관리하고, 학습/평가 시 필요에 따라 5-class scam_category로 묶어 사용할 수 있습니다.
            </p>
          </section>

          <div className="grid gap-6 lg:grid-cols-2">
            {/* 분석 씨앗 작성 */}
            <section className="rounded-2xl border border-white/10 bg-slate-950/40 p-5">
              <h2 className="mb-3 text-lg font-semibold text-white">분석 씨앗 작성 (사기 시도)</h2>
              <div className="space-y-3">
                <select
                  value={seedForm.scam_type}
                  onChange={(e) => setSeedForm((f) => ({ ...f, scam_type: e.target.value }))}
                  className="w-full rounded-lg border border-white/10 bg-slate-900/80 px-3 py-2 text-sm text-slate-100"
                >
                  {(stats?.scam_types ?? []).map((t) => (
                    <option key={t} value={t}>
                      {t}
                      {stats?.starved.includes(t) ? " ⚠️굶음" : ""}
                    </option>
                  ))}
                </select>
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
              <SeedList seeds={partSeeds} onDelete={deleteSeed} />
            </section>

            {/* 분석 증강 */}
            <section className="rounded-2xl border border-white/10 bg-slate-950/40 p-5">
              <h2 className="mb-3 text-lg font-semibold text-white">분석 데이터 증강</h2>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <AugmentBasicFields augForm={augForm} onChange={(patch) => setAugForm((f) => ({ ...f, ...patch }))} />
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
                {augSubmitting ? "시작 중..." : "분석 증강 시작"}
              </button>
              <p className="mt-2 text-xs text-slate-500">
                사기 시도(scam_attempt) 씨앗만 증강 → 분류기·추출기 학습 입력으로 사용.
              </p>
            </section>
          </div>
        </>
      )}

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

function GateBalancePanel({
  title,
  desc,
  counts,
  accent,
}: {
  title: string;
  desc: string;
  counts?: Record<string, number>;
  accent: "slate" | "amber";
}) {
  const labels = ["normal", "scam_attempt", "scam_news_edu"];
  const c = counts ?? {};
  const total = labels.reduce((a, l) => a + (c[l] ?? 0), 0);
  const data = labels.map((l) => ({ type: CONTENT_LABEL_KO[l] ?? l, count: c[l] ?? 0, starved: false }));
  const ratio = (n: number) => (total > 0 ? `${Math.round((n / total) * 1000) / 10}%` : "-");
  const border = accent === "amber" ? "border-amber-300/30 bg-amber-500/5" : "border-white/10 bg-slate-950/40";
  return (
    <div className={`rounded-xl border p-4 ${border}`}>
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold text-white">{title}</h3>
        <span className="shrink-0 font-mono text-xs text-slate-400">합계 {total.toLocaleString("ko-KR")}건</span>
      </div>
      <p className="mt-1 text-xs text-slate-500">{desc}</p>
      <div className="mt-3">
        <CoverageBar data={data} />
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2 text-center text-xs">
        {labels.map((l) => (
          <div key={l} className="rounded-lg border border-white/10 bg-black/20 px-2 py-1.5">
            <div className="text-slate-400">{CONTENT_LABEL_KO[l] ?? l}</div>
            <div className="mt-0.5 font-mono text-sm text-slate-100">{(c[l] ?? 0).toLocaleString("ko-KR")}</div>
            <div className="font-mono text-[11px] text-slate-500">{ratio(c[l] ?? 0)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AugmentBasicFields({
  augForm,
  onChange,
}: {
  augForm: AugForm;
  onChange: (patch: Partial<AugForm>) => void;
}) {
  return (
    <>
      <label className="space-y-1">
        <span className="text-xs text-slate-400">변형 수 (씨앗당)</span>
        <input
          type="number"
          min={1}
          value={augForm.variants}
          onChange={(e) => onChange({ variants: Number(e.target.value) })}
          className="w-full rounded-lg border border-white/10 bg-slate-900/80 px-3 py-2 text-slate-100"
        />
      </label>
      <label className="space-y-1">
        <span className="text-xs text-slate-400">라운드</span>
        <input
          type="number"
          min={1}
          value={augForm.rounds}
          onChange={(e) => onChange({ rounds: Number(e.target.value) })}
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
          onChange={(e) => onChange({ concurrency: Number(e.target.value) })}
          className="w-full rounded-lg border border-white/10 bg-slate-900/80 px-3 py-2 text-slate-100"
        />
      </label>
      <label className="space-y-1">
        <span className="text-xs text-slate-400">씨앗 한도 (0=전체)</span>
        <input
          type="number"
          min={0}
          value={augForm.limit}
          onChange={(e) => onChange({ limit: Number(e.target.value) })}
          className="w-full rounded-lg border border-white/10 bg-slate-900/80 px-3 py-2 text-slate-100"
        />
      </label>
    </>
  );
}

function SeedList({ seeds, onDelete }: { seeds: Seed[]; onDelete: (idx: number) => void }) {
  return (
    <div className="mt-4 max-h-56 space-y-1 overflow-auto">
      {seeds.length === 0 && <p className="text-xs text-slate-500">작성된 씨앗 없음</p>}
      {seeds.map((s) => (
        <div key={s.idx} className="flex items-start gap-2 rounded-lg border border-white/5 bg-white/5 px-3 py-2 text-xs">
          <span className="shrink-0 rounded bg-cyan-500/10 px-1.5 py-0.5 text-cyan-200">
            {s.scam_type || (CONTENT_LABEL_KO[s.content_label] ?? s.content_label)}
          </span>
          <span className="flex-1 text-slate-300">{s.text}</span>
          <button onClick={() => onDelete(s.idx)} className="shrink-0 text-rose-300 hover:text-rose-200">
            삭제
          </button>
        </div>
      ))}
    </div>
  );
}
