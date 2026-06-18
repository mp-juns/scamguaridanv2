"use client";

import { useState } from "react";

import {
  DEMO_FLOW_GRAPHS,
  nodeToneClass,
  type FlowGraph,
  type FlowNode,
} from "../../lib/demoArchitectureGraph";
import type { DemoMode } from "../../lib/demoArchitectureDetails";

function Arrow({ dir = "right" }: { dir?: "right" | "down" }) {
  if (dir === "down") {
    return (
      <svg className="mx-auto h-6 w-4 shrink-0 text-[#c9cdd2]" viewBox="0 0 16 24" aria-hidden>
        <path d="M8 0v18M3 14l5 6 5-6" fill="none" stroke="currentColor" strokeWidth="2" />
      </svg>
    );
  }
  return (
    <svg className="h-4 w-6 shrink-0 text-[#c9cdd2]" viewBox="0 0 24 16" aria-hidden>
      <path d="M0 8h16M12 3l6 5-6 5" fill="none" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

function FlowNodeBox({
  node,
  selected,
  onSelect,
}: {
  node: FlowNode;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      className={`flex min-w-[88px] max-w-[120px] flex-col items-center rounded-2xl border-2 px-3 py-3 transition ${nodeToneClass(node.tone)} ${
        selected ? "ring-2 ring-[#3182f6] ring-offset-2" : "hover:scale-[1.02]"
      }`}
    >
      <span className="text-xl leading-none">{node.icon}</span>
      <span className="mt-1.5 text-center text-xs font-bold leading-tight">{node.label}</span>
      {node.sub ? (
        <span className="mt-0.5 text-center text-[10px] opacity-75">{node.sub}</span>
      ) : null}
    </button>
  );
}

function ChainRow({
  graph,
  nodeIds,
  selectedId,
  onSelect,
  vertical,
}: {
  graph: FlowGraph;
  nodeIds: string[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  vertical?: boolean;
}) {
  return (
    <div
      className={`flex items-center justify-center gap-1 ${vertical ? "flex-col" : "flex-wrap"}`}
    >
      {nodeIds.map((id, i) => (
        <div key={id} className={`flex items-center ${vertical ? "flex-col" : ""}`}>
          {i > 0 ? <Arrow dir={vertical ? "down" : "right"} /> : null}
          <FlowNodeBox
            node={graph.nodes[id]}
            selected={selectedId === id}
            onSelect={() => onSelect(id)}
          />
        </div>
      ))}
    </div>
  );
}

function ParallelRow({
  graph,
  nodeIds,
  mergeTo,
  selectedId,
  onSelect,
}: {
  graph: FlowGraph;
  nodeIds: string[];
  mergeTo?: string;
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="flex flex-col items-center gap-2">
      <div className="relative flex flex-wrap items-center justify-center gap-3">
        <div className="absolute left-[10%] right-[10%] top-1/2 hidden h-0.5 -translate-y-1/2 bg-[#e5e8eb] sm:block" />
        {nodeIds.map((id) => (
          <FlowNodeBox
            key={id}
            node={graph.nodes[id]}
            selected={selectedId === id}
            onSelect={() => onSelect(id)}
          />
        ))}
      </div>
      {mergeTo ? (
        <>
          <Arrow dir="down" />
          <FlowNodeBox
            node={graph.nodes[mergeTo]}
            selected={selectedId === mergeTo}
            onSelect={() => onSelect(mergeTo)}
          />
        </>
      ) : null}
    </div>
  );
}

export default function PipelineFlowDiagram({ mode }: { mode: DemoMode }) {
  const graph = DEMO_FLOW_GRAPHS[mode];
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const selected = selectedId ? graph.nodes[selectedId] : null;
  const vertical = mode === "apk";

  return (
    <div className="rounded-2xl border border-[#e5e8eb] bg-[#fafbfc] p-6">
      <div className="mb-6 text-center">
        <h3 className="text-lg font-bold text-[#191f28]">{graph.title}</h3>
        <p className="mt-1 text-xs text-[#8b95a1]">{graph.subtitle}</p>
      </div>

      <div className="space-y-4 overflow-x-auto pb-2">
        {graph.rows.map((row, idx) => (
          <div key={idx}>
            {row.kind === "chain" ? (
              <ChainRow
                graph={graph}
                nodeIds={row.nodes}
                selectedId={selectedId}
                onSelect={setSelectedId}
                vertical={vertical}
              />
            ) : (
              <ParallelRow
                graph={graph}
                nodeIds={row.nodes}
                mergeTo={row.mergeTo}
                selectedId={selectedId}
                onSelect={setSelectedId}
              />
            )}
            {idx < graph.rows.length - 1 ? (
              <div className="my-2 flex justify-center">
                <Arrow dir="down" />
              </div>
            ) : null}
          </div>
        ))}
      </div>

      {selected?.files?.length ? (
        <div className="mt-6 rounded-xl border border-[#3182f6]/30 bg-white p-4">
          <div className="mb-2 text-xs font-semibold text-[#3182f6]">
            {selected.icon} {selected.label} — 소스
          </div>
          <div className="flex flex-wrap gap-2">
            {selected.files.map((f) => (
              <code
                key={f}
                className="rounded-lg bg-[#f2f4f6] px-2 py-1 font-mono text-[10px] text-[#333d4b]"
              >
                {f}
              </code>
            ))}
          </div>
        </div>
      ) : selected ? (
        <div className="mt-6 rounded-xl border border-dashed border-[#e5e8eb] bg-white p-4 text-center text-xs text-[#8b95a1]">
          노드를 클릭하면 연결된 모듈 경로가 표시됩니다
        </div>
      ) : (
        <div className="mt-6 rounded-xl border border-dashed border-[#e5e8eb] bg-white p-4 text-center text-xs text-[#8b95a1]">
          ↑ 다이어그램 노드를 클릭해 구현 파일을 확인하세요
        </div>
      )}
    </div>
  );
}
