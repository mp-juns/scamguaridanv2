// AdminRunEditor 공유 타입 + 순수 헬퍼 — RunContextPanel/RunMediaPanel 과 본체가 공용.
import { type ReactNode } from "react";

export type EntityItem = {
  text: string;
  label: string;
  score?: number;
  source?: string;
  start?: number;
  end?: number;
};

export type FlagItem = {
  flag: string;
  description?: string;
  evidence?: string[];
  score_delta?: number;
  source?: string;
};

export type AnnotationFlag = {
  flag: string;
  description?: string;
  evidence?: string;
  source?: string;
};

export type ChatTurn = { role?: string; message?: string };
export type QAPair = { question?: string; answer?: string };
export type UserContext = {
  qa_pairs?: QAPair[];
  summary_text?: string;
  turn_count?: number;
};
export type RunMedia = {
  kind?: string;
  original_filename?: string;
  stored_path?: string;
  size_bytes?: number;
  suffix?: string;
};

export type RunMetadata = {
  user_context?: UserContext | null;
  chat_history?: ChatTurn[];
  refined_llm_assessment?: Record<string, unknown> | null;
  source_type?: string;
  media?: RunMedia | null;
  [key: string]: unknown;
};

export type RunDetailResponse = {
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

export type EditableEntity = EntityItem & {
  id: string;
  enabled: boolean;
};

export type EditableFlag = AnnotationFlag & {
  id: string;
  enabled: boolean;
};

export function makeId() {
  return crypto.randomUUID();
}

export const VIDEO_SUFFIXES = new Set([".mp4", ".mov", ".webm", ".mkv"]);
export const AUDIO_SUFFIXES = new Set([".mp3", ".m4a", ".wav", ".ogg", ".aac"]);
export const IMAGE_SUFFIXES = new Set([".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"]);
export const PDF_SUFFIXES = new Set([".pdf"]);

// content_label — Stage 1 게이트와 동일 어휘. scam_type 보다 먼저 선택하는 기준 라벨.
export const SCAM_ATTEMPT = "scam_attempt";
export const CONTENT_LABEL_OPTIONS: { value: string; label: string }[] = [
  { value: "normal", label: "정상 (normal)" },
  { value: "scam_attempt", label: "사기 시도 (scam_attempt)" },
  { value: "scam_news_edu", label: "사기 뉴스·교육 (scam_news_edu)" },
  { value: "suspicious_insufficient", label: "의심·불충분 (suspicious_insufficient)" },
  { value: "undetermined", label: "판단 불가 (undetermined)" },
];
export const CONTENT_LABEL_VALUES = CONTENT_LABEL_OPTIONS.map((o) => o.value);

export const SAMPLE_KIND_OPTIONS: { value: string; label: string }[] = [
  { value: "real_scam_message", label: "실제 사기 메시지 (real_scam_message)" },
  { value: "synthetic_scam_message", label: "합성 사기 메시지 (synthetic_scam_message)" },
  { value: "scam_news_education", label: "뉴스·교육 (scam_news_education)" },
  { value: "normal_content", label: "정상 콘텐츠 (normal_content)" },
  { value: "review_needed", label: "검수 필요 (review_needed)" },
];

// 기존 annotation 에 content_label 이 없을 때 fallback (백엔드 resolve_content_label 과 동일).
export function resolveContentLabel(contentLabel: string, scamType: string): string {
  const cl = (contentLabel ?? "").trim();
  if (CONTENT_LABEL_VALUES.includes(cl)) return cl;
  const st = (scamType ?? "").trim();
  if (st && st !== "정상 대화") return SCAM_ATTEMPT;
  return "undetermined";
}

// sample_kind 미지정 시 content_label 로 추정.
export function inferSampleKind(contentLabel: string): string {
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

export function isHttpUrl(value: string): boolean {
  return /^https?:\/\//i.test(value.trim());
}

export function isYoutubeUrl(value: string): boolean {
  return /(?:youtube\.com\/|youtu\.be\/)/i.test(value);
}

export function youtubeEmbedUrl(value: string): string | null {
  const m = value.match(/(?:v=|youtu\.be\/|embed\/)([\w-]{11})/);
  return m ? `https://www.youtube.com/embed/${m[1]}` : null;
}

export function formatBytes(bytes?: number): string {
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

export function formatPercent(value: number) {
  return new Intl.NumberFormat("ko-KR", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

export function mapEntity(item: EntityItem): EditableEntity {
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

export function mapFlag(item: AnnotationFlag | FlagItem): EditableFlag {
  return {
    id: makeId(),
    flag: item.flag ?? "",
    description: item.description ?? "",
    evidence: Array.isArray(item.evidence) ? item.evidence.join(" | ") : item.evidence ?? "",
    source: item.source ?? "human",
    enabled: true,
  };
}

export type TranscriptEntitySpan = {
  start: number;
  end: number;
  label: string;
  text: string;
};

export function renderTranscriptWithEntityHighlights(
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
