import Link from "next/link";

export const metadata = {
  title: "데이터 증강 가이드 — ScamGuardian Admin",
};

type Term = {
  term: string;
  en: string;
  short: string;
  detail: string;
};

const TERMS: Term[] = [
  {
    term: "씨앗",
    en: "seed",
    short: "Claude 에게 보여주는 진짜 사기 메시지 원본 1개",
    detail:
      "사람이 수집·작성한 실제 사기 문장. 증강의 출발점이자 정답 라벨(scam_type·content_label)의 출처다. Claude 는 이걸 '본보기'로 보고 비슷한 수법의 새 메시지를 만든다.",
  },
  {
    term: "변형",
    en: "variant",
    short: "씨앗 1개에서 Claude 가 만든, 표면만 바꾼 새 메시지",
    detail:
      "수법(긴급 송금·링크 유도·기관 사칭 등)은 유지하고 이름·금액·URL·말투·문장 순서만 바꾼다. scam_type·content_label 은 씨앗에서 그대로 복사된다.",
  },
  {
    term: "라운드",
    en: "round",
    short: "같은 씨앗을 독립 패스로 몇 번 반복 증강하는지",
    detail:
      "2회차부터는 프롬프트에 '앞 라운드와 겹치지 않는 완전히 새로운 케이스로' 지시가 붙어 다양성이 올라간다. variants 를 한 번에 크게 뽑는 것보다, variants 를 적게 × rounds 를 여러 번이 더 다양하다.",
  },
  {
    term: "동시성",
    en: "concurrency",
    short: "한 번에 동시에 던지는 API 호출 수 (속도 레버)",
    detail:
      "기존 CLI 는 씨앗을 하나씩 순차 처리해 느렸다(600개 ~40분). 동시성 N 이면 벽시계 시간이 약 1/N 로 줄어든다. 토큰 총량은 같으므로 비용은 동일하고 시간만 단축된다. 상한 16.",
  },
  {
    term: "scam_type",
    en: "사기 유형",
    short: "스미싱·투자 사기 등 12개 유형 (분류기의 정답)",
    detail:
      "분류기(mDeBERTa)가 맞혀야 하는 라벨. 씨앗마다 하나씩 달려 있고, 변형이 이를 물려받는다. 유형별 씨앗 수가 고르지 않으면 적은 유형의 정확도가 무너진다.",
  },
  {
    term: "content_label",
    en: "콘텐츠 라벨",
    short: "scam_attempt / normal / scam_news_edu 3종",
    detail:
      "scam_type 분류기는 content_label == scam_attempt 인 샘플만 학습한다. normal(정상)·scam_news_edu(뉴스·교육)는 앞단 게이트용. 씨앗 작성 시 사기 메시지는 scam_attempt 로 둔다.",
  },
  {
    term: "굶은 유형",
    en: "starved",
    short: "씨앗이 3개 이하인 유형 (커버리지 갭)",
    detail:
      "씨앗이 적으면 변형을 아무리 늘려도 같은 1~3개 문장의 변주뿐이라 모델이 일반화를 못 한다 → 그 유형 F1 ≈ 0. macro_f1 이 낮은 근본 원인. 커버리지 막대에서 빨강으로 표시된다.",
  },
  {
    term: "내보내기",
    en: "promote",
    short: "증강 산출물을 학습 데이터로 합치기",
    detail:
      "완료된 세션의 output.jsonl 을 data/generated/ 의 학습 파일로 병합(중복 제거)한다. 그 경로를 Fine-tuning 폼의 extra_jsonl 에 넣으면 새 데이터로 학습이 된다.",
  },
];

const STEPS: { n: number; title: string; desc: string }[] = [
  { n: 1, title: "커버리지 확인", desc: "상단 막대에서 빨강(굶은 유형)을 찾는다. 씨앗이 적은 유형이 보강 대상이다." },
  { n: 2, title: "씨앗 작성", desc: "굶은 유형을 골라 진짜같은 사기 메시지를 직접 써넣는다. 수법이 서로 다른 씨앗일수록 가치가 크다." },
  { n: 3, title: "증강 실행", desc: "변형 수·라운드·동시성을 정하고 시작. 특정 유형만 보강하려면 '씨앗 소스 유형'을 지정한다." },
  { n: 4, title: "진행 모니터링", desc: "세션을 선택하면 진행률 바·누적 생성 그래프·로그가 실시간(5초 폴링)으로 갱신된다." },
  { n: 5, title: "내보내기", desc: "완료되면 'training 데이터로 내보내기' 로 학습 파일에 병합하고 경로를 받는다." },
  { n: 6, title: "학습", desc: "Fine-tuning 페이지에서 그 경로를 extra_jsonl 로 넣고 분류기를 학습한다." },
];

const COST_ROWS = [
  ["600", "~$3", "~40분", "~1.5시간*"],
  ["2,188", "~$12", "~2.5시간", "~15분*"],
  ["6,000", "~$32", "~6.7시간", "~40분*"],
  ["12,000", "~$65", "~14시간", "~1.5시간*"],
];

export default function AugmentAboutPage() {
  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,#111827_0%,#020617_60%,#000000_100%)] px-4 py-8 text-slate-100 sm:px-6">
      <div className="mx-auto w-full max-w-5xl space-y-8">
        <header className="space-y-2">
          <p className="text-sm text-slate-400">
            <Link href="/admin/augment" className="hover:text-slate-200">
              ← 데이터 증강
            </Link>
          </p>
          <h1 className="text-3xl font-semibold text-white">📖 데이터 증강이 뭐고 어떻게 하는 건가요?</h1>
          <p className="max-w-3xl text-sm leading-relaxed text-slate-400">
            분류기가 사기 유형을 잘 맞히려면 유형마다 충분한 학습 예시가 필요합니다. 그런데 실제로 모은 사기 문장(씨앗)은
            유형마다 개수가 들쭉날쭉하고, 어떤 유형은 한두 개뿐이라 그 유형은 거의 못 맞힙니다. <strong className="text-cyan-200">데이터 증강</strong>은
            이 씨앗 하나를 Claude 가 표면만 바꿔 여러 개로 늘려 부족한 유형을 메우는 작업입니다.
          </p>
        </header>

        {/* 핵심 비유 */}
        <section className="rounded-3xl border border-white/10 bg-white/5 p-6">
          <h2 className="mb-3 text-lg font-semibold text-white">🍳 한 줄 비유</h2>
          <p className="text-sm leading-relaxed text-slate-300">
            <strong className="text-fuchsia-200">씨앗</strong> = 셰프(Claude)에게 맛보여 주는 <strong>원본 요리 한 접시</strong>,{" "}
            <strong className="text-cyan-200">변형</strong> = 그걸 맛보고 비슷하게 다시 만든 <strong>응용 요리들</strong>.
            원본 접시 종류(씨앗)가 적으면 아무리 많이 만들어도 결국 비슷한 메뉴만 나옵니다 — 그래서{" "}
            <strong className="text-white">진짜 다양성은 씨앗 수에서 옵니다.</strong>
          </p>
        </section>

        {/* 용어 사전 */}
        <section className="rounded-3xl border border-white/10 bg-white/5 p-6">
          <h2 className="mb-4 text-lg font-semibold text-white">📚 용어 사전</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {TERMS.map((t) => (
              <div key={t.en} className="rounded-2xl border border-white/10 bg-slate-950/40 p-4">
                <div className="mb-1 flex items-baseline gap-2">
                  <span className="text-base font-semibold text-white">{t.term}</span>
                  <span className="font-mono text-xs text-cyan-300">{t.en}</span>
                </div>
                <p className="mb-2 text-sm font-medium text-slate-200">{t.short}</p>
                <p className="text-xs leading-relaxed text-slate-400">{t.detail}</p>
              </div>
            ))}
          </div>
        </section>

        {/* 어떻게 증강되나 */}
        <section className="rounded-3xl border border-white/10 bg-white/5 p-6">
          <h2 className="mb-4 text-lg font-semibold text-white">⚙️ 증강은 내부에서 어떻게 도나요?</h2>
          <div className="space-y-2">
            {[
              { k: "씨앗 1개", v: "진짜 사기 문장 + scam_type·content_label (정답)" },
              { k: "프롬프트 구성", v: "'수법·라벨은 유지, 이름·금액·URL·말투만 바꿔 N개 만들어라'" },
              { k: "Claude 호출", v: "tool(emit_variants)로 변형 N개를 구조화해 반환 (라운드>1이면 '앞과 겹치지 말라' 추가)" },
              { k: "검증·정제", v: "허용된 entity 라벨·risk_flag 만 통과(환각 차단), entity 위치를 본문에서 substring 매칭" },
              { k: "output.jsonl", v: "변형들을 학습용 스키마로 한 줄씩 기록 (씨앗과 동일 포맷)" },
              { k: "내보내기→학습", v: "data/generated 로 병합 → Fine-tuning 의 extra_jsonl 로 학습" },
            ].map((row, i) => (
              <div key={i} className="flex items-start gap-3">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-white/15 bg-black/30 font-mono text-xs text-slate-300">
                  {i + 1}
                </span>
                <div className="flex-1 rounded-xl border border-white/10 bg-slate-950/40 px-3 py-2">
                  <span className="text-sm font-semibold text-cyan-200">{row.k}</span>
                  <span className="mx-2 text-slate-600">→</span>
                  <span className="text-sm text-slate-300">{row.v}</span>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-4 rounded-xl border border-fuchsia-400/20 bg-fuchsia-500/5 p-3 text-sm text-slate-300">
            총 생성량 ≈ <span className="font-mono text-fuchsia-200">씨앗 수 × 변형(variants) × 라운드(rounds)</span>
          </div>
        </section>

        {/* 사용 단계 */}
        <section className="rounded-3xl border border-white/10 bg-white/5 p-6">
          <h2 className="mb-4 text-lg font-semibold text-white">🧭 어떻게 쓰나요? (6 단계)</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {STEPS.map((s) => (
              <div key={s.n} className="flex gap-3 rounded-2xl border border-white/10 bg-slate-950/40 p-4">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-cyan-400/40 bg-cyan-500/10 font-mono text-sm text-cyan-200">
                  {s.n}
                </span>
                <div>
                  <div className="text-sm font-semibold text-white">{s.title}</div>
                  <div className="mt-0.5 text-xs leading-relaxed text-slate-400">{s.desc}</div>
                </div>
              </div>
            ))}
          </div>
        </section>

        {/* 비용·시간 */}
        <section className="rounded-3xl border border-white/10 bg-white/5 p-6">
          <h2 className="mb-3 text-lg font-semibold text-white">💸 비용·시간 (sonnet-4-6 기준 추정)</h2>
          <div className="overflow-x-auto rounded-2xl border border-white/10">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 bg-white/5 text-left text-xs text-slate-400">
                  <th className="px-4 py-2">생성량</th>
                  <th className="px-4 py-2">API 비용</th>
                  <th className="px-4 py-2">순차(기존 CLI)</th>
                  <th className="px-4 py-2">병렬(이 어드민)</th>
                </tr>
              </thead>
              <tbody>
                {COST_ROWS.map((r) => (
                  <tr key={r[0]} className="border-b border-white/5 text-slate-300">
                    <td className="px-4 py-2 font-mono">{r[0]}</td>
                    <td className="px-4 py-2">{r[1]}</td>
                    <td className="px-4 py-2 text-slate-500">{r[2]}</td>
                    <td className="px-4 py-2 text-emerald-200">{r[3]}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-xs text-slate-500">* 병렬은 동시성 10 가정 추정치. 변형 1개 ≈ 약 0.5센트(출력 ~330 토큰).</p>
        </section>

        {/* 한계 */}
        <section className="rounded-3xl border border-amber-400/20 bg-amber-500/5 p-6">
          <h2 className="mb-3 text-lg font-semibold text-amber-200">⚠️ 꼭 알아둘 한계</h2>
          <ul className="space-y-2 text-sm leading-relaxed text-slate-300">
            <li className="flex gap-2">
              <span className="text-amber-300">•</span>
              <span>
                <strong className="text-white">다양성 상한 = 씨앗 다양성.</strong> 라운드·변형을 늘려도 한 씨앗에서 짜내는 것이라 한계가 있습니다.
                굶은 유형의 근본 해결은 <strong className="text-amber-200">서로 다른 수법의 씨앗을 추가</strong>하는 것입니다.
              </span>
            </li>
            <li className="flex gap-2">
              <span className="text-amber-300">•</span>
              <span>
                <strong className="text-white">합성 100%는 위험.</strong> 같은 골격을 대량 복제하면 평가가 부풀려집니다(누설). 검증은 실제 수집 데이터로 하세요.
              </span>
            </li>
            <li className="flex gap-2">
              <span className="text-amber-300">•</span>
              <span>비용은 변형 개수에만 비례합니다 — 동시성을 올려도 비용은 그대로(시간만 단축).</span>
            </li>
          </ul>
        </section>

        <div className="flex gap-2">
          <Link
            href="/admin/augment"
            className="rounded-2xl border border-cyan-400/30 bg-cyan-500/10 px-4 py-2 text-sm font-semibold text-cyan-200 transition hover:bg-cyan-500/20"
          >
            ← 데이터 증강으로
          </Link>
        </div>
      </div>
    </main>
  );
}
