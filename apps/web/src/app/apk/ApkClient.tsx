"use client";

import { useEffect, useState } from "react";

// 백엔드 /api/analyze-apk 응답 schema.
type ApkFlag = { labelKo: string; code: string };
type ApkTier = {
  key: string;
  title: string;
  verdict: "fail" | "pass" | "skipped" | "error" | "incomplete";
  note: string;
  flags: ApkFlag[];
};

// 티어 판정 배지 — 미실행/연결실패/분석불가를 '이상 없음'과 다른 색·문구로 구분.
//   error      = 진짜 연결 실패(VM/네트워크)
//   incomplete = 연결은 정상이나 앱이 에뮬레이터에서 실행 안 됨(packing·anti-emulator)
const TIER_BADGE: Record<ApkTier["verdict"], { cls: string; label: string }> = {
  fail: { cls: "bg-[#ffe4e6] text-[#be123c]", label: "신호 검출" },
  pass: { cls: "bg-[#ecfdf5] text-[#059669]", label: "이상 없음" },
  skipped: { cls: "bg-[#f2f4f6] text-[#8b95a1]", label: "미실행" },
  error: { cls: "bg-amber-100 text-amber-700", label: "연결 실패" },
  incomplete: { cls: "bg-orange-100 text-orange-700", label: "분석 불가" },
};
type ApkVt = {
  detected: number;
  total: number;
  permalink?: string | null;
  categories?: string[];
};
type ApkReport = {
  apk_name: string;
  apk_size: string;
  package: string;
  signal_count: number;
  tiers: ApkTier[];
  vt: ApkVt | null;
  summary: string;
  sample_label?: string;
  is_demo?: boolean;
};

type Sample = { id: string; name: string };
// enabled: APK_DYNAMIC_ENABLED, ready: api_server 가 격리 VM 에 실제로 닿음(Lv3 실행 가능)
type VmStatus = { enabled: boolean; ready: boolean };

function ApkTierCard({ tier }: { tier: ApkTier }) {
  const badge = TIER_BADGE[tier.verdict] ?? TIER_BADGE.pass;
  return (
    <div className="rounded-2xl border border-[#e5e8eb] bg-white p-4">
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-bold text-[#191f28]">{tier.title}</span>
        <span
          className={`shrink-0 whitespace-nowrap rounded-full px-2.5 py-0.5 text-[11px] font-bold ${badge.cls}`}
        >
          {badge.label}
        </span>
      </div>
      <p className="mt-1.5 text-xs text-[#8b95a1]">{tier.note}</p>
      {tier.flags.length ? (
        <ul className="mt-2.5 flex flex-col gap-1.5">
          {tier.flags.map((f) => (
            <li key={f.code} className="flex flex-wrap items-baseline gap-1.5">
              <span className="text-[13px] font-medium text-[#191f28]">🚩 {f.labelKo}</span>
              <span className="font-mono text-[11px] text-[#8b95a1]">{f.code}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function ApkResult({ apk }: { apk: ApkReport }) {
  const clean = apk.signal_count === 0;
  return (
    <div className="mt-5 flex flex-col gap-4">
      {/* 검출 신호 수 — 판정이 아닌 "개수"만 (Identity Boundary) */}
      <div
        className={`flex items-center gap-4 rounded-2xl border p-4 ${
          clean ? "border-emerald-200 bg-emerald-50" : "border-[#fecdd3] bg-[#fff5f5]"
        }`}
      >
        <span
          className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-full text-[22px] ${
            clean ? "bg-emerald-100 text-emerald-600" : "bg-[#fecdd3] text-[#be123c]"
          }`}
        >
          📱
        </span>
        <div className="min-w-0">
          <div className="text-base font-bold text-[#191f28]">
            {clean ? "위험 신호가 검출되지 않았어요" : `위험 신호 ${apk.signal_count}개 검출`}
          </div>
          <div className="mt-0.5 text-[13px] text-[#8b95a1]">
            {apk.apk_name} · {apk.apk_size} ·{" "}
            <span className="font-mono">{apk.package}</span>
          </div>
        </div>
      </div>

      {/* VirusTotal — 키 있을 때만. detected/total + "뭐가 위험한지"(categories) + 상세 리포트 링크 */}
      {apk.vt ? (
        <div className="rounded-xl border border-[#e5e8eb] bg-[#f2f4f6] px-4 py-3">
          <div className="flex flex-wrap items-center gap-2.5">
            <span className="text-base">🛡</span>
            <span className="text-sm text-[#4e5968]">
              VirusTotal:{" "}
              <strong className={apk.vt.detected > 0 ? "text-[#be123c]" : "text-[#059669]"}>
                {apk.vt.detected}
              </strong>{" "}
              / {apk.vt.total} 엔진 탐지
            </span>
            {apk.vt.permalink ? (
              <a
                href={apk.vt.permalink}
                target="_blank"
                rel="noopener noreferrer"
                className="ml-auto inline-flex items-center gap-1 rounded-full bg-[#e8f3ff] px-3 py-1 text-xs font-semibold text-[#3182f6] transition hover:bg-[#dbeafe]"
              >
                상세 리포트 열기 <span aria-hidden>↗</span>
              </a>
            ) : null}
          </div>
          {apk.vt.categories && apk.vt.categories.length ? (
            <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
              <span className="text-xs text-[#8b95a1]">뭐가 위험한지:</span>
              {apk.vt.categories.slice(0, 8).map((c) => (
                <span
                  key={c}
                  className="rounded-full bg-[#ffe4e6] px-2 py-0.5 text-[11px] font-medium text-[#be123c]"
                >
                  {c}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {/* 티어 카드 */}
      <div className="grid gap-3">
        {apk.tiers.map((t) => (
          <ApkTierCard key={t.key} tier={t} />
        ))}
      </div>

      {/* 요약 */}
      <div className="rounded-2xl border border-[#e5e8eb] bg-white p-4">
        <div className="text-[13px] font-bold text-[#191f28]">🤖 검출 요약</div>
        <p className="mt-1.5 text-sm leading-7 text-[#4e5968]">{apk.summary}</p>
        <p className="mt-2.5 text-xs text-[#8b95a1]">
          ScamGuardian 은 신호 검출만 보고합니다. 설치·실행은 항상 격리 VM 에 위임돼요.
        </p>
      </div>
    </div>
  );
}

// 동적 분석 VM 상태 LED — 읽기 전용 (제어는 어드민 콘솔 전용).
// 초록 = api_server 가 실제로 격리 VM 에 닿아 Lv3 실행 가능(ready).
// 노랑 = 활성화됐지만 연결 안 됨(VM 부팅됐어도 브릿지 끊김 등).  회색 = 비활성.
function VmStatusLed({ vm }: { vm: VmStatus | null }) {
  const ready = !!vm?.ready;
  const pending = !!vm?.enabled && !ready;
  const dot = ready ? "bg-[#16a34a]" : pending ? "bg-[#f59e0b]" : "bg-[#c9cdd2]";
  const label =
    vm === null
      ? "동적 분석 VM 상태 확인 중…"
      : ready
        ? "동적 분석 VM 가동 중"
        : pending
          ? "동적 분석 VM 연결 안 됨"
          : "동적 분석 VM 비활성";
  return (
    <div
      className="flex items-center gap-2 rounded-full border border-[#e5e8eb] bg-[#f2f4f6] px-3 py-1"
      title="동적(Lv3) 분석을 실제로 실행 가능한지 표시합니다 (격리 VM 도달 여부). VM 기동·정지는 어드민 콘솔에서만 가능합니다."
    >
      <span className="relative flex h-2.5 w-2.5">
        {ready ? (
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-[#22c55e] opacity-70" />
        ) : null}
        <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${dot}`} />
      </span>
      <span className="text-xs font-medium text-[#4e5968]">{label}</span>
    </div>
  );
}

export default function ApkClient() {
  const [file, setFile] = useState<File | null>(null);
  const [fileName, setFileName] = useState("");
  const [sampleId, setSampleId] = useState("");
  const [samples, setSamples] = useState<Sample[]>([]);
  const [vm, setVm] = useState<VmStatus | null>(null);
  const [phase, setPhase] = useState<"idle" | "running" | "done">("idle");
  const [report, setReport] = useState<ApkReport | null>(null);
  const [error, setError] = useState("");

  const busy = phase === "running";
  const canRun = !!file || !!sampleId;

  // 마운트 시: 샘플 10개 + VM 상태 로드. VM 상태는 20초마다 폴링 (LED 갱신).
  useEffect(() => {
    let alive = true;
    fetch("/api/apk-samples")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (alive && d && Array.isArray(d.samples)) setSamples(d.samples);
      })
      .catch(() => {});

    const loadVm = () =>
      fetch("/api/apk-dynamic-status")
        .then((r) => (r.ok ? r.json() : null))
        .then((d) => {
          if (alive && d) setVm({ enabled: !!d.enabled, ready: !!d.ready });
        })
        .catch(() => {});
    loadVm();
    const t = setInterval(loadVm, 20000);
    return () => {
      alive = false;
      clearInterval(t);
    };
  }, []);

  function pickSample(s: Sample) {
    setSampleId(s.id);
    setFileName(s.name);
    setFile(null);
    setError("");
  }

  // 실제 분석 — 업로드 파일 또는 서버 샘플을 백엔드 정적 분석(Lv1+Lv2+VT)으로 전송.
  async function run() {
    if (!canRun) return;
    setError("");
    setReport(null);
    setPhase("running");
    try {
      const fd = new FormData();
      if (file) fd.set("file", file);
      else fd.set("sample", sampleId);
      const res = await fetch("/api/analyze-apk", { method: "POST", body: fd });
      const data = (await res.json()) as ApkReport | { detail?: string };
      if (!res.ok) {
        const msg =
          "detail" in data && typeof data.detail === "string"
            ? data.detail
            : "APK 분석 중 오류가 발생했습니다.";
        throw new Error(msg);
      }
      setReport(data as ApkReport);
      setPhase("done");
    } catch (e) {
      setError(e instanceof Error ? e.message : "APK 분석 중 오류가 발생했습니다.");
      setPhase("idle");
    }
  }

  return (
    <section className="rounded-3xl border border-[#e5e8eb] bg-white p-8 shadow-[0_2px_12px_rgba(0,0,0,0.05)]">
      <div className="mb-5 flex flex-wrap items-center gap-3">
        <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-[#e8f3ff] text-2xl">
          📱
        </span>
        <div className="min-w-0 flex-1">
          <h2 className="text-xl font-bold text-[#191f28]">APK 분석</h2>
          <p className="mt-0.5 text-sm text-[#8b95a1]">안드로이드 설치 파일(.apk) 업로드</p>
        </div>
        <VmStatusLed vm={vm} />
      </div>

      <p className="text-[13px] leading-7 text-[#4e5968]">
        의심스러운 링크로 받은 <strong>안드로이드 앱(.apk)</strong>을 올리면 3단계로 분석해요 —
        Lv1 정적(manifest) · Lv2 bytecode · Lv3 격리 VM 동적 실행.
      </p>

      <div className="mt-4">
        <label className="mb-2 block text-sm font-medium text-[#333d4b]">APK 파일</label>
        <div className="flex flex-wrap items-center gap-2.5 rounded-2xl border border-dashed border-[#e5e8eb] bg-[#f2f4f6] px-4 py-3.5">
          <label className="cursor-pointer rounded-full bg-[#e8f3ff] px-4 py-1.5 text-[13px] font-semibold text-[#3182f6] transition hover:bg-[#dbeafe]">
            파일 선택
            {/* Safari(특히 iOS)는 .apk 를 아는 타입으로 인식 못 해 파일을 회색 처리함 →
                octet-stream/zip 까지 넓혀 선택 허용. 실제 APK 검증은 서버가 ZIP 매직으로 함. */}
            <input
              type="file"
              accept=".apk,application/vnd.android.package-archive,application/octet-stream,application/zip"
              className="hidden"
              disabled={busy}
              onChange={(e) => {
                const f = e.target.files?.[0] ?? null;
                setFile(f);
                setSampleId("");
                setFileName(f ? f.name : "");
              }}
            />
          </label>
          <span className={`text-[13px] ${fileName ? "text-[#191f28]" : "text-[#8b95a1]"}`}>
            {fileName ? `선택됨: ${fileName}` : "또는 아래 실제 샘플 앱으로 바로 테스트할 수 있어요."}
          </span>
        </div>
        <p className="mt-2 text-xs text-[#8b95a1]">
          .apk · 최대 100MB — 로컬에서 실행하지 않고 격리 VM 으로만 분석합니다.
        </p>
      </div>

      {/* 실제 샘플 APK (무작위 10개) — AndroZoo 실제 악성앱 + 패밀리 샘플 */}
      {samples.length ? (
        <div className="mt-4">
          <div className="mb-2 text-sm font-medium text-[#333d4b]">
            실제 악성앱 샘플로 테스트 <span className="text-xs font-normal text-[#8b95a1]">(무작위 {samples.length}개)</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {samples.map((s) => {
              const active = sampleId === s.id;
              return (
                <button
                  key={s.id}
                  type="button"
                  disabled={busy}
                  onClick={() => pickSample(s)}
                  className={`rounded-full border px-3 py-1.5 text-[13px] font-medium transition disabled:cursor-not-allowed ${
                    active
                      ? "border-[#3182f6] bg-[#e8f3ff] text-[#3182f6]"
                      : "border-[#e5e8eb] bg-white text-[#4e5968] hover:border-[#3182f6] hover:text-[#3182f6]"
                  }`}
                >
                  {s.name}
                </button>
              );
            })}
          </div>
        </div>
      ) : null}

      <button
        type="button"
        onClick={run}
        disabled={busy || !canRun}
        className="mt-5 w-full rounded-2xl bg-[#3182f6] py-3.5 text-[15px] font-semibold text-white transition hover:bg-[#1b64da] disabled:cursor-not-allowed disabled:bg-[#e5e8eb] disabled:text-[#8b95a1]"
      >
        {busy ? "정적 · bytecode · VirusTotal 분석 중…" : "📱 APK 분석 실행"}
      </button>

      {error ? (
        <div className="mt-4 rounded-2xl border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-700">
          {error}
        </div>
      ) : null}

      {phase === "done" && report ? (
        <>
          {report.is_demo ? (
            <p className="mt-4 rounded-xl border border-amber-300/40 bg-amber-50 px-4 py-2.5 text-xs leading-6 text-amber-700">
              🎬 시연용 데모 결과입니다 — 발표를 위해 Lv1·Lv2·Lv3 전체 단계 검출을 보여주는 고정 샘플이에요. 실제 APK 분석은 위에서 파일을 올리거나 다른 샘플을 선택하세요.
            </p>
          ) : null}
          <ApkResult apk={report} />
        </>
      ) : null}
    </section>
  );
}
