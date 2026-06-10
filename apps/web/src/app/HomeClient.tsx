"use client";

import Link from "next/link";
import { signIn } from "next-auth/react";
import { FormEvent, ReactNode, useEffect, useMemo, useState } from "react";

import {
  GUEST_DAILY_LIMIT,
  bumpGuestDaily,
  guestOverDailyLimit,
} from "./guestLimit";
import {
  blockForInjection,
  injectionBlockRemainingMs,
  looksLikeInjection,
} from "./injectionGuard";

// 비회원 분석 횟수 누적 키 + 로그인 권유 임계치 (이 횟수 이상부터 권유 모달)
const GUEST_COUNT_KEY = "sg_guest_analysis_count";
const GUEST_PROMPT_THRESHOLD = 3;

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
      chip: "border-sky-500/40 bg-sky-700/20 text-sky-700",
    };
  }
  if (bucket === "normal") {
    return {
      icon: "✅",
      label: "정상 콘텐츠",
      chip: "border-emerald-500/40 bg-emerald-700/20 text-emerald-700",
    };
  }
  // undetermined 는 Phase 2 (scam_type 분류) 가 실행된 버킷이라
  // scam_type 카드를 대체하지 않고 기존 결과 그대로 보여준다.
  return null;
}

const EXAMPLE_INPUT =
  "일론 머스크가 화성 이민 프로젝트에 300만원 투자하면 연 30% 수익을 보장한다고 합니다. 문의는 010-1234-5678로 하라고 합니다.";

const EXAMPLE_VIDEO_URL = "https://youtube.com/watch?v=dQw4w9WgXcQ";

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
    ? "bg-fuchsia-500/15 text-fuchsia-700 ring-1 ring-fuchsia-500/30"
    : "bg-[#e8f3ff] text-[#3182f6] ring-1 ring-[#3182f6]/30";
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
        ? "rounded-sm bg-[#dbeafe] px-0.5 text-[#1b64da]"
        : "rounded-sm bg-amber-500/20 px-0.5 text-amber-700";
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

export default function HomeClient({ isGuest = false }: { isGuest?: boolean }) {
  const [source, setSource] = useState(EXAMPLE_INPUT);
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [skipVerification, setSkipVerification] = useState(true);
  const [useRag, setUseRag] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [report, setReport] = useState<AnalysisReport | null>(null);
  const [sttBackend, setSttBackend] = useState<string | null>(null);
  const [showDetails, setShowDetails] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const [loginPromptOpen, setLoginPromptOpen] = useState(false);
  const [limitBlockOpen, setLimitBlockOpen] = useState(false);
  const [injectionBlocked, setInjectionBlocked] = useState(false);
  // 진입 후 분석 방식 선택 허브: null = 허브 화면, 'content' = 콘텐츠 입력 폼
  // (통화는 /live, APK는 /apk 별도 페이지 → 허브에서 Link 이동)
  const [mode, setMode] = useState<"content" | null>(null);

  // 허브에서 "콘텐츠 분석" 선택 → 입력 폼으로 전환 (텍스트·유튜브 URL·파일 한 폼)
  function pickContent() {
    setSource("");
    setUploadFile(null);
    setError("");
    setMode("content");
  }
  function backToHub() {
    setMode(null);
    setError("");
  }

  // 모달 열렸을 때 ESC 로 닫기 + 배경 스크롤 잠금
  useEffect(() => {
    if (!modalOpen && !loginPromptOpen && !limitBlockOpen && !injectionBlocked) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      if (injectionBlocked) setInjectionBlocked(false);
      else if (limitBlockOpen) setLimitBlockOpen(false);
      else if (loginPromptOpen) setLoginPromptOpen(false);
      else if (showDetails) setShowDetails(false);
      else setModalOpen(false);
    };
    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [modalOpen, loginPromptOpen, limitBlockOpen, injectionBlocked, showDetails]);

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

    // 이미 프롬프트 우회로 접근 제한된 상태면 즉시 차단
    if (injectionBlockRemainingMs() > 0) {
      setInjectionBlocked(true);
      return;
    }

    const trimmedSource = source.trim();
    if (!uploadFile && !trimmedSource) {
      setError("텍스트/유튜브 URL을 입력하거나 영상 파일을 업로드해주세요.");
      return;
    }

    // 프롬프트 우회(인젝션) 시도 감지 → 즉시 접근 제한 (분석 미실행)
    if (!uploadFile && looksLikeInjection(trimmedSource)) {
      blockForInjection();
      setInjectionBlocked(true);
      return;
    }

    // 비회원 일일 한도(홈+라이브 합산) 초과 시 분석 자체 차단
    if (isGuest && guestOverDailyLimit()) {
      setLimitBlockOpen(true);
      return;
    }

    setLoading(true);
    setShowDetails(false);
    setModalOpen(false);
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
      setShowDetails(false);

      // 비회원이면 분석 횟수 누적 → 임계 이상이면 결과 대신 로그인 권유 먼저
      let promptLogin = false;
      if (isGuest) {
        bumpGuestDaily(); // 오늘 한도 카운트(홈+라이브 합산)에 이번 실행 반영
        let count = 0;
        try {
          count = Number(window.localStorage.getItem(GUEST_COUNT_KEY) || "0") || 0;
        } catch {
          count = 0;
        }
        count += 1;
        try {
          window.localStorage.setItem(GUEST_COUNT_KEY, String(count));
        } catch {
          /* localStorage 불가 시 무시 */
        }
        promptLogin = count >= GUEST_PROMPT_THRESHOLD;
      }

      if (promptLogin) {
        setLoginPromptOpen(true);
      } else {
        setModalOpen(true);
      }
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
    <main className="min-h-screen bg-[#f2f4f6] px-6 py-10 text-[#191f28]">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-8">
        <section className="rounded-3xl border border-[#e5e8eb] bg-white p-8 shadow-[0_2px_12px_rgba(0,0,0,0.05)]">
          <div className="mb-7 flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-[#e8f3ff] px-3 py-1 text-xs font-bold tracking-[0.08em] text-[#3182f6]">
              ScamGuardian
            </span>
            <Link
              className="rounded-full border border-[#e5e8eb] px-3 py-1 text-xs text-[#4e5968] transition hover:bg-[#f2f4f6]"
              href="/evidence"
            >
              📚 근거
            </Link>
          </div>

          {mode === null ? (
            <div className="flex flex-col gap-3.5">
              <div className="mb-1">
                <h1 className="text-2xl font-bold tracking-tight text-[#191f28]">무엇을 분석할까요?</h1>
                <p className="mt-2 text-sm leading-6 text-[#4e5968]">
                  분석할 종류를 선택하면 바로 해당 화면으로 이동해요. 통화 중이라면 실시간 통화 분석을 추천해요.
                </p>
              </div>

              {/* 통화 분석 — 실시간이 핵심 */}
              <Link
                href="/live"
                className="group flex items-center gap-5 rounded-2xl border border-[#e5e8eb] bg-white p-6 shadow-[0_2px_12px_rgba(0,0,0,0.05)] transition hover:border-[#3182f6] hover:shadow-[0_6px_20px_rgba(49,130,246,0.12)]"
              >
                <span className="flex h-14 w-14 flex-shrink-0 items-center justify-center rounded-2xl bg-[#e8f3ff] text-3xl">🎙️</span>
                <span className="min-w-0 flex-1">
                  <span className="block text-lg font-bold text-[#191f28]">통화 분석</span>
                  <span className="mt-1 block text-sm leading-6 text-[#4e5968]">
                    통화 중 마이크를 켜면 위험 신호를 실시간으로 감지해요. 녹음 파일도 분석할 수 있어요.
                  </span>
                </span>
                <span className="flex flex-shrink-0 items-center gap-1.5 whitespace-nowrap text-sm font-semibold text-[#8b95a1] transition group-hover:text-[#3182f6]">
                  분석 시작 <span aria-hidden>→</span>
                </span>
              </Link>

              {/* 콘텐츠 분석 — 텍스트·문자 또는 유튜브 URL */}
              <button
                type="button"
                onClick={pickContent}
                className="group flex items-center gap-5 rounded-2xl border border-[#e5e8eb] bg-white p-6 text-left shadow-[0_2px_12px_rgba(0,0,0,0.05)] transition hover:border-[#3182f6] hover:shadow-[0_6px_20px_rgba(49,130,246,0.12)]"
              >
                <span className="flex h-14 w-14 flex-shrink-0 items-center justify-center rounded-2xl bg-[#e8f3ff] text-3xl">💬</span>
                <span className="min-w-0 flex-1">
                  <span className="block text-lg font-bold text-[#191f28]">콘텐츠 분석</span>
                  <span className="mt-1 block text-sm leading-6 text-[#4e5968]">
                    의심 문자·메시지 또는 유튜브 URL을 붙여넣으면 위험 신호를 검출해요. 영상·음성 파일도 올릴 수 있어요.
                  </span>
                </span>
                <span className="flex flex-shrink-0 items-center gap-1.5 whitespace-nowrap text-sm font-semibold text-[#8b95a1] transition group-hover:text-[#3182f6]">
                  분석 시작 <span aria-hidden>→</span>
                </span>
              </button>

              {/* APK 분석 — 안드로이드 설치 파일 */}
              <Link
                href="/apk"
                className="group flex items-center gap-5 rounded-2xl border border-[#e5e8eb] bg-white p-6 shadow-[0_2px_12px_rgba(0,0,0,0.05)] transition hover:border-[#3182f6] hover:shadow-[0_6px_20px_rgba(49,130,246,0.12)]"
              >
                <span className="flex h-14 w-14 flex-shrink-0 items-center justify-center rounded-2xl bg-[#e8f3ff] text-3xl">📱</span>
                <span className="min-w-0 flex-1">
                  <span className="block text-lg font-bold text-[#191f28]">APK 분석</span>
                  <span className="mt-1 block text-sm leading-6 text-[#4e5968]">
                    안드로이드 설치 파일(.apk)을 올려 악성 앱 신호를 검출해요. 격리 VM 으로만 분석합니다.
                  </span>
                </span>
                <span className="flex flex-shrink-0 items-center gap-1.5 whitespace-nowrap text-sm font-semibold text-[#8b95a1] transition group-hover:text-[#3182f6]">
                  분석 시작 <span aria-hidden>→</span>
                </span>
              </Link>
            </div>
          ) : (
          <div className="grid gap-8 lg:grid-cols-[1.1fr_0.9fr]">
            <div className="space-y-5">
              <button
                type="button"
                onClick={backToHub}
                className="inline-flex items-center gap-1.5 text-sm font-semibold text-[#4e5968] transition hover:text-[#191f28]"
              >
                <span aria-hidden>←</span> 분석 방식 선택으로
              </button>
              <h1 className="text-3xl font-bold leading-snug tracking-tight text-[#191f28] sm:text-[2.6rem]">
                💬 콘텐츠 분석
              </h1>
              <p className="max-w-md text-base leading-7 text-[#4e5968]">
                의심스러운 문자·메시지를 붙여넣거나 유튜브 영상 URL을 입력하면 위험 신호를 검출해요. 영상·음성 파일도 올릴 수 있어요.
              </p>
              <div className="flex flex-wrap gap-2 pt-1 text-xs text-[#8b95a1]">
                <span className="rounded-full bg-[#f2f4f6] px-3 py-1">검출만 — 판정은 본인이</span>
                <span className="rounded-full bg-[#f2f4f6] px-3 py-1">학술·법적 근거 제공</span>
              </div>
            </div>

            <form
              className="rounded-2xl border border-[#e5e8eb] bg-white p-5"
              onSubmit={handleSubmit}
            >
              <div className="mb-3 flex items-center justify-between">
                <label className="text-sm font-medium text-[#333d4b]" htmlFor="source">
                  분석할 텍스트 또는 유튜브 URL
                </label>
                <div className="flex gap-3">
                  <button
                    className="text-sm text-[#3182f6] transition hover:text-[#1b64da]"
                    onClick={() => {
                      setUploadFile(null);
                      setSource(EXAMPLE_INPUT);
                    }}
                    type="button"
                  >
                    텍스트 예시
                  </button>
                  <button
                    className="text-sm text-[#3182f6] transition hover:text-[#1b64da]"
                    onClick={() => {
                      setUploadFile(null);
                      setSource(EXAMPLE_VIDEO_URL);
                    }}
                    type="button"
                  >
                    URL 예시
                  </button>
                </div>
              </div>

              <textarea
                className="min-h-52 w-full rounded-2xl border border-[#e5e8eb] bg-[#f2f4f6] px-4 py-3 text-sm text-[#191f28] outline-none transition placeholder:text-[#8b95a1] focus:border-[#3182f6]"
                id="source"
                onChange={(event) => setSource(event.target.value)}
                placeholder="의심스러운 텍스트·문자를 붙여넣거나 유튜브 영상 URL을 입력하세요."
                value={source}
              />

              <div className="mt-4">
                <div className="text-sm font-medium text-[#333d4b]">또는 영상/음성 파일 업로드</div>
                <div className="mt-2 flex flex-wrap items-center gap-3">
                  <input
                    className="block w-full max-w-sm text-sm text-[#333d4b] file:mr-3 file:rounded-xl file:border-0 file:bg-[#f2f4f6] file:px-3 file:py-2 file:text-sm file:font-semibold file:text-[#191f28] hover:file:bg-[#e5e8eb]"
                    type="file"
                    accept="video/*,audio/*"
                    onChange={(event) => {
                      const selected = event.target.files?.[0] ?? null;
                      setUploadFile(selected);
                    }}
                  />
                  {uploadFile ? (
                    <button
                      className="rounded-xl border border-[#e5e8eb] px-3 py-2 text-xs text-[#333d4b] transition hover:bg-[#f2f4f6]"
                      type="button"
                      onClick={() => setUploadFile(null)}
                    >
                      선택 해제: {uploadFile.name}
                    </button>
                  ) : (
                    <div className="text-xs text-[#8b95a1]">
                      업로드 시 텍스트 입력 대신 파일을 STT로 전사합니다.
                    </div>
                  )}
                </div>
              </div>

              <div className="mt-3 text-sm text-[#8b95a1]">{sourceHint}</div>

              <div className="mt-5 grid gap-4 sm:grid-cols-2">
                <div className="space-y-2 text-sm text-[#4e5968]">
                  <span className="block">STT 백엔드</span>
                  <div className="flex items-center gap-2 rounded-xl border border-[#e5e8eb] bg-[#f2f4f6] px-3 py-2">
                    <span
                      className={`h-2 w-2 rounded-full ${
                        sttBackend ? "bg-emerald-400" : "bg-[#c9cdd2]"
                      }`}
                    />
                    <span className="text-[#191f28]">
                      {sttBackend === "claude"
                        ? "Claude Audio API"
                        : sttBackend === "openai_whisper"
                          ? "OpenAI Whisper API"
                          : "확인 중…"}
                    </span>
                  </div>
                  <p className="text-xs text-[#8b95a1]">
                    서버 환경변수 <code className="rounded bg-[#eef1f4] px-1">STT_BACKEND</code> 로 전환합니다.
                  </p>
                </div>

                <label className="flex items-center gap-3 rounded-2xl border border-[#e5e8eb] bg-[#f2f4f6] px-4 py-3 text-sm text-[#333d4b]">
                  <input
                    checked={skipVerification}
                    className="h-4 w-4 accent-[#3182f6]"
                    onChange={(event) => setSkipVerification(event.target.checked)}
                    type="checkbox"
                  />
                  검색 검증 건너뛰기
                </label>
              </div>

              <label className="mt-4 flex items-center gap-3 rounded-2xl border border-[#e5e8eb] bg-[#f2f4f6] px-4 py-3 text-sm text-[#333d4b]">
                <input
                  checked={useRag}
                  className="h-4 w-4 accent-[#3182f6]"
                  onChange={(event) => {
                    const checked = event.target.checked;
                    setUseRag(checked);
                  }}
                  type="checkbox"
                />
                사람 라벨 DB를 RAG로 참고
              </label>

              <p className="mt-3 text-xs leading-6 text-[#8b95a1]">
                검색 검증을 끄면 빠르게 데모할 수 있습니다. 켜면 `SERPER_API_KEY`
                가 필요합니다.
              </p>
              <p className="mt-2 text-xs leading-6 text-[#8b95a1]">
                LLM 보조 판정은 추가 엔티티를 병합하고, 높은 신뢰도의 플래그
                후보는 축소 가중치로 총점에 반영합니다.
              </p>
              <p className="mt-2 text-xs leading-6 text-[#8b95a1]">
                RAG는 어드민에서 사람이 확정한 과거 사례를 찾아 LLM 제안에만
                참고합니다. DB와 라벨 데이터가 있어야 효과가 납니다.
              </p>

              <button
                className="mt-5 inline-flex w-full items-center justify-center rounded-2xl bg-[#3182f6] px-4 py-3 font-semibold text-white transition hover:bg-[#1b64da] disabled:cursor-not-allowed disabled:bg-[#e5e8eb] disabled:text-[#8b95a1]"
                disabled={loading}
                type="submit"
              >
                {loading ? "분석 중..." : "분석 실행"}
              </button>

              {error ? (
                <div className="mt-4 rounded-2xl border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-700">
                  {error}
                </div>
              ) : null}

              {report && !modalOpen ? (
                <button
                  type="button"
                  onClick={() => {
                    setShowDetails(false);
                    setModalOpen(true);
                  }}
                  className="mt-3 inline-flex w-full items-center justify-center rounded-2xl border border-[#3182f6] px-4 py-3 text-sm font-semibold text-[#3182f6] transition hover:bg-[#e8f3ff]"
                >
                  📊 분석 결과 다시 보기
                </button>
              ) : null}
            </form>
          </div>
          )}
        </section>

        {injectionBlocked ? (
          <div
            className="fixed inset-0 z-[90] flex items-center justify-center overflow-y-auto bg-[#191f28]/60 p-4 sm:p-6"
            onClick={() => setInjectionBlocked(false)}
            role="dialog"
            aria-modal="true"
          >
            <div
              className="my-auto flex w-full max-w-sm flex-col"
              onClick={(event) => event.stopPropagation()}
            >
              <section className="relative rounded-3xl border border-[#fecaca] bg-white p-7 text-center shadow-[0_8px_30px_rgba(0,0,0,0.12)]">
                <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[#fff1f0] text-3xl">
                  🚫
                </span>
                <h2 className="mt-4 text-lg font-bold text-[#191f28]">
                  접근이 제한되었습니다
                </h2>
                <p className="mt-2 text-sm leading-6 text-[#4e5968]">
                  프롬프트 우회(인젝션) 시도가 감지되어 분석 이용이 일시 제한되었습니다.
                  정상적인 분석 요청만 이용해 주세요.
                </p>
                <button
                  type="button"
                  onClick={() => setInjectionBlocked(false)}
                  className="mt-6 inline-flex w-full items-center justify-center rounded-2xl bg-[#191f28] px-5 py-3 text-sm font-semibold text-white transition hover:bg-black"
                >
                  확인
                </button>
              </section>
            </div>
          </div>
        ) : null}

        {limitBlockOpen ? (
          <div
            className="fixed inset-0 z-[80] flex items-center justify-center overflow-y-auto bg-[#191f28]/50 p-4 sm:p-6"
            onClick={() => setLimitBlockOpen(false)}
            role="dialog"
            aria-modal="true"
          >
            <div
              className="my-auto flex w-full max-w-sm flex-col"
              onClick={(event) => event.stopPropagation()}
            >
              <section className="relative rounded-3xl border border-[#e5e8eb] bg-white p-7 text-center shadow-[0_8px_30px_rgba(0,0,0,0.12)]">
                <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[#fff1f0] text-3xl">
                  ⛔
                </span>
                <h2 className="mt-4 text-lg font-bold text-[#191f28]">
                  오늘 비회원 분석 한도를 모두 썼어요
                </h2>
                <p className="mt-2 text-sm leading-6 text-[#4e5968]">
                  비회원은 하루 {GUEST_DAILY_LIMIT}회까지 분석할 수 있어요(라이브 음성 포함).
                  로그인하면 이어서 계속 이용할 수 있어요.
                </p>

                <div className="mt-6 space-y-2">
                  <button
                    type="button"
                    onClick={() => signIn("google", { callbackUrl: "/" })}
                    className="flex w-full items-center justify-center gap-2 rounded-2xl bg-[#3182f6] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#1b64da]"
                  >
                    <svg className="h-4 w-4" viewBox="0 0 48 48" aria-hidden>
                      <path fill="#fff" d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.8 1.1 7.9 3l5.7-5.7C34.1 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
                    </svg>
                    Google 로 로그인
                  </button>
                  <button
                    type="button"
                    onClick={() => setLimitBlockOpen(false)}
                    className="inline-flex w-full items-center justify-center rounded-2xl px-5 py-3 text-sm font-semibold text-[#8b95a1] transition hover:bg-[#f2f4f6]"
                  >
                    닫기
                  </button>
                </div>
              </section>
            </div>
          </div>
        ) : null}

        {loginPromptOpen ? (
          <div
            className="fixed inset-0 z-[70] flex items-center justify-center overflow-y-auto bg-[#191f28]/40 p-4 sm:p-6"
            onClick={() => {
              setLoginPromptOpen(false);
              setModalOpen(true);
            }}
            role="dialog"
            aria-modal="true"
          >
            <div
              className="my-auto flex w-full max-w-sm flex-col"
              onClick={(event) => event.stopPropagation()}
            >
              <section className="relative rounded-3xl border border-[#e5e8eb] bg-white p-7 text-center shadow-[0_8px_30px_rgba(0,0,0,0.12)]">
                <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[#e8f3ff] text-3xl">
                  🔒
                </span>
                <h2 className="mt-4 text-lg font-bold text-[#191f28]">
                  로그인하고 계속 이용해 보세요
                </h2>
                <p className="mt-2 text-sm leading-6 text-[#4e5968]">
                  비회원으로 여러 번 분석하셨어요. 로그인하면 분석 결과를 안전하게
                  이어서 이용할 수 있어요.
                </p>

                <div className="mt-6 space-y-2">
                  <button
                    type="button"
                    onClick={() => signIn("google", { callbackUrl: "/" })}
                    className="flex w-full items-center justify-center gap-2 rounded-2xl bg-[#3182f6] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#1b64da]"
                  >
                    <svg className="h-4 w-4" viewBox="0 0 48 48" aria-hidden>
                      <path fill="#fff" d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.8 1.1 7.9 3l5.7-5.7C34.1 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
                    </svg>
                    Google 로 로그인
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      setLoginPromptOpen(false);
                      setModalOpen(true);
                    }}
                    className="inline-flex w-full items-center justify-center rounded-2xl px-5 py-3 text-sm font-semibold text-[#8b95a1] transition hover:bg-[#f2f4f6]"
                  >
                    비회원으로 결과 보기
                  </button>
                </div>
              </section>
            </div>
          </div>
        ) : null}

        {report && modalOpen ? (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-[#191f28]/40 p-4 sm:p-6"
            onClick={() => setModalOpen(false)}
            role="dialog"
            aria-modal="true"
          >
            <div
              className="my-auto flex w-full max-w-md flex-col"
              onClick={(event) => event.stopPropagation()}
            >
          <section className="relative rounded-3xl border border-[#e5e8eb] bg-white p-6 shadow-[0_8px_30px_rgba(0,0,0,0.12)]">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-bold text-[#191f28]">분석 결과</h2>
              <button
                type="button"
                onClick={() => setModalOpen(false)}
                aria-label="닫기"
                className="flex h-8 w-8 items-center justify-center rounded-full text-lg text-[#8b95a1] transition hover:bg-[#f2f4f6]"
              >
                ✕
              </button>
            </div>

            <div
              className={`mt-5 flex items-center gap-4 rounded-2xl border px-4 py-4 ${
                (report.detected_signals ?? []).length === 0
                  ? "border-emerald-200 bg-emerald-50"
                  : "border-amber-200 bg-amber-50"
              }`}
            >
              <span
                className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-full text-2xl font-bold ${
                  (report.detected_signals ?? []).length === 0
                    ? "bg-emerald-100 text-emerald-600"
                    : "bg-amber-100 text-amber-600"
                }`}
              >
                {(report.detected_signals ?? []).length === 0 ? "✓" : "!"}
              </span>
              <div className="min-w-0">
                <div className="text-base font-bold text-[#191f28]">
                  {(report.detected_signals ?? []).length === 0
                    ? "위험 신호가 검출되지 않았어요"
                    : `위험 신호 ${(report.detected_signals ?? []).length}개 검출`}
                </div>
                <div className="mt-0.5 text-sm text-[#8b95a1]">
                  유형 ·{" "}
                  {report.is_uncertain || (report.classification_confidence ?? 0) < 0.3
                    ? "정상"
                    : (report.scam_type ?? "").trim() || "미분류"}
                </div>
              </div>
            </div>

            {(() => {
              const ct = contentTypeBadge(report.content_type);
              const label = ct?.label ?? report.content_type?.label_ko?.trim();
              if (!label) return null;
              return (
                <div className="mt-3 flex items-center justify-between gap-4 rounded-2xl bg-[#f2f4f6] px-4 py-3">
                  <span className="text-sm text-[#8b95a1]">콘텐츠 분류</span>
                  <span className="text-right text-sm font-semibold text-[#191f28]">
                    {ct?.icon ? `${ct.icon} ` : ""}
                    {label}
                  </span>
                </div>
              );
            })()}

            {report.summary ? (
              <p className="mt-4 text-sm leading-6 text-[#4e5968]">
                {report.summary}
              </p>
            ) : null}

            <div className="mt-6 space-y-2">
              <button
                type="button"
                onClick={() => setShowDetails(true)}
                className="inline-flex w-full items-center justify-center rounded-2xl bg-[#3182f6] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#1b64da]"
              >
                세부사항 보기
              </button>
              <button
                type="button"
                onClick={() => setModalOpen(false)}
                className="inline-flex w-full items-center justify-center rounded-2xl px-5 py-3 text-sm font-semibold text-[#8b95a1] transition hover:bg-[#f2f4f6]"
              >
                닫기
              </button>
            </div>
          </section>
            </div>
          </div>
        ) : null}

        {report && modalOpen && showDetails ? (
          <div
            className="fixed inset-0 z-[60] flex items-start justify-center overflow-y-auto bg-black/60 p-4 backdrop-blur-sm sm:p-8"
            onClick={() => setShowDetails(false)}
            role="dialog"
            aria-modal="true"
          >
            <div
              className="my-auto flex w-full max-w-4xl flex-col gap-4"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="flex items-center justify-between">
                <button
                  type="button"
                  onClick={() => setShowDetails(false)}
                  className="inline-flex items-center gap-1 rounded-xl bg-white/90 px-4 py-2 text-sm font-semibold text-[#4e5968] shadow transition hover:bg-white"
                >
                  ← 결과로
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setShowDetails(false);
                    setModalOpen(false);
                  }}
                  aria-label="닫기"
                  className="flex h-9 w-9 items-center justify-center rounded-full bg-white/90 text-lg text-[#4e5968] shadow transition hover:bg-white"
                >
                  ✕
                </button>
              </div>
          <section className="grid gap-6 lg:grid-cols-[0.9fr_1.1fr]">
          <div className="rounded-3xl border border-[#e5e8eb] bg-white p-6 backdrop-blur">
            <div className="mb-4 flex items-center justify-between gap-3">
              <h2 className="text-xl font-semibold text-[#191f28]">검출 결과</h2>
              {report ? (
                <span className="rounded-full bg-fuchsia-500/20 px-3 py-1 text-sm font-medium text-fuchsia-700">
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
                    <div className={`rounded-2xl border bg-white p-4 ${ctBadge.chip}`}>
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
                    <div className="rounded-2xl border border-[#e5e8eb] bg-white p-4">
                      <div className="text-sm text-[#8b95a1]">스캠 유형</div>
                      <div className="mt-2 text-2xl font-semibold text-[#191f28]">
                        {report.is_uncertain || (report.classification_confidence ?? 0) < 0.3
                          ? "정상"
                          : (report.scam_type ?? "").trim() || "미분류"}
                      </div>
                      <div className="mt-2 text-sm text-[#4e5968]">
                        신뢰도 {formatPercent(report.classification_confidence)}
                      </div>
                    </div>
                  )}

                  <div className="rounded-2xl border border-[#e5e8eb] bg-white p-4">
                    <div className="text-sm text-[#8b95a1]">검출된 위험 신호</div>
                    <div className="mt-2 text-2xl font-semibold text-[#191f28]">
                      {(report.detected_signals ?? []).length}개
                    </div>
                    <div className="mt-2 text-xs text-[#8b95a1]">
                      ScamGuardian 은 검출만 — 판정은 통합 기업 (Identity Boundary)
                    </div>
                  </div>
                </div>

                {/* Identity Boundary: 판정(verdict) 없음 — 검출 요약만 노출 */}
                <div className="rounded-2xl border border-[#e5e8eb] bg-white p-4">
                  <div className="text-sm text-[#8b95a1]">검출 요약</div>
                  <div className="mt-2 text-base font-medium leading-7 text-[#191f28]">
                    {report.summary ??
                      `위험 신호 ${(report.detected_signals ?? []).length}개가 검출되었습니다.`}
                  </div>
                  {report.disclaimer ? (
                    <div className="mt-3 rounded-xl bg-white px-3 py-2 text-xs leading-6 text-[#8b95a1]">
                      {report.disclaimer}
                    </div>
                  ) : null}
                </div>

                <div className="rounded-2xl border border-[#e5e8eb] bg-white p-4">
                  <div className="flex items-center justify-between gap-4">
                    <div className="text-sm text-[#8b95a1]">전체 전사(하이라이트)</div>
                    <div className="text-xs text-[#8b95a1]">
                      <span className="mr-2 rounded px-1 bg-[#dbeafe] text-[#1b64da]">
                        엔티티
                      </span>
                      <span className="rounded px-1 bg-amber-500/20 text-amber-700">
                        플래그 근거
                      </span>
                    </div>
                  </div>
                  <div className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words font-mono text-xs leading-6 text-[#333d4b]">
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
                  <div className="rounded-2xl border border-[#e5e8eb] bg-white p-4">
                    <div className="text-sm text-[#8b95a1]">저장된 run ID</div>
                    <div className="mt-2 break-all text-sm text-[#333d4b]">
                      {report.analysis_run_id}
                    </div>
                  </div>
                ) : null}

                {/* 콘텐츠가 안전 버킷(뉴스·정상·판단불가)이면 신뢰도 경고 숨김 —
                    confidence 0% 는 Phase 2 skip 의 결과지 분류 실패가 아님. */}
                {report.is_uncertain && !ctBadge ? (
                  <div className="rounded-2xl border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-700">
                    분류 신뢰도가 낮아서 결과가 부정확할 수 있습니다.
                  </div>
                ) : null}
              </div>
                );
              })()
            ) : (
              <div className="rounded-2xl border border-dashed border-[#e5e8eb] bg-[#f9fafb] p-6 text-sm leading-7 text-[#8b95a1]">
                아직 결과가 없습니다. 왼쪽 폼에서 입력을 넣고 분석을 실행하세요.
              </div>
            )}
          </div>

          <div className="grid gap-6">
            <div className="rounded-3xl border border-[#e5e8eb] bg-white p-6 backdrop-blur">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-xl font-semibold text-[#191f28]">엔티티</h2>
                <span className="text-sm text-[#8b95a1]">
                  {report ? `${report.entities.length}개` : "0개"}
                </span>
              </div>

              <div className="flex flex-wrap gap-3">
                {report?.entities.length ? (
                  report.entities.map((entity, index) => (
                    <div
                      className="rounded-2xl border border-[#e5e8eb] bg-white px-4 py-3"
                      key={entityKey(entity, index)}
                    >
                      <div className="flex items-center gap-2">
                        <div className="text-xs text-[#3182f6]">{entity.label}</div>
                        <span
                          className={`rounded-full px-2 py-0.5 text-[10px] ${sourceBadgeClass(entity.source)}`}
                        >
                          {entity.source === "llm" ? "LLM" : "기본"}
                        </span>
                      </div>
                      <div className="mt-1 text-sm font-medium text-[#191f28]">
                        {entity.text}
                      </div>
                      <div className="mt-1 text-xs text-[#8b95a1]">
                        신뢰도 {entity.score.toFixed(2)}
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-2xl border border-dashed border-[#e5e8eb] bg-[#f9fafb] px-4 py-8 text-sm text-[#8b95a1]">
                    분석 후 추출된 엔티티가 여기에 표시됩니다.
                  </div>
                )}
              </div>
            </div>

            <div className="rounded-3xl border border-[#e5e8eb] bg-white p-6 backdrop-blur">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-xl font-semibold text-[#191f28]">검출된 위험 신호</h2>
                <span className="text-sm text-[#8b95a1]">
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
                        className="rounded-2xl border border-[#e5e8eb] bg-white p-4"
                        key={`${signal.flag}-${signalIndex}`}
                      >
                        <div className="flex flex-wrap items-baseline justify-between gap-2">
                          <div className="text-sm font-semibold text-[#191f28]">
                            {signal.label_ko ?? signal.flag}
                          </div>
                          <span className="rounded-full bg-[#e5e8eb] px-2 py-0.5 text-[10px] text-[#4e5968]">
                            {sourceTag}
                          </span>
                        </div>
                        {signal.description ? (
                          <p className="mt-1 text-xs text-[#8b95a1]">
                            {signal.description}
                          </p>
                        ) : null}
                        {signal.rationale ? (
                          <div className="mt-3 rounded-xl bg-[#f2f4f6] p-3 text-xs leading-6 text-[#4e5968]">
                            <div className="text-[#333d4b]">📖 학술/법적 근거</div>
                            <p className="mt-1">{signal.rationale}</p>
                            {signal.source ? (
                              <p className="mt-2 text-[#8b95a1]">출처: {signal.source}</p>
                            ) : null}
                          </div>
                        ) : null}
                        {(signal.evidence ?? []).length ? (
                          <div className="mt-2 space-y-1">
                            {(signal.evidence ?? []).slice(0, 2).map((ev, eIdx) => (
                              <div
                                className="rounded-xl bg-white px-3 py-1.5 text-[11px] leading-5 text-[#8b95a1]"
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
                  <div className="rounded-2xl border border-dashed border-[#e5e8eb] bg-[#f9fafb] px-4 py-8 text-sm text-[#8b95a1]">
                    검출된 위험 신호가 없습니다.
                  </div>
                )}
              </div>

              {report ? (
                <div className="mt-4 text-xs text-[#8b95a1]">
                  전체 검증 시도 수: {report.verification_count}
                </div>
              ) : null}
            </div>

            <div className="rounded-3xl border border-[#e5e8eb] bg-white p-6 backdrop-blur">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-xl font-semibold text-[#191f28]">RAG 참고 사례</h2>
                <span className="text-sm text-[#8b95a1]">
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
                        className="rounded-2xl border border-[#e5e8eb] bg-white p-4"
                        key={item.run_id}
                      >
                        <div className="flex flex-wrap items-center justify-between gap-2">
                          <div className="text-sm font-semibold text-[#191f28]">
                            {item.scam_type_gt}
                          </div>
                          <div className="text-xs text-[#8b95a1]">
                            distance {item.distance.toFixed(4)}
                          </div>
                        </div>
                        <div className="mt-2 text-sm leading-6 text-[#4e5968]">
                          {item.transcript_excerpt}
                        </div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="rounded-2xl border border-dashed border-[#e5e8eb] bg-[#f9fafb] px-4 py-8 text-sm text-[#8b95a1]">
                    참고할 사람 라벨 사례를 찾지 못했습니다.
                  </div>
                )
              ) : (
                <div className="rounded-2xl border border-dashed border-[#e5e8eb] bg-[#f9fafb] px-4 py-8 text-sm text-[#8b95a1]">
                  분석 시 `사람 라벨 DB를 RAG로 참고`를 켜면 이 영역에 유사 사례가
                  표시됩니다.
                </div>
              )}
            </div>

            <div className="rounded-3xl border border-[#e5e8eb] bg-white p-6 backdrop-blur">
              <div className="mb-4 flex items-center justify-between">
                <h2 className="text-xl font-semibold text-[#191f28]">LLM 보조 판정</h2>
                <span className="text-sm text-[#8b95a1]">
                  {report?.llm_assessment?.model ?? "미사용"}
                </span>
              </div>

              {report?.llm_assessment ? (
                report.llm_assessment.error ? (
                  <div className="rounded-2xl border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-700">
                    {report.llm_assessment.error}
                  </div>
                ) : (
                  <div className="space-y-4">
                    <div className="rounded-2xl border border-[#e5e8eb] bg-white p-4 text-sm leading-7 text-[#4e5968]">
                      {report.llm_assessment.summary || "LLM 요약이 없습니다."}
                    </div>
                    {report.llm_assessment.reasoning?.length ? (
                      <div className="rounded-2xl border border-[#e5e8eb] bg-white p-4">
                        <div className="text-sm font-medium text-[#333d4b]">문맥 근거</div>
                        <div className="mt-3 space-y-2">
                          {report.llm_assessment.reasoning.slice(0, 3).map((item, index) => (
                            <div
                              className="rounded-xl bg-white px-3 py-2 text-xs leading-6 text-[#4e5968]"
                              key={`${item}-${index}`}
                            >
                              {index + 1}. {item}
                            </div>
                          ))}
                        </div>
                      </div>
                    ) : null}

                    <div className="space-y-3">
                      <div className="text-sm font-medium text-[#333d4b]">
                        추가 엔티티 후보
                      </div>
                      {report.llm_assessment.suggested_entities.length ? (
                        report.llm_assessment.suggested_entities.map((entity, index) => (
                          <div
                            className="rounded-2xl border border-[#e5e8eb] bg-white px-4 py-3"
                            key={`${entity.label}-${entity.text}-${index}`}
                          >
                            <div className="text-xs text-[#3182f6]">{entity.label}</div>
                            <div className="mt-1 text-sm font-medium text-[#191f28]">
                              {entity.text}
                            </div>
                            <div className="mt-1 text-xs text-[#8b95a1]">
                              신뢰도 {entity.confidence.toFixed(2)}
                            </div>
                            <div className="mt-2 text-xs leading-6 text-[#8b95a1]">
                              {entity.reason}
                            </div>
                          </div>
                        ))
                      ) : (
                        <div className="rounded-2xl border border-dashed border-[#e5e8eb] bg-[#f9fafb] px-4 py-6 text-sm text-[#8b95a1]">
                          추가 엔티티 제안이 없습니다.
                        </div>
                      )}
                    </div>

                    <div className="space-y-3">
                      <div className="text-sm font-medium text-[#333d4b]">
                        추가 플래그 후보
                      </div>
                      {report.llm_assessment.suggested_flags.length ? (
                        report.llm_assessment.suggested_flags.map((flag, index) => (
                          <div
                            className="rounded-2xl border border-[#e5e8eb] bg-white px-4 py-3"
                            key={`${flag.flag}-${index}`}
                          >
                            <div className="text-sm font-semibold text-[#191f28]">
                              {flag.flag}
                            </div>
                            <div className="mt-1 text-xs text-[#8b95a1]">
                              신뢰도 {flag.confidence.toFixed(2)}
                            </div>
                            <div className="mt-2 text-sm leading-6 text-[#4e5968]">
                              {flag.reason}
                            </div>
                            {flag.evidence ? (
                              <div className="mt-2 rounded-xl bg-white px-3 py-2 text-xs leading-6 text-[#8b95a1]">
                                {flag.evidence}
                              </div>
                            ) : null}
                          </div>
                        ))
                      ) : (
                        <div className="rounded-2xl border border-dashed border-[#e5e8eb] bg-[#f9fafb] px-4 py-6 text-sm text-[#8b95a1]">
                          추가 플래그 제안이 없습니다.
                        </div>
                      )}
                    </div>
                  </div>
                )
              ) : (
                <div className="rounded-2xl border border-dashed border-[#e5e8eb] bg-[#f9fafb] px-4 py-8 text-sm text-[#8b95a1]">
                분석 시 `Claude LLM 보조 판정 사용`을 켜면 이 영역에 결과가
                표시됩니다.
              </div>
            )}
          </div>
          </div>
        </section>
            </div>
          </div>
        ) : null}
      </div>
    </main>
  );
}
