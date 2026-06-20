"use client";

import { useState } from "react";

import type { DemoSnapshot } from "../../lib/pipelineArchitecture";

type ContentStage = {
  id: string;
  step: string;
  title: string;
  subtitle: string;
  tone: string;
  dot: string;
  what: string;
  how: string[];
  learns: string[];
  applied: string;
  improved: string[];
  files: Array<{ path: string; role: string }>;
};

const CONTENT_STAGES: ContentStage[] = [
  {
    id: "augment",
    step: "01",
    title: "데이터 증강",
    subtitle: "실제 seed → Claude paraphrase → taxonomy 검증",
    tone: "border-sky-200 bg-sky-50 text-sky-700",
    dot: "bg-sky-500",
    what:
      "실사용자가 모은 사기 문자/메시지를 seed로 두고, 이름·금액·URL·기관명·말투만 바꾼 변형 데이터를 생성합니다.",
    how: [
      "content_label / scam_type은 보존해서 라벨 일관성 유지",
      "entities span은 생성 텍스트 안에서 substring 매칭으로 다시 계산",
      "risk_flags는 pipeline.config의 DETECTED_FLAGS로 제한해 환각 라벨 차단",
      "병렬 c=4: 8.7s/변형 → 2.82s/변형, 실측 3.1× 단축",
    ],
    learns: ["text", "content_label", "scam_type", "entities", "risk_flags", "flag_groups", "rag_texts"],
    applied: "data/generated/user_samples_augmented.jsonl 및 synthetic JSONL이 gate/classifier/GLiNER 학습 입력으로 들어갑니다.",
    improved: ["균형셋 생성 시간 5.6–6.2× 단축", "6-class 직접 학습 macro F1 +0.063 기록", "현재 user_samples_augmented 약 4,363건"],
    files: [
      {
        path: "scripts/augment_user_samples.py",
        role: "순차 증강. seed 1개씩 Claude 호출 후 스키마·taxonomy·span 검증.",
      },
      {
        path: "scripts/augment_seeds_concurrent.py",
        role: "최종 증강기. ThreadPoolExecutor 병렬, retry, 일괄 dedup, 단일 append.",
      },
      {
        path: "docs/experiments/augmentation_time_comparison.md",
        role: "증강 속도/품질 실험 기록. 3.1× 병렬 단축, 5.6–6.2× 전체 단축 근거.",
      },
    ],
  },
  {
    id: "gate",
    step: "02",
    title: "콘텐츠 게이트 학습",
    subtitle: "normal / scam_attempt / scam_news_edu",
    tone: "border-blue-200 bg-blue-50 text-blue-700",
    dot: "bg-blue-500",
    what:
      "입력이 일반 대화인지, 실제 분석 대상 사기 시도인지, 사기 뉴스/교육 콘텐츠인지 먼저 가릅니다.",
    how: [
      "mDeBERTa-v3-base-mnli-xnli 기반 3-class gate",
      "LoRA/checkpoint 활성화: content_label_gate_20260610 checkpoint-5610",
      "입력: data/generated/user_samples_augmented.jsonl",
      "10 epochs, val_ratio 0.1, seed 17",
    ],
    learns: ["normal", "scam_attempt", "scam_news_edu"],
    applied:
      ".scamguardian/active_models.json의 gate 경로를 pipeline/active_models.py가 읽고, pipeline/gate.py가 런타임 라우팅에 사용합니다.",
    improved: [
      "raw zero-shot smoke 3/9(33.3%) → latest fine-tuned 6/9(66.7%)",
      "같은 9개 gate smoke 문장에서 정답 +3개, accuracy +33.3%p",
      "예측 변경 8개 중 개선 5개 / 악화 2개 — normal hard-negative 보강 필요",
      "학습 로그 기준 초기 eval macro F1 36.8% → 최종 96.0%",
      "normal→scam_attempt 오탐 14.5% → 2.6%",
    ],
    files: [
      {
        path: ".scamguardian/training_sessions/content_label_gate_20260610/status.json",
        role: "최신 gate 학습 결과. accuracy 0.9794, macro F1 0.9600, confusion 기록.",
      },
      {
        path: ".scamguardian/training_sessions/content_label_gate_20260610/output/checkpoint-5610/trainer_state.json",
        role: "epoch 1 초기 eval(accuracy 0.746, macro F1 0.368)부터 최종 eval까지의 개선 추적.",
      },
      {
        path: ".scamguardian/training_sessions/content_label_gate_20260610/raw_compare_smoke.json",
        role: "raw base mDeBERTa zero-shot 3-class 와 최신 fine-tuned gate 를 9개 smoke 문장으로 비교.",
      },
      {
        path: "pipeline/gate.py",
        role: "활성 gate 체크포인트로 입력을 normal/scam_attempt/scam_news_edu로 라우팅.",
      },
      {
        path: "pipeline/active_models.py",
        role: "active_models.json을 60초 TTL로 읽어 학습 모델을 런타임에 적용.",
      },
    ],
  },
  {
    id: "classifier",
    step: "03",
    title: "유형 분류기 학습",
    subtitle: "12종 scam_type multi-class",
    tone: "border-violet-200 bg-violet-50 text-violet-700",
    dot: "bg-violet-500",
    what:
      "gate가 scam_attempt로 보낸 텍스트를 투자/스미싱/기관사칭/메신저피싱 등 12개 유형으로 분류합니다.",
    how: [
      "mDeBERTa multi-class classifier + LoRA",
      "활성 세션: b10859a4dbd2/output",
      "입력: data/generated/scamguardian_synthetic_12000.jsonl",
      "10 epochs 요청, early stopping으로 epoch 5 완료",
    ],
    learns: ["12 scam types", "문장 전체 패턴", "키워드+문맥 유형"],
    applied:
      "active_models.json의 classifier 경로를 pipeline/classifier.py가 로드합니다. 무효 경로면 zero-shot fallback으로 돌아갑니다.",
    improved: [
      "raw zero-shot smoke 10/12(83.3%) → fine-tuned 11/12(91.7%)",
      "같은 12개 실전형 문장에서 정답 +1개, accuracy +8.3%p",
      "활성 세션 own-val accuracy 1.000 / macro F1 1.000 기록",
      "이전 cls12 group best_metric 0.8534에서 별도 활성 세션으로 교체",
    ],
    files: [
      {
        path: ".scamguardian/training_sessions/b10859a4dbd2/status.json",
        role: "활성 classifier 학습 결과와 커맨드. extra_jsonl, LoRA, early stopping 기록.",
      },
      {
        path: "training/train_classifier.py",
        role: "mDeBERTa SFT/LoRA 학습, metrics.jsonl emit, checkpoint 저장.",
      },
      {
        path: "pipeline/classifier.py",
        role: "활성 체크포인트가 있으면 fine-tuned 분류, 없으면 zero-shot NLI fallback.",
      },
      {
        path: "api_server_pkg/admin_training_compare.py",
        role: "12개 smoke sample로 raw zero-shot과 fine-tuned 분류 결과를 비교.",
      },
    ],
  },
  {
    id: "gliner",
    step: "04",
    title: "엔티티 추출기 학습",
    subtitle: "GLiNER NER · 50 entity labels",
    tone: "border-emerald-200 bg-emerald-50 text-emerald-700",
    dot: "bg-emerald-500",
    what:
      "분류된 scam_type에 맞춰 수익률, URL, 계좌, 기관명, 사람 이름 같은 증거 단어를 뽑습니다.",
    how: [
      "GLiNER fine-tune",
      "활성 세션: c6ba617511b9/output",
      "train 10,785 / val 1,199",
      "entity 39,984개, label 50개, max_steps 3,000",
    ],
    learns: ["악성 URL", "기관명", "금액", "계좌", "사람 이름", "날짜/기간", "수익률 등"],
    applied:
      "active_models.json의 gliner 경로를 pipeline/extractor.py가 로드하고, 모델 경로 변경 시 재로드합니다.",
    improved: [
      "기존 fallback(JSON 저장만)에서 실제 GLiNER train_model 완료 세션 확보",
      "entity_count 39,984 / label_count 50 기반으로 NER 범위 확대",
      "추출 엔티티가 verifier와 scorer의 rule signal 증거가 됨",
    ],
    files: [
      {
        path: ".scamguardian/training_sessions/c6ba617511b9/status.json",
        role: "활성 GLiNER 학습 결과. train/val/entity/label/max_steps 기록.",
      },
      {
        path: "training/train_gliner.py",
        role: "GLiNER 학습 데이터 변환, train_model 실행, labels/config 저장.",
      },
      {
        path: "pipeline/extractor.py",
        role: "활성 GLiNER 모델로 scam_type별 엔티티 추출.",
      },
    ],
  },
  {
    id: "runtime",
    step: "05",
    title: "런타임 적용",
    subtitle: "active_models.json → pipeline 자동 swap",
    tone: "border-slate-200 bg-slate-50 text-slate-700",
    dot: "bg-slate-500",
    what:
      "학습이 끝난 모델은 active_models.json에 등록되고, API 분석 요청에서 자동으로 교체 적용됩니다.",
    how: [
      "gate: content_label_gate_20260610/checkpoint-5610",
      "classifier: b10859a4dbd2/output",
      "gliner: c6ba617511b9/output",
      "경로 무효 시 base/zero-shot fallback",
    ],
    learns: ["운영 적용 경로", "fallback 안전장치", "60s TTL cache"],
    applied:
      "ScamGuardianPipeline.analyze()의 gate → classifier → extractor 단계가 이 활성 모델 경로를 사용합니다.",
    improved: [
      "일반/뉴스 콘텐츠를 먼저 걸러 불필요한 Phase 2~4 비용 감소",
      "분류 정확도와 엔티티 근거가 올라가 LLM/Verifier 입력 품질 개선",
      "외부 응답은 여전히 detected_signals[]만 노출",
    ],
    files: [
      {
        path: ".scamguardian/active_models.json",
        role: "현재 런타임에 적용된 gate/classifier/gliner 체크포인트 경로.",
      },
      {
        path: "pipeline/runner.py",
        role: "분석 전체 phase를 오케스트레이션하고 활성 모델 결과를 결합.",
      },
      {
        path: "pipeline/scorer.py",
        role: "검출된 엔티티·검증·LLM 제안을 detected_signals로 정리.",
      },
    ],
  },
];

function pct(v: number) {
  return `${Math.round(v * 1000) / 10}%`;
}

function StageCard({
  stage,
  active,
  onClick,
}: {
  stage: ContentStage;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`relative w-full rounded-3xl border p-5 text-left transition ${
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
              {stage.subtitle}
            </span>
          </div>
          <p className="mt-2 text-sm leading-6 text-[#4e5968]">{stage.what}</p>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {stage.learns.slice(0, 5).map((item) => (
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

function MetricTile({
  label,
  value,
  note,
  tone,
}: {
  label: string;
  value: string;
  note: string;
  tone: string;
}) {
  return (
    <div className={`rounded-2xl border p-4 ${tone}`}>
      <div className="text-[10px] font-black uppercase tracking-wide opacity-70">{label}</div>
      <div className="mt-1 text-2xl font-black tabular-nums">{value}</div>
      <div className="mt-1 text-[11px] leading-5 opacity-80">{note}</div>
    </div>
  );
}

function RawCompareStrip() {
  const rows = [
    {
      label: "Gate",
      raw: "Raw 3/9",
      tuned: "Fine-tuned 6/9",
      delta: "+33.3%p",
      note: "base zero-shot 33.3% → 66.7% · 개선 5 / 악화 2",
      tone: "border-blue-200 bg-blue-50 text-blue-700",
    },
    {
      label: "Classifier",
      raw: "Raw 10/12",
      tuned: "Fine-tuned 11/12",
      delta: "+8.3%p",
      note: "zero-shot smoke set 83.3% → 91.7%",
      tone: "border-violet-200 bg-violet-50 text-violet-700",
    },
  ];

  return (
    <div className="mt-5 rounded-3xl border border-[#e5e8eb] bg-[#f8fafc] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-xs font-black text-[#333d4b]">Raw/Base 대비 개선</div>
          <p className="mt-1 text-[11px] leading-5 text-[#8b95a1]">
            Gate와 Classifier 모두 raw/base zero-shot과 최신 fine-tuned checkpoint를 같은 smoke 문장에 적용한 결과입니다.
          </p>
        </div>
        <span className="rounded-full bg-white px-3 py-1 text-[10px] font-bold text-[#4e5968]">
          같은 기준으로 전/후 표시
        </span>
      </div>
      <div className="mt-3 grid gap-3 sm:grid-cols-2">
        {rows.map((row) => (
          <div key={row.label} className={`rounded-2xl border p-4 ${row.tone}`}>
            <div className="flex items-center justify-between gap-3">
              <div className="text-sm font-black">{row.label}</div>
              <div className="rounded-full bg-white/80 px-2.5 py-1 text-xs font-black">{row.delta}</div>
            </div>
            <div className="mt-3 grid grid-cols-[1fr_auto_1fr] items-center gap-2">
              <div className="rounded-xl bg-white/80 px-3 py-2 text-center text-xs font-bold">{row.raw}</div>
              <div className="text-sm font-black">→</div>
              <div className="rounded-xl bg-white/80 px-3 py-2 text-center text-xs font-bold">{row.tuned}</div>
            </div>
            <div className="mt-2 text-[11px] font-medium opacity-80">{row.note}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ContentTrainingMap({ snap }: { snap: DemoSnapshot }) {
  const [activeId, setActiveId] = useState("augment");
  const active = CONTENT_STAGES.find((stage) => stage.id === activeId) ?? CONTENT_STAGES[0];
  const donePct = snap.label_queue.total
    ? snap.label_queue.annotated / snap.label_queue.total
    : 0;
  const activePaths = {
    gate: snap.gate.active_model_path?.split("/").slice(-2).join("/") ?? "base",
    classifier: snap.classifier.active_model_path?.split("/").slice(-2).join("/") ?? "base",
    gliner: snap.gliner.active_model_path?.split("/").slice(-2).join("/") ?? "base",
  };

  return (
    <div className="overflow-hidden rounded-3xl border border-[#e5e8eb] bg-[#fbfcfd]">
      <div className="border-b border-[#e5e8eb] bg-white p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="text-xs font-black tracking-[0.12em] text-[#3182f6]">CONTENT ML MAP</div>
            <h3 className="mt-1 text-2xl font-black tracking-tight text-[#191f28]">
              데이터가 어떻게 늘고, 무엇을 학습하고, 런타임에 어떻게 좋아졌는지
            </h3>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-[#4e5968]">
              콘텐츠 분석은 단순 7-Phase 그림이 아니라, 증강 데이터가 gate/classifier/GLiNER를 학습시키고
              active model swap으로 실제 분석 파이프라인에 들어가는 구조입니다.
            </p>
          </div>
          <div className="grid grid-cols-3 gap-2 rounded-2xl border border-[#e5e8eb] bg-[#f8fafc] p-2">
            <div className="rounded-xl bg-white px-3 py-2 text-center">
              <div className="text-[10px] font-bold text-[#8b95a1]">Gate</div>
              <div className="text-sm font-black text-[#3182f6]">{snap.gate.data_count}</div>
            </div>
            <div className="rounded-xl bg-white px-3 py-2 text-center">
              <div className="text-[10px] font-bold text-[#8b95a1]">Classifier</div>
              <div className="text-sm font-black text-violet-700">{snap.classifier.data_count}</div>
            </div>
            <div className="rounded-xl bg-white px-3 py-2 text-center">
              <div className="text-[10px] font-bold text-[#8b95a1]">GLiNER</div>
              <div className="text-sm font-black text-emerald-700">{snap.gliner.data_count}</div>
            </div>
          </div>
        </div>
      </div>

      <div className="grid gap-6 p-6 xl:grid-cols-[1.05fr_0.95fr]">
        <div>
          <div className="mb-3 flex items-center justify-between">
            <span className="text-xs font-black text-[#333d4b]">학습/적용 흐름</span>
            <span className="rounded-full bg-[#e8f3ff] px-3 py-1 text-[10px] font-bold text-[#3182f6]">
              click stage
            </span>
          </div>
          <div className="relative space-y-3">
            <div className="absolute bottom-12 left-6 top-12 w-0.5 bg-[#e5e8eb]" aria-hidden />
            {CONTENT_STAGES.map((stage) => (
              <StageCard
                key={stage.id}
                stage={stage}
                active={active.id === stage.id}
                onClick={() => setActiveId(stage.id)}
              />
            ))}
          </div>
        </div>

        <aside className="rounded-3xl border border-[#e5e8eb] bg-white p-5">
          <div className="text-xs font-black tracking-[0.12em] text-[#3182f6]">선택 단계</div>
          <h4 className="mt-2 text-xl font-black text-[#191f28]">{active.title}</h4>
          <p className="mt-2 text-sm leading-6 text-[#4e5968]">{active.what}</p>

          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            <MetricTile
              label="증강 속도"
              value="3.1×"
              note="c=4 병렬: 8.7s → 2.82s/변형"
              tone="border-sky-200 bg-sky-50 text-sky-700"
            />
            <MetricTile
              label="Gate Raw 대비"
              value="+33.3%p"
              note="zero-shot 3/9 → tuned 6/9"
              tone="border-blue-200 bg-blue-50 text-blue-700"
            />
            <MetricTile
              label="Classifier Raw 대비"
              value="+8.3%p"
              note="zero-shot 10/12 → tuned 11/12"
              tone="border-violet-200 bg-violet-50 text-violet-700"
            />
            <MetricTile
              label="GLiNER"
              value="39,984"
              note="학습 entity count / 50 labels"
              tone="border-emerald-200 bg-emerald-50 text-emerald-700"
            />
          </div>

          <RawCompareStrip />

          <div className="mt-5">
            <div className="mb-2 text-xs font-bold text-[#8b95a1]">어떻게 하는지</div>
            <ul className="space-y-2">
              {active.how.map((item) => (
                <li key={item} className="rounded-2xl border border-[#e5e8eb] bg-[#fafbfc] px-3 py-2 text-xs leading-5 text-[#4e5968]">
                  {item}
                </li>
              ))}
            </ul>
          </div>

          <div className="mt-5">
            <div className="mb-2 text-xs font-bold text-[#8b95a1]">무엇을 학습하는지</div>
            <div className="flex flex-wrap gap-2">
              {active.learns.map((item) => (
                <span key={item} className={`rounded-full border px-3 py-1 text-[11px] font-bold ${active.tone}`}>
                  {item}
                </span>
              ))}
            </div>
          </div>

          <div className="mt-5 rounded-2xl border border-[#e5e8eb] bg-[#f8fafc] p-4">
            <div className="text-xs font-bold text-[#333d4b]">어떻게 적용되는지</div>
            <p className="mt-2 text-xs leading-5 text-[#4e5968]">{active.applied}</p>
            <div className="mt-3 grid gap-2 text-[10px] font-mono text-[#3182f6]">
              <div>gate: {activePaths.gate}</div>
              <div>classifier: {activePaths.classifier}</div>
              <div>gliner: {activePaths.gliner}</div>
            </div>
          </div>

          <div className="mt-5">
            <div className="mb-2 text-xs font-bold text-[#8b95a1]">어떻게 나아졌는지</div>
            <ul className="space-y-2">
              {active.improved.map((item) => (
                <li key={item} className="rounded-2xl border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs leading-5 text-emerald-800">
                  {item}
                </li>
              ))}
            </ul>
          </div>

          <div className="mt-5">
            <div className="mb-2 text-xs font-bold text-[#8b95a1]">근거 파일</div>
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
            <div className="flex items-center justify-between text-xs">
              <span className="font-bold text-[#333d4b]">라벨 큐 완료율</span>
              <span className="font-black text-[#3182f6]">{pct(donePct)}</span>
            </div>
            <div className="mt-2 h-2 overflow-hidden rounded-full bg-[#e5e8eb]">
              <div className="h-full rounded-full bg-[#3182f6]" style={{ width: `${Math.round(donePct * 100)}%` }} />
            </div>
            <div className="mt-2 text-[11px] text-[#8b95a1]">
              완료 {snap.label_queue.annotated} / 미완료 {snap.label_queue.pending}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}
