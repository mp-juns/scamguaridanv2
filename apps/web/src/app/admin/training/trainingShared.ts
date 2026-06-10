// TrainingClient 공유 타입 + 포맷 헬퍼 — panels/KnowledgeGraphCanvas/본체가 공용.
export type DataStats = {
  classifier: { total: number; labels: Record<string, number> };
  gliner: {
    total: number;
    base_total?: number;
    total_entities: number;
    base_total_entities?: number;
    labels?: Record<string, number>;
    label_count?: number;
    extra_jsonl?: string;
  };
};

export type SessionInfo = {
  session_id: string;
  model: string;
  kind?: string;
  gate_name?: string;
  status: "running" | "completed" | "failed" | "cancelled";
  started_at: number;
  ended_at: number | null;
  exit_code: number | null;
  pid: number | null;
  output_dir: string;
  params: Record<string, unknown>;
  last_metrics: Record<string, unknown> | null;
};

export type SessionDetail = {
  session: SessionInfo;
  metrics: Record<string, unknown>[];
  log_tail: string;
  loss_spikes?: LossSpike[];
};

export type LossSpikeExample = {
  idx?: number;
  label?: string;
  source?: string;
  content_label?: string;
  sample_kind?: string;
  run_id?: string | null;
  source_ref?: string | null;
  text_len?: number;
  batch_text_len?: number | null;
  preview?: string;
  sample_loss?: number;
  gold_label?: string;
  pred_label?: string;
  pred_confidence?: number;
};

export type LossSpike = {
  kind: "loss_spike";
  step: number;
  epoch?: number | null;
  loss: number;
  max_sample_loss?: number;
  batch_size?: number;
  learning_rate?: number;
  examples?: LossSpikeExample[];
  ts?: number;
};

export type CompareScore = {
  label: string;
  score: number;
};

export type CompareSample = {
  id: string;
  expected: string;
  text: string;
  raw: {
    prediction: string;
    confidence: number;
    is_correct: boolean;
    top_scores: CompareScore[];
  };
  fine_tuned: {
    prediction: string;
    confidence: number;
    is_correct: boolean;
    top_scores: CompareScore[];
  };
  delta: {
    changed: boolean;
    confidence: number;
  };
};

export type ComparisonResult = {
  session_id: string;
  output_dir: string;
  sample_count: number;
  raw: { correct: number; accuracy: number };
  fine_tuned: { correct: number; accuracy: number };
  delta: { correct: number; accuracy: number; changed_predictions: number };
  samples: CompareSample[];
};

export type SyntheticAttempt = {
  session_id: string;
  output_dir: string;
  has_adapter: boolean;
  saves_classifier_head: boolean;
  label_count: number;
  global_step: number | null;
  epoch: number | null;
  best_metric: number | null;
  evals: Record<string, number | null>[];
  final_eval: Record<string, number | null>;
};

export type SyntheticGraphNode = {
  id: string;
  label: string;
  kind: "corpus" | "axis" | "scam_type" | "entity_label";
  group: string;
  weight: number;
};

export type SyntheticGraphLink = {
  source: string;
  target: string;
  kind: string;
  weight: number;
};

export type SyntheticSummary = {
  dataset: {
    path: string;
    total: number;
    labels: Record<string, number>;
    label_count: number;
    min_per_label: number;
    max_per_label: number;
  };
  graph?: {
    nodes: SyntheticGraphNode[];
    links: SyntheticGraphLink[];
  };
  attempts: SyntheticAttempt[];
  best_attempt: SyntheticAttempt | null;
  status: {
    headline: string;
    activation_ready: boolean;
    reason: string;
    next_step: string;
  };
};

export type SessionsResponse = {
  sessions: SessionInfo[];
  active_models: Record<string, string>;
};

export type StartTrainingResponse = SessionInfo | {
  session_id: string;
  status: "running";
  model: "multi";
  sessions: SessionInfo[];
  queued_sequence?: unknown;
};

export type GatePerClassMetric = {
  precision: number;
  recall: number;
  f1: number;
  support: number;
};

export type GateWatchCell = {
  true: string;
  pred: string;
  count: number;
  denom: number;
  rate: number;
};

export type GateMetrics = {
  accuracy?: number;
  macro_f1?: number;
  labels?: string[];
  per_class?: Record<string, GatePerClassMetric>;
  confusion?: number[][];
  watch_cells?: GateWatchCell[];
};

export const GATE_LABEL_KO: Record<string, string> = {
  normal: "정상",
  scam_attempt: "사기 시도",
  scam_news_edu: "사기 예방·뉴스",
};

export function gateLabelKo(label: string): string {
  return GATE_LABEL_KO[label] ?? label;
}

export const STATUS_BADGE: Record<string, string> = {
  running: "bg-cyan-500/20 text-cyan-200 border-cyan-400/30",
  completed: "bg-emerald-500/20 text-emerald-200 border-emerald-400/30",
  failed: "bg-rose-500/20 text-rose-200 border-rose-400/30",
  cancelled: "bg-slate-500/20 text-slate-200 border-slate-400/30",
};

export function fmtSeconds(value: number | null | undefined): string {
  if (!value) return "-";
  const d = new Date(value * 1000);
  return d.toLocaleString("ko-KR", { hour12: false });
}

export function fmtDuration(start: number, end: number | null | undefined): string {
  const sec = Math.floor(((end ?? Date.now() / 1000) - start));
  if (sec < 60) return `${sec}초`;
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  if (m < 60) return `${m}분 ${s}초`;
  const h = Math.floor(m / 60);
  return `${h}시간 ${m % 60}분`;
}

export function pct(value: unknown): string {
  return typeof value === "number" ? `${Math.round(value * 1000) / 10}%` : "-";
}

export function metricValue(value: unknown): string {
  if (typeof value !== "number") return "-";
  if (Math.abs(value) >= 10) return value.toFixed(1);
  return value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
}

export function attemptName(id: string): string {
  if (id.includes("lr5e6")) return "낮은 학습률";
  if (id.includes("lora_head")) return "저장 보완";
  if (id.includes("e3")) return "3회 반복";
  if (id.includes("1542")) return "첫 확인";
  return id.slice(-8);
}
