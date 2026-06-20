"use client";

import { useState } from "react";

type LiveStage = {
  id: string;
  step: string;
  title: string;
  subtitle: string;
  tone: string;
  dot: string;
  latency: string;
  description: string;
  outputs: string[];
  files: Array<{ path: string; role: string }>;
};

const LIVE_STAGES: LiveStage[] = [
  {
    id: "capture",
    step: "01",
    title: "마이크 캡처",
    subtitle: "getUserMedia · 본인 발화 중심",
    tone: "border-emerald-200 bg-emerald-50 text-emerald-700",
    dot: "bg-emerald-500",
    latency: "즉시",
    description:
      "브라우저 마이크 권한을 받고 echoCancellation/noiseSuppression/autoGainControl을 꺼서 STT가 원음에 가깝게 받도록 합니다.",
    outputs: ["mono audio", "echo off", "AGC off"],
    files: [
      {
        path: "apps/web/src/app/live/useLiveWebSocket.ts",
        role: "마이크 스트림을 열고 AudioWorklet/WebSocket 파이프라인을 시작합니다.",
      },
      {
        path: "apps/web/src/app/live/useLivePcmHttp.ts",
        role: "WebSocket 실패 시 같은 PCM을 HTTP chunk로 보내는 빠른 fallback입니다.",
      },
    ],
  },
  {
    id: "pcm",
    step: "02",
    title: "16kHz PCM 변환",
    subtitle: "AudioWorklet · 브라우저 내부 처리",
    tone: "border-teal-200 bg-teal-50 text-teal-700",
    dot: "bg-teal-500",
    latency: "< 50ms",
    description:
      "48kHz 브라우저 입력을 STT용 16kHz int16 PCM으로 변환합니다. 메인 스레드를 막지 않도록 AudioWorklet에서 처리합니다.",
    outputs: ["16kHz", "int16", "small packets"],
    files: [
      {
        path: "apps/web/public/live-pcm-processor.js",
        role: "브라우저 오디오 프레임을 16kHz mono PCM ArrayBuffer로 다운샘플링합니다.",
      },
    ],
  },
  {
    id: "transport",
    step: "03",
    title: "전송 경로",
    subtitle: "WebSocket 우선 · PCM HTTP fallback",
    tone: "border-blue-200 bg-blue-50 text-blue-700",
    dot: "bg-blue-500",
    latency: "실시간",
    description:
      "정상 환경에서는 /ws/live-transcribe로 계속 밀어넣고, WS가 막히면 /api/live-pcm-chunk로 동일 chunk를 보냅니다.",
    outputs: ["WS stream", "live_token", "PCM HTTP"],
    files: [
      {
        path: "api_server_pkg/live_ws.py",
        role: "WebSocket으로 PCM을 받아 서버 쪽 PCMBuffer에 누적하고 chunk마다 STT를 실행합니다.",
      },
      {
        path: "api_server_pkg/live_pcm_http.py",
        role: "WebSocket 불가 환경에서 WAV chunk 하나를 받아 동일한 STT/스캔 경로로 처리합니다.",
      },
      {
        path: "api_server_pkg/live_ws_token.py",
        role: "브라우저에 API key를 노출하지 않기 위한 짧은 수명 WebSocket 세션 토큰입니다.",
      },
    ],
  },
  {
    id: "stt",
    step: "04",
    title: "3초 chunk 전사",
    subtitle: "Whisper · 첫 결과 3초 + 처리시간",
    tone: "border-violet-200 bg-violet-50 text-violet-700",
    dot: "bg-violet-500",
    latency: "3s + STT",
    description:
      "기본 chunk를 5초에서 3초로 낮춰 첫 전사 대기 시간을 줄였습니다. 운영에서 정확도를 더 원하면 LIVE_CHUNK_SEC=5로 올릴 수 있습니다.",
    outputs: ["Korean STT", "latency_ms", "full transcript"],
    files: [
      {
        path: "pipeline/live_stt.py",
        role: "PCMBuffer, chunk WAV 생성, OpenAI Whisper 호출, 비용 기록을 담당합니다.",
      },
    ],
  },
  {
    id: "scan",
    step: "05",
    title: "즉시 신호 스캔",
    subtitle: "regex/keyword · 누적 dedup",
    tone: "border-amber-200 bg-amber-50 text-amber-700",
    dot: "bg-amber-500",
    latency: "< 10ms",
    description:
      "전사 chunk마다 민감정보, 송금 동의, 메타인식 표현을 즉시 스캔합니다. 같은 신호는 누적 dedup합니다.",
    outputs: ["matches[]", "tier", "tier_changed"],
    files: [
      {
        path: "api_server_pkg/stream_analyze.py",
        role: "_scan_text()와 tier 계산 로직을 Live/파일 스트리밍이 공통 사용합니다.",
      },
      {
        path: "apps/web/src/app/live/liveSignals.ts",
        role: "프론트에서 신호 dedup, tier 계산, OS 알림 트리거를 보조합니다.",
      },
    ],
  },
  {
    id: "alert",
    step: "06",
    title: "경보 출력",
    subtitle: "L1/L2/L3 · 화면/알림",
    tone: "border-rose-200 bg-rose-50 text-rose-700",
    dot: "bg-rose-500",
    latency: "즉시 push",
    description:
      "tier가 올라가면 배너, DangerOverlay, OS 알림으로 사용자에게 통화를 끊을 시간을 만듭니다.",
    outputs: ["L1 banner", "L2 caution", "L3 overlay"],
    files: [
      {
        path: "apps/web/src/app/live/LiveVoiceUpload.tsx",
        role: "실시간 상태, 전사 미리보기, 검출 신호, 경보 UI를 한 화면에서 관리합니다.",
      },
    ],
  },
];

const TIERS = [
  {
    id: "L1",
    label: "약함",
    trigger: "민감 키워드 1개",
    action: "노란 배너",
    cls: "border-yellow-300 bg-yellow-50 text-yellow-700",
  },
  {
    id: "L2",
    label: "중간",
    trigger: "메타인식 + 누적",
    action: "강한 주의 + 진동",
    cls: "border-orange-300 bg-orange-50 text-orange-700",
  },
  {
    id: "L3",
    label: "강함",
    trigger: "송금 동의 / 명시 신호",
    action: "풀스크린 경보",
    cls: "border-rose-300 bg-rose-50 text-rose-700",
  },
];

function StageLane({
  stage,
  active,
  onClick,
}: {
  stage: LiveStage;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative w-full rounded-3xl border p-4 text-left transition ${
        active
          ? `${stage.tone} ring-2 ring-[#3182f6]/40 ring-offset-2`
          : "border-[#e5e8eb] bg-white hover:border-[#3182f6]/40 hover:bg-[#fafbfc]"
      }`}
    >
      <div className="flex items-start gap-4">
        <div className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl text-sm font-black text-white ${stage.dot}`}>
          {stage.step}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-base font-black text-[#191f28]">{stage.title}</h3>
            <span className={`rounded-full border px-2.5 py-1 text-[10px] font-bold ${stage.tone}`}>
              {stage.latency}
            </span>
          </div>
          <p className="mt-1 text-xs font-semibold text-[#8b95a1]">{stage.subtitle}</p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {stage.outputs.map((item) => (
              <span
                key={item}
                className="rounded-full border border-[#e5e8eb] bg-white px-2.5 py-1 text-[10px] font-medium text-[#4e5968]"
              >
                {item}
              </span>
            ))}
          </div>
        </div>
      </div>
    </button>
  );
}

export default function LiveArchitectureMap() {
  const [activeId, setActiveId] = useState("stt");
  const active = LIVE_STAGES.find((stage) => stage.id === activeId) ?? LIVE_STAGES[3];

  return (
    <div className="overflow-hidden rounded-3xl border border-[#e5e8eb] bg-[#fbfcfd]">
      <div className="border-b border-[#e5e8eb] bg-white p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs font-black tracking-[0.12em] text-[#16a34a]">LIVE VOICE MAP</div>
            <h3 className="mt-1 text-2xl font-black tracking-tight text-[#191f28]">
              말하는 순간부터 경보까지, 3초 단위로 흐르는 실시간 파이프라인
            </h3>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-[#4e5968]">
              핵심 지연은 STT chunk 길이입니다. 기본값을 5초에서 3초로 줄여 첫 전사 체감을 빠르게 만들고,
              WebSocket이 막혀도 PCM HTTP fallback으로 같은 빠른 경로를 탑니다.
            </p>
          </div>
          <div className="grid grid-cols-3 gap-2 rounded-2xl border border-[#e5e8eb] bg-[#f8fafc] p-2">
            {TIERS.map((tier) => (
              <div key={tier.id} className={`rounded-xl border px-3 py-2 text-center ${tier.cls}`}>
                <div className="text-lg font-black">{tier.id}</div>
                <div className="text-[10px] font-bold">{tier.label}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="grid gap-6 p-6 lg:grid-cols-[1.05fr_0.95fr]">
        <div>
          <div className="mb-3 flex items-center justify-between">
            <span className="text-xs font-black text-[#333d4b]">데이터 흐름</span>
            <span className="rounded-full bg-[#e8f3ff] px-3 py-1 text-[10px] font-bold text-[#3182f6]">
              click stage
            </span>
          </div>
          <div className="relative space-y-3">
            <div className="absolute bottom-12 left-6 top-12 w-0.5 bg-[#e5e8eb]" aria-hidden />
            {LIVE_STAGES.map((stage) => (
              <StageLane
                key={stage.id}
                stage={stage}
                active={active.id === stage.id}
                onClick={() => setActiveId(stage.id)}
              />
            ))}
          </div>
        </div>

        <aside className="rounded-3xl border border-[#e5e8eb] bg-white p-5">
          <div className="text-xs font-black tracking-[0.12em] text-[#16a34a]">선택 단계</div>
          <h4 className="mt-2 text-xl font-black text-[#191f28]">{active.title}</h4>
          <p className="mt-2 text-sm leading-6 text-[#4e5968]">{active.description}</p>

          <div className="mt-5 grid gap-3 sm:grid-cols-3 lg:grid-cols-1 xl:grid-cols-3">
            {TIERS.map((tier) => (
              <div key={tier.id} className={`rounded-2xl border p-3 ${tier.cls}`}>
                <div className="text-base font-black">{tier.id}</div>
                <div className="mt-1 text-[11px] font-bold">{tier.trigger}</div>
                <div className="mt-2 rounded-full bg-white/70 px-2 py-1 text-center text-[10px] font-semibold">
                  {tier.action}
                </div>
              </div>
            ))}
          </div>

          <div className="mt-5">
            <div className="mb-2 text-xs font-bold text-[#8b95a1]">구현 파일과 역할</div>
            <div className="space-y-2">
              {active.files.map((file) => (
                <div key={file.path} className="rounded-2xl border border-[#e5e8eb] bg-[#fafbfc] p-3">
                  <code className="block break-all font-mono text-[11px] font-black text-[#3182f6]">
                    {file.path}
                  </code>
                  <p className="mt-2 text-xs leading-5 text-[#4e5968]">{file.role}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="mt-5 rounded-2xl border border-dashed border-[#c9cdd2] bg-[#f8fafc] p-4">
            <div className="text-xs font-bold text-[#333d4b]">속도 튜닝 포인트</div>
            <div className="mt-3 grid grid-cols-[auto_1fr] gap-x-3 gap-y-2 text-xs leading-5">
              <span className="font-black text-[#16a34a]">3초</span>
              <span className="text-[#4e5968]">기본 chunk. 첫 전사 대기시간을 줄이는 핵심값</span>
              <span className="font-black text-[#3182f6]">WS</span>
              <span className="text-[#4e5968]">성공 시 가장 안정적인 실시간 스트림</span>
              <span className="font-black text-[#d97706]">PCM HTTP</span>
              <span className="text-[#4e5968]">WS 실패 시에도 webm 재인코딩 없이 빠른 fallback</span>
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
