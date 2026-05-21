"use client";

import Link from "next/link";
import { useEffect, useMemo, useState, type ReactNode } from "react";

type EntityItem = {
  text: string;
  label: string;
  score?: number;
  source?: string;
  start?: number;
  end?: number;
};

type FlagItem = {
  flag: string;
  description?: string;
  evidence?: string[];
  score_delta?: number;
  source?: string;
};

type AnnotationFlag = {
  flag: string;
  description?: string;
  evidence?: string;
  source?: string;
};

type ChatTurn = { role?: string; message?: string };
type QAPair = { question?: string; answer?: string };
type UserContext = {
  qa_pairs?: QAPair[];
  summary_text?: string;
  turn_count?: number;
};
type RunMedia = {
  kind?: string;
  original_filename?: string;
  stored_path?: string;
  size_bytes?: number;
  suffix?: string;
};

type RunMetadata = {
  user_context?: UserContext | null;
  chat_history?: ChatTurn[];
  refined_llm_assessment?: Record<string, unknown> | null;
  source_type?: string;
  media?: RunMedia | null;
  [key: string]: unknown;
};

type RunDetailResponse = {
  run: {
    id: string;
    created_at: string;
    input_source: string;
    whisper_model: string;
    skip_verification: boolean;
    use_llm: boolean;
    use_rag: boolean;
    transcript_text: string;
    classification_scanner: {
      scam_type: string;
      confidence: number;
      is_uncertain: boolean;
    };
    entities_predicted: EntityItem[];
    triggered_flags_predicted: FlagItem[];
    // DB 컬럼 호환 유지 — 값은 검출 신호 개수 (Stage 3 reframe), risk_level_predicted 는 deprecated.
    total_score_predicted: number;
    risk_level_predicted: string;
    metadata?: RunMetadata | null;
  };
  annotation: {
    labeler?: string | null;
    scam_type_gt: string;
    entities_gt: EntityItem[];
    triggered_flags_gt: AnnotationFlag[];
    transcript_corrected_text?: string | null;
    stt_quality?: number | null;
    notes?: string | null;
    content_label?: string | null;
    sample_kind?: string | null;
    source_ref?: string | null;
  } | null;
  options: {
    scam_types: string[];
    label_sets: Record<string, string[]>;
    flags: string[];
  };
  detail?: string;
};

type EditableEntity = EntityItem & {
  id: string;
  enabled: boolean;
};

type EditableFlag = AnnotationFlag & {
  id: string;
  enabled: boolean;
};

function makeId() {
  return crypto.randomUUID();
}

const VIDEO_SUFFIXES = new Set([".mp4", ".mov", ".webm", ".mkv"]);
const AUDIO_SUFFIXES = new Set([".mp3", ".m4a", ".wav", ".ogg", ".aac"]);
const IMAGE_SUFFIXES = new Set([".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"]);
const PDF_SUFFIXES = new Set([".pdf"]);

// content_label — Stage 1 게이트와 동일 어휘. scam_type 보다 먼저 선택하는 기준 라벨.
const SCAM_ATTEMPT = "scam_attempt";
const CONTENT_LABEL_OPTIONS: { value: string; label: string }[] = [
  { value: "normal", label: "정상 (normal)" },
  { value: "scam_attempt", label: "사기 시도 (scam_attempt)" },
  { value: "scam_news_edu", label: "사기 뉴스·교육 (scam_news_edu)" },
  { value: "suspicious_insufficient", label: "의심·불충분 (suspicious_insufficient)" },
  { value: "undetermined", label: "판단 불가 (undetermined)" },
];
const CONTENT_LABEL_VALUES = CONTENT_LABEL_OPTIONS.map((o) => o.value);

const SAMPLE_KIND_OPTIONS: { value: string; label: string }[] = [
  { value: "real_scam_message", label: "실제 사기 메시지 (real_scam_message)" },
  { value: "synthetic_scam_message", label: "합성 사기 메시지 (synthetic_scam_message)" },
  { value: "scam_news_education", label: "뉴스·교육 (scam_news_education)" },
  { value: "normal_content", label: "정상 콘텐츠 (normal_content)" },
  { value: "review_needed", label: "검수 필요 (review_needed)" },
];

// 기존 annotation 에 content_label 이 없을 때 fallback (백엔드 resolve_content_label 과 동일).
function resolveContentLabel(contentLabel: string, scamType: string): string {
  const cl = (contentLabel ?? "").trim();
  if (CONTENT_LABEL_VALUES.includes(cl)) return cl;
  const st = (scamType ?? "").trim();
  if (st && st !== "정상 대화") return SCAM_ATTEMPT;
  return "undetermined";
}

// sample_kind 미지정 시 content_label 로 추정.
function inferSampleKind(contentLabel: string): string {
  switch (contentLabel) {
    case "scam_attempt":
      return "real_scam_message";
    case "scam_news_edu":
      return "scam_news_education";
    case "normal":
      return "normal_content";
    default:
      return "review_needed";
  }
}

function isHttpUrl(value: string): boolean {
  return /^https?:\/\//i.test(value.trim());
}

function isYoutubeUrl(value: string): boolean {
  return /(?:youtube\.com\/|youtu\.be\/)/i.test(value);
}

function youtubeEmbedUrl(value: string): string | null {
  const m = value.match(/(?:v=|youtu\.be\/|embed\/)([\w-]{11})/);
  return m ? `https://www.youtube.com/embed/${m[1]}` : null;
}

function formatBytes(bytes?: number): string {
  if (!bytes || bytes <= 0) return "?";
  const units = ["B", "KB", "MB", "GB"];
  let value = bytes;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i += 1;
  }
  return `${value.toFixed(value >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

function formatPercent(value: number) {
  return new Intl.NumberFormat("ko-KR", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

function mapEntity(item: EntityItem): EditableEntity {
  return {
    id: makeId(),
    text: item.text ?? "",
    label: item.label ?? "",
    score: item.score,
    source: item.source ?? "human",
    start: item.start,
    end: item.end,
    enabled: true,
  };
}

function mapFlag(item: AnnotationFlag | FlagItem): EditableFlag {
  return {
    id: makeId(),
    flag: item.flag ?? "",
    description: item.description ?? "",
    evidence: Array.isArray(item.evidence) ? item.evidence.join(" | ") : item.evidence ?? "",
    source: item.source ?? "human",
    enabled: true,
  };
}

type TranscriptEntitySpan = {
  start: number;
  end: number;
  label: string;
  text: string;
};

function renderTranscriptWithEntityHighlights(
  transcript: string,
  spans: TranscriptEntitySpan[],
) {
  if (!transcript) return null;

  const sorted = [...spans]
    .filter((s) => Number.isFinite(s.start) && Number.isFinite(s.end) && s.end > s.start)
    .sort((a, b) => a.start - b.start || a.end - b.end);

  // 겹치는 span은 뒤에 오는 걸 스킵해서 UI가 깨지지 않게 한다.
  const nonOverlapping: TranscriptEntitySpan[] = [];
  for (const s of sorted) {
    const last = nonOverlapping[nonOverlapping.length - 1];
    if (!last || s.start >= last.end) {
      nonOverlapping.push(s);
    }
  }

  const parts: ReactNode[] = [];
  let idx = 0;
  nonOverlapping.forEach((s, i) => {
    if (s.start > idx) {
      parts.push(<span key={`t-${i}-pre`}>{transcript.slice(idx, s.start)}</span>);
    }
    parts.push(
      <mark
        key={`t-${i}-mark`}
        title={`[${s.label}] ${s.text}`}
        className="rounded-sm bg-cyan-500/20 px-0.5 text-cyan-100"
      >
        {transcript.slice(s.start, s.end)}
      </mark>,
    );
    idx = s.end;
  });

  if (idx < transcript.length) {
    parts.push(<span key="t-tail">{transcript.slice(idx)}</span>);
  }

  return <>{parts}</>;
}

export default function AdminRunEditor({ runId }: { runId: string }) {
  const [detail, setDetail] = useState<RunDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const [labeler, setLabeler] = useState("");
  const [scamType, setScamType] = useState("");
  const [entities, setEntities] = useState<EditableEntity[]>([]);
  const [flags, setFlags] = useState<EditableFlag[]>([]);
  const [transcriptCorrectedText, setTranscriptCorrectedText] = useState("");
  const [sttQuality, setSttQuality] = useState<string>("");
  const [notes, setNotes] = useState("");
  const [contentLabel, setContentLabel] = useState("");
  const [sampleKind, setSampleKind] = useState("");
  const [sourceRef, setSourceRef] = useState("");

  const [draftLoading, setDraftLoading] = useState(false);
  const [draftError, setDraftError] = useState("");
  const [draft, setDraft] = useState<{
    scam_type: string;
    entities: { text: string; label: string }[];
    flags: { flag: string; description: string; evidence: string }[];
    reasoning: string;
  } | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setLoading(true);
      setError("");
      setSuccess("");

      try {
        const response = await fetch(`/api/admin/runs/${runId}`, {
          cache: "no-store",
        });
        const data = (await response.json()) as RunDetailResponse;

        if (!response.ok) {
          throw new Error(data.detail ?? "run 상세를 불러오지 못했습니다.");
        }

        if (cancelled) {
          return;
        }

        setDetail(data);
        const initialScamType =
          data.annotation?.scam_type_gt ??
          data.run.classification_scanner.scam_type ??
          data.options.scam_types[0] ??
          "";
        setScamType(initialScamType);
        // content_label 우선 — 없으면 scam_type 으로 fallback (화면 깨짐 방지).
        const initialContentLabel = resolveContentLabel(
          data.annotation?.content_label ?? "",
          data.annotation?.scam_type_gt ??
            data.run.classification_scanner.scam_type ??
            "",
        );
        setContentLabel(initialContentLabel);
        setSampleKind(
          (data.annotation?.sample_kind ?? "").trim() ||
            inferSampleKind(initialContentLabel),
        );
        setSourceRef(data.annotation?.source_ref ?? "");
        setLabeler(data.annotation?.labeler ?? "");
        setTranscriptCorrectedText(
          data.annotation?.transcript_corrected_text ?? data.run.transcript_text,
        );
        setSttQuality(
          data.annotation?.stt_quality ? String(data.annotation.stt_quality) : "",
        );
        setNotes(data.annotation?.notes ?? "");
        setEntities(
          (
            data.annotation?.entities_gt.length
              ? data.annotation.entities_gt
              : data.run.entities_predicted
          ).map(mapEntity),
        );
        setFlags(
          (
            data.annotation?.triggered_flags_gt.length
              ? data.annotation.triggered_flags_gt
              : data.run.triggered_flags_predicted
          ).map(mapFlag),
        );
      } catch (loadError) {
        if (!cancelled) {
          setError(
            loadError instanceof Error
              ? loadError.message
              : "run 상세를 불러오지 못했습니다.",
          );
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [runId]);

  const availableLabels = useMemo(() => {
    if (!detail) {
      return [];
    }
    return detail.options.label_sets[scamType] ?? [];
  }, [detail, scamType]);

  // scam_type 선택은 content_label == scam_attempt 일 때만 활성.
  const isScamAttempt = contentLabel === SCAM_ATTEMPT;

  async function saveAnnotation() {
    setSaving(true);
    setError("");
    setSuccess("");

    try {
      const response = await fetch(`/api/admin/runs/${runId}/annotations`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          labeler: labeler.trim() || null,
          content_label: contentLabel,
          sample_kind: sampleKind,
          source_ref: sourceRef.trim() || null,
          // scam_type 은 content_label == scam_attempt 일 때만 — API validator 와 일치.
          scam_type_gt: contentLabel === SCAM_ATTEMPT ? scamType : "",
          entities_gt: entities
            .filter((item) => item.enabled && item.text.trim() && item.label.trim())
            .map((item) => ({
              text: item.text.trim(),
              label: item.label.trim(),
              score: item.score,
              source: item.source,
              start: item.start,
              end: item.end,
            })),
          triggered_flags_gt: flags
            .filter((item) => item.enabled && item.flag.trim())
            .map((item) => ({
              flag: item.flag.trim(),
              description: item.description?.trim() ?? "",
              evidence: item.evidence?.trim() ?? "",
              source: item.source,
            })),
          transcript_corrected_text: transcriptCorrectedText.trim() || null,
          stt_quality: sttQuality ? Number(sttQuality) : null,
          notes,
        }),
      });

      const data = (await response.json()) as {
        ok?: boolean;
        detail?: string;
      };
      if (!response.ok) {
        throw new Error(data.detail ?? "라벨 저장에 실패했습니다.");
      }

      setSuccess("라벨이 저장되었습니다.");
    } catch (saveError) {
      setError(
        saveError instanceof Error
          ? saveError.message
          : "라벨 저장에 실패했습니다.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function generateDraft() {
    setDraftLoading(true);
    setDraftError("");
    setDraft(null);

    try {
      const response = await fetch(`/api/admin/runs/${runId}/ai-draft`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = (await response.json()) as {
        ok?: boolean;
        draft?: typeof draft;
        detail?: string;
      };
      if (!response.ok) {
        throw new Error(data.detail ?? "AI 초안 생성에 실패했습니다.");
      }
      setDraft(data.draft ?? null);
    } catch (err) {
      setDraftError(err instanceof Error ? err.message : "AI 초안 생성에 실패했습니다.");
    } finally {
      setDraftLoading(false);
    }
  }

  function applyDraft() {
    if (!draft || !detail) return;

    // AI 초안은 scam_type 기반 — 적용 시 content_label 을 scam_attempt 로 둔다.
    setContentLabel(SCAM_ATTEMPT);
    if (detail.options.scam_types.includes(draft.scam_type)) {
      setScamType(draft.scam_type);
    }

    const availableLabelsForDraft = detail.options.label_sets[draft.scam_type] ?? [];
    setEntities(
      draft.entities
        .filter((e) => e.text.trim() && availableLabelsForDraft.includes(e.label))
        .map((e) => ({
          id: makeId(),
          text: e.text,
          label: e.label,
          enabled: true,
          source: "ai-draft",
        })),
    );

    setFlags(
      draft.flags
        .filter((f) => detail.options.flags.includes(f.flag))
        .map((f) => ({
          id: makeId(),
          flag: f.flag,
          description: f.description,
          evidence: f.evidence,
          enabled: true,
          source: "ai-draft",
        })),
    );
  }

  if (loading) {
    return (
      <div className="rounded-3xl border border-white/10 bg-white/5 p-6 text-sm text-slate-300">
        불러오는 중...
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="rounded-3xl border border-rose-400/30 bg-rose-500/10 p-6 text-sm text-rose-100">
        {error || "run 정보를 찾지 못했습니다."}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-sm uppercase tracking-[0.2em] text-cyan-200">
            Label Run
          </div>
          <h1 className="mt-2 text-3xl font-semibold text-white">
            {detail.run.id}
          </h1>
        </div>
        <div className="flex flex-wrap gap-3">
          <Link
            className="rounded-2xl border border-white/10 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/5"
            href="/admin"
          >
            목록으로
          </Link>
          <button
            className="rounded-2xl border border-fuchsia-400/30 bg-fuchsia-500/10 px-4 py-2 text-sm font-semibold text-fuchsia-200 transition hover:bg-fuchsia-500/20 disabled:cursor-not-allowed disabled:opacity-50"
            disabled={draftLoading}
            onClick={() => void generateDraft()}
            type="button"
          >
            {draftLoading ? "Claude 분석 중..." : "AI 초안 생성"}
          </button>
          <button
            className="rounded-2xl bg-cyan-300 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:cursor-not-allowed disabled:bg-slate-700 disabled:text-slate-400"
            disabled={saving}
            onClick={() => void saveAnnotation()}
            type="button"
          >
            {saving ? "저장 중..." : "라벨 저장"}
          </button>
        </div>
      </div>

      {error ? (
        <div className="rounded-2xl border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
          {error}
        </div>
      ) : null}
      {success ? (
        <div className="rounded-2xl border border-emerald-400/30 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100">
          {success}
        </div>
      ) : null}

      {draftError ? (
        <div className="rounded-2xl border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
          {draftError}
        </div>
      ) : null}

      {draft ? (
        <section className="rounded-3xl border border-fuchsia-400/20 bg-fuchsia-500/5 p-6 backdrop-blur">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div>
              <div className="text-sm font-semibold text-fuchsia-200">Claude AI 초안</div>
              <div className="mt-1 text-sm leading-6 text-slate-300">{draft.reasoning}</div>
            </div>
            <button
              className="rounded-2xl bg-fuchsia-400 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-fuchsia-300"
              onClick={applyDraft}
              type="button"
            >
              초안 전체 적용
            </button>
          </div>

          <div className="grid gap-4 lg:grid-cols-2">
            <div>
              <div className="mb-2 text-xs font-medium uppercase tracking-widest text-slate-400">
                제안 스캠 유형
              </div>
              <div className="rounded-2xl border border-white/10 bg-slate-950/40 px-4 py-3 text-sm font-semibold text-white">
                {draft.scam_type}
              </div>
            </div>

            <div>
              <div className="mb-2 text-xs font-medium uppercase tracking-widest text-slate-400">
                제안 엔티티 ({draft.entities.length}개)
              </div>
              <div className="flex flex-wrap gap-2">
                {draft.entities.length ? (
                  draft.entities.map((e, i) => (
                    <span
                      className="rounded-full border border-fuchsia-400/20 bg-fuchsia-500/10 px-3 py-1 text-xs text-fuchsia-200"
                      key={`draft-e-${i}`}
                    >
                      [{e.label}] {e.text}
                    </span>
                  ))
                ) : (
                  <span className="text-sm text-slate-400">제안 없음</span>
                )}
              </div>
            </div>

            <div className="lg:col-span-2">
              <div className="mb-2 text-xs font-medium uppercase tracking-widest text-slate-400">
                제안 플래그 ({draft.flags.length}개)
              </div>
              <div className="space-y-2">
                {draft.flags.length ? (
                  draft.flags.map((f, i) => (
                    <div
                      className="rounded-2xl border border-fuchsia-400/20 bg-slate-950/40 px-4 py-3"
                      key={`draft-f-${i}`}
                    >
                      <div className="text-sm font-semibold text-white">{f.flag}</div>
                      <div className="mt-1 text-xs text-slate-300">{f.description}</div>
                      {f.evidence ? (
                        <div className="mt-2 rounded-xl bg-white/5 px-3 py-1.5 text-xs text-slate-400">
                          &ldquo;{f.evidence}&rdquo;
                        </div>
                      ) : null}
                    </div>
                  ))
                ) : (
                  <span className="text-sm text-slate-400">제안 없음</span>
                )}
              </div>
            </div>
          </div>
        </section>
      ) : null}

      {(() => {
        const metadata = (detail.run.metadata ?? {}) as RunMetadata;
        const userCtx = metadata.user_context ?? null;
        const chatHistory = metadata.chat_history ?? [];
        const qaPairs = userCtx?.qa_pairs ?? [];
        const hasUserCtx = qaPairs.length > 0;
        const hasChat = chatHistory.length > 0;
        if (!hasUserCtx && !hasChat) return null;
        return (
          <section className="space-y-4">
            {hasUserCtx ? (
              <div className="rounded-3xl border border-fuchsia-400/30 bg-fuchsia-500/5 p-6 backdrop-blur">
                <div className="mb-3 flex items-center gap-2">
                  <div className="text-lg font-semibold text-fuchsia-200">
                    💡 사용자 제공 정보
                  </div>
                  <span className="rounded bg-fuchsia-500/20 px-2 py-0.5 text-xs text-fuchsia-200">
                    분석에 prior 로 반영됨
                  </span>
                </div>
                <p className="mb-3 text-xs text-fuchsia-200/70">
                  사용자가 챗봇과 대화하며 직접 알려준 컨텍스트입니다. 라벨링 시 참고하세요.
                </p>
                <ol className="space-y-2">
                  {qaPairs.map((qa, idx) => (
                    <li key={idx} className="rounded-lg bg-fuchsia-950/40 p-3">
                      {qa.question ? (
                        <div className="text-xs text-fuchsia-300/80">Q. {qa.question}</div>
                      ) : null}
                      <div className="mt-1 text-sm text-fuchsia-100">A. {qa.answer ?? ""}</div>
                    </li>
                  ))}
                </ol>
              </div>
            ) : null}
            {hasChat ? (
              <div className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
                <div className="mb-3 text-lg font-semibold text-white">
                  💬 챗봇 대화 전체
                  <span className="ml-2 text-xs text-slate-400">({chatHistory.length}턴)</span>
                </div>
                <details>
                  <summary className="cursor-pointer text-sm text-slate-400 hover:text-slate-200">
                    펼쳐서 보기
                  </summary>
                  <ol className="mt-3 space-y-2">
                    {chatHistory.map((t, idx) => (
                      <li
                        key={idx}
                        className={
                          t.role === "user"
                            ? "ml-8 rounded bg-blue-900/30 p-2 text-sm text-blue-100"
                            : "rounded bg-slate-800/40 p-2 text-sm text-slate-200"
                        }
                      >
                        <div className="text-xs text-slate-400">
                          {t.role === "user" ? "👤 사용자" : "🤖 챗봇"}
                        </div>
                        <div className="mt-1 whitespace-pre-wrap">{t.message ?? ""}</div>
                      </li>
                    ))}
                  </ol>
                </details>
              </div>
            ) : null}
          </section>
        );
      })()}

      {(() => {
        const inputSource = detail.run.input_source ?? "";
        const media = (detail.run.metadata ?? {}).media ?? null;
        const hasMedia = !!media?.stored_path;
        const sourceLooksLikeUrl = inputSource && isHttpUrl(inputSource);
        if (!hasMedia && !sourceLooksLikeUrl) return null;

        const mediaUrl = hasMedia ? `/api/admin/runs/${runId}/media` : null;
        const suffix = (media?.suffix ?? "").toLowerCase();
        const isVideo = VIDEO_SUFFIXES.has(suffix);
        const isAudio = AUDIO_SUFFIXES.has(suffix);
        const isImage = IMAGE_SUFFIXES.has(suffix);
        const isPdf = PDF_SUFFIXES.has(suffix);
        const ytEmbed = sourceLooksLikeUrl && isYoutubeUrl(inputSource)
          ? youtubeEmbedUrl(inputSource)
          : null;

        return (
          <section className="rounded-3xl border border-cyan-400/20 bg-cyan-500/5 p-6 backdrop-blur">
            <div className="mb-3 flex items-center gap-2">
              <div className="text-lg font-semibold text-cyan-100">🎞 원본 미디어</div>
              <span className="rounded bg-cyan-500/20 px-2 py-0.5 text-xs text-cyan-100">
                STT 외 라벨러 직접 검증용
              </span>
            </div>

            {sourceLooksLikeUrl ? (
              <div className="mb-4 space-y-2 text-sm">
                <div className="text-xs text-slate-400">입력 URL</div>
                <a
                  href={inputSource}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="block break-all text-cyan-200 underline-offset-2 hover:underline"
                >
                  {inputSource}
                </a>
                {ytEmbed ? (
                  <div className="mt-3 aspect-video w-full overflow-hidden rounded-xl border border-white/10 bg-black">
                    <iframe
                      src={ytEmbed}
                      title="YouTube 미리보기"
                      allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                      allowFullScreen
                      className="h-full w-full"
                    />
                  </div>
                ) : null}
              </div>
            ) : null}

            {hasMedia && mediaUrl ? (
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
                  <span>저장된 원본:</span>
                  <span className="rounded bg-slate-950/40 px-2 py-0.5 font-mono text-slate-200">
                    {media?.original_filename ?? "source"}
                  </span>
                  <span>· {formatBytes(media?.size_bytes)}</span>
                  <a
                    href={mediaUrl}
                    download={media?.original_filename ?? undefined}
                    className="ml-auto rounded-lg border border-white/10 px-2 py-1 text-slate-200 transition hover:bg-white/5"
                  >
                    다운로드
                  </a>
                </div>
                {isVideo ? (
                  <video
                    controls
                    preload="metadata"
                    src={mediaUrl}
                    className="w-full rounded-xl border border-white/10 bg-black"
                  />
                ) : isAudio ? (
                  <audio controls preload="metadata" src={mediaUrl} className="w-full" />
                ) : isImage ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={mediaUrl}
                    alt={media?.original_filename ?? "uploaded image"}
                    className="max-h-[600px] w-full rounded-xl border border-white/10 bg-slate-950/40 object-contain"
                  />
                ) : isPdf ? (
                  <iframe
                    src={mediaUrl}
                    title="PDF 미리보기"
                    className="h-[80vh] w-full rounded-xl border border-white/10 bg-slate-950/40"
                  />
                ) : (
                  <div className="rounded-xl border border-white/10 bg-slate-950/40 px-4 py-3 text-xs text-slate-400">
                    이 형식({suffix || "?"})은 브라우저 미리보기를 지원하지 않을 수 있어요. 다운로드 후 확인해 주세요.
                  </div>
                )}
              </div>
            ) : null}
          </section>
        );
      })()}

      <section className="grid gap-6 lg:grid-cols-[1fr_1fr]">
        <div className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
          <div className="mb-4 text-lg font-semibold text-white">원본 정보</div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
              <div className="text-sm text-slate-400">예측 스캠 유형</div>
              <div className="mt-2 text-xl font-semibold text-white">
                {detail.run.classification_scanner.scam_type}
              </div>
              <div className="mt-2 text-sm text-slate-300">
                신뢰도 {formatPercent(detail.run.classification_scanner.confidence)}
              </div>
            </div>
            <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
              <div className="text-sm text-slate-400">검출 신호</div>
              <div className="mt-2 text-xl font-semibold text-white">
                {detail.run.total_score_predicted}개
              </div>
              <div className="mt-2 text-xs text-slate-500">
                (판정 X — 검출 사실만)
              </div>
            </div>
          </div>

          <div className="mt-4 rounded-2xl border border-white/10 bg-slate-950/40 p-4 text-sm leading-7 text-slate-300">
            <div className="mb-2 text-sm font-medium text-slate-200">원본 transcript</div>
            <div className="max-h-96 overflow-auto whitespace-pre-wrap break-words font-mono text-xs text-slate-200">
              {renderTranscriptWithEntityHighlights(
                detail.run.transcript_text,
                entities
                  .filter(
                    (e) =>
                      e.enabled &&
                      typeof e.start === "number" &&
                      typeof e.end === "number" &&
                      e.text.trim().length > 0,
                  )
                  .map((e) => ({
                    start: e.start as number,
                    end: e.end as number,
                    label: e.label,
                    text: e.text,
                  })),
              )}
            </div>
          </div>

          <div className="mt-4 space-y-3">
            <div className="text-sm font-medium text-slate-200">예측 엔티티</div>
            <div className="flex flex-wrap gap-2">
              {detail.run.entities_predicted.map((entity, index) => (
                <span
                  className="rounded-full border border-white/10 bg-slate-950/40 px-3 py-1 text-sm text-slate-200"
                  key={`${entity.label}-${entity.text}-${index}`}
                >
                  [{entity.label}] {entity.text}
                </span>
              ))}
            </div>
          </div>

          <div className="mt-4 space-y-3">
            <div className="text-sm font-medium text-slate-200">예측 플래그</div>
            <div className="flex flex-col gap-2">
              {detail.run.triggered_flags_predicted.length ? (
                detail.run.triggered_flags_predicted.map((flag, index) => (
                  <div
                    className="rounded-2xl border border-white/10 bg-slate-950/40 px-4 py-3 text-sm text-slate-200"
                    key={`${flag.flag}-${index}`}
                  >
                    <div className="font-medium">{flag.flag}</div>
                    <div className="mt-1 text-slate-400">{flag.description}</div>
                  </div>
                ))
              ) : (
                <div className="text-sm text-slate-400">예측 플래그 없음</div>
              )}
            </div>
          </div>
        </div>

        <div className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
          <div className="mb-4 text-lg font-semibold text-white">정답 라벨 편집</div>

          {/* 1단계: content_label — scam_type 보다 먼저 선택하는 기준 라벨 */}
          <div className="grid gap-4 sm:grid-cols-2">
            <label className="space-y-2 text-sm text-slate-300">
              <span className="block">콘텐츠 라벨 (content_label)</span>
              <select
                className="w-full rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 text-slate-100 outline-none focus:border-cyan-400/50"
                onChange={(event) => setContentLabel(event.target.value)}
                value={contentLabel}
              >
                {CONTENT_LABEL_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="space-y-2 text-sm text-slate-300">
              <span className="block">샘플 종류 (sample_kind)</span>
              <select
                className="w-full rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 text-slate-100 outline-none focus:border-cyan-400/50"
                onChange={(event) => setSampleKind(event.target.value)}
                value={sampleKind}
              >
                {SAMPLE_KIND_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
          </div>

          {/* 2단계: scam_type — content_label == scam_attempt 일 때만 활성 */}
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <label className="space-y-2 text-sm text-slate-300">
              <span className="block">
                정답 스캠 유형
                {isScamAttempt ? null : (
                  <span className="ml-2 text-xs text-slate-500">
                    — content_label 이 scam_attempt 일 때만 선택
                  </span>
                )}
              </span>
              <select
                className="w-full rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 text-slate-100 outline-none focus:border-cyan-400/50 disabled:cursor-not-allowed disabled:opacity-40"
                disabled={!isScamAttempt}
                onChange={(event) => setScamType(event.target.value)}
                value={scamType}
              >
                {detail.options.scam_types.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </select>
            </label>

            <label className="space-y-2 text-sm text-slate-300">
              <span className="block">검수자</span>
              <input
                className="w-full rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 text-slate-100 outline-none focus:border-cyan-400/50"
                onChange={(event) => setLabeler(event.target.value)}
                placeholder="이름 또는 닉네임"
                value={labeler}
              />
            </label>
          </div>

          <label className="mt-4 block space-y-2 text-sm text-slate-300">
            <span className="block">
              출처 참조 (source_ref)
              <span className="ml-2 text-xs text-slate-500">
                — synthetic 샘플의 원본 뉴스 URL 등 (선택)
              </span>
            </span>
            <input
              className="w-full rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 text-slate-100 outline-none focus:border-cyan-400/50"
              onChange={(event) => setSourceRef(event.target.value)}
              placeholder="https://news.example.com/..."
              value={sourceRef}
            />
          </label>

          <label className="mt-4 block space-y-2 text-sm text-slate-300">
            <span className="block">교정 transcript</span>
            <textarea
              className="min-h-40 w-full rounded-2xl border border-white/10 bg-slate-900/80 px-4 py-3 text-sm text-slate-100 outline-none focus:border-cyan-400/50"
              onChange={(event) => setTranscriptCorrectedText(event.target.value)}
              value={transcriptCorrectedText}
            />
          </label>

          {(() => {
            const sourceType = (detail.run.metadata?.source_type ?? "").toString().toLowerCase();
            const isTextInput = sourceType === "text";
            return (
              <div className={`mt-4 grid gap-4 ${isTextInput ? "" : "sm:grid-cols-2"}`}>
                {isTextInput ? null : (
                  <label className="space-y-2 text-sm text-slate-300">
                    <span className="block">STT 품질(1~5)</span>
                    <select
                      className="w-full rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 text-slate-100 outline-none focus:border-cyan-400/50"
                      onChange={(event) => setSttQuality(event.target.value)}
                      value={sttQuality}
                    >
                      <option value="">선택 안 함</option>
                      <option value="1">1</option>
                      <option value="2">2</option>
                      <option value="3">3</option>
                      <option value="4">4</option>
                      <option value="5">5</option>
                    </select>
                  </label>
                )}

                <label className="space-y-2 text-sm text-slate-300">
                  <span className="block">메모</span>
                  <input
                    className="w-full rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 text-slate-100 outline-none focus:border-cyan-400/50"
                    onChange={(event) => setNotes(event.target.value)}
                    placeholder="판단 근거 메모"
                    value={notes}
                  />
                </label>
              </div>
            );
          })()}
        </div>
      </section>

      <section className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
        <div className="mb-4 flex items-center justify-between gap-4">
          <div className="text-lg font-semibold text-white">정답 엔티티</div>
          <button
            className="rounded-2xl border border-white/10 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/5"
            onClick={() =>
              setEntities((current) => [
                ...current,
                {
                  id: makeId(),
                  text: "",
                  label: availableLabels[0] ?? "",
                  enabled: true,
                  source: "human",
                },
              ])
            }
            type="button"
          >
            엔티티 추가
          </button>
        </div>

        <div className="space-y-3">
          {entities.map((entity, index) => {
            const labelOptions = entity.label && !availableLabels.includes(entity.label)
              ? [entity.label, ...availableLabels]
              : availableLabels;

            return (
              <div
                className="grid gap-3 rounded-2xl border border-white/10 bg-slate-950/40 p-4 lg:grid-cols-[auto_1.2fr_1fr_auto]"
                key={entity.id}
              >
                <label className="flex items-center gap-2 text-sm text-slate-300">
                  <input
                    checked={entity.enabled}
                    className="h-4 w-4 accent-cyan-300"
                    onChange={(event) =>
                      setEntities((current) =>
                        current.map((item) =>
                          item.id === entity.id
                            ? { ...item, enabled: event.target.checked }
                            : item,
                        ),
                      )
                    }
                    type="checkbox"
                  />
                  사용
                </label>
                <input
                  className="rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400/50"
                  onChange={(event) =>
                    setEntities((current) =>
                      current.map((item) =>
                        item.id === entity.id
                          ? { ...item, text: event.target.value }
                          : item,
                      ),
                    )
                  }
                  placeholder="엔티티 텍스트"
                  value={entity.text}
                />
                <select
                  className="rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400/50"
                  onChange={(event) =>
                    setEntities((current) =>
                      current.map((item) =>
                        item.id === entity.id
                          ? { ...item, label: event.target.value }
                          : item,
                      ),
                    )
                  }
                  value={entity.label}
                >
                  {labelOptions.map((option) => (
                    <option key={`${entity.id}-${option}`} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
                <button
                  className="rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-300 transition hover:bg-white/5"
                  onClick={() =>
                    setEntities((current) =>
                      current.filter((item) => item.id !== entity.id),
                    )
                  }
                  type="button"
                >
                  삭제
                </button>
                <div className="text-xs text-slate-500 lg:col-start-2 lg:col-end-5">
                  #{index + 1} source: {entity.source ?? "human"}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
        <div className="mb-4 flex items-center justify-between gap-4">
          <div className="text-lg font-semibold text-white">정답 플래그</div>
          <button
            className="rounded-2xl border border-white/10 px-4 py-2 text-sm text-slate-200 transition hover:bg-white/5"
            onClick={() =>
              setFlags((current) => [
                ...current,
                {
                  id: makeId(),
                  flag: detail.options.flags[0] ?? "",
                  description: "",
                  evidence: "",
                  enabled: true,
                  source: "human",
                },
              ])
            }
            type="button"
          >
            플래그 추가
          </button>
        </div>

        {contentLabel === "scam_news_edu" ? (
          <div className="mb-4 rounded-2xl border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-xs leading-5 text-amber-100">
            ⚠️ 이 콘텐츠는 <strong>사기 뉴스·교육(scam_news_edu)</strong>입니다. 아래 플래그는
            “보도·교육에서 <strong>언급된</strong> 위험 신호”이며, 현재 입력이 실제로 실행 중인
            사기 신호가 아닙니다.
          </div>
        ) : null}

        <div className="space-y-3">
          {flags.map((flag) => {
            const flagOptions = flag.flag && !detail.options.flags.includes(flag.flag)
              ? [flag.flag, ...detail.options.flags]
              : detail.options.flags;

            return (
              <div
                className="grid gap-3 rounded-2xl border border-white/10 bg-slate-950/40 p-4 lg:grid-cols-[auto_1fr_1fr_1.2fr_auto]"
                key={flag.id}
              >
                <label className="flex items-center gap-2 text-sm text-slate-300">
                  <input
                    checked={flag.enabled}
                    className="h-4 w-4 accent-cyan-300"
                    onChange={(event) =>
                      setFlags((current) =>
                        current.map((item) =>
                          item.id === flag.id
                            ? { ...item, enabled: event.target.checked }
                            : item,
                        ),
                      )
                    }
                    type="checkbox"
                  />
                  사용
                </label>
                <select
                  className="rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400/50"
                  onChange={(event) =>
                    setFlags((current) =>
                      current.map((item) =>
                        item.id === flag.id
                          ? { ...item, flag: event.target.value }
                          : item,
                      ),
                    )
                  }
                  value={flag.flag}
                >
                  {flagOptions.map((option) => (
                    <option key={`${flag.id}-${option}`} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
                <input
                  className="rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400/50"
                  onChange={(event) =>
                    setFlags((current) =>
                      current.map((item) =>
                        item.id === flag.id
                          ? { ...item, description: event.target.value }
                          : item,
                      ),
                    )
                  }
                  placeholder="설명"
                  value={flag.description ?? ""}
                />
                <input
                  className="rounded-xl border border-white/10 bg-slate-900/80 px-3 py-2 text-sm text-slate-100 outline-none focus:border-cyan-400/50"
                  onChange={(event) =>
                    setFlags((current) =>
                      current.map((item) =>
                        item.id === flag.id
                          ? { ...item, evidence: event.target.value }
                          : item,
                      ),
                    )
                  }
                  placeholder="근거 문구"
                  value={flag.evidence ?? ""}
                />
                <button
                  className="rounded-xl border border-white/10 px-3 py-2 text-sm text-slate-300 transition hover:bg-white/5"
                  onClick={() =>
                    setFlags((current) => current.filter((item) => item.id !== flag.id))
                  }
                  type="button"
                >
                  삭제
                </button>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}

