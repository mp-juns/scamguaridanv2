"use client";

import { useEffect, useMemo, useState } from "react";

type CompareScore = {
  label: string;
  score: number;
};

type CompareEntity = {
  text?: string;
  label?: string;
  score?: number;
  reason?: string;
  confidence?: number;
  source?: string;
};

type CompareSignal = {
  flag?: string;
  flag_description?: string;
  reason?: string;
  evidence?: string;
  evidence_snippets?: string[];
  confidence?: number;
  entity_text?: string;
  entity_label?: string;
};

type ModelCompareResult = {
  session_id: string;
  classifier_session_id?: string;
  gliner_session_id?: string | null;
  output_dir: string;
  classifier_output_dir?: string;
  gliner_output_dir?: string;
  compare_scope: "both" | "classifier" | "extractor";
  input: {
    source: string;
    transcript_text: string;
    source_type: string;
    metadata: Record<string, unknown>;
  };
  existing: {
    label: string;
    method: string;
    scam_type: string;
    confidence: number;
    is_uncertain: boolean;
    top_scores: CompareScore[];
    entities: CompareEntity[];
    signals: CompareSignal[];
    signal_candidates: CompareSignal[];
  };
  claude: {
    label: string;
    method: string;
    scam_type: string;
    confidence: number | null;
    summary: string;
    reasoning: string[];
    suggested_flags: { flag: string; reason: string; evidence: string; confidence: number }[];
    suggested_entities: { text: string; label: string; reason: string; confidence: number }[];
    error: string;
    entities: CompareEntity[];
    signals: CompareSignal[];
  };
  fine_tuned: {
    label: string;
    method: string;
    scam_type: string;
    confidence: number;
    is_uncertain: boolean;
    top_scores: CompareScore[];
    entities: CompareEntity[];
    signals: CompareSignal[];
    signal_candidates: CompareSignal[];
  };
  agreement: {
    existing_vs_fine_tuned: boolean;
    existing_vs_claude: boolean;
    claude_vs_fine_tuned: boolean;
  };
};

type SessionInfo = {
  session_id: string;
  model: "classifier" | "gliner";
  status: string;
  started_at: number;
  ended_at?: number | null;
  output_dir?: string;
  params?: Record<string, unknown>;
};

type SessionsResponse = {
  sessions: SessionInfo[];
  active_models: Record<string, string>;
};

function pct(value: unknown): string {
  return typeof value === "number" ? `${Math.round(value * 1000) / 10}%` : "-";
}

export default function CompareClient() {
  const [form, setForm] = useState({
    text: "서울중앙지검 수사관입니다. 본인 명의 계좌가 사건에 연루되어 안전계좌로 3000만원 검증 이체가 필요합니다.",
    source: "",
    scope: "both" as "both" | "classifier" | "extractor",
    classifierSessionId: "",
    glinerSessionId: "",
  });
  const [sessions, setSessions] = useState<SessionInfo[]>([]);
  const [activeModels, setActiveModels] = useState<Record<string, string>>({});
  const [result, setResult] = useState<ModelCompareResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function loadSessions() {
      try {
        const response = await fetch("/api/admin/training/sessions?limit=100", { cache: "no-store" });
        const data = (await response.json()) as SessionsResponse;
        if (cancelled) return;
        const completed = (data.sessions ?? []).filter((session) => session.status === "completed");
        setSessions(completed);
        setActiveModels(data.active_models ?? {});
        const classifiers = completed.filter((session) => session.model === "classifier");
        const gliners = completed.filter((session) => session.model === "gliner");
        setForm((prev) => ({
          ...prev,
          classifierSessionId: prev.classifierSessionId || classifiers[0]?.session_id || "",
          glinerSessionId: prev.glinerSessionId || gliners[0]?.session_id || "",
        }));
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "세션 목록 로드 실패");
      }
    }
    void loadSessions();
    return () => {
      cancelled = true;
    };
  }, []);

  const classifierSessions = useMemo(
    () => sessions.filter((session) => session.model === "classifier"),
    [sessions],
  );
  const glinerSessions = useMemo(
    () => sessions.filter((session) => session.model === "gliner"),
    [sessions],
  );

  async function runComparison() {
    setLoading(true);
    setError("");
    try {
      const response = await fetch("/api/admin/training/compare-analysis", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: form.text.trim() || null,
          source: form.source.trim() || null,
          compare_scope: form.scope,
          classifier_session_id: form.classifierSessionId || null,
          gliner_session_id: form.glinerSessionId || null,
        }),
      });
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail ?? "모델 비교 분석 실패");
      setResult(data as ModelCompareResult);
    } catch (err) {
      setError(err instanceof Error ? err.message : "모델 비교 분석 실패");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[0.86fr_1.14fr]">
      <section className="rounded-2xl border border-white/10 bg-white/5 p-5">
        <div className="text-xs uppercase tracking-widest text-violet-200">Compare Session</div>
        <h2 className="mt-2 text-xl font-semibold text-white">입력 기반 비교</h2>
        <p className="mt-1 text-sm text-slate-400">
          분류기와 추출기를 함께 보거나, 필요한 범위만 좁혀서 비교할 수 있습니다.
        </p>

        {error && (
          <div className="mt-4 rounded-xl border border-rose-400/30 bg-rose-500/10 px-3 py-2 text-sm text-rose-100">
            {error}
          </div>
        )}

        <label className="mt-5 block text-sm">
          <span className="text-slate-300">분석 문구</span>
          <textarea
            value={form.text}
            onChange={(event) => setForm({ ...form, text: event.target.value })}
            rows={8}
            className="mt-2 w-full resize-y rounded-xl border border-white/10 bg-slate-950/70 px-3 py-3 text-sm leading-relaxed text-slate-100"
          />
        </label>

        <label className="mt-4 block text-sm">
          <span className="text-slate-300">링크 또는 파일 경로</span>
          <input
            type="text"
            value={form.source}
            onChange={(event) => setForm({ ...form, source: event.target.value })}
            placeholder="텍스트 대신 URL/YouTube 링크/로컬 파일 경로"
            className="mt-2 w-full rounded-xl border border-white/10 bg-slate-950/70 px-3 py-2 font-mono text-xs text-slate-100"
          />
        </label>

        <div className="mt-4 text-sm">
          <span className="text-slate-300">비교 범위</span>
          <div className="mt-2 grid gap-2 sm:grid-cols-3">
            {[
              ["both", "분류+추출"],
              ["classifier", "분류기만"],
              ["extractor", "추출기만"],
            ].map(([value, label]) => (
              <button
                key={value}
                type="button"
                onClick={() => setForm({ ...form, scope: value as "both" | "classifier" | "extractor" })}
                className={`rounded-xl border px-3 py-2 text-sm transition ${
                  form.scope === value
                    ? "border-violet-300/50 bg-violet-300 text-slate-950"
                    : "border-white/10 bg-slate-950/70 text-slate-300 hover:bg-white/5"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label className="block text-sm">
            <span className="text-slate-300">분류기 모델</span>
            <select
              value={form.classifierSessionId}
              onChange={(event) => setForm({ ...form, classifierSessionId: event.target.value })}
              className="mt-2 w-full rounded-xl border border-white/10 bg-slate-950/70 px-3 py-2 font-mono text-xs text-slate-100"
            >
              {classifierSessions.length === 0 && <option value="">완료된 classifier 없음</option>}
              {classifierSessions.map((session) => (
                <option key={session.session_id} value={session.session_id}>
                  {session.session_id} {activeModels.classifier === session.output_dir ? "(active)" : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="block text-sm">
            <span className="text-slate-300">GLiNER 추출기</span>
            <select
              value={form.glinerSessionId}
              onChange={(event) => setForm({ ...form, glinerSessionId: event.target.value })}
              className="mt-2 w-full rounded-xl border border-white/10 bg-slate-950/70 px-3 py-2 font-mono text-xs text-slate-100"
              disabled={form.scope === "classifier"}
            >
              <option value="">active/base 사용</option>
              {glinerSessions.map((session) => (
                <option key={session.session_id} value={session.session_id}>
                  {session.session_id} {activeModels.gliner === session.output_dir ? "(active)" : ""}
                </option>
              ))}
            </select>
          </label>
        </div>

        <button
          onClick={() => void runComparison()}
          disabled={loading}
          className="mt-5 w-full rounded-xl bg-violet-300 px-5 py-2 text-sm font-semibold text-slate-950 transition hover:bg-violet-200 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? "비교 중..." : "비교 분석 실행"}
        </button>
      </section>

      <section className="rounded-2xl border border-white/10 bg-white/5 p-5">
        {result ? (
          <ModelComparePanel result={result} />
        ) : (
          <div className="flex h-full min-h-[520px] items-center justify-center rounded-xl border border-dashed border-white/10 bg-slate-950/30 px-4 py-8 text-center text-sm text-slate-500">
            비교 분석을 실행하면 세 관점의 유형, 엔티티, 위험 신호 후보가 표시됩니다.
          </div>
        )}
      </section>
    </div>
  );
}

function ModelComparePanel({ result }: { result: ModelCompareResult }) {
  const scope = result.compare_scope ?? "both";
  const showClassifier = scope === "both" || scope === "classifier";
  const showExtractor = scope === "both" || scope === "extractor";
  const columns = [
    {
      key: "existing",
      title: "기존 분석",
      subtitle: result.existing.method,
      scamType: result.existing.scam_type,
      confidence: result.existing.confidence,
      entities: result.existing.entities,
      signals: result.existing.signals,
      tone: "cyan" as const,
    },
    {
      key: "claude",
      title: "Claude 분석",
      subtitle: result.claude.method,
      scamType: result.claude.scam_type || "-",
      confidence: result.claude.confidence,
      entities: result.claude.entities ?? result.claude.suggested_entities,
      signals: result.claude.signals ?? result.claude.suggested_flags,
      tone: "violet" as const,
      error: result.claude.error,
      summary: result.claude.summary,
    },
    {
      key: "fine_tuned",
      title: "파인튜닝 모델",
      subtitle: result.classifier_session_id ?? result.session_id,
      scamType: result.fine_tuned.scam_type,
      confidence: result.fine_tuned.confidence,
      entities: result.fine_tuned.entities,
      signals: result.fine_tuned.signals,
      tone: "emerald" as const,
    },
  ];

  return (
    <div className="space-y-4">
      {showClassifier && (
        <div className="grid gap-3 sm:grid-cols-3">
          {columns.map((column) => (
            <ModelVerdictCard
              key={column.key}
              title={column.title}
              subtitle={column.subtitle}
              scamType={column.scamType}
              confidence={column.confidence}
              tone={column.tone}
            />
          ))}
        </div>
      )}

      {showClassifier && (
        <div className="rounded-xl border border-white/10 bg-slate-950/50 p-3">
          <div className="mb-2 text-xs uppercase tracking-widest text-slate-400">일치 여부</div>
          <div className="flex flex-wrap gap-2 text-xs">
            <AgreementPill label="기존 = 파인튜닝" ok={result.agreement.existing_vs_fine_tuned} />
            <AgreementPill label="기존 = Claude" ok={result.agreement.existing_vs_claude} />
            <AgreementPill label="Claude = 파인튜닝" ok={result.agreement.claude_vs_fine_tuned} />
          </div>
        </div>
      )}

      {result.claude.error ? (
        <div className="rounded-xl border border-rose-400/25 bg-rose-500/10 p-3 text-sm text-rose-100">
          Claude 분석 오류: {result.claude.error}
        </div>
      ) : (
        <div className="rounded-xl border border-white/10 bg-slate-950/50 p-3">
          <div className="mb-2 text-xs uppercase tracking-widest text-slate-400">Claude 근거 후보</div>
          <p className="text-sm leading-relaxed text-slate-300">{result.claude.summary || "요약 없음"}</p>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <CompareList title="신호 후보" items={result.claude.suggested_flags.map((flag) => `${flag.flag}: ${flag.evidence || flag.reason}`)} />
            <CompareList title="엔티티 후보" items={result.claude.suggested_entities.map((entity) => `${entity.label}: ${entity.text}`)} />
          </div>
        </div>
      )}

      {showExtractor && (
        <div className="overflow-hidden rounded-xl border border-white/10 bg-slate-950/50">
          <div className="border-b border-white/10 p-3">
            <div className="text-xs uppercase tracking-widest text-slate-400">
              {showClassifier ? "유형 + 추출 비교" : "추출기 비교"}
            </div>
            <p className="mt-1 text-xs text-slate-500">
              같은 입력에서 엔티티와 위험 신호 후보가 어떻게 달라지는지 비교합니다.
            </p>
          </div>
          <div className="grid gap-0 lg:grid-cols-3">
            {columns.map((column) => (
              <div key={column.key} className="border-b border-white/10 p-3 lg:border-b-0 lg:border-r last:border-r-0">
                <div className="mb-3">
                  <div className="text-xs text-slate-500">{column.title}</div>
                  <div className="mt-1 text-sm font-semibold text-white">{showClassifier ? column.scamType : "추출 결과"}</div>
                  {column.error && (
                    <div className="mt-2 rounded-lg border border-rose-400/25 bg-rose-500/10 px-2 py-1 text-xs text-rose-100">
                      {column.error}
                    </div>
                  )}
                  {column.summary && !column.error && (
                    <p className="mt-2 line-clamp-3 text-xs leading-relaxed text-slate-400">{column.summary}</p>
                  )}
                </div>
                <CompareChipList
                  title={`위험요소/엔티티 ${column.entities.length}개`}
                  empty="추출된 엔티티 없음"
                  items={column.entities.map((entity) => `${entity.label || "-"}: ${entity.text || ""}`)}
                />
                <CompareChipList
                  title={`위험 신호 후보 ${column.signals.length}개`}
                  empty="검출된 신호 후보 없음"
                  items={column.signals.map((signal) => {
                    const evidence = signal.evidence || signal.reason || signal.evidence_snippets?.[0] || signal.flag_description || "";
                    return `${signal.flag || signal.flag_description || "-"}${evidence ? `: ${evidence}` : ""}`;
                  })}
                />
              </div>
            ))}
          </div>
        </div>
      )}

      <details className="rounded-xl border border-white/10 bg-slate-950/40 p-3 text-sm">
        <summary className="cursor-pointer text-slate-300">비교에 사용한 transcript</summary>
        <p className="mt-2 max-h-36 overflow-auto whitespace-pre-wrap text-xs leading-relaxed text-slate-400">
          {result.input.transcript_text}
        </p>
      </details>
    </div>
  );
}

function CompareChipList({ title, items, empty }: { title: string; items: string[]; empty: string }) {
  const visible = items.filter(Boolean).slice(0, 8);
  return (
    <div className="mb-3">
      <div className="mb-2 text-xs font-semibold text-slate-300">{title}</div>
      {visible.length === 0 ? (
        <div className="rounded-lg border border-dashed border-white/10 px-2 py-2 text-xs text-slate-500">
          {empty}
        </div>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {visible.map((item, index) => (
            <span key={`${item}-${index}`} className="rounded-full border border-slate-600 bg-slate-900 px-2 py-0.5 text-xs text-slate-300" title={item}>
              {item.length > 42 ? `${item.slice(0, 42)}...` : item}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function ModelVerdictCard({
  title,
  subtitle,
  scamType,
  confidence,
  tone,
}: {
  title: string;
  subtitle: string;
  scamType: string;
  confidence: number | null;
  tone: "cyan" | "violet" | "emerald";
}) {
  const toneClass = {
    cyan: "border-cyan-400/25 bg-cyan-500/10 text-cyan-100",
    violet: "border-violet-400/25 bg-violet-500/10 text-violet-100",
    emerald: "border-emerald-400/25 bg-emerald-500/10 text-emerald-100",
  }[tone];
  return (
    <div className={`rounded-xl border p-3 ${toneClass}`}>
      <div className="text-xs opacity-75">{title}</div>
      <div className="mt-2 text-lg font-semibold text-white">{scamType}</div>
      <div className="mt-1 truncate text-[11px] opacity-70">{subtitle}</div>
      <div className="mt-2 font-mono text-xs opacity-80">confidence {confidence === null ? "-" : pct(confidence)}</div>
    </div>
  );
}

function AgreementPill({ label, ok }: { label: string; ok: boolean }) {
  return (
    <span
      className={`rounded-full border px-2.5 py-1 ${
        ok
          ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-200"
          : "border-amber-400/30 bg-amber-500/10 text-amber-100"
      }`}
    >
      {label}: {ok ? "일치" : "차이"}
    </span>
  );
}

function CompareList({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div className="text-xs font-semibold text-slate-300">{title}</div>
      <div className="mt-2 space-y-1">
        {items.length === 0 ? (
          <div className="text-xs text-slate-500">없음</div>
        ) : (
          items.slice(0, 4).map((item) => (
            <div key={item} className="rounded-lg bg-white/5 px-2 py-1 text-xs text-slate-300">
              {item}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
