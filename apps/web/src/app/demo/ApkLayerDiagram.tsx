"use client";

import { useState } from "react";

type ApkStage = {
  id: string;
  step: string;
  title: string;
  subtitle: string;
  badge: string;
  tone: string;
  ring: string;
  description: string;
  catches: string[];
  misses?: string;
  files: Array<{ path: string; role: string }>;
  future?: boolean;
};

const APK_STAGES: ApkStage[] = [
  {
    id: "vt",
    step: "01",
    title: "VirusTotal",
    subtitle: "70+ 엔진 SHA256 시그니처",
    badge: "Known malware",
    tone: "text-rose-700 bg-rose-50 border-rose-200",
    ring: "bg-rose-500",
    description: "이미 알려진 악성 APK를 해시 기반으로 빠르게 걸러냅니다.",
    catches: ["SHA256 hit", "악성 엔진 합의", "파일 reputation"],
    misses: "zero-day·변형 APK는 다음 정적 분석으로 넘김",
    files: [
      {
        path: "pipeline/safety.py",
        role: "VirusTotal 파일 해시 조회와 미스 시 업로드 스캔을 담당합니다.",
      },
    ],
  },
  {
    id: "manifest",
    step: "02",
    title: "Manifest Lv1",
    subtitle: "권한·서명·패키지명 정적 분석",
    badge: "Static manifest",
    tone: "text-amber-700 bg-amber-50 border-amber-200",
    ring: "bg-amber-500",
    description: "APK를 실행하지 않고 manifest만 읽어 위험한 권한 조합과 위장을 찾습니다.",
    catches: ["SEND_SMS + READ_SMS", "Accessibility 권한", "self-signed", "패키지명 사칭"],
    misses: "코드 내부 C&C·API 호출은 bytecode 단계에서 확인",
    files: [
      {
        path: "pipeline/apk_analyzer.py",
        role: "analyze_apk_static()이 manifest 권한, 서명, 패키지명 휴리스틱을 계산합니다.",
      },
    ],
  },
  {
    id: "bytecode",
    step: "03",
    title: "Bytecode Lv2",
    subtitle: "DEX xref·문자열·난독화 분석",
    badge: "Static bytecode",
    tone: "text-violet-700 bg-violet-50 border-violet-200",
    ring: "bg-violet-500",
    description: "DEX를 disassemble해서 보이스피싱 앱에서 자주 보이는 API 호출과 문자열을 찾습니다.",
    catches: ["SmsManager", "TelephonyManager", "Hard-coded C&C", "사칭 키워드", "난독화"],
    misses: "packing·reflection·실행 후 행동은 동적 분석 후보",
    files: [
      {
        path: "pipeline/apk_analyzer.py",
        role: "analyze_apk_bytecode()가 dex xref, 문자열 풀, C&C URL, 난독화 흔적을 탐색합니다.",
      },
    ],
  },
  {
    id: "runtime",
    step: "04",
    title: "Runtime Lv3",
    subtitle: "격리 Android VM 동적 분석",
    badge: "Future remote VM",
    tone: "text-teal-700 bg-teal-50 border-teal-200",
    ring: "bg-teal-500",
    description: "별도 VM에서 실제 실행 행동을 관찰하는 인터페이스입니다. 로컬 실행은 안전상 차단합니다.",
    catches: ["runtime C&C", "SMS 가로채기", "overlay 공격", "credential exfiltration"],
    misses: "현재는 인터페이스·카탈로그만 구현",
    future: true,
    files: [
      {
        path: "pipeline/apk_analyzer.py",
        role: "analyze_apk_dynamic()이 remote emulator 결과를 받아 runtime 신호로 변환합니다.",
      },
    ],
  },
];

function StageCard({
  stage,
  active,
  onClick,
}: {
  stage: ApkStage;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`group relative grid w-full gap-4 rounded-3xl border p-5 text-left transition ${
        active
          ? `${stage.tone} ring-2 ring-[#3182f6]/40 ring-offset-2`
          : "border-[#e5e8eb] bg-white hover:border-[#3182f6]/40 hover:bg-[#fafbfc]"
      } md:grid-cols-[4.5rem_1fr]`}
    >
      <div className="flex items-start gap-3 md:flex-col md:items-center">
        <div className={`flex h-14 w-14 items-center justify-center rounded-2xl text-lg font-black text-white ${stage.ring}`}>
          {stage.step}
        </div>
        <div className="hidden h-full w-px bg-[#e5e8eb] md:block" />
      </div>

      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-lg font-black tracking-tight text-[#191f28]">{stage.title}</h3>
          <span className={`rounded-full border px-2.5 py-1 text-[10px] font-bold ${stage.tone}`}>
            {stage.badge}
          </span>
          {stage.future ? (
            <span className="rounded-full border border-dashed border-teal-300 px-2.5 py-1 text-[10px] font-bold text-teal-700">
              local 실행 금지
            </span>
          ) : null}
        </div>
        <p className="mt-1 text-xs font-semibold text-[#8b95a1]">{stage.subtitle}</p>
        <p className="mt-3 text-sm leading-6 text-[#4e5968]">{stage.description}</p>

        <div className="mt-4 flex flex-wrap gap-2">
          {stage.catches.map((item) => (
            <span
              key={item}
              className="rounded-full border border-[#e5e8eb] bg-white px-3 py-1 text-[11px] font-medium text-[#333d4b]"
            >
              {item}
            </span>
          ))}
        </div>

        {stage.misses ? (
          <div className="mt-3 rounded-2xl bg-white/70 px-3 py-2 text-xs leading-5 text-[#6b7280]">
            다음 단계로 넘기는 것: {stage.misses}
          </div>
        ) : null}
      </div>
    </button>
  );
}

export default function ApkLayerDiagram() {
  const [activeId, setActiveId] = useState(APK_STAGES[0].id);
  const active = APK_STAGES.find((stage) => stage.id === activeId) ?? APK_STAGES[0];

  return (
    <div className="overflow-hidden rounded-3xl border border-[#e5e8eb] bg-[#fbfcfd]">
      <div className="border-b border-[#e5e8eb] bg-white p-6">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-xs font-black tracking-[0.12em] text-[#3182f6]">APK DEFENSE MAP</div>
            <h3 className="mt-1 text-2xl font-black tracking-tight text-[#191f28]">
              APK를 실행하지 않고, 점점 깊게 파고드는 4계층 분석
            </h3>
            <p className="mt-2 max-w-2xl text-sm leading-6 text-[#4e5968]">
              위 단계에서 놓친 샘플만 아래 단계로 내려갑니다. 각 계층은 서로 다른 증거를 잡고,
              최종 UI는 검출 신호만 보고합니다.
            </p>
          </div>
          <div className="rounded-2xl border border-[#e5e8eb] bg-[#f8fafc] px-4 py-3 text-right">
            <div className="text-[10px] font-bold text-[#8b95a1]">최종 출력</div>
            <div className="mt-1 text-sm font-black text-emerald-700">tier cards + detected_signals[]</div>
          </div>
        </div>
      </div>

      <div className="grid gap-6 p-6 lg:grid-cols-[1fr_0.72fr]">
        <div className="relative space-y-4">
          <div className="absolute bottom-16 left-7 top-16 w-0.5 bg-[#e5e8eb]" aria-hidden />
          {APK_STAGES.map((stage) => (
            <StageCard
              key={stage.id}
              stage={stage}
              active={active.id === stage.id}
              onClick={() => setActiveId(stage.id)}
            />
          ))}
        </div>

        <aside className="rounded-3xl border border-[#e5e8eb] bg-white p-5">
          <div className="text-xs font-black tracking-[0.12em] text-[#3182f6]">선택 계층</div>
          <h4 className="mt-2 text-xl font-black text-[#191f28]">{active.title}</h4>
          <p className="mt-2 text-sm leading-6 text-[#4e5968]">{active.description}</p>

          <div className="mt-5">
            <div className="mb-2 text-xs font-bold text-[#8b95a1]">검출하는 신호</div>
            <div className="flex flex-wrap gap-2">
              {active.catches.map((item) => (
                <span
                  key={item}
                  className={`rounded-full border px-3 py-1 text-[11px] font-bold ${active.tone}`}
                >
                  {item}
                </span>
              ))}
            </div>
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
            <div className="text-xs font-bold text-[#333d4b]">설계 원칙</div>
            <p className="mt-2 text-xs leading-5 text-[#8b95a1]">
              단일 신호로 사기 판정하지 않고, 각 계층에서 관찰한 증거를 detected_signals로만 보고합니다.
              판정 로직은 통합 기업의 정책 영역입니다.
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}
