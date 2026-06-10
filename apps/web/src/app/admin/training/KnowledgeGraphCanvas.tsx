"use client";

// 데이터 연결망 canvas — ResizeObserver/rAF 사용이라 client 전용.
// TrainingClient 에서 dynamic(() => import("./KnowledgeGraphCanvas"), { ssr: false }) 로 로드.
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent } from "react";

import type { SyntheticGraphLink, SyntheticGraphNode } from "./trainingShared";

export default function KnowledgeGraphCanvas({
  graph,
}: {
  graph: { nodes: SyntheticGraphNode[]; links: SyntheticGraphLink[] };
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const [hovered, setHovered] = useState<SyntheticGraphNode | null>(null);

  const layout = useMemo(() => buildGraphLayout(graph), [graph]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    if (!canvas || !wrap) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let frame = 0;
    let raf = 0;
    const resize = () => {
      const rect = wrap.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const draw = () => {
      const { width, height } = canvas.getBoundingClientRect();
      const scale = Math.min(width, height) * 0.43;
      const cx = width / 2;
      const cy = height / 2;
      frame += 1;

      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "#282b36";
      ctx.fillRect(0, 0, width, height);

      ctx.lineWidth = 0.7;
      ctx.globalCompositeOperation = "lighter";
      for (const link of graph.links) {
        const source = layout.positions.get(link.source);
        const target = layout.positions.get(link.target);
        if (!source || !target) continue;
        const sx = cx + source.x * scale;
        const sy = cy + source.y * scale;
        const tx = cx + target.x * scale;
        const ty = cy + target.y * scale;
        const alpha = Math.min(0.34, 0.045 + Math.log1p(link.weight) * 0.018);
        ctx.strokeStyle = `rgba(128, 160, 229, ${alpha})`;
        ctx.beginPath();
        ctx.moveTo(sx, sy);
        ctx.lineTo(tx, ty);
        ctx.stroke();
      }

      ctx.globalCompositeOperation = "source-over";
      for (const node of graph.nodes) {
        const point = layout.positions.get(node.id);
        if (!point) continue;
        const pulse = Math.sin(frame * 0.018 + point.phase) * 0.7;
        const x = cx + point.x * scale;
        const y = cy + point.y * scale;
        const radius = nodeRadius(node) + (node.kind === "corpus" ? pulse : 0);
        ctx.fillStyle = nodeColor(node);
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.fill();
      }

      raf = window.requestAnimationFrame(draw);
    };

    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(wrap);
    raf = window.requestAnimationFrame(draw);
    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(raf);
    };
  }, [graph, layout]);

  const handlePointerMove = useCallback(
    (event: PointerEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current;
      if (!canvas) return;
      const rect = canvas.getBoundingClientRect();
      const scale = Math.min(rect.width, rect.height) * 0.43;
      const cx = rect.width / 2;
      const cy = rect.height / 2;
      const px = event.clientX - rect.left;
      const py = event.clientY - rect.top;
      let nearest: SyntheticGraphNode | null = null;
      let nearestDist = 18;
      for (const node of graph.nodes) {
        const point = layout.positions.get(node.id);
        if (!point) continue;
        const x = cx + point.x * scale;
        const y = cy + point.y * scale;
        const dist = Math.hypot(px - x, py - y);
        if (dist < nearestDist) {
          nearest = node;
          nearestDist = dist;
        }
      }
      setHovered(nearest);
    },
    [graph.nodes, layout],
  );

  return (
    <div ref={wrapRef} className="relative h-[520px] overflow-hidden rounded-lg border border-white/10 bg-[#282b36]">
      <canvas
        ref={canvasRef}
        className="h-full w-full"
        onPointerMove={handlePointerMove}
        onPointerLeave={() => setHovered(null)}
      />
      <div className="pointer-events-none absolute left-4 top-4 flex flex-wrap gap-2 text-[11px] text-slate-300">
        <GraphLegend color="bg-cyan-300" label="분류기 축" />
        <GraphLegend color="bg-violet-400" label="추출기 축" />
        <GraphLegend color="bg-sky-300" label="중심 데이터" />
      </div>
      {hovered && (
        <div className="pointer-events-none absolute bottom-4 left-4 max-w-[min(360px,calc(100%-2rem))] rounded-md border border-white/15 bg-slate-950/90 px-3 py-2 text-xs text-slate-200 shadow-xl">
          <div className="font-semibold text-white">{hovered.label}</div>
          <div className="mt-1 text-slate-400">
            {kindLabel(hovered.kind)} · 데이터 {hovered.weight.toLocaleString("ko-KR")}개
          </div>
        </div>
      )}
    </div>
  );
}

function GraphLegend({ color, label }: { color: string; label: string }) {
  return (
    <span className="inline-flex items-center gap-1 rounded-full bg-black/20 px-2 py-1">
      <span className={`h-2 w-2 rounded-full ${color}`} />
      {label}
    </span>
  );
}

function buildGraphLayout(graph: { nodes: SyntheticGraphNode[]; links: SyntheticGraphLink[] }) {
  const positions = new Map<string, { x: number; y: number; phase: number }>();
  const classifierNodes = graph.nodes
    .filter((node) => node.kind === "scam_type")
    .sort((a, b) => b.weight - a.weight);
  const extractorNodes = graph.nodes
    .filter((node) => node.kind === "entity_label")
    .sort((a, b) => b.weight - a.weight);

  positions.set("corpus", { x: 0, y: 0, phase: 0 });
  positions.set("axis:classifier", { x: -0.28, y: 0, phase: 1.1 });
  positions.set("axis:extractor", { x: 0.28, y: 0, phase: 2.2 });

  const placeArc = (
    nodes: SyntheticGraphNode[],
    startAngle: number,
    endAngle: number,
    radius: number,
  ) => {
    const total = Math.max(1, nodes.length - 1);
    nodes.forEach((node, index) => {
      const h = hashString(node.id);
      const t = nodes.length === 1 ? 0.5 : index / total;
      const angle = startAngle + (endAngle - startAngle) * t;
      const jitter = ((h % 1000) / 1000 - 0.5) * 0.08;
      const rj = (((h >> 5) % 1000) / 1000 - 0.5) * 0.08;
      positions.set(node.id, {
        x: Math.cos(angle + jitter) * (radius + rj),
        y: Math.sin(angle + jitter) * (radius + rj),
        phase: (h % 628) / 100,
      });
    });
  };

  placeArc(classifierNodes, Math.PI * 0.72, Math.PI * 1.28, 0.78);
  placeArc(extractorNodes, -Math.PI * 0.28, Math.PI * 0.28, 0.88);

  return { positions };
}

function nodeRadius(node: SyntheticGraphNode) {
  const scaled = Math.min(16, Math.max(3, 2.6 + Math.log1p(node.weight || 1) * 1.6));
  switch (node.kind) {
    case "corpus":
      return 10;
    case "axis":
      return 8;
    case "scam_type":
    case "entity_label":
      return scaled;
    default:
      return 3;
  }
}

function nodeColor(node: SyntheticGraphNode) {
  if (node.kind === "corpus") return "#e0f2fe";
  if (node.kind === "axis" && node.group === "classifier") return "#67e8f9";
  if (node.kind === "axis" && node.group === "extractor") return "#c4b5fd";
  if (node.kind === "entity_label") return "#8b7ac7";
  if (node.kind === "scam_type") return "#ffffff";
  return "#f8fafc";
}

function kindLabel(kind: SyntheticGraphNode["kind"]) {
  const labels: Record<SyntheticGraphNode["kind"], string> = {
    corpus: "전체 코퍼스",
    axis: "학습 축",
    scam_type: "사기 유형",
    entity_label: "엔티티 라벨",
  };
  return labels[kind];
}

function hashString(value: string) {
  let hash = 2166136261;
  for (let i = 0; i < value.length; i += 1) {
    hash ^= value.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}
