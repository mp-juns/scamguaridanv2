import { useRef, useState } from "react";

import type { Phase, StreamChunk, StreamMatch, Turn } from "./liveTypes";
import { fmtTime, pickAlertAction, speakerTag } from "./liveSignals";

export function CautionBanner({ matches }: { matches: StreamMatch[] }) {
  const labels = Array.from(new Set(matches.map((m) => m.label_ko))).slice(0, 4);
  return (
    <div
      role="alert"
      className="mt-4 flex animate-pulse items-start gap-3 rounded-2xl border border-amber-400/50 bg-amber-500/15 px-5 py-4 text-amber-700"
    >
      <div className="text-2xl leading-none">⚠️</div>
      <div>
        <div className="text-base font-bold">주의 신호가 쌓이고 있어요</div>
        <div className="mt-1 text-xs leading-5 opacity-90">
          {labels.length ? labels.join(" · ") : "사기 의심 신호"} 감지됨 — 발화 맥락을 다시 확인하세요.
        </div>
      </div>
    </div>
  );
}

export function DangerOverlay({
  matches,
  onDismiss,
}: {
  matches: StreamMatch[];
  onDismiss: () => void;
}) {
  const picked = pickAlertAction(matches);
  return (
    <div
      role="alertdialog"
      aria-modal="true"
      className="animate-danger-flash fixed inset-0 z-50 flex flex-col items-center justify-center px-6 text-center"
    >
      <div className="mb-3 text-6xl">🚨</div>
      <div className="text-3xl font-black text-white drop-shadow-lg">
        지금 전화를 끊으세요
      </div>
      {picked && (
        <div className="mt-4 inline-block rounded-full bg-white/15 px-3 py-1 text-sm font-semibold text-white">
          {speakerTag(picked.speaker) ? speakerTag(picked.speaker) + " · " : ""}
          {picked.label}
        </div>
      )}
      {picked && (
        <div className="mt-3 max-w-md text-lg font-semibold text-rose-50">
          {picked.action}
        </div>
      )}
      <div className="mt-3 max-w-md text-sm text-rose-50/90">
        위험 신호가 감지되었습니다. ScamGuardian 은 신호만 알려드려요 — 최종 판단은 본인이 하세요.
      </div>
      <button
        type="button"
        onClick={onDismiss}
        className="mt-8 rounded-full bg-white/95 px-7 py-3 text-base font-bold text-rose-700 shadow-lg hover:bg-white"
      >
        확인했어요
      </button>
    </div>
  );
}

export function ChunkRow({ chunk }: { chunk: StreamChunk }) {
  const tone =
    chunk.alert_level >= 3
      ? "border-rose-400/60 bg-rose-500/10"
      : chunk.alert_level === 2
        ? "border-amber-400/40 bg-amber-500/10"
        : chunk.alert_level === 1
          ? "border-yellow-400/30 bg-yellow-500/5"
          : "border-[#e5e8eb] bg-white";
  const badge =
    chunk.alert_level >= 3
      ? { label: "DANGER", tone: "bg-rose-500/80 text-white" }
      : chunk.alert_level === 2
        ? { label: "WARN", tone: "bg-amber-500/80 text-white" }
        : chunk.alert_level === 1
          ? { label: "WATCH", tone: "bg-yellow-400/60 text-slate-900" }
          : { label: "OK", tone: "bg-emerald-500/30 text-emerald-700" };
  return (
    <li className={`rounded-xl border px-4 py-3 ${tone}`}>
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
        <div className="flex items-center gap-2 text-[#333d4b]">
          <span className="font-semibold">청크 {chunk.chunk_index + 1}</span>
          <span className="text-[#8b95a1]">
            {fmtTime(chunk.start_sec)} ~ {fmtTime(chunk.end_sec)}
          </span>
          <span className="text-[#8b95a1]">· {chunk.latency_ms} ms</span>
        </div>
        <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold tracking-wide ${badge.tone}`}>
          {badge.label}
        </span>
      </div>
      {chunk.turns && chunk.turns.length > 0 ? (
        <div className="mt-2">
          <Conversation turns={chunk.turns} />
        </div>
      ) : chunk.transcript ? (
        <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-[#191f28]">
          {chunk.transcript}
        </p>
      ) : (
        <p className="mt-2 text-sm italic text-[#8b95a1]">(빈 전사)</p>
      )}
      {chunk.matches.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
          {chunk.matches.map((m, i) => (
            <li
              key={`${m.flag}-${i}`}
              className="rounded-full border border-rose-400/40 bg-rose-500/10 px-2 py-0.5 text-rose-700"
            >
              {speakerTag(m.speaker) ? speakerTag(m.speaker) + " · " : ""}
              {m.label_ko} · &ldquo;{m.snippet}&rdquo;
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export function PhaseBadge({ phase, prefix }: { phase: Phase; prefix: string }) {
  const badge = (() => {
    switch (phase) {
      case "running":
        return { label: "처리 중", tone: "border-amber-300/40 bg-amber-400/10 text-amber-700" };
      case "done":
        return { label: "완료", tone: "border-emerald-300/40 bg-emerald-400/10 text-emerald-700" };
      case "error":
        return { label: "오류", tone: "border-rose-400/50 bg-rose-500/15 text-rose-700" };
      default:
        return { label: "대기", tone: "border-[#e5e8eb] bg-white text-[#4e5968]" };
    }
  })();
  return (
    <span className={`rounded-full border px-2 py-0.5 uppercase ${badge.tone}`}>
      {prefix} · {badge.label}
    </span>
  );
}

export function Conversation({
  turns,
  audioUrl,
}: {
  turns: Turn[];
  audioUrl?: string | null;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const pauseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [playingIndex, setPlayingIndex] = useState<number | null>(null);

  const playSegment = (index: number, turn: Turn) => {
    if (!audioRef.current || turn.start_sec == null || turn.end_sec == null) return;
    if (pauseTimerRef.current) {
      clearTimeout(pauseTimerRef.current);
      pauseTimerRef.current = null;
    }
    audioRef.current.currentTime = turn.start_sec;
    void audioRef.current.play().catch(() => {});
    setPlayingIndex(index);
    const durationMs = Math.max(200, (turn.end_sec - turn.start_sec) * 1000);
    pauseTimerRef.current = setTimeout(() => {
      audioRef.current?.pause();
      setPlayingIndex(null);
    }, durationMs);
  };

  const stopPlayback = () => {
    if (pauseTimerRef.current) {
      clearTimeout(pauseTimerRef.current);
      pauseTimerRef.current = null;
    }
    audioRef.current?.pause();
    setPlayingIndex(null);
  };

  return (
    <div className="space-y-2">
      {audioUrl ? <audio ref={audioRef} src={audioUrl} className="hidden" /> : null}
      {turns.map((t, i) => {
        const me = t.speaker === "본인";
        const playable = Boolean(audioUrl && t.start_sec != null && t.end_sec != null);
        return (
          <div
            key={`${t.speaker}-${i}-${t.text.slice(0, 20)}`}
            className={`flex ${me ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[82%] rounded-2xl px-4 py-3 text-sm leading-6 ${
                me ? "bg-[#3182f6] text-white" : "border border-[#e5e8eb] bg-white text-[#191f28]"
              }`}
            >
              <div className={`mb-1 flex items-center justify-between gap-2 text-[11px] ${me ? "text-white/75" : "text-[#8b95a1]"}`}>
                <span>{speakerTag(t.speaker) || t.speaker}</span>
                {t.start_sec != null ? <span className="opacity-60">{fmtTime(Math.floor(t.start_sec))}</span> : null}
              </div>
              <div className="whitespace-pre-wrap">{t.text}</div>
              {t.entities?.length ? (
                <div className={`mt-2 flex flex-wrap gap-1 text-[10px] ${me ? "text-white/90" : "text-[#3182f6]"}`}>
                  {t.entities.slice(0, 4).map((e, idx) => (
                    <span
                      key={`${e.label}-${e.text}-${idx}`}
                      className={`rounded-full px-2 py-0.5 ${me ? "bg-white/15" : "bg-[#e8f3ff]"}`}
                    >
                      {e.label}: {e.text}
                    </span>
                  ))}
                </div>
              ) : null}
              {playable ? (
                <button
                  type="button"
                  onClick={() => (playingIndex === i ? stopPlayback() : playSegment(i, t))}
                  className={`mt-2 rounded-full px-2 py-1 text-[11px] font-semibold ${
                    me ? "bg-white/15 text-white hover:bg-white/25" : "bg-[#f2f4f6] text-[#4e5968] hover:bg-[#e5e8eb]"
                  }`}
                >
                  {playingIndex === i ? "정지" : "▶ 이 구간 듣기"}
                </button>
              ) : null}
            </div>
          </div>
        );
      })}
    </div>
  );
}
