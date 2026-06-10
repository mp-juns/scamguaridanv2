"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import dynamic from "next/dynamic";

import {
  ClassifierComparisonPanel,
  GateMetricsPanel,
  GateRoleCard,
  LearningStep,
  LossSpikePanel,
  MiniMetric,
  PlainMetric,
  Stat,
} from "./panels";
import {
  STATUS_BADGE,
  attemptName,
  fmtDuration,
  fmtSeconds,
  metricValue,
  pct,
  type ComparisonResult,
  type DataStats,
  type GateMetrics,
  type SessionDetail,
  type SessionInfo,
  type SessionsResponse,
  type StartTrainingResponse,
  type SyntheticSummary,
} from "./trainingShared";

// recharts 는 무거운 클라이언트 청크 → lazy-load (초기 admin 진입 JS 에서 제외)
const SyntheticLabelBar = dynamic(
  () => import("../charts").then((m) => m.SyntheticLabelBar),
  { ssr: false },
);
const AttemptLine = dynamic(
  () => import("../charts").then((m) => m.AttemptLine),
  { ssr: false },
);
const GlinerLabelBar = dynamic(
  () => import("../charts").then((m) => m.GlinerLabelBar),
  { ssr: false },
);
const TrainingMetricsChart = dynamic(
  () => import("../charts").then((m) => m.TrainingMetricsChart),
  { ssr: false },
);
// canvas 지식그래프 — client 전용이라 ssr:false 가 의미상으로도 맞음
const KnowledgeGraphCanvas = dynamic(() => import("./KnowledgeGraphCanvas"), { ssr: false });

export default function TrainingClient() {
  const [stats, setStats] = useState<DataStats | null>(null);
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [activeModels, setActiveModels] = useState<Record<string, string>>({});
  const [synthetic, setSynthetic] = useState<SyntheticSummary | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<SessionDetail | null>(null);
  const [comparison, setComparison] = useState<ComparisonResult | null>(null);
  const [comparing, setComparing] = useState(false);
  const [error, setError] = useState("");
  const logRef = useRef<HTMLPreElement | null>(null);

  const [form, setForm] = useState({
    models: ["classifier", "gliner"] as Array<"classifier" | "gliner">,
    epochs: 3,
    batch_size: 8,
    lora: true,
    extra_jsonl: "",
    early_stopping_patience: 2,
  });
  const [submitting, setSubmitting] = useState(false);

  // 게이트(content_label 3-class) 학습 폼 — 평가 전용, classifier/gliner 와 분리.
  const [gateForm, setGateForm] = useState({
    epochs: 10,
    val_ratio: 0.1,
    input: "data/generated/user_samples_augmented.jsonl",
  });
  const [gateSubmitting, setGateSubmitting] = useState(false);

  const refreshList = useCallback(async () => {
    try {
      const [s1, s2, s3] = await Promise.all([
        fetch("/api/admin/training/data-stats", { cache: "no-store" }),
        fetch("/api/admin/training/sessions", { cache: "no-store" }),
        fetch("/api/admin/training/synthetic-summary", { cache: "no-store" }),
      ]);
      if (s1.ok) setStats(await s1.json());
      if (s3.ok) setSynthetic((await s3.json()) as SyntheticSummary);
      if (s2.ok) {
        const data = (await s2.json()) as SessionsResponse;
        setSessions(data.sessions);
        setActiveModels(data.active_models ?? {});
        if (!selectedId && data.sessions[0]) {
          setSelectedId(data.sessions[0].session_id);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "목록 로드 실패");
    }
  }, [selectedId]);

  const fetchSessionDetail = useCallback(async (sessionId: string) => {
    const r = await fetch(`/api/admin/training/sessions/${sessionId}`, { cache: "no-store" });
    if (!r.ok) return null;
    return (await r.json()) as SessionDetail;
  }, []);

  const refreshDetail = useCallback(async () => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    try {
      setDetail(await fetchSessionDetail(selectedId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "상세 로드 실패");
    }
  }, [fetchSessionDetail, selectedId]);

  useEffect(() => {
    void refreshList();
  }, [refreshList]);

  useEffect(() => {
    void refreshDetail();
    setComparison(null);
  }, [refreshDetail]);

  useEffect(() => {
    if (!synthetic?.dataset.path || form.extra_jsonl.trim()) return;
    setForm((prev) => ({ ...prev, extra_jsonl: synthetic.dataset.path }));
  }, [synthetic?.dataset.path, form.extra_jsonl]);

  useEffect(() => {
    const el = logRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [detail?.log_tail]);

  // 진행 중 세션이 있으면 5초마다 폴링
  useEffect(() => {
    const hasRunning = sessions.some((s) => s.status === "running");
    if (!hasRunning && detail?.session.status !== "running") return;
    const id = setInterval(() => {
      void refreshList();
      void refreshDetail();
    }, 5000);
    return () => clearInterval(id);
  }, [sessions, detail, refreshList, refreshDetail]);

  async function startSession() {
    setSubmitting(true);
    setError("");
    try {
      if (form.models.length === 0) {
        throw new Error("학습할 모델을 하나 이상 선택해주세요.");
      }
      const r = await fetch("/api/admin/training/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: form.models[0],
          models: form.models,
          epochs: form.epochs,
          batch_size: form.batch_size,
          lora: form.lora && form.models.includes("classifier"),
          extra_jsonl: form.extra_jsonl.trim() || null,
          early_stopping_patience: form.early_stopping_patience,
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail ?? "세션 시작 실패");
      const started = data as StartTrainingResponse;
      const firstSessionId = "sessions" in started ? started.sessions[0]?.session_id : started.session_id;
      if (!firstSessionId) throw new Error("시작된 세션 정보를 찾지 못했습니다.");
      setSelectedId(firstSessionId);
      const startedDetail = await fetchSessionDetail(firstSessionId);
      if (startedDetail) setDetail(startedDetail);
      await refreshList();
    } catch (err) {
      setError(err instanceof Error ? err.message : "세션 시작 실패");
    } finally {
      setSubmitting(false);
    }
  }

  async function startGateSession() {
    setGateSubmitting(true);
    setError("");
    try {
      const r = await fetch("/api/admin/training/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          model: "gate",
          epochs: gateForm.epochs,
          val_ratio: gateForm.val_ratio,
          extra_jsonl: gateForm.input.trim() || null,
        }),
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail ?? "게이트 세션 시작 실패");
      const started = data as StartTrainingResponse;
      const firstSessionId = "sessions" in started ? started.sessions[0]?.session_id : started.session_id;
      if (firstSessionId) {
        setSelectedId(firstSessionId);
        const startedDetail = await fetchSessionDetail(firstSessionId);
        if (startedDetail) setDetail(startedDetail);
      }
      await refreshList();
    } catch (err) {
      setError(err instanceof Error ? err.message : "게이트 세션 시작 실패");
    } finally {
      setGateSubmitting(false);
    }
  }

  async function cancelSession(id: string) {
    if (!confirm("이 세션을 취소할까요?")) return;
    const r = await fetch(`/api/admin/training/sessions/${id}/cancel`, { method: "POST" });
    if (!r.ok) {
      const data = await r.json().catch(() => ({}));
      setError(data.detail ?? "취소 실패");
    }
    await refreshList();
    await refreshDetail();
  }

  async function activateSession(id: string) {
    if (!confirm("이 세션의 모델을 파이프라인에 적용할까요?")) return;
    const r = await fetch(`/api/admin/training/sessions/${id}/activate`, { method: "POST" });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) {
      setError(data.detail ?? "활성화 실패");
      return;
    }
    await refreshList();
  }

  async function runComparison(id: string) {
    setComparing(true);
    setError("");
    try {
      const r = await fetch(`/api/admin/training/sessions/${id}/compare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: "{}",
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail ?? "비교 실행 실패");
      setComparison(data as ComparisonResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : "비교 실행 실패");
    } finally {
      setComparing(false);
    }
  }

  const chartData = useMemo(() => {
    if (!detail) return [];
    return detail.metrics
      .filter((m) => typeof m.step === "number" || m.model === "gliner" || typeof m.gliner_progress === "number")
      .map((m, index) => ({
        step: typeof m.step === "number" ? m.step : index,
        loss: typeof m.loss === "number" ? m.loss : null,
        eval_loss: typeof m.eval_loss === "number" ? m.eval_loss : null,
        eval_macro_f1: typeof m.eval_macro_f1 === "number" ? m.eval_macro_f1 : null,
        eval_accuracy: typeof m.eval_accuracy === "number" ? m.eval_accuracy : null,
        gliner_progress: typeof m.gliner_progress === "number" ? m.gliner_progress : null,
        gliner_train_size: typeof m.train_size === "number" ? m.train_size : null,
        gliner_val_size: typeof m.val_size === "number" ? m.val_size : null,
        gliner_label_count: typeof m.label_count === "number" ? m.label_count : null,
      }));
  }, [detail]);

  const syntheticLabelBars = useMemo(() => {
    if (!synthetic) return [];
    return Object.entries(synthetic.dataset.labels)
      .map(([label, count]) => ({ label, count }))
      .sort((a, b) => b.count - a.count);
  }, [synthetic]);

  const attemptBars = useMemo(() => {
    if (!synthetic) return [];
    return synthetic.attempts
      .slice()
      .reverse()
      .map((a) => ({
        name: attemptName(a.session_id),
        f1: typeof a.final_eval.eval_macro_f1 === "number" ? a.final_eval.eval_macro_f1 : 0,
        accuracy: typeof a.final_eval.eval_accuracy === "number" ? a.final_eval.eval_accuracy : 0,
      }));
  }, [synthetic]);

  const glinerLabelBars = useMemo(() => {
    if (!stats?.gliner.labels) return [];
    return Object.entries(stats.gliner.labels)
      .map(([label, count]) => ({ label, count }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 24);
  }, [stats]);

  const selectedSession = detail?.session ?? sessions.find((session) => session.session_id === selectedId) ?? null;
  const lastMetric = detail?.metrics.at(-1) ?? selectedSession?.last_metrics ?? null;
  const hasClassifierChart = chartData.some((row) =>
    row.loss !== null || row.eval_loss !== null || row.eval_macro_f1 !== null || row.eval_accuracy !== null,
  );
  const hasGlinerChart = chartData.some((row) => row.gliner_progress !== null);
  const lossSpikes = detail?.loss_spikes ?? [];
  const isGateSession = selectedSession?.kind === "gate";
  const gateMetrics: GateMetrics | null = isGateSession
    ? ((selectedSession?.last_metrics ?? null) as GateMetrics | null)
    : null;
  const trainsClassifier = form.models.includes("classifier");
  const trainsGliner = form.models.includes("gliner");
  const toggleTrainingModel = (model: "classifier" | "gliner", checked: boolean) => {
    setForm((prev) => {
      const next = checked
        ? Array.from(new Set([...prev.models, model]))
        : prev.models.filter((item) => item !== model);
      return { ...prev, models: next };
    });
  };

  return (
    <div className="space-y-6">
      {error && (
        <div className="rounded-2xl border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
          {error}
        </div>
      )}

      {synthetic && (
        <section className="overflow-hidden rounded-2xl border border-cyan-400/20 bg-slate-950/50">
          <div className="grid gap-0 lg:grid-cols-[1.05fr_0.95fr]">
            <div className="border-b border-white/10 p-5 lg:border-b-0 lg:border-r">
              <div className="text-xs uppercase tracking-widest text-cyan-200">이번 합성 데이터 학습 한눈에 보기</div>
              <h2 className="mt-2 text-2xl font-semibold text-white">
                {synthetic.status.headline}
              </h2>
              <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-300">
                이 화면은 모델 학습을 시험공부처럼 보여줍니다. 자료를 얼마나 봤는지, 몇 번 연습했는지,
                연습 문제에서는 얼마나 맞혔는지, 그리고 실제 투입 전 왜 한 번 더 검사가 필요한지를 순서대로 보여줍니다.
              </p>
              <div className="mt-5 grid gap-3 sm:grid-cols-3">
                <PlainMetric label="공부한 문장" value={`${synthetic.dataset.total.toLocaleString("ko-KR")}건`} help="12가지 사기 유형을 고르게 넣었습니다" />
                <PlainMetric label="유형 수" value={`${synthetic.dataset.label_count}개`} help="투자, 기관 사칭, 스미싱 등" />
                <PlainMetric
                  label="최고 연습 점수"
                  value={pct(synthetic.best_attempt?.final_eval.eval_macro_f1)}
                  help="모든 유형을 골고루 맞혔는지 보는 값"
                />
              </div>
              <div className="mt-4 rounded-xl border border-amber-400/20 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
                <div className="font-semibold">아직 자동 적용을 보류한 이유</div>
                <p className="mt-1 text-amber-100/80">{synthetic.status.reason}</p>
                <p className="mt-2 text-xs text-amber-100/70">다음 단계: {synthetic.status.next_step}</p>
              </div>
            </div>

            <div className="p-5">
              <div className="grid gap-3">
                <LearningStep
                  index="1"
                  title="데이터 준비"
                  body={`${synthetic.dataset.min_per_label}~${synthetic.dataset.max_per_label}건 사이로 유형별 개수가 거의 균형입니다.`}
                  tone="cyan"
                />
                <LearningStep
                  index="2"
                  title="학습 안정화"
                  body="처음에는 저장 방식과 학습률 때문에 흔들렸고, classifier head 저장 + 낮은 학습률로 안정화했습니다."
                  tone="emerald"
                />
                <LearningStep
                  index="3"
                  title="적용 전 검문"
                  body="연습 문제 점수만 믿지 않고, 실제 문장과 닮은 hard smoke set을 통과한 뒤 적용합니다."
                  tone="amber"
                />
              </div>
            </div>
          </div>

          {synthetic.graph && (
            <div className="border-t border-white/10 p-5">
              <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-white">데이터 연결망</h3>
                  <p className="text-xs text-slate-400">
                    유형, 시나리오, 사례, 검출 신호가 어떤 학습 재료로 묶이는지 보여줍니다.
                  </p>
                </div>
                <div className="font-mono text-xs text-slate-500">
                  {synthetic.graph.nodes.length.toLocaleString("ko-KR")} nodes ·{" "}
                  {synthetic.graph.links.length.toLocaleString("ko-KR")} links
                </div>
              </div>
              <KnowledgeGraphCanvas graph={synthetic.graph} />
            </div>
          )}

          <div className="grid gap-0 border-t border-white/10 lg:grid-cols-2">
            <div className="p-5">
              <div className="mb-3">
                <h3 className="text-sm font-semibold text-white">데이터 균형</h3>
                <p className="text-xs text-slate-400">막대 길이가 비슷할수록 모델이 특정 유형만 편애할 가능성이 줄어듭니다.</p>
              </div>
              <SyntheticLabelBar data={syntheticLabelBars} />
            </div>

            <div className="border-t border-white/10 p-5 lg:border-l lg:border-t-0">
              <div className="mb-3">
                <h3 className="text-sm font-semibold text-white">학습 시도별 개선</h3>
                <p className="text-xs text-slate-400">초록선은 골고루 맞힌 정도, 보라선은 전체 정답률입니다.</p>
              </div>
              <AttemptLine data={attemptBars} />
            </div>
          </div>
        </section>
      )}

      {/* 데이터 현황 + 활성 모델 */}
      <section className="grid gap-4 lg:grid-cols-3">
        <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
          <div className="text-xs uppercase tracking-widest text-slate-400">현재 학습 후보 전체</div>
          <div className="mt-2 text-3xl font-bold">
            {(synthetic?.dataset.total ?? stats?.classifier.total)?.toLocaleString("ko-KR") ?? "-"}
            <span className="ml-2 text-base font-normal text-slate-400">건</span>
          </div>
          <div className="mt-1 text-xs text-slate-500">
            기본 검수 라벨 {stats?.classifier.total ?? 0}건
            {synthetic ? ` + synthetic ${synthetic.dataset.path}` : ""}
          </div>
          {(synthetic || stats) && (
            <div className="mt-3 max-h-32 space-y-1 overflow-auto pr-2 text-xs text-slate-300">
              {Object.entries(synthetic?.dataset.labels ?? stats?.classifier.labels ?? {}).map(([label, n]) => (
                <div key={label} className="flex justify-between">
                  <span>{label}</span>
                  <span className="font-mono">{n}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
          <div className="text-xs uppercase tracking-widest text-slate-400">GLiNER 학습 데이터</div>
          <div className="mt-2 text-3xl font-bold">
            {stats?.gliner.total ?? "-"}
            <span className="ml-2 text-base font-normal text-slate-400">문서</span>
          </div>
          <div className="mt-2 space-y-1 text-sm text-slate-400">
            <div>엔티티 합계 {(stats?.gliner.total_entities ?? 0).toLocaleString("ko-KR")}개</div>
            <div>라벨 {stats?.gliner.label_count ?? 0}종</div>
            {stats?.gliner.extra_jsonl && (
              <div className="truncate font-mono text-xs text-slate-500">{stats.gliner.extra_jsonl}</div>
            )}
          </div>
        </div>

        <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
          <div className="text-xs uppercase tracking-widest text-slate-400">활성 모델</div>
          <div className="mt-3 space-y-2 text-sm">
            {(["classifier", "gliner"] as const).map((m) => (
              <div key={m} className="flex items-center justify-between">
                <span className="text-slate-300">{m}</span>
                <span className="truncate font-mono text-xs text-slate-400">
                  {activeModels[m] ?? "default"}
                </span>
              </div>
            ))}
          </div>
        </div>
      </section>

      {glinerLabelBars.length > 0 && (
        <section className="rounded-2xl border border-sky-400/20 bg-white/5 p-5">
          <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
            <div>
              <div className="text-xs uppercase tracking-widest text-sky-200">GLiNER Entity Distribution</div>
              <h2 className="mt-1 text-lg font-semibold text-white">추출기 라벨 분포</h2>
              <p className="mt-1 text-sm text-slate-400">
                추출기는 scam_type 균형보다 entity label 균형이 중요합니다. 상위 라벨 쏠림과 long-tail을 확인합니다.
              </p>
            </div>
            <div className="text-right font-mono text-xs text-slate-500">
              {stats?.gliner.label_count ?? 0} labels · {(stats?.gliner.total_entities ?? 0).toLocaleString("ko-KR")} entities
            </div>
          </div>
          <GlinerLabelBar data={glinerLabelBars} />
        </section>
      )}

      {/* 세션 시작 폼 */}
      <section className="rounded-2xl border border-white/10 bg-white/5 p-6">
        <h2 className="mb-4 text-lg font-semibold">새 학습 세션</h2>
        <div className="grid gap-4 md:grid-cols-6">
          <div className="space-y-1 text-sm md:col-span-2">
            <span className="block text-slate-300">학습 대상</span>
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="flex items-center gap-2 rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2">
                <input
                  type="checkbox"
                  checked={trainsClassifier}
                  onChange={(e) => toggleTrainingModel("classifier", e.target.checked)}
                  className="h-4 w-4 accent-cyan-300"
                />
                <span>classifier</span>
              </label>
              <label className="flex items-center gap-2 rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2">
                <input
                  type="checkbox"
                  checked={trainsGliner}
                  onChange={(e) => toggleTrainingModel("gliner", e.target.checked)}
                  className="h-4 w-4 accent-cyan-300"
                />
                <span>GLiNER</span>
              </label>
            </div>
            <p className="text-xs text-slate-500">
              둘 다 선택하면 각각 별도 프로세스로 바로 시작해서 동시에 학습합니다.
            </p>
          </div>
          <label className="space-y-1 text-sm">
            <span className="block text-slate-300">epochs</span>
            <input
              type="number"
              min={1}
              max={20}
              value={form.epochs}
              onChange={(e) => setForm({ ...form, epochs: Number(e.target.value) })}
              className="w-full rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span className="block text-slate-300">batch size</span>
            <input
              type="number"
              min={1}
              max={64}
              value={form.batch_size}
              onChange={(e) => setForm({ ...form, batch_size: Number(e.target.value) })}
              className="w-full rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2"
            />
          </label>
          <label className="flex items-center gap-2 text-sm md:mt-6">
            <input
              type="checkbox"
              checked={form.lora}
              onChange={(e) => setForm({ ...form, lora: e.target.checked })}
              className="h-4 w-4 accent-cyan-300"
              disabled={!trainsClassifier}
            />
            <span>LoRA (classifier 만)</span>
          </label>
          <label className="space-y-1 text-sm">
            <span className="block text-slate-300">early stop</span>
            <input
              type="number"
              min={0}
              max={10}
              value={form.early_stopping_patience}
              onChange={(e) => setForm({ ...form, early_stopping_patience: Number(e.target.value) })}
              className="w-full rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2"
              disabled={!trainsClassifier}
            />
          </label>
          <label className="space-y-1 text-sm md:col-span-1">
            <span className="block text-slate-300">extra JSONL (선택)</span>
            <input
              type="text"
              placeholder="data/processed/aihub.jsonl"
              value={form.extra_jsonl}
              onChange={(e) => setForm({ ...form, extra_jsonl: e.target.value })}
              className="w-full rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 font-mono text-xs"
            />
          </label>
        </div>
        <div className="mt-4 flex justify-end">
          <button
            onClick={() => void startSession()}
            disabled={submitting || form.models.length === 0}
            className="rounded-xl bg-cyan-300 px-5 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {submitting ? "시작 중..." : form.models.length > 1 ? "순차 학습 시작" : "학습 시작"}
          </button>
        </div>

        {(submitting || selectedSession) && (
          <div className="mt-5 overflow-hidden rounded-xl border border-cyan-400/20 bg-slate-950/60">
            <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 px-4 py-3">
              <div>
                <div className="text-xs uppercase tracking-widest text-cyan-200">Live Training Console</div>
                <div className="mt-1 text-sm font-semibold text-white">
                  {submitting
                    ? "세션을 만들고 있습니다"
                    : `${selectedSession?.model ?? "training"} · ${selectedSession?.session_id ?? ""}`}
                </div>
              </div>
              <span
                className={`rounded-full border px-2.5 py-1 text-xs ${
                  selectedSession
                    ? STATUS_BADGE[selectedSession.status] ?? STATUS_BADGE.cancelled
                    : "border-cyan-400/30 bg-cyan-500/20 text-cyan-200"
                }`}
              >
                {selectedSession?.status ?? "starting"}
              </span>
            </div>

            <div className="grid gap-0 lg:grid-cols-[0.9fr_1.1fr]">
              <div className="border-b border-white/10 p-4 lg:border-b-0 lg:border-r">
                <div className="grid gap-3 sm:grid-cols-2">
                  <Stat label="시작" value={selectedSession ? fmtSeconds(selectedSession.started_at) : "-"} />
                  <Stat
                    label="경과"
                    value={selectedSession ? fmtDuration(selectedSession.started_at, selectedSession.ended_at) : "-"}
                  />
                  <Stat label="PID" value={selectedSession?.pid ? String(selectedSession.pid) : "-"} />
                  <Stat
                    label="마지막 step"
                    value={typeof lastMetric?.step === "number" ? String(lastMetric.step) : "-"}
                  />
                </div>

                <div className="mt-3 rounded-xl border border-white/10 bg-black/20 p-3">
                  <div className="mb-2 text-xs uppercase tracking-widest text-slate-400">실행 설정</div>
                  <div className="space-y-1 break-all font-mono text-xs text-slate-300">
                    <div>model: {selectedSession?.model ?? form.models.join(",")}</div>
                    <div>epochs: {String(selectedSession?.params?.epochs ?? form.epochs)}</div>
                    <div>batch_size: {String(selectedSession?.params?.batch_size ?? form.batch_size)}</div>
                    <div>lora: {String(selectedSession?.params?.lora ?? form.lora)}</div>
                    <div>
                      early_stopping_patience:{" "}
                      {String(selectedSession?.params?.early_stopping_patience ?? form.early_stopping_patience)}
                    </div>
                    <div>extra_jsonl: {String((selectedSession?.params?.extra_jsonl ?? form.extra_jsonl) || "-")}</div>
                    {selectedSession?.output_dir && <div>output: {selectedSession.output_dir}</div>}
                  </div>
                </div>

                {lastMetric && (
                  <div className="mt-3 grid gap-2 sm:grid-cols-2">
                    {selectedSession?.model === "gliner" ? (
                      <>
                        <MiniMetric label="progress" value={pct(lastMetric.gliner_progress)} />
                        <MiniMetric label="train docs" value={metricValue(lastMetric.train_size)} />
                        <MiniMetric label="val docs" value={metricValue(lastMetric.val_size)} />
                        <MiniMetric label="labels" value={metricValue(lastMetric.label_count)} />
                      </>
                    ) : (
                      <>
                        <MiniMetric label="loss" value={metricValue(lastMetric.loss)} />
                        <MiniMetric label="eval loss" value={metricValue(lastMetric.eval_loss)} />
                        <MiniMetric label="macro F1" value={pct(lastMetric.eval_macro_f1)} />
                        <MiniMetric label="accuracy" value={pct(lastMetric.eval_accuracy)} />
                      </>
                    )}
                  </div>
                )}
              </div>

              <div className="p-4">
                <div className="mb-2 flex items-center justify-between">
                  <div className="text-xs uppercase tracking-widest text-slate-400">실시간 로그</div>
                  <div className="text-xs text-slate-500">자동 갱신 · tail 8KB</div>
                </div>
                <pre
                  ref={logRef}
                  className="h-72 overflow-auto whitespace-pre-wrap break-words rounded-xl border border-white/10 bg-black/30 p-3 font-mono text-xs leading-relaxed text-slate-300"
                >
                  {detail?.log_tail || (submitting ? "세션 생성 요청을 보내는 중..." : "아직 출력 없음")}
                </pre>
              </div>
            </div>
          </div>
        )}
      </section>

      {/* 게이트(content_label 3-class) 학습 — 평가 전용 */}
      <section className="rounded-2xl border border-amber-300/25 bg-amber-500/5 p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-xs uppercase tracking-widest text-amber-200">Gate · content_label 3-class</div>
            <h2 className="mt-1 text-lg font-semibold text-white">게이트 학습 (평가 전용)</h2>
            <p className="mt-1 max-w-3xl text-sm leading-relaxed text-slate-300">
              파이프라인 맨 앞단에서 메시지를 <b>정상 / 사기 시도 / 사기 예방·뉴스</b> 3-class 로 거르는 게이트입니다.
              hard negative(정상 안내문) 추가가 오탐(정상→사기)을 얼마나 줄이는지 측정하는 용도라, 학습은 하되
              파이프라인에는 <b>적용하지 않습니다</b>(평가 전용).
            </p>
          </div>
        </div>

        <div className="mt-4 grid gap-3 rounded-xl border border-white/10 bg-slate-950/40 p-4 sm:grid-cols-3">
          <GateRoleCard
            tone="amber"
            title="게이트 (이 카드)"
            io="입력: 모든 메시지 · 출력: content_label 3종"
            note="문지기 — 사기 시도만 다음 단계로 통과. 정상/예방 콘텐츠 오탐 차단."
          />
          <GateRoleCard
            tone="cyan"
            title="분류기 (classifier)"
            io="입력: 사기 시도 · 출력: scam_type 12종"
            note="게이트를 통과한 메시지가 어떤 사기 유형인지 판별. 파이프라인 Stage 2."
          />
          <GateRoleCard
            tone="violet"
            title="추출기 (GLiNER)"
            io="입력: 사기 메시지 · 출력: entity 27종"
            note="금액·기관·URL 등 사기 단서 span 추출. 파이프라인 Stage 3."
          />
        </div>

        <div className="mt-4 grid gap-4 md:grid-cols-6">
          <label className="space-y-1 text-sm md:col-span-3">
            <span className="block text-slate-300">평가 입력 JSONL</span>
            <input
              type="text"
              value={gateForm.input}
              onChange={(e) => setGateForm({ ...gateForm, input: e.target.value })}
              className="w-full rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 font-mono text-xs"
            />
            <p className="text-xs text-slate-500">
              증강 페이지에서 게이트 클래스(normal 등)를 늘린 뒤 promote 한 파일을 지정하면 됩니다.
            </p>
          </label>
          <label className="space-y-1 text-sm">
            <span className="block text-slate-300">epochs</span>
            <input
              type="number"
              min={1}
              max={30}
              value={gateForm.epochs}
              onChange={(e) => setGateForm({ ...gateForm, epochs: Number(e.target.value) })}
              className="w-full rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2"
            />
          </label>
          <label className="space-y-1 text-sm">
            <span className="block text-slate-300">val ratio</span>
            <input
              type="number"
              min={0.05}
              max={0.5}
              step={0.05}
              value={gateForm.val_ratio}
              onChange={(e) => setGateForm({ ...gateForm, val_ratio: Number(e.target.value) })}
              className="w-full rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2"
            />
          </label>
          <div className="flex items-end md:col-span-1">
            <button
              onClick={() => void startGateSession()}
              disabled={gateSubmitting}
              className="w-full rounded-xl bg-amber-300 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-amber-200 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {gateSubmitting ? "시작 중..." : "게이트 학습 시작"}
            </button>
          </div>
        </div>
      </section>

      <section className="flex flex-wrap items-center justify-between gap-4 rounded-2xl border border-violet-300/20 bg-white/5 p-5">
        <div>
          <div className="text-xs uppercase tracking-widest text-violet-200">모델 비교 분석</div>
          <h2 className="mt-1 text-lg font-semibold text-white">별도 세션에서 비교하기</h2>
          <p className="mt-1 text-sm text-slate-400">
            입력 하나를 기존 분석, Claude 분석, fine-tuned 모델 관점으로 비교합니다.
          </p>
        </div>
        <Link
          href="/admin/training/compare"
          className="rounded-xl bg-violet-300 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-violet-200"
        >
          비교 페이지 열기
        </Link>
      </section>

      {/* 세션 목록 + 상세 */}
      <section className="grid gap-6 lg:grid-cols-[260px_1fr]">
        <div className="rounded-2xl border border-white/10 bg-white/5 p-3">
          <div className="mb-2 px-2 text-xs uppercase tracking-widest text-slate-400">세션 ({sessions.length})</div>
          <div className="max-h-[600px] space-y-1 overflow-y-auto pr-1">
            {sessions.length === 0 && (
              <div className="px-2 py-4 text-sm text-slate-500">아직 세션이 없습니다.</div>
            )}
            {sessions.map((s) => (
              <button
                key={s.session_id}
                onClick={() => setSelectedId(s.session_id)}
                className={`w-full rounded-xl border px-3 py-2 text-left transition ${
                  selectedId === s.session_id
                    ? "border-cyan-400/40 bg-cyan-500/10"
                    : "border-transparent hover:bg-white/5"
                }`}
              >
                <div className="flex items-center justify-between text-xs">
                  <span className="font-mono text-slate-400">{s.session_id.slice(0, 8)}</span>
                  <span className={`rounded-full border px-2 py-0.5 ${STATUS_BADGE[s.status] ?? ""}`}>
                    {s.status}
                  </span>
                </div>
                <div className="mt-1 flex items-center gap-1.5 text-sm text-slate-200">
                  <span>{s.model}</span>
                  {s.kind === "gate" && (
                    <span className="rounded-full border border-amber-400/30 bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-200">
                      평가
                    </span>
                  )}
                </div>
                <div className="mt-0.5 text-xs text-slate-500">
                  {fmtSeconds(s.started_at)} · {fmtDuration(s.started_at, s.ended_at)}
                </div>
              </button>
            ))}
          </div>
        </div>

        <div className="rounded-2xl border border-white/10 bg-white/5 p-6">
          {detail ? (
            <div className="space-y-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <div className="font-mono text-xs text-slate-400">{detail.session.session_id}</div>
                  <div className="text-xl font-semibold">{detail.session.model}</div>
                </div>
                <div className="flex gap-2">
                  {detail.session.status === "running" && (
                    <button
                      onClick={() => void cancelSession(detail.session.session_id)}
                      className="rounded-xl border border-rose-400/40 bg-rose-500/10 px-4 py-2 text-sm font-semibold text-rose-200 hover:bg-rose-500/20"
                    >
                      취소
                    </button>
                  )}
                  {detail.session.status === "completed" && detail.session.kind === "gate" && (
                    <span className="rounded-xl border border-amber-400/30 bg-amber-500/15 px-4 py-2 text-sm font-semibold text-amber-200">
                      게이트 · 평가 전용 (적용 불가)
                    </span>
                  )}
                  {detail.session.status === "completed" && detail.session.kind !== "gate" && (
                    <button
                      onClick={() => void activateSession(detail.session.session_id)}
                      className="rounded-xl bg-emerald-300 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-emerald-200"
                    >
                      파이프라인 적용
                    </button>
                  )}
                  {detail.session.status === "completed" && detail.session.model === "classifier" && (
                    <button
                      onClick={() => void runComparison(detail.session.session_id)}
                      disabled={comparing}
                      className="rounded-xl border border-violet-300/40 bg-violet-500/10 px-4 py-2 text-sm font-semibold text-violet-100 hover:bg-violet-500/20 disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {comparing ? "비교 중..." : "Raw와 비교"}
                    </button>
                  )}
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-3 text-sm">
                <Stat label="상태" value={detail.session.status} />
                <Stat label="시작" value={fmtSeconds(detail.session.started_at)} />
                <Stat label="경과" value={fmtDuration(detail.session.started_at, detail.session.ended_at)} />
              </div>

              {detail.session.kind === "gate" && gateMetrics && (
                <GateMetricsPanel metrics={gateMetrics} />
              )}

              {chartData.length > 0 && (
                <div className="rounded-xl border border-white/10 bg-slate-950/40 p-3">
                  <div className="mb-2 text-xs uppercase tracking-widest text-slate-400">메트릭 그래프</div>
                  <TrainingMetricsChart
                    data={chartData}
                    hasClassifierChart={hasClassifierChart}
                    hasGlinerChart={hasGlinerChart}
                  />
                  {hasGlinerChart && (
                    <div className="mt-2 text-xs text-slate-500">
                      GLiNER 0.2.x 환경에서 trainer API 가 없으면 train/val JSON 준비 완료까지의 진행값을 표시합니다.
                    </div>
                  )}
                </div>
              )}

              {lossSpikes.length > 0 && (
                <LossSpikePanel spikes={lossSpikes} />
              )}

              {comparison && (
                <ClassifierComparisonPanel comparison={comparison} />
              )}

              <div className="rounded-xl border border-white/10 bg-slate-950/60 p-3">
                <div className="mb-2 text-xs uppercase tracking-widest text-slate-400">로그 (tail 8KB)</div>
                <pre className="max-h-72 overflow-auto whitespace-pre-wrap break-words font-mono text-xs text-slate-300">
                  {detail.log_tail || "(아직 출력 없음)"}
                </pre>
              </div>

              <details className="rounded-xl border border-white/10 bg-slate-950/40 p-3 text-sm">
                <summary className="cursor-pointer text-slate-300">파라미터 / raw status</summary>
                <pre className="mt-2 overflow-auto text-xs text-slate-400">
                  {JSON.stringify(detail.session, null, 2)}
                </pre>
              </details>
            </div>
          ) : (
            <div className="py-10 text-center text-sm text-slate-500">
              왼쪽에서 세션을 선택하세요.
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
