import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";

const API_BASE_URL =
  process.env.SCAMGUARDIAN_API_URL ?? "http://127.0.0.1:8000";

type PageProps = {
  params: Promise<{ token: string }>;
};

// DetectionReport.detected_signals[] 의 element schema
type DetectedSignalDict = {
  flag?: string;
  label_ko?: string;
  rationale?: string;
  source?: string;             // 출처 기관·논문
  detection_source?: string;   // rule | llm | safety | sandbox
  evidence?: string[];
  description?: string;
};

// Stage 3 — 검출 신호 그룹핑 레이어 (UI 표시용 보조 필드, optional).
// 세부 detected_signals 와 학술·법적 rationale 매핑은 그대로 유지된다.
type SignalGroupDict = {
  group_id?: string;
  label_ko?: string;
  description?: string;
  summary?: string;
  count?: number;
  flags?: string[];
};

type EntityDict = {
  label?: string;
  text?: string;
  score?: number;
  source?: string;
};

type LLMAssessment = {
  model?: string;
  summary?: string;
  reasoning?: string[];
  suggested_entities?: Array<{ label?: string; text?: string; reason?: string }>;
  suggested_flags?: Array<{ flag?: string; reason?: string; evidence?: string }>;
  error?: string;
};

type SafetyCheckDict = {
  target_kind?: string;
  target?: string;
  scanner?: string;
  threat_level?: string;  // safe | suspicious | malicious | unknown
  detections?: number;
  suspicious?: number;
  total_engines?: number;
  threat_categories?: string[];
  permalink?: string | null;
  error?: string | null;
};

type ReportDict = {
  scam_type?: string;
  classification_confidence?: number;
  is_uncertain?: boolean;
  scam_type_reason?: string;
  scam_type_source?: string;
  transcript_text?: string;
  entities?: EntityDict[];
  // Identity Boundary (CLAUDE.md): score / risk_level 필드 *없음*. detected_signals 만.
  detected_signals?: DetectedSignalDict[];
  // Stage 3 — 검출 신호 그룹핑(표시용). 없으면 detected_signals 만 표시로 fallback.
  signal_groups?: SignalGroupDict[];
  summary?: string;
  disclaimer?: string;
  llm_assessment?: LLMAssessment | null;
  safety_check?: SafetyCheckDict | null;
};

type QAPair = { question?: string; answer?: string };

type UserContextDict = {
  qa_pairs?: QAPair[];
  summary_text?: string;
  turn_count?: number;
};

type ChatTurnDict = { role?: string; message?: string };

type FlagRationaleEntry = { rationale?: string; source?: string };

// Stage 1 게이트 안전 버킷만 결과 페이지에 노출 (Identity Boundary).
// scam_attempt / suspicious_insufficient 는 백엔드에서 절대 전달되지 않음.
type ContentTypeDict = {
  bucket?: string;        // normal | scam_news_edu | undetermined
  label_ko?: string;
};

type ResultPayload = {
  result: ReportDict;
  user_context: UserContextDict | null;
  input_type: string;
  chat_history: ChatTurnDict[];
  flag_rationale?: Record<string, FlagRationaleEntry>;
  content_type?: ContentTypeDict | null;
  expires_at: number;
};

// 안전 버킷별 결과 페이지 헤더 배지 스타일·문구.
function contentTypeBadge(
  ct: ContentTypeDict | null | undefined,
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
  if (bucket === "undetermined") {
    return {
      icon: "❔",
      label: "판단 불가 (입력이 짧거나 모호)",
      chip: "border-slate-500/40 bg-slate-700/30 text-slate-200",
    };
  }
  return null;
}

// 검출 신호 개수에 따른 색·아이콘. 등급 매기기 X — 단순 시각 변별.
function detectionStyle(signalCount: number): { color: string; icon: string; title: string } {
  if (signalCount <= 0) {
    return {
      color: "bg-emerald-700/30 border-emerald-500 text-emerald-200",
      icon: "✅",
      title: "검출된 위험 신호 없음",
    };
  }
  if (signalCount <= 2) {
    return {
      color: "bg-yellow-700/30 border-yellow-500 text-yellow-200",
      icon: "⚠️",
      title: `위험 신호 ${signalCount}개 검출`,
    };
  }
  return {
    color: "bg-orange-700/30 border-orange-500 text-orange-200",
    icon: "🚨",
    title: `위험 신호 ${signalCount}개 검출`,
  };
}

const INPUT_TYPE_LABEL: Record<string, string> = {
  text: "💬 텍스트",
  url: "🔗 URL/영상",
  video: "🎬 업로드 영상",
  file: "📎 파일",
};

async function fetchResult(token: string): Promise<ResultPayload | { status: number }> {
  const url = `${API_BASE_URL}/api/result/${encodeURIComponent(token)}`;
  try {
    const resp = await fetch(url, { cache: "no-store" });
    if (!resp.ok) {
      return { status: resp.status };
    }
    return (await resp.json()) as ResultPayload;
  } catch {
    return { status: 502 };
  }
}

function fmtConfidence(c?: number): string {
  if (typeof c !== "number") return "-";
  return `${(c * 100).toFixed(0)}%`;
}

function fmtExpires(epoch: number): string {
  const remaining = epoch - Date.now() / 1000;
  if (remaining <= 0) return "만료됨";
  const minutes = Math.floor(remaining / 60);
  if (minutes < 1) return "1분 이내 만료";
  if (minutes < 60) return `${minutes}분 후 만료`;
  return `${Math.floor(minutes / 60)}시간 ${minutes % 60}분 후 만료`;
}

export default async function ResultPage({ params }: PageProps) {
  const { token } = await params;
  const data = await fetchResult(token);

  if ("status" in data) {
    if (data.status === 404 || data.status === 410) {
      notFound();
    }
    return (
      <main className="min-h-screen bg-[radial-gradient(circle_at_top,#111827_0%,#020617_60%,#000000_100%)] px-6 py-10 text-slate-100">
        <div className="mx-auto max-w-3xl">
          <div className="rounded-2xl border border-red-500/40 bg-red-950/30 p-6">
            <h1 className="text-xl font-bold text-red-200">결과를 불러올 수 없습니다</h1>
            <p className="mt-2 text-sm text-red-300/80">
              백엔드 API 응답: HTTP {data.status}
            </p>
          </div>
        </div>
      </main>
    );
  }

  const { result, user_context, input_type, chat_history, expires_at } = data;
  const signals = result.detected_signals ?? [];
  // Stage 3 그룹핑 — 없으면(legacy 응답·빈 배열) detected_signals 표시로 자연 fallback.
  const signalGroups = result.signal_groups ?? [];
  // Stage 1 안전 버킷 배지 (사기 시도/의심 버킷은 백엔드 단계에서 이미 걸러짐).
  const ctBadge = contentTypeBadge(data.content_type);
  const detection = detectionStyle(signals.length);
  const inputLabel = INPUT_TYPE_LABEL[input_type] ?? input_type;
  const llm = result.llm_assessment ?? null;

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,#111827_0%,#020617_60%,#000000_100%)] px-4 py-8 text-slate-100 sm:px-6 sm:py-10">
      <div className="mx-auto w-full max-w-4xl space-y-6">
        {/* 헤더 — 안전 버킷이면 콘텐츠 타입 배지로, 아니면 scam_type 표시 */}
        <header className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
          <div className="space-y-2">
            <p className="text-sm text-slate-400">ScamGuardian 검출 결과</p>
            {ctBadge ? (
              <div className="space-y-2">
                <h1 className="text-2xl font-bold text-slate-100">
                  <span className="mr-2">{ctBadge.icon}</span>
                  {ctBadge.label}
                </h1>
                <span
                  className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs ${ctBadge.chip}`}
                >
                  콘텐츠 분류 (사기 판정 X)
                </span>
              </div>
            ) : (
              <h1 className="text-2xl font-bold text-slate-100">
                {(result.scam_type ?? "").trim() || "미분류"}{" "}
                <span className="text-base text-slate-500">(추정 유형)</span>
              </h1>
            )}
          </div>
          <p className="text-xs text-slate-500">{fmtExpires(expires_at)} · {inputLabel}</p>
        </header>

        {/* v3 Phase 0 안전성 경고 — malicious/suspicious 일 때 최상단 prominent */}
        {(() => {
          const sc = result.safety_check;
          if (!sc) return null;
          const level = (sc.threat_level ?? "").toLowerCase();
          if (level !== "malicious" && level !== "suspicious") return null;
          const isMal = level === "malicious";
          const styles = isMal
            ? "border-red-500 bg-red-950/40 text-red-100"
            : "border-amber-500 bg-amber-950/30 text-amber-100";
          const icon = isMal ? "🚨" : "⚠️";
          const targetLabel = sc.target_kind === "url" ? "URL" : "파일";
          const head = isMal
            ? `${icon} 위험! 이 ${targetLabel}은 악성으로 확인됐어요`
            : `${icon} 주의: 이 ${targetLabel}에 일부 의심 신호가 있어요`;
          return (
            <section className={`rounded-2xl border p-6 shadow-lg ${styles}`}>
              <div className="text-lg font-bold">{head}</div>
              <p className="mt-2 text-sm opacity-90">
                VirusTotal {sc.detections ?? 0}/{sc.total_engines ?? 0} 엔진이 위험 판정.
                {sc.target_kind === "url"
                  ? " 클릭하지 마시고 차단·신고를 권장합니다."
                  : " 실행하지 마시고 즉시 삭제하세요."}
              </p>
              {sc.threat_categories && sc.threat_categories.length > 0 && (
                <div className="mt-3 flex flex-wrap gap-2">
                  {sc.threat_categories.slice(0, 5).map((c, i) => (
                    <span
                      key={i}
                      className="rounded-full border border-current/40 bg-black/20 px-2 py-0.5 text-xs"
                    >
                      {c}
                    </span>
                  ))}
                </div>
              )}
              {sc.permalink && (
                <a
                  href={sc.permalink}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="mt-3 inline-block text-xs underline opacity-80 hover:opacity-100"
                >
                  VirusTotal 상세 리포트 →
                </a>
              )}
            </section>
          );
        })()}

        {/* 검출 결과 배지 — 점수·등급 X, 신호 개수만 */}
        <section className={`rounded-2xl border p-6 shadow-lg ${detection.color}`}>
          <div className="flex items-baseline gap-3">
            <span className="text-3xl">{detection.icon}</span>
            <span className="text-2xl font-bold">{detection.title}</span>
          </div>
          {result.summary && (
            <p className="mt-2 text-sm opacity-90">{result.summary}</p>
          )}
          <p className="mt-2 text-xs opacity-70">
            분류 신뢰도: {fmtConfidence(result.classification_confidence)}
            {result.is_uncertain && " · ⚠️ 분류 신뢰도 낮음"}
          </p>
        </section>

        {/* AI 요약 */}
        {llm?.summary && (
          <section className="rounded-2xl border border-slate-700 bg-slate-900/60 p-6">
            <h2 className="mb-3 text-lg font-semibold text-slate-100">🤖 AI 요약</h2>
            <p className="text-sm leading-relaxed text-slate-200">{llm.summary}</p>
            {llm.reasoning && llm.reasoning.length > 0 && (
              <ul className="mt-4 list-inside list-disc space-y-1 text-sm text-slate-300">
                {llm.reasoning.map((r, idx) => (
                  <li key={idx}>{r}</li>
                ))}
              </ul>
            )}
          </section>
        )}

        {/* 사용자 제공 정보 — prominent */}
        {(user_context?.qa_pairs?.length ?? 0) > 0 && (
          <section className="rounded-2xl border border-fuchsia-500/40 bg-fuchsia-950/20 p-6">
            <div className="mb-3 flex items-center gap-2">
              <h2 className="text-lg font-semibold text-fuchsia-200">💡 사용자 제공 정보</h2>
              <span className="rounded bg-fuchsia-500/20 px-2 py-0.5 text-xs text-fuchsia-200">
                분석에 prior 로 반영됨
              </span>
            </div>
            <p className="mb-4 text-xs text-fuchsia-200/70">
              아래 정보는 분석가(Claude)가 사기 여부 판단에 직접 참고했어요.
            </p>
            <ol className="space-y-3">
              {(user_context?.qa_pairs ?? []).map((qa, idx) => (
                <li key={idx} className="rounded-lg bg-fuchsia-950/40 p-3">
                  {qa.question && (
                    <p className="text-xs text-fuchsia-300/80">Q. {qa.question}</p>
                  )}
                  <p className="mt-1 text-sm text-fuchsia-100">A. {qa.answer}</p>
                </li>
              ))}
            </ol>
          </section>
        )}

        {/* Stage 3 — 신호 그룹 요약 (detected_signals 보다 먼저). 그룹 없으면 자연 생략. */}
        {signalGroups.length > 0 && (
          <section className="rounded-2xl border border-slate-700 bg-slate-900/60 p-6">
            <h2 className="mb-3 text-lg font-semibold text-slate-100">
              📊 위험 신호 그룹 요약 ({signalGroups.length}그룹)
            </h2>
            <p className="mb-4 text-sm text-slate-400">
              검출된 신호를 의미별로 묶어 본 요약입니다. 각 신호의 학술·법적 근거는
              아래 “검출된 위험 신호” 섹션을 참고하세요.
            </p>
            <ul className="space-y-3">
              {signalGroups.map((g, idx) => (
                <li key={g.group_id ?? idx} className="rounded bg-slate-800/60 p-4">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="text-base font-semibold text-slate-100">
                      {g.label_ko ?? g.group_id ?? "기타"}
                    </span>
                    <span className="rounded bg-slate-700/60 px-2 py-0.5 text-xs text-slate-300">
                      {g.count ?? (g.flags?.length ?? 0)}개
                    </span>
                  </div>
                  {g.summary && (
                    <p className="mt-1 text-sm text-slate-300">{g.summary}</p>
                  )}
                  {(g.flags?.length ?? 0) > 0 && (
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {(g.flags ?? []).map((f, fidx) => (
                        <span
                          key={fidx}
                          className="rounded-full border border-slate-600 bg-slate-950/40 px-2 py-0.5 font-mono text-xs text-slate-400"
                        >
                          {f}
                        </span>
                      ))}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* 검출된 위험 신호 상세 — 학술/법적 근거 함께 표시 (점수·등급 X) */}
        {signals.length > 0 && (
          <section className="rounded-2xl border border-slate-700 bg-slate-900/60 p-6">
            <h2 className="mb-3 text-lg font-semibold text-slate-100">
              🚩 검출된 위험 신호 ({signals.length}개)
            </h2>
            <p className="mb-4 text-sm text-slate-400">
              각 신호 옆 학술/법적 근거를 참고하세요. ScamGuardian 은 검출만 하고 사기 여부 판정은 하지 않습니다.
            </p>
            <ul className="space-y-3">
              {signals.map((s, idx) => {
                const detSrc = s.detection_source ?? "rule";
                const sourceTag =
                  detSrc === "llm" ? "🤖 LLM 보조"
                  : detSrc === "safety" ? "🛡 VirusTotal"
                  : detSrc === "sandbox" ? "📦 샌드박스"
                  : "📋 규칙";
                const evidenceList: string[] = Array.isArray(s.evidence)
                  ? s.evidence
                  : [];
                return (
                  <li key={idx} className="rounded bg-slate-800/60 p-4 text-sm">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <span className="text-base font-semibold text-slate-100">
                        {s.label_ko ?? s.flag}
                      </span>
                      <span className="rounded bg-slate-700/60 px-2 py-0.5 text-xs text-slate-300">
                        {sourceTag}
                      </span>
                    </div>
                    {s.description && (
                      <p className="mt-1 text-xs text-slate-400">{s.description}</p>
                    )}
                    {s.rationale && (
                      <div className="mt-3 rounded bg-slate-950/50 p-3 text-xs leading-relaxed text-slate-300">
                        <div className="text-slate-200">📖 학술/법적 근거</div>
                        <p className="mt-1">{s.rationale}</p>
                        {s.source && (
                          <p className="mt-2 text-slate-500">출처: {s.source}</p>
                        )}
                      </div>
                    )}
                    {evidenceList.length > 0 && (
                      <ul className="mt-2 space-y-1 text-xs text-slate-400">
                        {evidenceList.slice(0, 3).map((e, eidx) => (
                          <li key={eidx} className="truncate">• {e}</li>
                        ))}
                      </ul>
                    )}
                  </li>
                );
              })}
            </ul>
          </section>
        )}

        {/* 추출 엔티티 */}
        {(result.entities?.length ?? 0) > 0 && (
          <section className="rounded-2xl border border-slate-700 bg-slate-900/60 p-6">
            <h2 className="mb-3 text-lg font-semibold text-slate-100">
              🔖 추출 엔티티 ({result.entities?.length ?? 0}개)
            </h2>
            <div className="flex flex-wrap gap-2">
              {(result.entities ?? []).map((e, idx) => (
                <span
                  key={idx}
                  className="rounded-full border border-slate-600 bg-slate-800/40 px-3 py-1 text-xs text-slate-200"
                  title={`source: ${e.source ?? "-"}, score: ${e.score?.toFixed?.(2) ?? "-"}`}
                >
                  <span className="text-slate-400">{e.label}: </span>
                  {e.text}
                </span>
              ))}
            </div>
          </section>
        )}

        {/* 입력 본문 / 전사 */}
        {result.transcript_text && (
          <section className="rounded-2xl border border-slate-700 bg-slate-900/60 p-6">
            <h2 className="mb-3 text-lg font-semibold text-slate-100">
              📜 {input_type === "text" ? "입력 본문" : "음성 전사"}
              <span className="ml-2 text-xs text-slate-500">
                ({result.transcript_text.length.toLocaleString()}자)
              </span>
            </h2>
            <details className="text-sm text-slate-300">
              <summary className="cursor-pointer text-slate-400 hover:text-slate-200">
                전체 보기 / 접기
              </summary>
              <pre className="mt-3 max-h-[60vh] overflow-auto whitespace-pre-wrap rounded bg-slate-950/60 p-4 text-xs leading-relaxed">
                {result.transcript_text}
              </pre>
            </details>
          </section>
        )}

        {/* 챗봇 대화 전체 (Q&A 외에 봇 발화도 포함된 풀 트랜스크립트) */}
        {chat_history.length > 0 && (
          <section className="rounded-2xl border border-slate-700 bg-slate-900/60 p-6">
            <h2 className="mb-3 text-lg font-semibold text-slate-100">
              💬 챗봇 대화 전체 ({chat_history.length}턴)
            </h2>
            <details className="text-sm">
              <summary className="cursor-pointer text-slate-400 hover:text-slate-200">
                펼쳐서 보기
              </summary>
              <ol className="mt-3 space-y-2">
                {chat_history.map((t, idx) => (
                  <li
                    key={idx}
                    className={
                      t.role === "user"
                        ? "ml-8 rounded bg-blue-900/30 p-2 text-sm text-blue-100"
                        : "rounded bg-slate-800/40 p-2 text-sm text-slate-200"
                    }
                  >
                    <span className="text-xs text-slate-400">
                      {t.role === "user" ? "👤 사용자" : "🤖 챗봇"}
                    </span>
                    <p className="mt-1 whitespace-pre-wrap">{t.message}</p>
                  </li>
                ))}
              </ol>
            </details>
          </section>
        )}

        {/* Identity Boundary disclaimer */}
        {result.disclaimer && (
          <section className="rounded-2xl border border-slate-700 bg-slate-900/40 p-5 text-sm text-slate-300">
            <p>ⓘ {result.disclaimer}</p>
          </section>
        )}

        <footer className="pt-4 text-center text-xs text-slate-500">
          이 결과 페이지는 1시간 후 자동 만료됩니다.
        </footer>
      </div>
    </main>
  );
}
