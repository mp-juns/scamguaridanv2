export type DetectedSignal = {
  flag: string;
  score_delta?: number;
  label_ko?: string;
  rationale?: string;
  source?: string;
  evidence?: Record<string, unknown>;
};

export type AnalysisResult = {
  scam_type?: string;
  classification_confidence?: number;
  detected_signals?: DetectedSignal[];
  triggered_flags?: DetectedSignal[];
  transcript_text?: string;
  analysis_run_id?: string;
  summary?: string;
  disclaimer?: string;
};

export type TurnEntity = {
  label: string;
  text: string;
};

export type Turn = {
  speaker: string;
  text: string;
  entities?: TurnEntity[];
  start_sec?: number;
  end_sec?: number;
};

export type TranscriptResult = {
  transcript_text: string;
  turns?: Turn[];
  language?: string;
  source_type?: string;
  latency_ms?: number;
  stt_ms?: number;
  diarize_ms?: number;
  source_filename?: string;
};

export type Phase = "idle" | "running" | "done" | "error";

export type StreamMatch = {
  flag: string;
  label_ko: string;
  level: number;
  snippet: string;
  instant?: boolean;
  action?: string;
  speaker?: string | null;
};

export type StreamChunk = {
  chunk_index: number;
  start_sec: number;
  end_sec: number;
  transcript: string;
  turns?: Turn[];
  alert_level: number;
  matches: StreamMatch[];
  tier?: number;
  tier_changed?: boolean;
  latency_ms: number;
};

export type Mode = "single" | "stream" | "live";
