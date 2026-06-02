"use client";

import { useEffect, useMemo, useState } from "react";

type SessionInfo = {
  session_id: string;
  model: "classifier" | "gliner";
  status: string;
  started_at: number;
  ended_at?: number | null;
  output_dir?: string;
  params?: Record<string, unknown>;
  last_metrics?: Record<string, unknown> | null;
};

type SessionsResponse = {
  sessions: SessionInfo[];
  active_models: Record<string, string>;
};

const badgeClass: Record<string, string> = {
  completed: "border-emerald-400/30 bg-emerald-500/10 text-emerald-200",
  running: "border-cyan-400/30 bg-cyan-500/10 text-cyan-200",
  failed: "border-rose-400/30 bg-rose-500/10 text-rose-200",
  cancelled: "border-slate-400/30 bg-slate-500/10 text-slate-200",
};

function fmtTime(value?: number | null) {
  if (!value) return "-";
  return new Date(value * 1000).toLocaleString("ko-KR");
}

export default function ModelsClient() {
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [activeModels, setActiveModels] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState("");
  const [error, setError] = useState("");

  async function refresh() {
    setError("");
    const response = await fetch("/api/admin/training/sessions?limit=100", { cache: "no-store" });
    const data = (await response.json()) as SessionsResponse;
    if (!response.ok) throw new Error((data as unknown as { detail?: string }).detail ?? "모델 목록 로드 실패");
    setSessions(data.sessions ?? []);
    setActiveModels(data.active_models ?? {});
  }

  useEffect(() => {
    let cancelled = false;
    async function run() {
      try {
        await refresh();
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "모델 목록 로드 실패");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    void run();
    return () => {
      cancelled = true;
    };
  }, []);

  const completed = useMemo(
    () => sessions.filter((session) => session.status === "completed"),
    [sessions],
  );
  const classifiers = completed.filter((session) => session.model === "classifier");
  const gliners = completed.filter((session) => session.model === "gliner");

  async function activate(sessionId: string) {
    setBusyId(sessionId);
    setError("");
    try {
      const response = await fetch(`/api/admin/training/sessions/${sessionId}/activate`, { method: "POST" });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "모델 적용 실패");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "모델 적용 실패");
    } finally {
      setBusyId("");
    }
  }

  return (
    <div className="space-y-5">
      {error && (
        <div className="rounded-xl border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
          {error}
        </div>
      )}

      <section className="grid gap-3 md:grid-cols-2">
        {(["classifier", "gliner"] as const).map((model) => (
          <div key={model} className="rounded-2xl border border-white/10 bg-white/5 p-5">
            <div className="text-xs uppercase tracking-widest text-slate-400">Active {model}</div>
            <div className="mt-2 break-all font-mono text-sm text-white">
              {activeModels[model] || "base model"}
            </div>
          </div>
        ))}
      </section>

      <ModelSection
        title="Classifier Models"
        sessions={classifiers}
        activePath={activeModels.classifier}
        busyId={busyId}
        onActivate={activate}
      />
      <ModelSection
        title="GLiNER Models"
        sessions={gliners}
        activePath={activeModels.gliner}
        busyId={busyId}
        onActivate={activate}
      />

      {loading && (
        <div className="rounded-2xl border border-white/10 bg-white/5 p-6 text-sm text-slate-400">
          모델 목록을 불러오는 중...
        </div>
      )}
    </div>
  );
}

function ModelSection({
  title,
  sessions,
  activePath,
  busyId,
  onActivate,
}: {
  title: string;
  sessions: SessionInfo[];
  activePath?: string;
  busyId: string;
  onActivate: (sessionId: string) => Promise<void>;
}) {
  return (
    <section className="rounded-2xl border border-white/10 bg-white/5 p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-lg font-semibold text-white">{title}</h2>
        <span className="text-xs text-slate-500">{sessions.length} completed</span>
      </div>

      <div className="mt-4 grid gap-3">
        {sessions.length === 0 && <div className="text-sm text-slate-500">완료된 모델 세션이 없습니다.</div>}
        {sessions.map((session) => {
          const isActive = Boolean(activePath && session.output_dir === activePath);
          return (
            <div
              key={session.session_id}
              className="grid gap-3 rounded-xl border border-white/10 bg-slate-950/50 p-4 md:grid-cols-[1fr_auto]"
            >
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm text-white">{session.session_id}</span>
                  <span className={`rounded-full border px-2 py-0.5 text-xs ${badgeClass[session.status] ?? badgeClass.completed}`}>
                    {isActive ? "active" : session.status}
                  </span>
                </div>
                <div className="mt-2 break-all font-mono text-xs text-slate-500">{session.output_dir}</div>
                <div className="mt-2 text-xs text-slate-400">
                  started {fmtTime(session.started_at)} · ended {fmtTime(session.ended_at)}
                </div>
              </div>
              <button
                onClick={() => void onActivate(session.session_id)}
                disabled={isActive || busyId === session.session_id}
                className="h-10 rounded-xl bg-emerald-300 px-4 text-sm font-semibold text-slate-950 transition hover:bg-emerald-200 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {isActive ? "적용됨" : busyId === session.session_id ? "적용 중..." : "파이프라인 적용"}
              </button>
            </div>
          );
        })}
      </div>
    </section>
  );
}
