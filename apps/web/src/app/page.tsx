"use client";

import Link from "next/link";
import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";

type Entity = {
  label: string;
  text: string;
  score: number;
  start?: number;
  end?: number;
  source?: string;
};

// DetectionReport.detected_signals[] schema (Stage 2 reframe — total_score / risk_level 폐기)
type DetectedSignal = {
  flag: string;
  label_ko: string;
  rationale?: string;
  source?: string;             // 출처 기관·논문
  detection_source?: string;   // rule | llm | safety | sandbox | static_lv1 | static_lv2 | dynamic_lv3
  evidence?: string[];
  description?: string;
};

type LlmSuggestedEntity = {
  text: string;
  label: string;
  reason: string;
  confidence: number;
};

type LlmSuggestedFlag = {
  flag: string;
  reason: string;
  evidence: string;
  confidence: number;
};

type LlmAssessment = {
  model: string;
  summary: string;
  reasoning?: string[];
  suggested_entities: LlmSuggestedEntity[];
  suggested_flags: LlmSuggestedFlag[];
  error: string;
};

type RagSimilarCase = {
  run_id: string;
  scam_type_gt: string;
  distance: number;
  transcript_excerpt: string;
};

type RagContext = {
  enabled: boolean;
  similar_cases: RagSimilarCase[];
};

// Stage 1 게이트 안전 버킷만 노출 (Identity Boundary).
// scam_attempt / suspicious_insufficient 는 백엔드에서 절대 전달되지 않음.
type ContentType = {
  bucket?: string;        // normal | scam_news_edu | undetermined
  label_ko?: string;
};

type AnalysisReport = {
  scam_type: string;
  classification_confidence: number;
  is_uncertain: boolean;
  transcript_preview: string;
  transcript_text?: string;
  // DetectionReport (Stage 2 reframe) — 점수·등급 X, 검출 신호 list 만
  detected_signals: DetectedSignal[];
  summary?: string;
  disclaimer?: string;
  entities: Entity[];
  verification_count: number;
  llm_assessment?: LlmAssessment | null;
  rag_context?: RagContext | null;
  analysis_run_id?: string;
  // Stage 1 안전 버킷 — 없으면 기존 scam_type 표시로 자연 fallback.
  content_type?: ContentType | null;
};

function contentTypeBadge(
  ct: ContentType | null | undefined,
): { icon: string; label: string; chip: string } | null {
  const bucket = (ct?.bucket ?? "").trim();
  if (bucket === "scam_news_edu") {
    return {
      icon: "🗞️",
      label: "사기 보도·교육 콘텐츠",
      chip: "border-sky-500/40 bg-sky-700/20 text-sky-200",
    };
  }
  if (bucket === "normal") {
    return {
      icon: "✅",
      label: "정상 콘텐츠",
      chip: "border-emerald-500/40 bg-emerald-700/20 text-emerald-200",
    };
  }
  // undetermined 는 Phase 2 (scam_type 분류) 가 실행된 버킷이라
  // scam_type 카드를 대체하지 않고 기존 결과 그대로 보여준다.
  return null;
}

const EXAMPLE_INPUT =
  "일론 머스크가 화성 이민 프로젝트에 300만원 투자하면 연 30% 수익을 보장한다고 합니다. 문의는 010-1234-5678로 하라고 합니다.";

function formatPercent(value: number) {
  return new Intl.NumberFormat("ko-KR", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

function entityKey(entity: Entity, index: number) {
  return `${entity.label}-${entity.text}-${entity.start ?? "na"}-${entity.end ?? "na"}-${index}`;
}

function sourceBadgeClass(source?: string) {
  return source === "llm"
    ? "bg-fuchsia-500/15 text-fuchsia-200 ring-1 ring-fuchsia-500/30"
    : "bg-cyan-500/15 text-cyan-200 ring-1 ring-cyan-500/30";
}

type TranscriptSpan = {
  start: number;
  end: number;
  kind: "entity" | "evidence";
  label?: string;
};

function renderTranscriptWithHighlights(
  transcript: string,
  spans: TranscriptSpan[],
) {
  if (!transcript) return null;

  const sorted = [...spans]
    .filter((s) => Number.isFinite(s.start) && Number.isFinite(s.end) && s.end > s.start)
    .sort((a, b) => a.start - b.start || a.end - b.end);

  const nonOverlapping: TranscriptSpan[] = [];
  for (const s of sorted) {
    const last = nonOverlapping[nonOverlapping.length - 1];
    if (!last || s.start >= last.end) nonOverlapping.push(s);
  }

  const parts: ReactNode[] = [];
  let idx = 0;
  nonOverlapping.forEach((s, i) => {
    if (s.start > idx) {
      parts.push(<span key={`p-${i}`}>{transcript.slice(idx, s.start)}</span>);
    }
    const className =
      s.kind === "entity"
        ? "rounded-sm bg-cyan-500/20 px-0.5 text-cyan-100"
        : "rounded-sm bg-amber-500/20 px-0.5 text-amber-100";
    parts.push(
      <mark
        key={`m-${i}`}
        title={s.label ? `${s.kind}: ${s.label}` : s.kind}
        className={className}
      >
        {transcript.slice(s.start, s.end)}
      </mark>,
    );
    idx = s.end;
  });

  if (idx < transcript.length) {
    parts.push(<span key="tail">{transcript.slice(idx)}</span>);
  }

  return <>{parts}</>;
}

export default function Home() {
  const [source, setSource] = useState(EXAMPLE_INPUT);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [skipVerification, setSkipVerification] = useState(true);
  const [useLlm] = useState(true);
  const [useRag, setUseRag] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState<AnalysisReport | null>(null);
  const [sttBackend, setSttBackend] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/config/runtime")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (!cancelled && d && typeof d.stt_backend === "string") {
          setSttBackend(d.stt_backend);
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const sourceHint = useMemo(() => {
    if (source.startsWith("http://") || source.startsWith("https://")) {
      return "유튜브 URL로 인식됩니다.";
    }

    return "텍스트로 인식됩니다.";
  }, [source]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const trimmedSource = source.trim();
    if (!uploadFile && !trimmedSource) {
      setError("텍스트/유튜브 URL을 입력하거나 영상 파일을 업로드해주세요.");
      return;
    }

    setLoading(true);
    setError("");
    setReport(null);

    try {
      const response = uploadFile
        ? await (async () => {
            const formData = new FormData();
            formData.set("file", uploadFile);
            formData.set("skip_verification", String(skipVerification));
            formData.set("use_llm", "true");
            formData.set("use_rag", String(useRag));
            return await fetch("/api/analyze-upload", {
              method: "POST",
              body: formData,
            });
          })()
        : await fetch("/api/analyze", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
            },
            body: JSON.stringify({
              source: trimmedSource,
              skip_verification: skipVerification,
              use_llm: true,
              use_rag: useRag,
            }),
          });

      const data = (await response.json()) as AnalysisReport | { detail?: string };
      if (!response.ok) {
        const message =
          "detail" in data && typeof data.detail === "string"
            ? data.detail
            : "분석 중 오류가 발생했습니다.";
        throw new Error(message);
      }

      setReport(data as AnalysisReport);
    } catch (submitError) {
      const message =
        submitError instanceof Error
          ? submitError.message
          : "분석 중 오류가 발생했습니다.";
      setError(message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,#1e293b_0%,#0f172a_45%,#020617_100%)] px-6 py-10 text-slate-100">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
        <section className="rounded-3xl border border-white/10 bg-white/5 p-8 shadow-2xl shadow-slate-950/30 backdrop-blur">
          <div className="mb-6 flex flex-wrap items-center gap-3">
            <span className="rounded-full bg-cyan-400/10 px-3 py-1 text-xs font-semibold tracking-[0.2em] text-cyan-200 uppercase">
              ScamGuardian
            </span>
            <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-slate-300">
              웹 분석 대시보드
            </span>
            <Link
              className="rounded-full border border-white/10 px-3 py-1 text-xs text-slate-300 transition hover:bg-white/5"
              href="/admin"
            >
              라벨링 어드민
            </Link>
            <Link
              className="rounded-full border border-fuchsia-400/40 px-3 py-1 text-xs text-fuchsia-200 transition hover:bg-fuchsia-500/10"
              href="/evidence"
            >
              📚 EVIDENCE — 학술·법적 근거
            </Link>
          </div>

          <div className="grid gap-8 lg:grid-cols-[1.1fr_0.9fr]">
            <div className="space-y-4">
              <h1 className="text-4xl font-semibold tracking-tight text-white">
                스캠 탐지 파이프라인을 웹에서 바로 실행합니다.
              </h1>
              <p className="max-w-2xl text-sm leading-7 text-slate-300 sm:text-base">
                텍스트나 유튜브 URL을 넣으면 분류, 엔티티 추출, 검증, 점수화를
                한 번에 수행합니다. 검색 검증은 시간이 더 걸리지만 근거가 더
                풍부해집니다.
              </p>
              <div className="flex flex-wrap gap-3 text-sm text-slate-300">
                <span className="rounded-full border border-white/10 px-3 py-1">
                  1. 분류
                </span>
                <span className="rounded-full border border-white/10 px-3 py-1">
                  2. 엔티티 추출
                </span>
                <span className="rounded-full border border-white/10 px-3 py-1">
                  3. 검색 검증
                </span>
                <span className="rounded-full border border-white/10 px-3 py-1">
                  4. 위험도 점수화
                </span>
              </div>
            </div>

            <form
              className="rounded-2xl border border-white/10 bg-slate-950/40 p-5"
              onSubmit={handleSubmit}
            >
              <div className="mb-3 flex items-center justify-between">
                <label className="text-sm font-medium text-slate-200" htmlFor="source">
                  분석할 텍스트 또는 유튜브 URL
                </label>
                <button
                  className="text-sm text-cyan-200 transition hover:text-cyan-100"
                  onClick={() => setSource(EXAMPLE_INPUT)}
                  type="button"
                >
                  예시 채우기
                </button>
              </div>

              <textarea
                className="min-h-52 w-full rounded-2xl border border-white/10 bg-slate-900/80 px-4 py-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-cyan-400/50"
                id="source"
                onChange={(event) => setSource(event.target.value)}
                placeholder="텍스트를 붙여넣거나 유튜브 URL을 입력하세요."
                value={source}
              />

              <div className="mt-4">
                <div className="text-sm font-medium text-slate-200">또는 영상/음성 파일 업로드</div>
                <div className="mt-2 flex flex-wrap items-center gap-3">
                  <input
                    className="block w-full max-w-sm text-sm text-slate-200 file:mr-3 file:rounded-xl file:border-0 file:bg-white/10 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-slate-100 hover:file:bg-white/15"
                    type="file"
                    accept="video/*,audio/*"
                    onChange={(event) => {
                      const selected = event.target.files?.[0] ?? null;
                      setUploadFile(selected);
                    }}
                  />
                  {uploadFile ? (
                    <button
                      className="rounded-xl border border-white/10 px-3 py-2 text-xs text-slate-200 transition hover:bg-white/5"
                      type="button"
                      onClick={() => setUploadFile(null)}
                    >
                      선택 해제: {uploadFile.name}
                    </button>
                  ) : (
                    <div className="text-xs text-slate-400">
                      업로드 시 텍스트 입력 대신 파일을 STT로 전사합니다.
                    </div>
                  )}
                </div>
              </div>

              <div className="mt-3 text-sm text-slate-400">{sourceHint}</div>

              <div className="mt-5 grid gap-4 sm:grid-cols-2">
                <div className="space-y-2 text-sm text-slate-300">
                  <span className="block">STT 백엔드</span>
                  <div className="flex items-center gap-2 rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2">
                    <span
                      className={`h-2 w-2 rounded-full ${
                        sttBackend ? "bg-emerald-400" : "bg-slate-500"
                      }`}
                    />
                    <span className="text-slate-100">
                      {sttBackend === "claude"
                        ? "Claude Audio API"
                        : sttBackend === "openai_whisper"
                          ? "OpenAI Whisper API"
                          : "확인 중…"}
                    </span>
                  </div>
                  <p className="text-xs text-slate-500">
                    서버 환경변수 <code className="rounded bg-slate-800/80 px-1">STT_BACKEND</code> 로 전환합니다.
                  </p>
                </div>

                <label className="flex items-center gap-3 rounded-2xl border border-white/10 bg-slate-900/50 px-4 py-3 text-sm text-slate-200">
                  <input
                    checked={skipVerification}
                    className="h-4 w-4 accent-cyan-300"
                    onChange={(event) => setSkipVerification(event.target.checked)}
                    type="checkbox"
                  />
                  검색 검증 건너뛰기
                </label>
              </div>

              <label className="mt-4 flex items-center gap-3 rounded-2xl border border-white/10 bg-slate-900/50 px-4 py-3 text-sm text-slate-200">
                <input
                  checked={useLlm}
                  className="h-4 w-4 accent-cyan-300"
                  disabled
                  type="checkbox"
                />
                Claude LLM 보조 판정 사용 (항상 켜짐)
              </label>

              <label className="mt-3 flex items-center gap-3 rounded-2xl border border-white/10 bg-slate-900/50 px-4 py-3 text-sm text-slate-200">
                <input
                  checked={useRag}
                  className="h-4 w-4 accent-cyan-300"
                  onChange={(event) => {
                    const checked = event.target.checked;
                    setUseRag(checked);
                  }}
                  type="checkbox"
                />
                사람 라벨 DB를 RAG로 참고
              </label>

              <p className="mt-3 text-xs leading-6 text-slate-400">
                검색 검증을 끄면 빠르게 데모할 수 있습니다. 켜면 `SERPER_API_KEY`
                가 필요합니다.
              </p>
              <p className="mt-2 text-xs leading-6 text-slate-400">
                LLM 보조 판정은 추가 엔티티를 병합하고, 높은 신뢰도의 플래그
                후보는 축소 가중치로 총점에 반영합니다.
              </p>
              <p className="mt-2 text-xs leading-6 text-slate-400">
                RAG는 어드민에서 사람이 확정한 과거 사례를 찾아 LLM 제안에만
                참고합니다. DB와 라벨 데이터가 있어야 효과가 납니다.
              </p>

              <button
                className="mt-5 inline-flex w-full items-center justify-center rounded-2xl bg-cyan-300 px-4 py-3 font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
                disabled={loading}
                type="submit"
              >
                {loading ? "분석 중..." : "분석 실행"}
              </button>

              {error ? (
                <div className="mt-4 rounded-2xl border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
                  {error}
                </div>
              ) : null}
            </form>
          </div>
        </section>

        <section className="grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
          <div className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h2 className="text-xl font-semibold text-white">검출 결과</h2>
              {report ? (
                <span className="rounded-full bg-fuchsia-500/20 px-3 py-1 text-sm font-medium text-fuchsia-200">
                  위험 신호 {(report.detected_signals ?? []).length}개 검출
                </span>
              ) : null}
            </div>

            {report ? (
              (() => {
                const ctBadge = contentTypeBadge(report.content_type);
                return (
              <div className="space-y-5">
                <div className="grid gap-4 sm:grid-cols-2">
                  {ctBadge ? (
                    <div className={`rounded-2xl border bg-slate-950/40 p-4 ${ctBadge.chip}`}>
                      <div className="text-sm opacity-80">콘텐츠 분류 (사기 판정 X)</div>
                      <div className="mt-2 text-2xl font-semibold">
                        <span className="mr-2">{ctBadge.icon}</span>
                        {ctBadge.label}
                      </div>
                      <div className="mt-2 text-xs opacity-70">
                        Stage 1 게이트 안전 버킷 — scam_type 분류·검증 단계 skip
                      </div>
                    </div>
                  ) : (
                    <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
                      <div className="text-sm text-slate-400">스캠 유형</div>
                      <div className="mt-2 text-2xl font-semibold text-white">
                        {(report.scam_type ?? "").trim() || "미분류"}
                      </div>
                      <div className="mt-2 text-sm text-slate-300">
                        신뢰도 {formatPercent(report.classification_confidence)}
                      </div>
                    </div>
                  )}

                  <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
                    <div className="text-sm text-slate-400">검출된 위험 신호</div>
                    <div className="mt-2 text-2xl font-semibold text-white">
                      {(report.detected_signals ?? []).length}개
                    </div>
                    <div className="mt-2 text-xs text-slate-400">
                      ScamGuardian 은 검출만 — 판정은 통합 기업 (Identity Boundary)
                    </div>
                  </div>
                </div>

                {/* Identity Boundary: 판정(verdict) 없음 — 검출 요약만 노출 */}
                <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
                  <div className="text-sm text-slate-400">검출 요약</div>
                  <div className="mt-2 text-base font-medium leading-7 text-white">
                    {report.summary ??
                      `위험 신호 ${(report.detected_signals ?? []).length}개가 검출되었습니다.`}
                  </div>
                  {report.disclaimer ? (
                    <div className="mt-3 rounded-xl bg-white/5 px-3 py-2 text-xs leading-6 text-slate-400">
                      {report.disclaimer}
                    </div>
                  ) : null}
                </div>

                <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
                  <div className="flex items-center justify-between gap-4">
                    <div className="text-sm text-slate-400">전체 전사(하이라이트)</div>
                    <div className="text-xs text-slate-500">
                      <span className="mr-2 rounded px-1 bg-cyan-500/20 text-cyan-100">
                        엔티티
                      </span>
                      <span className="rounded px-1 bg-amber-500/20 text-amber-100">
                        플래그 근거
                      </span>
                    </div>
                  </div>
                  <div className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-6 text-slate-200">
                    {renderTranscriptWithHighlights(
                      report.transcript_text || report.transcript_preview || "",
                      [
                        ...report.entities
                          .filter(
                            (e) =>
                              typeof e.start === "number" &&
                              typeof e.end === "number" &&
                              (e.start ?? -1) >= 0 &&
                              (e.end ?? 0) > (e.start ?? 0) &&
                              (e.text?.trim().length ?? 0) > 0,
                          )
                          .map((e) => ({
                            start: e.start as number,
                            end: e.end as number,
                            kind: "entity" as const,
                            label: e.label,
                          })),
                        ...(() => {
                          const transcript =
                            report.transcript_text || report.transcript_preview || "";

                          const entitySpans = report.entities
                            .filter(
                              (e) =>
                                typeof e.start === "number" &&
                                typeof e.end === "number" &&
                                (e.start ?? -1) >= 0 &&
                                (e.end ?? 0) > (e.start ?? 0),
                            )
                            .map((e) => ({ start: e.start as number, end: e.end as number }));

                          const overlaps = (
                            a: { start: number; end: number },
                            b: { start: number; end: number },
                          ) => a.start < b.end && b.start < a.end;

                          const evidence: TranscriptSpan[] = [];
                          const maxEvidence = 10;

                          for (const flag of report.detected_signals ?? []) {
                            for (const ev of flag.evidence ?? []) {
                              const snippet = ev?.trim();
                              if (!snippet) continue;
                              const idx = transcript.indexOf(snippet);
                              if (idx === -1) continue;

                              const span = { start: idx, end: idx + snippet.length };
                              if (span.end <= span.start) continue;
                              if (entitySpans.some((es) => overlaps(es, span))) continue;
                              if (
                                evidence.some((s) =>
                                  overlaps({ start: s.start, end: s.end }, span),
                                )
                              )
                                continue;

                              evidence.push({
                                start: span.start,
                                end: span.end,
                                kind: "evidence",
                                label: flag.flag,
                              });
                              if (evidence.length >= maxEvidence) return evidence;
                            }
                          }

                          return evidence;
                        })(),
                      ],
                    )}
                  </div>
                </div>

                {report.analysis_run_id ? (
                  <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
                    <div className="text-sm text-slate-400">저장된 run ID</div>
                    <div className="mt-2 break-all text-sm text-slate-200">
                      {report.analysis_run_id}
                    </div>
                  </div>
                ) : null}

                {/* 콘텐츠가 안전 버킷(뉴스·정상·판단불가)이면 신뢰도 경고 숨김 —
                    confidence 0% 는 Phase 2 skip 의 결과지 분류 실패가 아님. */}
                {report.is_uncertain && !ctBadge ? (
                  <div className="rounded-2xl border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
                    분류 신뢰도가 낮아서 결과가 부정확할 수 있습니다.
                  </div>
                ) : null}
              </div>
                );
              })()
            ) : (
              <div className="rounded-2xl border border-dashed border-white/10 bg-slate-950/20 p-6 text-sm leading-7 text-slate-400">
                아직 결과가 없습니다. 왼쪽 폼에서 입력을 넣고 분석을 실행하세요.
              </div>
            )}
          </div>

          <div className="grid gap-6">
            <div className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-xl font-semibold text-white">엔티티</h2>
                <span className="text-sm text-slate-400">
                  {report ? `${report.entities.length}개` : "0개"}
                </span>
              </div>

              <div className="flex flex-wrap gap-3">
                {report?.entities.length ? (
                  report.entities.map((entity, index) => (
                    <div
                      className="rounded-2xl border border-white/10 bg-slate-950/40 px-4 py-3"
                      key={entityKey(entity, index)}
                    >
                      <div className="flex items-center gap-2">
                        <div className="text-xs text-cyan-200">{entity.label}</div>
                        <span
                          className={`rounded-full px-2 py-0.5 text-[10px] ${sourceBadgeClass(entity.source)}`}
                        >
                          {entity.source === "llm" ? "LLM" : "기본"}
                        </span>
                      </div>
                      <div className="mt-1 text-sm font-medium text-white">
                        {entity.text}
                      </div>
                      <div className="mt-1 text-xs text-slate-400">
                        신뢰도 {entity.score.toFixed(2)}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-2xl border border-dashed border-white/10 bg-slate-950/20 px-4 py-8 text-sm text-slate-400">
                    분석 후 추출된 엔티티가 여기에 표시됩니다.
                  </div>
                )}
              </div>
            </div>

            <div className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-xl font-semibold text-white">검출된 위험 신호</h2>
                <span className="text-sm text-slate-400">
                  {report ? `${(report.detected_signals ?? []).length}개` : "0개"}
                </span>
              </div>

              <div className="space-y-3">
                {(report?.detected_signals ?? []).length ? (
                  (report?.detected_signals ?? []).map((signal, signalIndex) => {
                    const detSrc = signal.detection_source ?? "rule";
                    const sourceTag =
                      detSrc === "llm" ? "🤖 LLM"
                      : detSrc === "safety" ? "🛡 VirusTotal"
                      : detSrc === "sandbox" ? "📦 샌드박스"
                      : detSrc === "static_lv1" ? "🔍 정적 Lv1"
                      : detSrc === "static_lv2" ? "🔬 정적 Lv2"
                      : detSrc === "dynamic_lv3" ? "🧪 동적 Lv3"
                      : "📋 규칙";
                    return (
                      <article
                        className="rounded-2xl border border-white/10 bg-slate-950/40 p-4"
                        key={`${signal.flag}-${signalIndex}`}
                      >
                        <div className="flex flex-wrap items-baseline justify-between gap-2">
                          <div className="text-sm font-semibold text-white">
                            {signal.label_ko ?? signal.flag}
                          </div>
                          <span className="rounded-full bg-slate-700/60 px-2 py-0.5 text-[10px] text-slate-300">
                            {sourceTag}
                          </span>
                        </div>
                        {signal.description ? (
                          <p className="mt-1 text-xs text-slate-400">
                            {signal.description}
                          </p>
                        ) : null}
                        {signal.rationale ? (
                          <div className="mt-3 rounded-xl bg-slate-950/60 p-3 text-xs leading-6 text-slate-300">
                            <div className="text-slate-200">📖 학술/법적 근거</div>
                            <p className="mt-1">{signal.rationale}</p>
                            {signal.source ? (
                              <p className="mt-2 text-slate-500">출처: {signal.source}</p>
                            ) : null}
                          </div>
                        ) : null}
                        {(signal.evidence ?? []).length ? (
                          <div className="mt-2 space-y-1">
                            {(signal.evidence ?? []).slice(0, 2).map((ev, eIdx) => (
                              <div
                                className="rounded-xl bg-white/5 px-3 py-1.5 text-[11px] leading-5 text-slate-400"
                                key={`${signal.flag}-ev-${eIdx}`}
                              >
                                {ev}
                              </div>
                            ))}
                          </div>
                        ) : null}
                      </article>
                    );
                  })
                ) : (
                  <div className="rounded-2xl border border-dashed border-white/10 bg-slate-950/20 px-4 py-8 text-sm text-slate-400">
                    검출된 위험 신호가 없습니다.
                  </div>
                )}
              </div>

              {report ? (
                <div className="mt-4 text-xs text-slate-500">
                  전체 검증 시도 수: {report.verification_count}
                </div>
              ) : null}
            </div>

            <div className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-xl font-semibold text-white">RAG 참고 사례</h2>
                <span className="text-sm text-slate-400">
                  {report?.rag_context?.enabled
                    ? `${report.rag_context.similar_cases.length}개`
                    : "미사용"}
                </span>
              </div>

              {report?.rag_context?.enabled ? (
                report.rag_context.similar_cases.length ? (
                  <div className="space-y-3">
                    {report.rag_context.similar_cases.map((item) => (
                      <div
                        className="rounded-2xl border border-white/10 bg-slate-950/40 p-4"
                        key={item.run_id}
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="text-sm font-semibold text-white">
                            {item.scam_type_gt}
                          </div>
                          <div className="text-xs text-slate-400">
                            distance {item.distance.toFixed(4)}
                          </div>
                        </div>
                        <div className="mt-2 text-sm leading-6 text-slate-300">
                          {item.transcript_excerpt}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-2xl border border-dashed border-white/10 bg-slate-950/20 px-4 py-8 text-sm text-slate-400">
                    참고할 사람 라벨 사례를 찾지 못했습니다.
                  </div>
                )
              ) : (
                <div className="rounded-2xl border border-dashed border-white/10 bg-slate-950/20 px-4 py-8 text-sm text-slate-400">
                  분석 시 `사람 라벨 DB를 RAG로 참고`를 켜면 이 영역에 유사 사례가
                  표시됩니다.
                </div>
              )}
            </div>

            <div className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-xl font-semibold text-white">LLM 보조 판정</h2>
                <span className="text-sm text-slate-400">
                  {report?.llm_assessment?.model ?? "미사용"}
                </span>
              </div>

              {report?.llm_assessment ? (
                report.llm_assessment.error ? (
                  <div className="rounded-2xl border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
                    {report.llm_assessment.error}
                  </div>
                ) : (
                  <div className="space-y-4">
                    <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-4 text-sm leading-7 text-slate-300">
                      {report.llm_assessment.summary || "LLM 요약이 없습니다."}
                    </div>
                    {report.llm_assessment.reasoning?.length ? (
                      <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
                        <div className="text-sm font-medium text-slate-200">문맥 근거</div>
                        <div className="mt-3 space-y-2">
                          {report.llm_assessment.reasoning.slice(0, 3).map((item, index) => (
                            <div
                              className="rounded-xl bg-white/5 px-3 py-2 text-xs leading-6 text-slate-300"
                              key={`${item}-${index}`}
                            >
                              {index + 1}. {item}
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}

                    <div className="space-y-3">
                      <div className="text-sm font-medium text-slate-200">
                        추가 엔티티 후보
                      </div>
                      {report.llm_assessment.suggested_entities.length ? (
                        report.llm_assessment.suggested_entities.map((entity, index) => (
                          <div
                            className="rounded-2xl border border-white/10 bg-slate-950/40 px-4 py-3"
                            key={`${entity.label}-${entity.text}-${index}`}
                          >
                            <div className="text-xs text-cyan-200">{entity.label}</div>
                            <div className="mt-1 text-sm font-medium text-white">
                              {entity.text}
                            </div>
                            <div className="mt-1 text-xs text-slate-400">
                              신뢰도 {entity.confidence.toFixed(2)}
                            </div>
                            <div className="mt-2 text-xs leading-6 text-slate-400">
                              {entity.reason}
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="rounded-2xl border border-dashed border-white/10 bg-slate-950/20 px-4 py-6 text-sm text-slate-400">
                          추가 엔티티 제안이 없습니다.
                        </div>
                      )}
                    </div>

                    <div className="space-y-3">
                      <div className="text-sm font-medium text-slate-200">
                        추가 플래그 후보
                      </div>
                      {report.llm_assessment.suggested_flags.length ? (
                        report.llm_assessment.suggested_flags.map((flag, index) => (
                          <div
                            className="rounded-2xl border border-white/10 bg-slate-950/40 px-4 py-3"
                            key={`${flag.flag}-${index}`}
                          >
                            <div className="text-sm font-semibold text-white">
                              {flag.flag}
                            </div>
                            <div className="mt-1 text-xs text-slate-400">
                              신뢰도 {flag.confidence.toFixed(2)}
                            </div>
                            <div className="mt-2 text-sm leading-6 text-slate-300">
                              {flag.reason}
                            </div>
                            {flag.evidence ? (
                              <div className="mt-2 rounded-xl bg-white/5 px-3 py-2 text-xs leading-6 text-slate-400">
                                {flag.evidence}
                              </div>
                            ) : null}
                          </div>
                        ))
                      ) : (
                        <div className="rounded-2xl border border-dashed border-white/10 bg-slate-950/20 px-4 py-6 text-sm text-slate-400">
                          추가 플래그 제안이 없습니다.
                        </div>
                      )}
                    </div>
                  </div>
                )
              ) : (
                <div className="rounded-2xl border border-dashed border-white/10 bg-slate-950/20 px-4 py-8 text-sm text-slate-400">
                분석 시 `Claude LLM 보조 판정 사용`을 켜면 이 영역에 결과가
                표시됩니다.
              </div>
            )}
          </div>
          </div>
        </section>
      </div>
    </main>
  );
}
