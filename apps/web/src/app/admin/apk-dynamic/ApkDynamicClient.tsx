"use client";

import { useCallback, useEffect, useRef, useState } from "react";

// APK flag → 한국어 라벨 (pipeline/config.py FLAG_LABELS_KO 의 APK 부분과 일치).
const APK_FLAG_KO: Record<string, string> = {
  apk_dangerous_permissions_combo: "APK: 위험 권한 조합 (4종 이상)",
  apk_self_signed: "APK: 자체 서명 인증서",
  apk_suspicious_package_name: "APK: 패키지명 위장 의심",
  apk_sms_auto_send_code: "APK: SMS 자동 발송 코드",
  apk_call_state_listener: "APK: 통화 상태 가로채기",
  apk_accessibility_abuse: "APK: 접근성 서비스 악용",
  apk_impersonation_keywords: "APK: 사칭 키워드 string",
  apk_hardcoded_c2_url: "APK: 의심 URL 하드코딩",
  apk_string_obfuscation: "APK: 난독화 흔적",
  apk_device_admin_lock: "APK: 화면 잠금 권한",
  apk_runtime_c2_network_call: "APK: C&C 서버 호출 (런타임)",
  apk_runtime_sms_intercepted: "APK: SMS 가로채기 (런타임)",
  apk_runtime_overlay_attack: "APK: 화면 오버레이 공격 (런타임)",
  apk_runtime_credential_exfiltration: "APK: 자격증명 탈취 (런타임)",
  apk_runtime_persistence_install: "APK: 지속성 설치 (런타임)",
};

type VmStatus = {
  ok?: boolean;
  error?: string;
  vm_running?: boolean;
  redroid_booted?: boolean;
  frida_running?: boolean;
  server_up?: boolean;
  remote_url?: string;
  cached?: boolean;
  active_op?: { op_id: string; op: string; status: string } | null;
};

type OpInfo = {
  op_id: string;
  op: string;
  status: string;
  exit_code: number | null;
  elapsed_ms: number;
  log?: string;
};

type TierCheck = {
  status?: string;
  detected_flags?: string[];
  backend?: string;
  error?: string;
  duration_ms?: number;
  raw_observations?: unknown;
};

type JobResult = {
  mode?: string;
  detected_signals?: { flag: string; label_ko: string; detection_source: string }[];
  apk_static_check?: TierCheck;
  apk_bytecode_check?: TierCheck;
  apk_dynamic_check?: TierCheck;
};

type JobInfo = {
  job_id: string;
  status: string;
  force_dynamic: boolean;
  apk_name: string;
  elapsed_ms: number;
  result: JobResult | null;
  error: string | null;
};

function flagKo(flag: string): string {
  return APK_FLAG_KO[flag] ?? flag;
}

function Badge({ on, label }: { on: boolean | undefined; label: string }) {
  return (
    <span
      className={`rounded-xl border px-3 py-1 text-xs font-semibold ${
        on
          ? "border-emerald-400/40 bg-emerald-500/15 text-emerald-200"
          : "border-white/10 bg-white/5 text-slate-400"
      }`}
    >
      {on ? "● " : "○ "}
      {label}
    </span>
  );
}

export default function ApkDynamicClient() {
  const [vm, setVm] = useState<VmStatus | null>(null);
  const [op, setOp] = useState<OpInfo | null>(null);
  const [job, setJob] = useState<JobInfo | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [url, setUrl] = useState("");
  const [forceDynamic, setForceDynamic] = useState(true);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const opIdRef = useRef<string | null>(null);
  const jobIdRef = useRef<string | null>(null);

  const refreshVm = useCallback(async () => {
    try {
      const r = await fetch("/api/admin/apk-dynamic/vm", { cache: "no-store" });
      setVm(await r.json());
    } catch {
      setVm({ ok: false, error: "상태 조회 실패 (프록시/백엔드 확인)" });
    }
  }, []);

  const refreshOp = useCallback(async () => {
    const id = opIdRef.current;
    if (!id) return;
    const r = await fetch(`/api/admin/apk-dynamic/ops/${id}`, { cache: "no-store" });
    if (!r.ok) return;
    const data: OpInfo = await r.json();
    setOp(data);
    if (data.status !== "running") {
      opIdRef.current = null;
      void refreshVm();
    }
  }, [refreshVm]);

  const refreshJob = useCallback(async () => {
    const id = jobIdRef.current;
    if (!id) return;
    const r = await fetch(`/api/admin/apk-dynamic/jobs/${id}`, { cache: "no-store" });
    if (!r.ok) return;
    const data: JobInfo = await r.json();
    setJob(data);
    if (data.status !== "running") jobIdRef.current = null;
  }, []);

  useEffect(() => {
    void refreshVm();
    const t = setInterval(() => {
      void refreshVm();
      void refreshOp();
      void refreshJob();
    }, 5000);
    return () => clearInterval(t);
  }, [refreshVm, refreshOp, refreshJob]);

  async function vmAction(action: "start" | "stop") {
    setBusy(true);
    setNotice(null);
    try {
      const r = await fetch(`/api/admin/apk-dynamic/vm/${action}`, { method: "POST" });
      const data = await r.json();
      if (!r.ok) {
        setNotice(data?.detail ?? `VM ${action} 실패`);
        return;
      }
      opIdRef.current = data.op_id;
      setOp(data);
    } finally {
      setBusy(false);
    }
  }

  async function analyze() {
    const trimmedUrl = url.trim();
    if (!file && !trimmedUrl) return;
    setBusy(true);
    setNotice(null);
    setJob(null);
    try {
      const fd = new FormData();
      if (file) {
        fd.append("file", file);
      } else {
        fd.append("url", trimmedUrl);
      }
      fd.append("force_dynamic", String(forceDynamic));
      const r = await fetch("/api/admin/apk-dynamic/analyze", { method: "POST", body: fd });
      const data = await r.json();
      if (!r.ok) {
        setNotice(data?.detail ?? "분석 시작 실패");
        return;
      }
      jobIdRef.current = data.job_id;
      setJob(data);
    } finally {
      setBusy(false);
    }
  }

  const opRunning = op?.status === "running" || !!vm?.active_op;
  const jobRunning = job?.status === "running";
  const needVmWarning = forceDynamic && !vm?.redroid_booted;

  return (
    <div className="space-y-6">
      {/* VM 상태 + 제어 */}
      <section className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-lg font-semibold text-white">격리 VM (redroid + Frida)</h2>
          <div className="flex gap-2">
            <button
              onClick={() => vmAction("start")}
              disabled={busy || opRunning}
              className="rounded-2xl bg-emerald-300 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-emerald-200 disabled:opacity-40"
            >
              VM 기동
            </button>
            <button
              onClick={() => vmAction("stop")}
              disabled={busy || opRunning}
              className="rounded-2xl border border-rose-400/40 bg-rose-500/10 px-4 py-2 text-sm font-semibold text-rose-200 transition hover:bg-rose-500/20 disabled:opacity-40"
            >
              VM 정지
            </button>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap gap-2">
          <Badge on={vm?.vm_running} label="VM" />
          <Badge on={vm?.redroid_booted} label="redroid" />
          <Badge on={vm?.frida_running} label="frida-server" />
          <Badge on={vm?.server_up} label="API server" />
        </div>

        <p className="mt-3 text-xs text-slate-400">
          remote: <code className="text-slate-300">{vm?.remote_url ?? "—"}</code>
          {vm?.cached ? " · (cached)" : ""}
          {vm?.ok === false && vm?.error ? (
            <span className="text-rose-300"> · {vm.error}</span>
          ) : null}
        </p>

        {opRunning ? (
          <p className="mt-2 text-xs text-amber-200">⏳ VM 작업 진행 중… (부팅은 수 분 걸릴 수 있습니다)</p>
        ) : null}

        {op?.log ? (
          <pre className="mt-3 max-h-60 overflow-auto rounded-2xl border border-white/10 bg-black/40 p-3 text-[11px] leading-relaxed text-slate-300">
            {op.log}
          </pre>
        ) : null}
      </section>

      {/* APK 분석 */}
      <section className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
        <h2 className="text-lg font-semibold text-white">APK 동적 분석</h2>
        <p className="mt-1 text-sm text-slate-400">
          APK 를 <strong>올리거나 다운로드 링크</strong>를 넣으면 VM 안 redroid 에 실제 설치·실행하고 Frida 로 행동을 관찰해 런타임 신호를 검출합니다.
        </p>

        {/* 입력 1 — 다운로드 링크 */}
        <div className="mt-4">
          <label className="text-xs uppercase tracking-widest text-slate-400">APK 다운로드 링크</label>
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            disabled={!!file}
            placeholder="https://… (확장자 없는 토큰/CDN 링크도 가능)"
            className="mt-1 w-full rounded-2xl border border-white/10 bg-black/30 px-4 py-2 text-sm text-slate-100 placeholder:text-slate-500 disabled:opacity-40"
          />
          <p className="mt-1 text-xs text-slate-500">
            파일을 선택하면 링크는 무시됩니다. Content-Type 으로 APK 여부를 먼저 판단 후 받아서 분석합니다.
          </p>
        </div>

        {/* 입력 2 — 파일 + 옵션 + 실행 */}
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <input
            type="file"
            accept=".apk,application/vnd.android.package-archive"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="text-sm text-slate-300 file:mr-3 file:rounded-xl file:border-0 file:bg-white/10 file:px-4 file:py-2 file:text-sm file:text-slate-100"
          />
          <label className="flex items-center gap-2 text-sm text-slate-300">
            <input
              type="checkbox"
              checked={forceDynamic}
              onChange={(e) => setForceDynamic(e.target.checked)}
            />
            정적 신호 무시하고 동적 강제
          </label>
          <button
            onClick={analyze}
            disabled={busy || jobRunning || (!file && !url.trim())}
            className="rounded-2xl bg-cyan-300 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-cyan-200 disabled:opacity-40"
          >
            분석 시작
          </button>
        </div>

        {needVmWarning ? (
          <div className="mt-3 rounded-2xl border border-amber-400/30 bg-amber-500/10 px-4 py-2 text-sm text-amber-100">
            ⚠️ 동적 강제인데 redroid 가 아직 부팅되지 않았습니다. 먼저 <strong>VM 기동</strong> 후 부팅 완료를 기다리세요.
          </div>
        ) : null}

        {notice ? (
          <div className="mt-3 rounded-2xl border border-rose-400/30 bg-rose-500/10 px-4 py-2 text-sm text-rose-100">
            {notice}
          </div>
        ) : null}

        {jobRunning ? (
          <p className="mt-3 text-sm text-amber-200">⏳ 분석 중… ({job?.apk_name})</p>
        ) : null}

        {job && job.status !== "running" ? (
          <JobResultView job={job} />
        ) : null}
      </section>
    </div>
  );
}

function TierCard({ title, check }: { title: string; check?: TierCheck }) {
  if (!check) return null;
  const flags = check.detected_flags ?? [];
  return (
    <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
      <div className="flex items-center justify-between">
        <span className="text-sm font-semibold text-slate-100">{title}</span>
        <span className="text-xs text-slate-400">{check.status ?? "—"}</span>
      </div>
      {flags.length ? (
        <ul className="mt-2 space-y-1">
          {flags.map((f) => (
            <li key={f} className="text-sm text-rose-200">
              ⚑ {flagKo(f)} <span className="text-xs text-slate-500">({f})</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="mt-2 text-xs text-slate-500">검출된 신호 없음</p>
      )}
      {check.error ? <p className="mt-2 text-xs text-amber-300">{check.error}</p> : null}
    </div>
  );
}

function JobResultView({ job }: { job: JobInfo }) {
  if (job.error) {
    return (
      <div className="mt-3 rounded-2xl border border-rose-400/30 bg-rose-500/10 px-4 py-2 text-sm text-rose-100">
        분석 실패: {job.error}
      </div>
    );
  }
  const result = job.result;
  if (!result) return null;
  const dyn = result.apk_dynamic_check;
  return (
    <div className="mt-4 space-y-4">
      <p className="text-xs text-slate-400">
        모드: <code className="text-slate-300">{result.mode}</code> · 소요 {Math.round(job.elapsed_ms / 100) / 10}s
      </p>

      <div className="grid gap-3 sm:grid-cols-3">
        <TierCard title="Lv1 정적 (manifest)" check={result.apk_static_check} />
        <TierCard title="Lv2 bytecode" check={result.apk_bytecode_check} />
        <TierCard title="Lv3 동적 (VM)" check={dyn} />
      </div>

      {dyn?.raw_observations ? (
        <details className="rounded-2xl border border-white/10 bg-black/20 p-4">
          <summary className="cursor-pointer text-sm font-semibold text-slate-200">
            동적 관찰 로그 (observations)
          </summary>
          <pre className="mt-2 max-h-72 overflow-auto text-[11px] leading-relaxed text-slate-300">
            {JSON.stringify(dyn.raw_observations, null, 2)}
          </pre>
        </details>
      ) : null}

      {result.detected_signals && result.detected_signals.length ? (
        <div className="rounded-2xl border border-white/10 bg-black/20 p-4">
          <p className="text-sm font-semibold text-slate-100">검출 신호 (전체 파이프라인)</p>
          <ul className="mt-2 space-y-1">
            {result.detected_signals.map((s, i) => (
              <li key={`${s.flag}-${i}`} className="text-sm text-slate-200">
                ⚑ {s.label_ko}
                <span className="ml-2 text-xs text-slate-500">[{s.detection_source}]</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
