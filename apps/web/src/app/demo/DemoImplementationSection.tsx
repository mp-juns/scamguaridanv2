"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import type { DemoMode } from "../../lib/demoArchitectureDetails";
import type { DemoSnapshot } from "../../lib/pipelineArchitecture";

import ApkLayerDiagram from "./ApkLayerDiagram";
import ContentTrainingMap from "./ContentTrainingMap";
import LiveArchitectureMap from "./LiveArchitectureMap";

const CONTENT_FALLBACK_SNAPSHOT: DemoSnapshot = {
  gate: {
    data_count: 385,
    data_label: "씨앗 content_label 합계",
    augment_sessions: [],
    training_sessions: [
      { id: "content_label_gate_20260610", status: "completed" },
      { id: "content_label_gate_20260609", status: "completed" },
    ],
    active_model_path: ".scamguardian/training_sessions/content_label_gate_20260610/output/checkpoint-5610",
    admin_links: {
      data: "/admin/browse",
      augment: "/admin/augment",
      training: "/admin/training",
    },
  },
  classifier: {
    data_count: 25,
    data_label: "classifier 학습 샘플",
    augment_sessions: [],
    training_sessions: [{ id: "b10859a4dbd2", status: "completed" }],
    active_model_path: ".scamguardian/training_sessions/b10859a4dbd2/output",
    admin_links: {
      data: "/admin",
      augment: "/admin/augment",
      training: "/admin/training",
    },
  },
  gliner: {
    data_count: 20,
    data_label: "GLiNER 학습 샘플",
    augment_sessions: [],
    training_sessions: [{ id: "c6ba617511b9", status: "completed" }],
    active_model_path: ".scamguardian/training_sessions/c6ba617511b9/output",
    admin_links: {
      data: "/admin/browse",
      augment: "/admin/augment",
      training: "/admin/training",
    },
  },
  label_queue: { pending: 180, annotated: 26, total: 206 },
  runtime_demos: [
    { id: "live", title: "실시간 통화 분석", href: "/demo/live", badge: "Live v4" },
    { id: "content", title: "콘텐츠 분석 (텍스트·URL·파일)", href: "/demo/content", badge: "시연" },
    { id: "apk", title: "APK 검사 데모", href: "/demo/apk", badge: "시연" },
  ],
};

export default function DemoImplementationSection({ mode }: { mode: DemoMode }) {
  const [snap, setSnap] = useState<DemoSnapshot | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const resp = await fetch("/api/demo/ml-snapshot");
        if (!resp.ok) return;
        const data = (await resp.json()) as DemoSnapshot;
        if (!cancelled) setSnap(data);
      } catch {
        /* optional */
      }
    }
    void load();
    const id = setInterval(load, 15000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <section className="rounded-3xl border-2 border-[#3182f6]/20 bg-white p-6 sm:p-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="rounded-full bg-[#e8f3ff] px-3 py-1 text-xs font-bold text-[#3182f6]">
            시연 · 구현 구조
          </span>
          <span className="text-xs text-[#8b95a1]">노드 클릭 → 소스 파일</span>
        </div>
        <Link
          href="/demo"
          className="rounded-full border border-[#e5e8eb] px-4 py-2 text-xs font-semibold text-[#4e5968] transition hover:bg-[#f2f4f6]"
        >
          ← 시연 허브
        </Link>
      </div>

      {mode === "apk" ? (
        <ApkLayerDiagram />
      ) : mode === "live" ? (
        <LiveArchitectureMap />
      ) : mode === "content" ? (
        <ContentTrainingMap snap={snap ?? CONTENT_FALLBACK_SNAPSHOT} />
      ) : (
        null
      )}

      {(snap ?? (mode === "content" ? CONTENT_FALLBACK_SNAPSHOT : null))?.runtime_demos?.length ? (
        <div className="mt-6 flex flex-wrap justify-center gap-2 border-t border-[#f2f4f6] pt-6">
          {(snap ?? CONTENT_FALLBACK_SNAPSHOT).runtime_demos.map((d) => (
            <Link
              key={d.id}
              href={d.href}
              className="inline-flex items-center gap-2 rounded-full border border-[#e5e8eb] px-3 py-1.5 text-xs font-semibold text-[#191f28] hover:border-[#3182f6]"
            >
              <span className="rounded-full bg-[#e8f3ff] px-2 py-0.5 text-[10px] text-[#3182f6]">
                {d.badge}
              </span>
              {d.title}
            </Link>
          ))}
        </div>
      ) : null}
    </section>
  );
}
