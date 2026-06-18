import { ReactNode } from "react";

import type { ContentType, Entity, TranscriptSpan } from "./homeTypes";

export function contentTypeBadge(
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
      icon: "💬",
      label: "일반 메시지",
      chip: "border-slate-300 bg-slate-100 text-slate-600",
    };
  }
  // 게이트는 normal 이지만 룰 기반 고위험 신호가 감지된 경우 — 정상 단정 금지
  if (bucket === "needs_review") {
    return {
      icon: "⚠️",
      label: "추가 확인 필요",
      chip: "border-amber-500/40 bg-amber-700/20 text-amber-700",
    };
  }
  return null;
}

export function formatPercent(value: number) {
  return new Intl.NumberFormat("ko-KR", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
}

export function entityKey(entity: Entity, index: number) {
  return `${entity.label}-${entity.text}-${entity.start ?? "na"}-${entity.end ?? "na"}-${index}`;
}

export function sourceBadgeClass(source?: string) {
  return source === "llm"
    ? "bg-fuchsia-500/15 text-fuchsia-700 ring-1 ring-fuchsia-500/30"
    : "bg-[#e8f3ff] text-[#3182f6] ring-1 ring-[#3182f6]/30";
}

export function renderTranscriptWithHighlights(
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
