"use client";

import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

// recharts 는 ~400KB raw 의 무거운 클라이언트 라이브러리다. admin 차트들을 이 단일
// 모듈에 모아 각 페이지에서 next/dynamic(ssr:false) 으로 lazy-load 하면, recharts 가
// "하나의" async 청크로만 번들되어 (1) 초기 admin 진입 JS 에서 제외되고 (2) 페이지별
// 중복(stats/platform/training/augment 4중복)이 제거된다.

const usdTick = (v: number) => (v < 1 ? `$${v.toFixed(2)}` : `$${v.toFixed(0)}`);
const darkTooltip = {
  background: "#0f172a",
  border: "1px solid #334155",
} as const;
const darkTooltipBox = {
  backgroundColor: "#0f172a",
  border: "1px solid #334155",
  borderRadius: 8,
  fontSize: 12,
} as const;

function pct(value: unknown): string {
  return typeof value === "number" ? `${Math.round(value * 1000) / 10}%` : "-";
}

// ── stats ─────────────────────────────────────────────────────────────

export function DailyRunsChart({
  data,
}: {
  data: { date: string; count: number }[];
}) {
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={data}>
        <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
        <XAxis
          dataKey="date"
          tick={{ fontSize: 11 }}
          tickFormatter={(v: string) => v.slice(5)}
        />
        <YAxis tick={{ fontSize: 11 }} allowDecimals={false} />
        <Tooltip />
        <Line
          type="monotone"
          dataKey="count"
          stroke="#3b82f6"
          strokeWidth={2}
          dot={false}
          name="분석 수"
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function HBarChart({
  data,
  height,
  fill,
  name,
}: {
  data: { name: string; count: number }[];
  height: number;
  fill: string;
  name: string;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ left: 10, right: 20 }}>
        <XAxis type="number" tick={{ fontSize: 11 }} allowDecimals={false} />
        <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={100} />
        <Tooltip />
        <Bar dataKey="count" fill={fill} radius={[0, 4, 4, 0]} name={name} />
      </BarChart>
    </ResponsiveContainer>
  );
}

// ── platform ──────────────────────────────────────────────────────────

export function DailyCostArea({
  data,
  fmtMoney,
}: {
  data: { label: string; usd: number }[];
  fmtMoney: (n: number) => string;
}) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <AreaChart data={data} margin={{ top: 5, right: 8, left: 0, bottom: 5 }}>
        <defs>
          <linearGradient id="costGradient" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#22d3ee" stopOpacity={0.6} />
            <stop offset="100%" stopColor="#22d3ee" stopOpacity={0.05} />
          </linearGradient>
        </defs>
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
        <XAxis
          dataKey="label"
          stroke="#64748b"
          tick={{ fontSize: 11 }}
          axisLine={{ stroke: "#334155" }}
        />
        <YAxis
          stroke="#64748b"
          tick={{ fontSize: 11 }}
          axisLine={{ stroke: "#334155" }}
          tickFormatter={usdTick}
        />
        <Tooltip
          contentStyle={darkTooltipBox}
          labelStyle={{ color: "#cbd5e1" }}
          formatter={(value, name) => {
            const n = typeof value === "number" ? value : Number(value ?? 0);
            return name === "usd" ? [fmtMoney(n), "USD"] : [`${n}회`, "호출"];
          }}
        />
        <Area
          type="monotone"
          dataKey="usd"
          stroke="#22d3ee"
          strokeWidth={2}
          fill="url(#costGradient)"
        />
      </AreaChart>
    </ResponsiveContainer>
  );
}

export function ProviderBar({
  data,
  fmtMoney,
  colorOf,
}: {
  data: { provider: string; usd: number }[];
  fmtMoney: (n: number) => string;
  colorOf: (provider: string) => string;
}) {
  return (
    <ResponsiveContainer width="100%" height={Math.max(120, data.length * 38)}>
      <BarChart
        data={data}
        layout="vertical"
        margin={{ top: 0, right: 16, left: 0, bottom: 0 }}
      >
        <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" horizontal={false} />
        <XAxis
          type="number"
          stroke="#64748b"
          tick={{ fontSize: 11 }}
          axisLine={{ stroke: "#334155" }}
          tickFormatter={usdTick}
        />
        <YAxis
          type="category"
          dataKey="provider"
          stroke="#64748b"
          tick={{ fontSize: 12 }}
          axisLine={{ stroke: "#334155" }}
          width={92}
        />
        <Tooltip
          contentStyle={darkTooltipBox}
          labelStyle={{ color: "#cbd5e1" }}
          formatter={(value) => {
            const n = typeof value === "number" ? value : Number(value ?? 0);
            return [fmtMoney(n), "USD"];
          }}
        />
        <Bar dataKey="usd" radius={[0, 6, 6, 0]}>
          {data.map((p) => (
            <Cell key={p.provider} fill={colorOf(p.provider)} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ── augment ───────────────────────────────────────────────────────────

export function CoverageBar({
  data,
}: {
  data: { type: string; count: number; starved: boolean }[];
}) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 40, left: 0 }}>
        <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
        <XAxis
          dataKey="type"
          stroke="#64748b"
          fontSize={10}
          angle={-35}
          textAnchor="end"
          interval={0}
          height={60}
        />
        <YAxis stroke="#64748b" fontSize={11} allowDecimals={false} />
        <Tooltip contentStyle={darkTooltip} labelStyle={{ color: "#cbd5f5" }} />
        <Bar dataKey="count">
          {data.map((d) => (
            <Cell key={d.type} fill={d.starved ? "#f43f5e" : "#22d3ee"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function AugmentProgressLine({
  data,
}: {
  data: { done: number | undefined; generated: number }[];
}) {
  return (
    <ResponsiveContainer width="100%" height={180}>
      <LineChart data={data}>
        <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
        <XAxis dataKey="done" stroke="#64748b" fontSize={10} />
        <YAxis stroke="#64748b" fontSize={10} allowDecimals={false} />
        <Tooltip contentStyle={darkTooltip} labelStyle={{ color: "#cbd5f5" }} />
        <Line type="monotone" dataKey="generated" stroke="#22d3ee" dot={false} connectNulls />
      </LineChart>
    </ResponsiveContainer>
  );
}

// ── training ──────────────────────────────────────────────────────────

export type LabelBar = { label: string; count: number };

export function SyntheticLabelBar({ data }: { data: LabelBar[] }) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <BarChart data={data} layout="vertical" margin={{ left: 42, right: 12 }}>
        <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" horizontal={false} />
        <XAxis type="number" stroke="#64748b" fontSize={11} />
        <YAxis dataKey="label" type="category" width={86} stroke="#94a3b8" fontSize={11} />
        <Tooltip contentStyle={darkTooltip} labelStyle={{ color: "#cbd5f5" }} />
        <Bar dataKey="count" radius={[0, 6, 6, 0]}>
          {data.map((entry, index) => (
            <Cell key={entry.label} fill={index % 2 ? "#38bdf8" : "#22c55e"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function AttemptLine({
  data,
}: {
  data: { name: string; f1: number; accuracy: number }[];
}) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data}>
        <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
        <XAxis dataKey="name" stroke="#94a3b8" fontSize={11} />
        <YAxis
          stroke="#64748b"
          fontSize={11}
          domain={[0, 1]}
          tickFormatter={(v) => `${Math.round(Number(v) * 100)}%`}
        />
        <Tooltip
          formatter={(value) => pct(value)}
          contentStyle={darkTooltip}
          labelStyle={{ color: "#cbd5f5" }}
        />
        <Legend />
        <Line type="monotone" dataKey="f1" name="골고루 맞힌 정도" stroke="#22c55e" strokeWidth={2} />
        <Line type="monotone" dataKey="accuracy" name="전체 정답률" stroke="#a78bfa" strokeWidth={2} />
      </LineChart>
    </ResponsiveContainer>
  );
}

export function GlinerLabelBar({ data }: { data: LabelBar[] }) {
  return (
    <ResponsiveContainer width="100%" height={320}>
      <BarChart data={data} layout="vertical" margin={{ left: 94, right: 14 }}>
        <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" horizontal={false} />
        <XAxis type="number" stroke="#64748b" fontSize={11} />
        <YAxis dataKey="label" type="category" width={132} stroke="#94a3b8" fontSize={11} />
        <Tooltip contentStyle={darkTooltip} labelStyle={{ color: "#cbd5f5" }} />
        <Bar dataKey="count" radius={[0, 6, 6, 0]}>
          {data.map((entry, index) => (
            <Cell key={entry.label} fill={index < 6 ? "#38bdf8" : "#818cf8"} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

// ── gate (content_label 3-class) ──────────────────────────────────────

export type GatePerClass = {
  label: string;
  precision: number;
  recall: number;
  f1: number;
};

export function GatePerClassBar({ data }: { data: GatePerClass[] }) {
  return (
    <ResponsiveContainer width="100%" height={240}>
      <BarChart data={data} margin={{ top: 8, right: 8, bottom: 8, left: 0 }}>
        <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
        <XAxis dataKey="label" stroke="#94a3b8" fontSize={11} />
        <YAxis
          stroke="#64748b"
          fontSize={11}
          domain={[0, 1]}
          tickFormatter={(v) => `${Math.round(Number(v) * 100)}%`}
        />
        <Tooltip
          formatter={(value) => pct(value)}
          contentStyle={darkTooltip}
          labelStyle={{ color: "#cbd5f5" }}
        />
        <Legend />
        <Bar dataKey="precision" name="정밀도(P)" fill="#22d3ee" radius={[4, 4, 0, 0]} />
        <Bar dataKey="recall" name="재현율(R)" fill="#a78bfa" radius={[4, 4, 0, 0]} />
        <Bar dataKey="f1" name="F1" fill="#22c55e" radius={[4, 4, 0, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export type MetricRow = {
  step: number;
  loss: number | null;
  eval_loss: number | null;
  eval_macro_f1: number | null;
  eval_accuracy: number | null;
  gliner_progress: number | null;
  gliner_train_size: number | null;
  gliner_val_size: number | null;
  gliner_label_count: number | null;
};

export function TrainingMetricsChart({
  data,
  hasClassifierChart,
  hasGlinerChart,
}: {
  data: MetricRow[];
  hasClassifierChart: boolean;
  hasGlinerChart: boolean;
}) {
  return (
    <ResponsiveContainer width="100%" height={260}>
      <LineChart data={data}>
        <CartesianGrid stroke="#1e293b" strokeDasharray="3 3" />
        <XAxis dataKey="step" stroke="#64748b" fontSize={11} />
        <YAxis stroke="#64748b" fontSize={11} />
        <Tooltip contentStyle={darkTooltip} labelStyle={{ color: "#cbd5f5" }} />
        <Legend />
        {hasClassifierChart && (
          <>
            <Line type="monotone" dataKey="loss" stroke="#22d3ee" dot={false} connectNulls />
            <Line type="monotone" dataKey="eval_loss" stroke="#f97316" dot={false} connectNulls />
            <Line type="monotone" dataKey="eval_macro_f1" stroke="#22c55e" dot={false} connectNulls />
            <Line type="monotone" dataKey="eval_accuracy" stroke="#a78bfa" dot={false} connectNulls />
          </>
        )}
        {hasGlinerChart && (
          <Line
            type="monotone"
            dataKey="gliner_progress"
            name="gliner_progress"
            stroke="#38bdf8"
            strokeWidth={2}
            dot
            connectNulls
          />
        )}
      </LineChart>
    </ResponsiveContainer>
  );
}
