"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

type RunItem = {
  id: string;
  created_at: string;
  transcript_preview: string;
  predicted_scam_type: string;
  predicted_confidence: number;
  // DB 컬럼은 호환을 위해 유지 — 의미는 검출 신호 *개수* (점수 X). risk_level_predicted 는 deprecated (빈 문자열).
  total_score_predicted: number;
  risk_level_predicted: string;
  status: "미완료" | "진행중" | "완료";
  claimed_by: string | null;
  labeler: string | null;
};

type LabelerStat = {
  sample_count: number;
  classification_accuracy: number;
  entity_f1: number;
  flag_f1: number;
};

type NeedsReviewItem = {
  run_id: string;
  reasons: string[];
};

type MetricsResponse = {
  sample_count: number;
  classification_accuracy: number;
  entity_micro: { f1: number; precision: number; recall: number };
  flag_micro: { f1: number; precision: number; recall: number };
  per_labeler: Record<string, LabelerStat>;
  needs_review: NeedsReviewItem[];
  detail?: string;
};

type ScamTypeCatalogItem = {
  name: string;
  description: string;
  labels: string[];
  created_at: string;
  updated_at: string;
};

const STATUS_STYLES: Record<string, string> = {
  완료: "bg-emerald-500/15 text-emerald-200 border-emerald-400/20",
  진행중: "bg-amber-500/15 text-amber-200 border-amber-400/20",
  미완료: "bg-slate-500/15 text-slate-300 border-slate-400/20",
};

function formatPercent(value: number) {
  return new Intl.NumberFormat("ko-KR", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

export default function AdminDashboardPage() {
  const [runs, setRuns] = useState<RunItem[]>([]);
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [customScamTypes, setCustomScamTypes] = useState<ScamTypeCatalogItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [labeler, setLabeler] = useState("");
  const [statusFilter, setStatusFilter] = useState<string>("미완료");
  const [claimingId, setClaimingId] = useState<string | null>(null);
  const [claimError, setClaimError] = useState("");

  const [typeSaving, setTypeSaving] = useState(false);
  const [typeMessage, setTypeMessage] = useState("");
  const [typeName, setTypeName] = useState("");
  const [typeDescription, setTypeDescription] = useState("");
  const [typeLabels, setTypeLabels] = useState("");

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError("");

      try {
        const qs = statusFilter ? `?status=${encodeURIComponent(statusFilter)}` : "";
        const [runsResponse, metricsResponse, scamTypesResponse] = await Promise.all([
          fetch(`/api/admin/runs/list${qs}`, { cache: "no-store" }),
          fetch("/api/admin/metrics", { cache: "no-store" }),
          fetch("/api/admin/scam-types", { cache: "no-store" }),
        ]);

        const runsData = (await runsResponse.json()) as { runs?: RunItem[]; detail?: string };
        const metricsData = (await metricsResponse.json()) as MetricsResponse;
        const scamTypesData = (await scamTypesResponse.json()) as {
          items?: ScamTypeCatalogItem[];
          detail?: string;
        };

        if (!runsResponse.ok) throw new Error(runsData.detail ?? "run 목록을 불러오지 못했습니다.");
        if (!scamTypesResponse.ok) throw new Error(scamTypesData.detail ?? "스캠 유형을 불러오지 못했습니다.");

        if (!cancelled) {
          setRuns(runsData.runs ?? []);
          setMetrics(metricsData);
          setCustomScamTypes(scamTypesData.items ?? []);
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "데이터를 불러오지 못했습니다.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => { cancelled = true; };
  }, [statusFilter]);

  async function claimAndGo(runId: string) {
    setClaimError("");
    if (!labeler.trim()) {
      setClaimError("먼저 검수자 이름을 입력해주세요.");
      return;
    }
    setClaimingId(runId);
    try {
      const resp = await fetch(`/api/admin/runs/${runId}/claim`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ labeler: labeler.trim() }),
      });
      const data = (await resp.json()) as { ok?: boolean; detail?: string };
      if (!resp.ok) throw new Error(data.detail ?? "클레임 실패");
      window.location.href = `/admin/${runId}`;
    } catch (err) {
      setClaimError(err instanceof Error ? err.message : "클레임에 실패했습니다.");
      setClaimingId(null);
    }
  }

  async function addScamType() {
    const trimmedName = typeName.trim();
    if (!trimmedName) { setTypeMessage("새 스캠 유형 이름을 입력해주세요."); return; }
    setTypeSaving(true);
    setTypeMessage("");
    try {
      const labels = typeLabels.split(",").map((l) => l.trim()).filter(Boolean);
      const resp = await fetch("/api/admin/scam-types", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: trimmedName, description: typeDescription.trim() || null, labels }),
      });
      const data = (await resp.json()) as { ok?: boolean; item?: ScamTypeCatalogItem; detail?: string };
      if (!resp.ok || !data.item) throw new Error(data.detail ?? "저장 실패");
      const saved = data.item;
      setCustomScamTypes((cur) => {
        const next = cur.filter((i) => i.name !== saved.name);
        next.push(saved);
        return next.sort((a, b) => a.name.localeCompare(b.name, "ko-KR"));
      });
      setTypeName(""); setTypeDescription(""); setTypeLabels("");
      setTypeMessage("저장되었습니다.");
    } catch (err) {
      setTypeMessage(err instanceof Error ? err.message : "저장 실패");
    } finally {
      setTypeSaving(false);
    }
  }

  const statusCounts = runs.reduce<Record<string, number>>(
    (acc, r) => { acc[r.status] = (acc[r.status] ?? 0) + 1; return acc; },
    {},
  );

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,#111827_0%,#020617_60%,#000000_100%)] px-6 py-10 text-slate-100">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-6">

        {/* 헤더 */}
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-sm uppercase tracking-[0.2em] text-cyan-200">Label Admin</div>
            <h1 className="mt-2 text-3xl font-semibold text-white">라벨링 큐</h1>
          </div>
          <div className="flex gap-2">
            <Link
              className="rounded-2xl border border-white/10 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/5"
              href="/admin/stats"
            >
              대시보드
            </Link>
            <Link
              className="rounded-2xl border border-white/10 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/5"
              href="/admin/browse"
            >
              DB 브라우저
            </Link>
            <Link
              className="rounded-2xl border border-white/10 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/5"
              href="/admin/training"
            >
              🧪 Fine-tuning
            </Link>
            <Link
              className="rounded-2xl border border-white/10 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/5"
              href="/admin/apk-dynamic"
            >
              🧪 APK 동적
            </Link>
            <Link
              className="rounded-2xl border border-white/10 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/5"
              href="/admin/users"
            >
              👥 사용자
            </Link>
            <Link
              className="rounded-2xl border border-white/10 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/5"
              href="/admin/platform"
            >
              ⚙️ Platform
            </Link>
            <Link
              className="rounded-2xl border border-white/10 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/5"
              href="/"
            >
              분석 화면으로
            </Link>
          </div>
        </div>

        {error ? (
          <div className="rounded-2xl border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
            {error}
          </div>
        ) : null}

        {/* 메트릭 + 검수자 설정 */}
        <section className="grid gap-4 lg:grid-cols-[1fr_1fr_1fr_1.2fr]">
          <div className="rounded-3xl border border-white/10 bg-white/5 p-5 backdrop-blur">
            <div className="text-sm text-slate-400">완료</div>
            <div className="mt-2 text-3xl font-semibold text-emerald-300">
              {metrics?.sample_count ?? 0}
            </div>
          </div>
          <div className="rounded-3xl border border-white/10 bg-white/5 p-5 backdrop-blur">
            <div className="text-sm text-slate-400">분류 정확도</div>
            <div className="mt-2 text-3xl font-semibold text-white">
              {formatPercent(metrics?.classification_accuracy ?? 0)}
            </div>
          </div>
          <div className="rounded-3xl border border-white/10 bg-white/5 p-5 backdrop-blur">
            <div className="text-sm text-slate-400">엔티티 F1</div>
            <div className="mt-2 text-3xl font-semibold text-white">
              {formatPercent(metrics?.entity_micro?.f1 ?? 0)}
            </div>
          </div>
          <div className="rounded-3xl border border-white/10 bg-white/5 p-5 backdrop-blur">
            <div className="mb-1 text-sm text-slate-400">내 이름 (라벨링 전 설정)</div>
            <input
              className="w-full rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400/50"
              onChange={(e) => setLabeler(e.target.value)}
              placeholder="검수자 이름 또는 닉네임"
              value={labeler}
            />
            {claimError ? (
              <div className="mt-2 text-xs text-rose-300">{claimError}</div>
            ) : null}
          </div>
        </section>

        {/* 품질 대시보드 */}
        {metrics && !metrics.detail && metrics.sample_count > 0 ? (
          <section className="grid gap-6 lg:grid-cols-2">
            {/* per-labeler */}
            <div className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
              <div className="mb-4 text-lg font-semibold text-white">검수자별 통계</div>
              {Object.keys(metrics.per_labeler).length === 0 ? (
                <div className="text-sm text-slate-400">데이터 없음</div>
              ) : (
                <div className="space-y-3">
                  {Object.entries(metrics.per_labeler).map(([name, stat]) => (
                    <div
                      className="grid grid-cols-[1fr_auto_auto_auto] gap-4 rounded-2xl border border-white/10 bg-slate-950/40 px-4 py-3 text-sm"
                      key={name}
                    >
                      <div className="font-medium text-white">{name}</div>
                      <div className="text-center">
                        <div className="text-xs text-slate-400">완료</div>
                        <div className="text-slate-200">{stat.sample_count}</div>
                      </div>
                      <div className="text-center">
                        <div className="text-xs text-slate-400">분류 acc</div>
                        <div className="text-slate-200">{formatPercent(stat.classification_accuracy)}</div>
                      </div>
                      <div className="text-center">
                        <div className="text-xs text-slate-400">엔티티 F1</div>
                        <div className="text-slate-200">{formatPercent(stat.entity_f1)}</div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* 재검토 필요 */}
            <div className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
              <div className="mb-4 flex items-center gap-2 text-lg font-semibold text-white">
                재검토 필요
                {metrics.needs_review.length > 0 ? (
                  <span className="rounded-full bg-rose-500/20 px-2 py-0.5 text-sm text-rose-300">
                    {metrics.needs_review.length}
                  </span>
                ) : null}
              </div>
              {metrics.needs_review.length === 0 ? (
                <div className="rounded-2xl border border-emerald-400/20 bg-emerald-500/10 px-4 py-4 text-sm text-emerald-100">
                  모든 라벨이 파이프라인 예측과 잘 일치합니다.
                </div>
              ) : (
                <div className="space-y-2">
                  {metrics.needs_review.slice(0, 10).map((item) => (
                    <Link
                      className="block rounded-2xl border border-rose-400/15 bg-rose-500/5 px-4 py-3 transition hover:bg-rose-500/10"
                      href={`/admin/${item.run_id}`}
                      key={item.run_id}
                    >
                      <div className="font-mono text-xs text-slate-400">{item.run_id.slice(0, 8)}…</div>
                      <div className="mt-1 space-y-0.5">
                        {item.reasons.map((r, i) => (
                          <div className="text-xs text-rose-300" key={i}>{r}</div>
                        ))}
                      </div>
                    </Link>
                  ))}
                </div>
              )}
            </div>
          </section>
        ) : null}

        {/* run 목록 */}
        <section className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div className="text-lg font-semibold text-white">Run 목록</div>
            <div className="flex gap-2">
              {(["미완료", "진행중", "완료", "전체"] as const).map((s) => (
                <button
                  className={`rounded-full border px-3 py-1 text-xs transition ${
                    statusFilter === (s === "전체" ? "" : s)
                      ? "border-cyan-400/50 bg-cyan-500/20 text-cyan-200"
                      : "border-white/10 text-slate-400 hover:bg-white/5"
                  }`}
                  key={s}
                  onClick={() => setStatusFilter(s === "전체" ? "" : s)}
                  type="button"
                >
                  {s}
                  {s !== "전체" && statusCounts[s] !== undefined
                    ? ` (${statusCounts[s]})`
                    : null}
                </button>
              ))}
            </div>
          </div>

          {loading ? (
            <div className="py-8 text-center text-sm text-slate-400">불러오는 중...</div>
          ) : runs.length === 0 ? (
            <div className="rounded-2xl border border-white/10 bg-slate-950/40 px-4 py-6 text-center text-sm text-slate-400">
              해당하는 run이 없습니다.
            </div>
          ) : (
            <div className="space-y-2">
              {runs.map((run) => (
                <div
                  className="grid gap-3 rounded-2xl border border-white/10 bg-slate-950/40 p-4 lg:grid-cols-[1fr_auto_auto_auto]"
                  key={run.id}
                >
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`rounded-full border px-2 py-0.5 text-xs ${STATUS_STYLES[run.status]}`}
                      >
                        {run.status}
                        {run.status === "진행중" && run.claimed_by ? ` — ${run.claimed_by}` : ""}
                        {run.status === "완료" && run.labeler ? ` — ${run.labeler}` : ""}
                      </span>
                      <span className="text-xs text-slate-500">
                        {run.created_at.slice(0, 16).replace("T", " ")}
                      </span>
                    </div>
                    <div className="mt-1 text-sm font-medium text-white">
                      {run.predicted_scam_type}
                      <span className="ml-2 text-xs text-slate-400">
                        {formatPercent(run.predicted_confidence)}
                      </span>
                    </div>
                    <div className="mt-1 line-clamp-1 text-xs text-slate-400">
                      {run.transcript_preview}
                    </div>
                  </div>

                  <div className="flex items-center">
                    <span className="rounded-full border border-white/10 px-2 py-0.5 text-xs text-slate-300">
                      검출 신호 {run.total_score_predicted}개
                    </span>
                  </div>

                  <div className="flex items-center">
                    <span className="font-mono text-xs text-slate-500">
                      {run.id.slice(0, 8)}…
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    {run.status === "완료" ? (
                      <Link
                        className="rounded-xl border border-white/10 px-3 py-1.5 text-xs text-slate-300 transition hover:bg-white/5"
                        href={`/admin/${run.id}`}
                      >
                        수정
                      </Link>
                    ) : (
                      <button
                        className="rounded-xl bg-cyan-300 px-3 py-1.5 text-xs font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:opacity-50"
                        disabled={claimingId === run.id}
                        onClick={() => void claimAndGo(run.id)}
                        type="button"
                      >
                        {claimingId === run.id ? "..." : "라벨링"}
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </section>

        {/* 스캠 유형 관리 */}
        <section className="grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
          <div className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
            <div className="mb-4 text-lg font-semibold text-white">스캠 유형 추가</div>
            <div className="space-y-4">
              <label className="block space-y-2 text-sm text-slate-300">
                <span className="block">유형 이름</span>
                <input
                  className="w-full rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 text-slate-100 outline-none focus:border-cyan-400/50"
                  onChange={(e) => setTypeName(e.target.value)}
                  placeholder="예: 대출 사기"
                  value={typeName}
                />
              </label>
              <label className="block space-y-2 text-sm text-slate-300">
                <span className="block">분류 설명</span>
                <input
                  className="w-full rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 text-slate-100 outline-none focus:border-cyan-400/50"
                  onChange={(e) => setTypeDescription(e.target.value)}
                  placeholder="예: 급전, 대출 승인, 선입금 수수료를 요구"
                  value={typeDescription}
                />
              </label>
              <label className="block space-y-2 text-sm text-slate-300">
                <span className="block">추가 엔티티 라벨 (선택, 쉼표 구분)</span>
                <input
                  className="w-full rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 text-slate-100 outline-none focus:border-cyan-400/50"
                  onChange={(e) => setTypeLabels(e.target.value)}
                  placeholder="비우면 공통 라벨만 사용"
                  value={typeLabels}
                />
              </label>
              <button
                className="rounded-2xl bg-cyan-300 px-4 py-3 font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
                disabled={typeSaving}
                onClick={() => void addScamType()}
                type="button"
              >
                {typeSaving ? "저장 중..." : "스캠 유형 저장"}
              </button>
              {typeMessage ? (
                <div className="rounded-2xl border border-cyan-400/20 bg-cyan-500/10 px-4 py-3 text-sm text-cyan-100">
                  {typeMessage}
                </div>
              ) : null}
            </div>
          </div>

          <div className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
            <div className="mb-4 text-lg font-semibold text-white">사용자 추가 유형</div>
            {customScamTypes.length ? (
              <div className="space-y-3">
                {customScamTypes.map((item) => (
                  <div
                    className="rounded-2xl border border-white/10 bg-slate-950/40 p-4"
                    key={item.name}
                  >
                    <div className="text-lg font-semibold text-white">{item.name}</div>
                    <div className="mt-2 text-sm text-slate-300">{item.description || "설명 없음"}</div>
                    <div className="mt-3 flex flex-wrap gap-2">
                      {(item.labels.length ? item.labels : ["공통 라벨만 사용"]).map((label) => (
                        <span
                          className="rounded-full border border-white/10 px-3 py-1 text-xs text-slate-300"
                          key={`${item.name}-${label}`}
                        >
                          {label}
                        </span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-2xl border border-white/10 bg-slate-950/40 px-4 py-4 text-sm text-slate-300">
                아직 추가된 사용자 정의 스캠 유형이 없습니다.
              </div>
            )}
          </div>
        </section>

      </div>
    </main>
  );
}
