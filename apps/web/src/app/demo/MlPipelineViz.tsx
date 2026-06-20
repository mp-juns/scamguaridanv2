"use client";

import {
  Bar,
  BarChart,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { ML_PARTS, type DemoSnapshot, type MlPart } from "../../lib/pipelineArchitecture";

const PART_COLORS = ["#3182f6", "#9333ea", "#16a34a"];

function SessionDots({
  sessions,
}: {
  sessions: Array<{ id: string; status: string }>;
}) {
  if (!sessions.length) {
    return <span className="text-[10px] text-[#c9cdd2]">—</span>;
  }
  const statusColor: Record<string, string> = {
    running: "#f59e0b",
    completed: "#16a34a",
    failed: "#e11d48",
  };
  return (
    <div className="flex flex-wrap gap-1">
      {sessions.slice(0, 4).map((s) => (
        <span
          key={s.id}
          title={`${s.id.slice(0, 8)}… ${s.status}`}
          className="h-2.5 w-2.5 rounded-full"
          style={{ backgroundColor: statusColor[s.status] ?? "#94a3b8" }}
        />
      ))}
    </div>
  );
}

function LabelQueueBar({ pending, annotated }: { pending: number; annotated: number }) {
  const total = pending + annotated || 1;
  const donePct = Math.round((annotated / total) * 100);
  return (
    <div className="rounded-xl border border-[#e5e8eb] bg-white p-4">
      <div className="mb-2 flex justify-between text-xs">
        <span className="font-semibold text-[#191f28]">라벨 큐</span>
        <span className="text-[#8b95a1]">
          완료 {annotated} / 미완료 {pending}
        </span>
      </div>
      <div className="h-3 overflow-hidden rounded-full bg-[#f2f4f6]">
        <div
          className="h-full rounded-full bg-[#3182f6] transition-all duration-500"
          style={{ width: `${donePct}%` }}
        />
      </div>
      <div className="mt-1 text-right text-[10px] font-bold text-[#3182f6]">{donePct}%</div>
    </div>
  );
}

function MlPartCard({
  part,
  snap,
  color,
}: {
  part: MlPart;
  snap: DemoSnapshot[typeof part.id];
  color: string;
}) {
  const active = snap.active_model_path
    ? snap.active_model_path.split("/").slice(-2).join("/")
    : "base";

  return (
    <div className="rounded-xl border border-[#e5e8eb] bg-white p-4">
      <div className="flex items-center gap-2">
        <span
          className="flex h-8 w-8 items-center justify-center rounded-lg text-sm"
          style={{ backgroundColor: `${color}18`, color }}
        >
          {part.emoji}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-xs font-bold text-[#191f28]">{part.title}</div>
          <div className="text-[10px] text-[#8b95a1]">{part.phase}</div>
        </div>
      </div>

      <div className="mt-3 flex items-end gap-2">
        <span className="text-2xl font-black tabular-nums" style={{ color }}>
          {snap.data_count.toLocaleString()}
        </span>
        <span className="mb-1 text-[10px] text-[#8b95a1]">samples</span>
      </div>

      <div className="mt-3 space-y-2 border-t border-[#f2f4f6] pt-3">
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-[#8b95a1]">증강</span>
          <SessionDots sessions={snap.augment_sessions} />
        </div>
        <div className="flex items-center justify-between">
          <span className="text-[10px] text-[#8b95a1]">학습</span>
          <SessionDots sessions={snap.training_sessions} />
        </div>
        <div className="truncate rounded bg-[#f9fafb] px-2 py-1 font-mono text-[9px] text-[#3182f6]">
          {active}
        </div>
      </div>
    </div>
  );
}

export default function MlPipelineViz({ snap }: { snap: DemoSnapshot }) {
  const chartData = ML_PARTS.map((p, i) => ({
    name: p.id.toUpperCase(),
    count: snap[p.id].data_count,
    fill: PART_COLORS[i],
  }));
  const maxCount = Math.max(...chartData.map((d) => d.count), 1);

  return (
    <div className="space-y-4">
      <LabelQueueBar pending={snap.label_queue.pending} annotated={snap.label_queue.annotated} />

      <div className="rounded-xl border border-[#e5e8eb] bg-white p-4">
        <div className="mb-2 text-xs font-semibold text-[#191f28]">ML 3-tier · 데이터량</div>
        <div className="h-40 w-full">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
              <XAxis dataKey="name" tick={{ fontSize: 10, fill: "#8b95a1" }} axisLine={false} tickLine={false} />
              <YAxis
                domain={[0, maxCount * 1.1]}
                tick={{ fontSize: 10, fill: "#8b95a1" }}
                axisLine={false}
                tickLine={false}
              />
              <Tooltip
                formatter={(v) => [Number(v).toLocaleString(), "samples"]}
                contentStyle={{ fontSize: 11, borderRadius: 8, border: "1px solid #e5e8eb" }}
              />
              <Bar dataKey="count" radius={[6, 6, 0, 0]} maxBarSize={48}>
                {chartData.map((entry) => (
                  <Cell key={entry.name} fill={entry.fill} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        {ML_PARTS.map((part, i) => (
          <MlPartCard key={part.id} part={part} snap={snap[part.id]} color={PART_COLORS[i]} />
        ))}
      </div>
    </div>
  );
}
