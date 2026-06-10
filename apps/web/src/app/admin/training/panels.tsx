"use client";

// TrainingClient 세션 상세 패널 모음 — 손실 진단·비교·게이트 메트릭·소형 위젯.
import dynamic from "next/dynamic";

import {
  gateLabelKo,
  metricValue,
  pct,
  type ComparisonResult,
  type GateMetrics,
  type LossSpike,
} from "./trainingShared";

// recharts 단일 lazy 청크 패턴 유지 (charts.tsx 주석 참고)
const GatePerClassBar = dynamic(
  () => import("../charts").then((m) => m.GatePerClassBar),
  { ssr: false },
);

export function LossSpikePanel({ spikes }: { spikes: LossSpike[] }) {
  const ordered = spikes
    .slice()
    .sort((a, b) => (b.loss ?? 0) - (a.loss ?? 0))
    .slice(0, 12);

  return (
    <div className="overflow-hidden rounded-xl border border-amber-300/20 bg-amber-500/5">
      <div className="border-b border-amber-300/10 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-xs uppercase tracking-widest text-amber-200">손실 튐 진단</div>
            <h3 className="mt-1 text-lg font-semibold text-white">모델이 크게 헷갈린 학습 배치</h3>
            <p className="mt-1 text-xs leading-relaxed text-slate-400">
              batch loss 가 임계값을 넘은 순간의 샘플을 기록합니다. 라벨 충돌, 너무 긴 문장,
              synthetic 패턴 편향을 찾기 위한 내부 학습 로그입니다.
            </p>
          </div>
          <div className="font-mono text-xs text-amber-100/70">{spikes.length} spikes</div>
        </div>
      </div>

      <div className="max-h-[520px] space-y-3 overflow-auto p-4">
        {ordered.map((spike) => (
          <details
            key={`${spike.step}-${spike.loss}`}
            className="rounded-xl border border-white/10 bg-slate-950/50 p-3"
          >
            <summary className="cursor-pointer list-none">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-sm text-amber-100">step {spike.step}</span>
                  <span className="rounded-full border border-amber-300/20 bg-amber-300/10 px-2 py-0.5 text-xs text-amber-100">
                    loss {metricValue(spike.loss)}
                  </span>
                  <span className="rounded-full border border-white/10 bg-white/5 px-2 py-0.5 text-xs text-slate-300">
                    max sample {metricValue(spike.max_sample_loss)}
                  </span>
                </div>
                <div className="font-mono text-xs text-slate-500">
                  epoch {metricValue(spike.epoch)} · lr {metricValue(spike.learning_rate)}
                </div>
              </div>
            </summary>
            <div className="mt-3 space-y-2">
              {(spike.examples ?? []).map((example, index) => (
                <div key={`${spike.step}-${example.idx ?? index}`} className="rounded-lg border border-white/10 bg-black/20 p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className="font-mono text-slate-500">#{example.idx ?? index}</span>
                      <span className="rounded-full bg-cyan-300/10 px-2 py-0.5 text-cyan-100">
                        gold {example.gold_label ?? example.label ?? "-"}
                      </span>
                      <span className="rounded-full bg-rose-300/10 px-2 py-0.5 text-rose-100">
                        pred {example.pred_label ?? "-"}
                      </span>
                    </div>
                    <div className="font-mono text-xs text-slate-500">
                      sample loss {metricValue(example.sample_loss)} · conf {pct(example.pred_confidence)}
                    </div>
                  </div>
                  <div className="mt-2 text-xs text-slate-500">
                    source {example.source ?? "-"} · kind {example.sample_kind ?? "-"} · len{" "}
                    {example.text_len ?? example.batch_text_len ?? "-"}
                  </div>
                  {example.preview && (
                    <p className="mt-2 line-clamp-3 text-sm leading-relaxed text-slate-300">
                      {example.preview}
                    </p>
                  )}
                </div>
              ))}
            </div>
          </details>
        ))}
      </div>
    </div>
  );
}

export function ClassifierComparisonPanel({ comparison }: { comparison: ComparisonResult }) {
  const improved = comparison.samples.filter((sample) => !sample.raw.is_correct && sample.fine_tuned.is_correct).length;
  const regressed = comparison.samples.filter((sample) => sample.raw.is_correct && !sample.fine_tuned.is_correct).length;
  return (
    <div className="overflow-hidden rounded-xl border border-violet-300/20 bg-slate-950/50">
      <div className="border-b border-white/10 p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-xs uppercase tracking-widest text-violet-200">Raw vs Fine-tuned</div>
            <h3 className="mt-1 text-lg font-semibold text-white">같은 문장으로 분류기 비교</h3>
            <p className="mt-1 text-xs text-slate-400">
              기본 zero-shot 모델과 이 세션의 fine-tuned checkpoint 를 12개 실전형 smoke 문장에 동시에 적용했습니다.
            </p>
          </div>
          <div className="font-mono text-xs text-slate-500">{comparison.session_id}</div>
        </div>

        <div className="mt-4 grid gap-3 sm:grid-cols-4">
          <PlainMetric
            label="Raw 정답"
            value={`${comparison.raw.correct}/${comparison.sample_count}`}
            help={pct(comparison.raw.accuracy)}
          />
          <PlainMetric
            label="Fine-tuned 정답"
            value={`${comparison.fine_tuned.correct}/${comparison.sample_count}`}
            help={pct(comparison.fine_tuned.accuracy)}
          />
          <PlainMetric
            label="개선/악화"
            value={`+${improved} / -${regressed}`}
            help={`${comparison.delta.changed_predictions}개 예측 변경`}
          />
          <PlainMetric
            label="정답 변화"
            value={comparison.delta.correct >= 0 ? `+${comparison.delta.correct}` : String(comparison.delta.correct)}
            help={pct(comparison.delta.accuracy)}
          />
        </div>
      </div>

      <div className="max-h-[520px] overflow-auto">
        <table className="w-full min-w-[880px] text-left text-xs">
          <thead className="sticky top-0 bg-slate-950 text-slate-400">
            <tr className="border-b border-white/10">
              <th className="px-4 py-3 font-medium">기대 유형</th>
              <th className="px-4 py-3 font-medium">Raw</th>
              <th className="px-4 py-3 font-medium">Fine-tuned</th>
              <th className="px-4 py-3 font-medium">문장</th>
            </tr>
          </thead>
          <tbody>
            {comparison.samples.map((sample) => (
              <tr key={sample.id} className="border-b border-white/5 align-top">
                <td className="px-4 py-3 font-semibold text-slate-200">{sample.expected}</td>
                <td className="px-4 py-3">
                  <ComparePrediction prediction={sample.raw.prediction} hit={sample.raw.is_correct} confidence={sample.raw.confidence} />
                </td>
                <td className="px-4 py-3">
                  <ComparePrediction
                    prediction={sample.fine_tuned.prediction}
                    hit={sample.fine_tuned.is_correct}
                    confidence={sample.fine_tuned.confidence}
                  />
                </td>
                <td className="px-4 py-3 leading-relaxed text-slate-400">{sample.text}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function ComparePrediction({
  prediction,
  hit,
  confidence,
}: {
  prediction: string;
  hit: boolean;
  confidence: number;
}) {
  return (
    <div>
      <span
        className={`inline-flex rounded-full border px-2 py-1 font-semibold ${
          hit
            ? "border-emerald-400/30 bg-emerald-500/10 text-emerald-200"
            : "border-rose-400/30 bg-rose-500/10 text-rose-200"
        }`}
      >
        {prediction || "-"}
      </span>
      <div className="mt-1 font-mono text-[11px] text-slate-500">{pct(confidence)}</div>
    </div>
  );
}

export function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-slate-950/40 px-3 py-2">
      <div className="text-xs text-slate-400">{label}</div>
      <div className="mt-1 font-mono text-slate-100">{value}</div>
    </div>
  );
}

export function MiniMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-slate-900/60 px-3 py-2">
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 font-mono text-sm text-slate-100">{value}</div>
    </div>
  );
}

export function GateRoleCard({
  tone,
  title,
  io,
  note,
}: {
  tone: "amber" | "cyan" | "violet";
  title: string;
  io: string;
  note: string;
}) {
  const toneClass = {
    amber: "border-amber-400/30 bg-amber-500/10",
    cyan: "border-cyan-400/30 bg-cyan-500/10",
    violet: "border-violet-400/30 bg-violet-500/10",
  }[tone];
  return (
    <div className={`rounded-lg border px-3 py-2 ${toneClass}`}>
      <div className="text-sm font-semibold text-white">{title}</div>
      <div className="mt-1 font-mono text-[11px] text-slate-300">{io}</div>
      <p className="mt-1 text-xs leading-relaxed text-slate-400">{note}</p>
    </div>
  );
}

export function GateMetricsPanel({ metrics }: { metrics: GateMetrics }) {
  const labels = metrics.labels ?? Object.keys(metrics.per_class ?? {});
  const perClassBars = labels
    .filter((l) => metrics.per_class?.[l])
    .map((l) => {
      const m = metrics.per_class![l];
      return {
        label: gateLabelKo(l),
        precision: m.precision,
        recall: m.recall,
        f1: m.f1,
      };
    });
  const confusion = metrics.confusion ?? [];
  const watchCells = metrics.watch_cells ?? [];

  return (
    <div className="space-y-4 rounded-xl border border-amber-300/20 bg-amber-500/5 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="text-xs uppercase tracking-widest text-amber-200">게이트 평가 결과</div>
          <h3 className="mt-1 text-lg font-semibold text-white">content_label 3-class 성능</h3>
        </div>
        <div className="flex gap-2">
          <PlainMetric label="정확도" value={pct(metrics.accuracy)} help="전체 정답률" />
          <PlainMetric label="macro F1" value={pct(metrics.macro_f1)} help="3 class 균형 점수" />
        </div>
      </div>

      {perClassBars.length > 0 && (
        <div className="rounded-lg border border-white/10 bg-slate-950/40 p-3">
          <div className="mb-2 text-xs uppercase tracking-widest text-slate-400">클래스별 정밀도/재현율/F1</div>
          <GatePerClassBar data={perClassBars} />
        </div>
      )}

      {confusion.length > 0 && (
        <div className="rounded-lg border border-white/10 bg-slate-950/40 p-3">
          <div className="mb-2 text-xs uppercase tracking-widest text-slate-400">
            혼동 행렬 (행=실제, 열=예측)
          </div>
          <div className="overflow-auto">
            <table className="text-center text-xs">
              <thead>
                <tr className="text-slate-400">
                  <th className="px-2 py-1" />
                  {labels.map((l) => (
                    <th key={l} className="px-2 py-1 font-medium">
                      {gateLabelKo(l)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {confusion.map((row, i) => {
                  const rowTotal = row.reduce((a, b) => a + b, 0) || 1;
                  return (
                    <tr key={labels[i] ?? i}>
                      <td className="px-2 py-1 text-right font-medium text-slate-400">
                        {gateLabelKo(labels[i] ?? String(i))}
                      </td>
                      {row.map((cell, j) => {
                        const intensity = Math.min(1, cell / rowTotal);
                        const correct = i === j;
                        const bg = correct
                          ? `rgba(34, 197, 94, ${0.12 + intensity * 0.55})`
                          : cell > 0
                            ? `rgba(244, 63, 94, ${0.1 + intensity * 0.6})`
                            : "transparent";
                        return (
                          <td
                            key={j}
                            className="px-3 py-2 font-mono text-slate-100"
                            style={{ backgroundColor: bg }}
                          >
                            {cell}
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {watchCells.length > 0 && (
        <div className="rounded-lg border border-white/10 bg-slate-950/40 p-3">
          <div className="mb-2 text-xs uppercase tracking-widest text-slate-400">
            집중 오류 셀 (낮을수록 좋음 · 정상→사기 오탐이 핵심 지표)
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            {watchCells.map((c) => {
              const hot = c.rate >= 0.05;
              return (
                <div
                  key={`${c.true}-${c.pred}`}
                  className={`rounded-lg border px-3 py-2 ${
                    hot
                      ? "border-rose-400/40 bg-rose-500/10"
                      : "border-emerald-400/25 bg-emerald-500/10"
                  }`}
                >
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-slate-200">
                      {gateLabelKo(c.true)} → {gateLabelKo(c.pred)}
                    </span>
                    <span className={`font-mono ${hot ? "text-rose-200" : "text-emerald-200"}`}>
                      {pct(c.rate)}
                    </span>
                  </div>
                  <div className="mt-1 font-mono text-[11px] text-slate-500">
                    {c.count} / {c.denom}건
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export function PlainMetric({ label, value, help }: { label: string; value: string; help: string }) {
  return (
    <div className="rounded-xl border border-white/10 bg-slate-900/70 px-4 py-3">
      <div className="text-xs text-slate-400">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-white">{value}</div>
      <div className="mt-1 text-xs leading-relaxed text-slate-400">{help}</div>
    </div>
  );
}

export function LearningStep({
  index,
  title,
  body,
  tone,
}: {
  index: string;
  title: string;
  body: string;
  tone: "cyan" | "emerald" | "amber";
}) {
  const toneClass = {
    cyan: "border-cyan-400/25 bg-cyan-500/10 text-cyan-100",
    emerald: "border-emerald-400/25 bg-emerald-500/10 text-emerald-100",
    amber: "border-amber-400/25 bg-amber-500/10 text-amber-100",
  }[tone];
  return (
    <div className={`rounded-xl border px-4 py-3 ${toneClass}`}>
      <div className="flex items-center gap-3">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-current/30 bg-black/20 font-mono text-xs">
          {index}
        </span>
        <div className="font-semibold">{title}</div>
      </div>
      <p className="mt-2 text-sm leading-relaxed opacity-80">{body}</p>
    </div>
  );
}
