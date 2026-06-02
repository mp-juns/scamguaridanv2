import Link from "next/link";

export const metadata = {
  title: "AI 공부시키기 — 어떻게 동작하나",
};

type ModelCardProps = {
  emoji: string;
  title: string;
  phase: string;
  base: string;
  role: string;
  inputs: string;
  outputs: string;
  pains: string[];
  fineTuneEffects: string[];
  metricKey: string;
};

function ModelCard({ emoji, title, phase, base, role, inputs, outputs, pains, fineTuneEffects, metricKey }: ModelCardProps) {
  return (
    <section className="rounded-3xl border border-white/10 bg-white/5 p-6">
      <div className="mb-4 flex flex-wrap items-baseline gap-3">
        <span className="text-3xl">{emoji}</span>
        <h2 className="text-2xl font-semibold text-white">{title}</h2>
        <span className="rounded-full border border-cyan-400/30 bg-cyan-500/10 px-3 py-1 text-xs text-cyan-200">
          {phase}
        </span>
      </div>

      <p className="mb-4 text-sm leading-relaxed text-slate-300">{role}</p>

      <div className="mb-5 grid gap-3 sm:grid-cols-3 text-sm">
        <Field label="처음에 데려온 모델" value={base} mono />
        <Field label="이 모델이 받는 것" value={inputs} />
        <Field label="이 모델이 내놓는 것" value={outputs} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="rounded-2xl border border-rose-400/20 bg-rose-500/5 p-4">
          <div className="mb-2 text-sm font-semibold text-rose-200">😩 공부 안 시켰을 때 아쉬운 점</div>
          <ul className="space-y-1.5 text-sm text-slate-300">
            {pains.map((p, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-rose-300">•</span>
                <span>{p}</span>
              </li>
            ))}
          </ul>
        </div>
        <div className="rounded-2xl border border-emerald-400/20 bg-emerald-500/5 p-4">
          <div className="mb-2 text-sm font-semibold text-emerald-200">🎯 공부 시키면 좋아지는 점</div>
          <ul className="space-y-1.5 text-sm text-slate-300">
            {fineTuneEffects.map((p, i) => (
              <li key={i} className="flex gap-2">
                <span className="text-emerald-300">•</span>
                <span>{p}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>

      <div className="mt-4 rounded-xl border border-white/10 bg-slate-950/40 p-3 text-xs text-slate-400">
        잘하는지 재는 자: <span className="font-mono text-slate-200">{metricKey}</span>
      </div>
    </section>
  );
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="rounded-xl border border-white/10 bg-slate-950/40 px-3 py-2">
      <div className="text-xs text-slate-400">{label}</div>
      <div className={`mt-1 ${mono ? "font-mono text-xs" : "text-sm"} text-slate-100 break-words`}>
        {value}
      </div>
    </div>
  );
}

const PHASES = [
  { num: 0, title: "안전성 검사", desc: "받은 링크·파일이 이미 알려진 악성인지 외부 백신에 조회합니다", model: null },
  { num: 1, title: "글자로 바꾸기", desc: "음성·이미지·PDF 같은 자료를 글자로 풀어냅니다", model: null },
  { num: 2, title: "유형 가려내기", desc: "이 글이 어떤 종류의 사기에 가까운지 12가지 중에 골라줍니다", model: "classifier" },
  { num: 3, title: "단어 뽑기 + 비슷한 사례 찾기", desc: "글에서 중요한 단어·표현을 추출하고, 옛날 비슷한 사례를 찾습니다", model: "gliner" },
  { num: 4, title: "사실 확인", desc: "뽑아낸 단어들을 구글 검색으로 한 번 더 확인합니다", model: null },
  { num: 5, title: "신호 정리", desc: "여기까지 모은 위험 신호들을 한 장에 정리해 보고합니다", model: null },
];

export default function TrainingAboutPage() {
  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,#111827_0%,#020617_60%,#000000_100%)] px-4 py-8 text-slate-100 sm:px-6">
      <div className="mx-auto w-full max-w-5xl space-y-8">
        <header className="space-y-2">
          <p className="text-sm text-slate-400">
            <Link href="/admin/training" className="hover:text-slate-200">
              ← AI 공부시키기 화면으로
            </Link>
          </p>
          <h1 className="text-3xl font-semibold text-white">📖 AI 모델을 공부시킨다는 게 무슨 뜻인가요?</h1>
          <p className="max-w-3xl text-sm leading-relaxed text-slate-400">
            ScamGuardian 의 분석은 6 단계로 이뤄집니다. 그중 두 단계에는 작은 AI 모델 두 개가 일하고 있어요.
            처음에는 인터넷에 공개된 <strong className="text-cyan-200">공용 모델</strong>(누군가 미리 만들어 둔 신입 같은 존재) 을 그대로 가져다 씁니다.
            여기에 우리 사기 자료로 연습을 시키면 점점 한국 사기 말투에 익숙해지고 실수가 줄어듭니다 — 그 연습이 바로 <strong className="text-fuchsia-200">&quot;공부시키기&quot;</strong>예요.
            연습이 끝나면 <strong className="text-white">[적용]</strong> 버튼 한 번으로 다음 분석부터 새 모델이 자동으로 일하게 됩니다.
          </p>
        </header>

        {/* 파이프라인 다이어그램 */}
        <section className="rounded-3xl border border-white/10 bg-white/5 p-6">
          <h2 className="mb-4 text-lg font-semibold text-white">🧭 6 단계 중 어디에 쓰이나요?</h2>
          <p className="mb-4 text-sm text-slate-400">
            아래 6 단계 중 <span className="text-cyan-200">2 번</span> 과 <span className="text-fuchsia-200">3 번</span> 자리에서 일하는 모델이 공부 대상입니다.
          </p>
          <div className="space-y-2">
            {PHASES.map((p) => {
              const highlight =
                p.model === "classifier"
                  ? "border-cyan-400/40 bg-cyan-500/5"
                  : p.model === "gliner"
                  ? "border-fuchsia-400/40 bg-fuchsia-500/5"
                  : "border-white/10 bg-slate-950/40";
              return (
                <div key={p.num} className={`flex items-center gap-4 rounded-2xl border px-4 py-3 ${highlight}`}>
                  <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-white/15 bg-black/30 font-mono text-sm">
                    {p.num}
                  </div>
                  <div className="flex-1">
                    <div className="text-sm font-semibold text-white">
                      {p.num} 단계 · {p.title}
                    </div>
                    <div className="text-xs text-slate-400">{p.desc}</div>
                  </div>
                  {p.model === "classifier" && (
                    <span className="rounded-full border border-cyan-400/40 bg-cyan-500/10 px-3 py-1 text-xs text-cyan-200">
                      🎯 유형 가려내기 모델
                    </span>
                  )}
                  {p.model === "gliner" && (
                    <span className="rounded-full border border-fuchsia-400/40 bg-fuchsia-500/10 px-3 py-1 text-xs text-fuchsia-200">
                      🔖 단어 뽑기 모델
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </section>

        {/* 각 모델 상세 */}
        <ModelCard
          emoji="🎯"
          title="유형 가려내기 모델"
          phase="2 단계"
          base="공용 다국어 글 분류 모델"
          role={
            "받은 글이 12 가지 사기 유형(예: 투자 권유 사기, 검찰청·금감원 사칭, 메신저 가족 사칭, 로맨스, 택배 사칭 등) 중 어느 쪽에 가까운지 골라주는 모델입니다. 결과 카드 위쪽에 보이는 '유형: 투자 사기' 한 줄이 바로 이 모델이 답한 결과예요."
          }
          inputs="글자로 풀어쓴 본문 (최대 약 2,000 자)"
          outputs="가장 가까운 사기 유형 + 12 가지 유형별 가까움 정도"
          pains={[
            "원래 인터넷 일반 글로만 공부한 모델이라 한국 보이스피싱 특유의 말투(반말 명령·생략·압박체) 를 잘 모릅니다",
            "자기 답에 자신이 없어서 어정쩡한 점수만 내는 일이 잦아요 (= 헷갈려 함)",
            "그래서 매번 추가로 비싼 외부 AI 한테 한 번 더 물어보게 되고 — 시간·비용이 더 듭니다",
            "단순히 '투자' 단어만 봐도 투자 사기로 단정하는 헛다리 짚기가 종종 일어납니다",
          ]}
          fineTuneEffects={[
            "한국 사기 자료로 직접 연습시키면 정답 맞히는 비율이 크게 올라갑니다 (대략 70 % → 90 % 수준 기대)",
            "자기 답에 자신을 갖게 되면서 외부 AI 한테 다시 물어보는 일이 줄어 — 분석 시간·비용 모두 절감",
            "키워드 한 개만 보고 단정하던 헛다리 짚기가 줄어듭니다",
            "새로운 사기 유형을 추가하고 싶을 때, 자료만 모이면 바로 추가 학습이 가능합니다",
          ]}
          metricKey="정답 맞힌 비율 · 외부 AI 한테 다시 물어본 비율"
        />

        <ModelCard
          emoji="🔖"
          title="단어 뽑기 모델"
          phase="3 단계 (다른 작업과 동시 진행)"
          base="공용 한국어 단어 추출 모델"
          role={
            "받은 글에서 중요한 단어·표현을 잘라주는 모델입니다. 예: '연 30 %' → 수익률 약속, '검찰청' → 기관 사칭, '안전계좌로 이체' → 송금 압박. 잘라낸 단어들은 다음 단계 사실 확인(구글 검색) 과 결과 카드의 '뽑아낸 단어' 칸에 사용됩니다. 모두 27 가지 의미 분류가 있어요."
          }
          inputs="글 본문 + 어떤 종류의 단어를 찾아야 하는지 알려주는 목록"
          outputs="뽑아낸 단어 한 개씩과 의미 라벨 (예: '연 30 %' = 수익률 약속)"
          pains={[
            "원래 일반 한국어 (뉴스·소설·SNS 등) 로만 공부한 모델이라 사기 특유의 추상 표현(예: '긴박감을 조성하는 어휘', '권위를 사칭하는 호칭') 을 거의 못 잡습니다",
            "정작 중요한 단어는 놓치고 별로 안 중요한 단어를 뽑는 경우가 잦아요",
            "이걸 메우려고 외부 AI 를 또 부르게 됩니다 — 비용 추가",
          ]}
          fineTuneEffects={[
            "사기 자료로 연습시키면 사기 단서에만 집중하게 되고, 잘 잡는 비율이 크게 오릅니다 (대략 50 % → 80 % 기대)",
            "검색해 볼 만한 단어만 깔끔하게 뽑혀 — 뒤이은 사실 확인 단계의 검색 횟수도 줄어듭니다",
            "외부 AI 에게 의존하는 비율도 자연스럽게 떨어집니다",
            "새 분류 라벨을 만든 뒤 자료만 채우면 즉시 추가 학습이 가능합니다",
          ]}
          metricKey="중요한 단어를 잘 잡은 비율 · 검색 횟수 · 외부 AI 의존도"
        />

        {/* before / after 직관 표 */}
        <section className="rounded-3xl border border-white/10 bg-white/5 p-6">
          <h2 className="mb-4 text-lg font-semibold text-white">📊 공부 전 vs 공부 후 (예상치)</h2>
          <p className="mb-3 text-sm text-slate-400">
            한 분류당 50 건 이상 자료가 모였을 때를 가정한 일반적인 기댓값입니다. 실제 결과는 자료의 양과 질에 따라 달라집니다.
          </p>
          <div className="overflow-x-auto rounded-2xl border border-white/10">
            <table className="w-full text-sm">
              <thead className="bg-slate-800/60 text-xs uppercase tracking-wider text-slate-400">
                <tr>
                  <th className="px-3 py-2 text-left">무엇을 재나</th>
                  <th className="px-3 py-2 text-right">공부 전</th>
                  <th className="px-3 py-2 text-right">공부 후</th>
                  <th className="px-3 py-2 text-left">전체에 미치는 효과</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-white/5">
                <tr>
                  <td className="px-3 py-3 text-slate-200">유형 가려내기 · 정답 맞히기</td>
                  <td className="px-3 py-3 text-right font-mono text-rose-300">~ 65 %</td>
                  <td className="px-3 py-3 text-right font-mono text-emerald-300">~ 90 %</td>
                  <td className="px-3 py-3 text-xs text-slate-400">잘못 분류되는 일이 줄어듭니다</td>
                </tr>
                <tr>
                  <td className="px-3 py-3 text-slate-200">유형 가려내기 · 외부 AI 다시 부른 비율</td>
                  <td className="px-3 py-3 text-right font-mono text-rose-300">~ 40 %</td>
                  <td className="px-3 py-3 text-right font-mono text-emerald-300">~ 10 %</td>
                  <td className="px-3 py-3 text-xs text-slate-400">분석 한 번당 비용·대기 시간이 줄어듭니다</td>
                </tr>
                <tr>
                  <td className="px-3 py-3 text-slate-200">단어 뽑기 · 잘 잡은 비율</td>
                  <td className="px-3 py-3 text-right font-mono text-rose-300">~ 50 %</td>
                  <td className="px-3 py-3 text-right font-mono text-emerald-300">~ 80 %</td>
                  <td className="px-3 py-3 text-xs text-slate-400">엉뚱한 단어가 빠지면서 다음 검색 단계도 빨라집니다</td>
                </tr>
                <tr>
                  <td className="px-3 py-3 text-slate-200">단어 뽑기 · 한 글에서 평균 뽑는 단어 수</td>
                  <td className="px-3 py-3 text-right font-mono text-slate-300">10 ~ 15 개</td>
                  <td className="px-3 py-3 text-right font-mono text-slate-300">8 ~ 12 개</td>
                  <td className="px-3 py-3 text-xs text-slate-400">덜 뽑는 대신 정확한 것만 뽑힙니다</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        {/* 권장 학습 분량 */}
        <section className="rounded-3xl border border-white/10 bg-white/5 p-6">
          <h2 className="mb-4 text-lg font-semibold text-white">📦 자료가 얼마나 있어야 공부시킬 수 있나요?</h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <div className="rounded-2xl border border-cyan-400/20 bg-cyan-500/5 p-4">
              <div className="text-sm font-semibold text-cyan-200">🎯 유형 가려내기 모델</div>
              <ul className="mt-2 space-y-1 text-sm text-slate-300">
                <li>최소: 한 종류당 5 건</li>
                <li>권장: 한 종류당 50 건 이상</li>
                <li>합계: 약 700 건 (12 종류 × 50 건 + 정상 사례)</li>
              </ul>
            </div>
            <div className="rounded-2xl border border-fuchsia-400/20 bg-fuchsia-500/5 p-4">
              <div className="text-sm font-semibold text-fuchsia-200">🔖 단어 뽑기 모델</div>
              <ul className="mt-2 space-y-1 text-sm text-slate-300">
                <li>최소: 한 의미 라벨당 30 번 등장</li>
                <li>권장: 한 라벨당 200 번 이상 등장</li>
                <li>한 글에 평균 10 ~ 30 개의 라벨이 등장합니다</li>
              </ul>
            </div>
          </div>
          <p className="mt-4 text-xs text-slate-400">
            자료가 부족할 때는 (1) 사람이 직접 정답을 매기는 화면(<code className="rounded bg-slate-950/40 px-1">/admin</code>)을 활용하거나,
            (2) 정상 콜센터 통화 자료를 추가해 &quot;정상 사례&quot; 를 보강하거나,
            (3) AI 에게 합성 사례를 만들게 해 드물게 보이는 사기 종류(예: 코인·로맨스·납치 협박) 를 채우는 방법이 있습니다.
          </p>
        </section>

        {/* swap 흐름 */}
        <section className="rounded-3xl border border-white/10 bg-white/5 p-6">
          <h2 className="mb-4 text-lg font-semibold text-white">🔄 공부가 끝나면 어떻게 적용되나요?</h2>
          <ol className="space-y-3 text-sm text-slate-300">
            <li className="rounded-2xl border border-white/10 bg-slate-950/40 px-4 py-3">
              <span className="mr-2 inline-flex h-6 w-6 items-center justify-center rounded-full bg-cyan-500/20 font-mono text-xs text-cyan-200">1</span>
              공부 세션이 끝나면 <strong className="text-white">[적용]</strong> 버튼을 누릅니다
            </li>
            <li className="rounded-2xl border border-white/10 bg-slate-950/40 px-4 py-3">
              <span className="mr-2 inline-flex h-6 w-6 items-center justify-center rounded-full bg-cyan-500/20 font-mono text-xs text-cyan-200">2</span>
              &quot;지금부터는 새 모델 사용&quot; 이라는 메모가 시스템에 기록됩니다
            </li>
            <li className="rounded-2xl border border-white/10 bg-slate-950/40 px-4 py-3">
              <span className="mr-2 inline-flex h-6 w-6 items-center justify-center rounded-full bg-cyan-500/20 font-mono text-xs text-cyan-200">3</span>
              다음 분석부터 자동으로 새 모델이 일을 시작합니다 (서버 다시 시작 안 해도 됩니다)
            </li>
            <li className="rounded-2xl border border-emerald-400/20 bg-emerald-500/5 px-4 py-3">
              <span className="mr-2 inline-flex h-6 w-6 items-center justify-center rounded-full bg-emerald-500/30 font-mono text-xs text-emerald-200">✓</span>
              만약 새 모델 파일이 사라지거나 망가져도, 시스템이 자동으로 원래 공용 모델로 되돌아갑니다 — 분석이 멈추지 않습니다
            </li>
          </ol>
        </section>

        {/* 학습 데이터 소스 */}
        <section className="rounded-3xl border border-white/10 bg-white/5 p-6">
          <h2 className="mb-4 text-lg font-semibold text-white">🗂 공부에 쓰는 자료는 어디서 나오나요?</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
              <div className="text-sm font-semibold text-white">사람이 직접 매긴 정답</div>
              <p className="mt-1 text-xs text-slate-400">
                관리자 화면에서 검수자가 매긴 정답이 그대로 공부 자료로 들어갑니다. 즉, 라벨링을 많이 할수록 모델이 더 똑똑해지는 구조입니다.
              </p>
            </div>
            <div className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
              <div className="text-sm font-semibold text-white">외부에서 가져온 자료 (선택 사항)</div>
              <p className="mt-1 text-xs text-slate-400">
                예를 들어 정부의 공공 데이터(AI Hub) 의 정상 콜센터 통화 자료를 받아 &quot;정상 사례&quot; 로 추가하면, 모델이 정상 vs 사기 차이를 더 잘 구분합니다.
                또는 AI 가 만든 합성 사례로 드문 사기 유형을 채울 수도 있습니다.
              </p>
            </div>
          </div>
        </section>

        <footer className="pt-2 text-center text-xs text-slate-500">
          <Link href="/admin/training" className="hover:text-slate-300">
            ← AI 공부시키기 화면으로 돌아가기
          </Link>
        </footer>
      </div>
    </main>
  );
}
