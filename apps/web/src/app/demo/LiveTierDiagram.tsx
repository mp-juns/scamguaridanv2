"use client";

import { LIVE_TIER_LEVELS } from "../../lib/demoArchitectureGraph";

export default function LiveTierDiagram() {
  return (
    <div className="rounded-2xl border border-[#e5e8eb] bg-white p-6">
      <h3 className="mb-4 text-center text-sm font-bold text-[#191f28]">계단식 경보 tier</h3>
      <div className="flex items-end justify-center gap-3 sm:gap-6">
        {LIVE_TIER_LEVELS.map((t, i) => (
          <div key={t.tier} className="flex flex-col items-center">
            <div
              className="flex w-16 flex-col items-center justify-end rounded-t-xl sm:w-24"
              style={{
                height: `${56 + i * 36}px`,
                backgroundColor: `${t.color}22`,
                borderLeft: `3px solid ${t.color}`,
                borderRight: `3px solid ${t.color}`,
                borderTop: `3px solid ${t.color}`,
              }}
            >
              <span
                className="mb-2 text-lg font-black sm:text-2xl"
                style={{ color: t.color }}
              >
                {t.tier}
              </span>
            </div>
            <span className="mt-2 text-xs font-bold text-[#191f28]">{t.label}</span>
            <ul className="mt-1 space-y-0.5 text-center">
              {t.triggers.map((tr) => (
                <li key={tr} className="text-[10px] text-[#8b95a1]">
                  {tr}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <div className="mt-4 flex justify-center gap-2">
        {["배너", "진동", "TTS", "SMS"].map((ch) => (
          <span
            key={ch}
            className="rounded-full bg-[#f2f4f6] px-2.5 py-1 text-[10px] font-medium text-[#4e5968]"
          >
            {ch}
          </span>
        ))}
      </div>
    </div>
  );
}
