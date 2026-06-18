import Link from "next/link";

const API_BASE_URL =
  process.env.SCAMGUARDIAN_API_URL ?? "http://127.0.0.1:8000";

type Flag = {
  flag: string;
  label_ko: string;
  rationale: string;
  source: string;
};

type Methodology = {
  flags: Flag[];
  weights: {
    llm_entity_merge_threshold: number;
    llm_flag_detection_confidence_threshold: number;
    llm_scam_type_override_threshold: number;
    classification_threshold: number;
    gliner_threshold: number;
    keyword_boost_weight: number;
  };
  models: Record<string, string>;
};

async function fetchMethodology(): Promise<Methodology | { error: string }> {
  try {
    const resp = await fetch(`${API_BASE_URL}/api/methodology`, {
      next: { revalidate: 600 },
    });
    if (!resp.ok) {
      return { error: `백엔드 응답: HTTP ${resp.status}` };
    }
    return (await resp.json()) as Methodology;
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err) };
  }
}

export const metadata = {
  title: "검출 방법론 — ScamGuardian",
  description: "ScamGuardian의 검출 신호 카탈로그, 근거, 내부 채택 임계값을 설명합니다.",
};

function ThresholdCard({
  label,
  value,
  note,
}: {
  label: string;
  value: number;
  note: string;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/40 p-4">
      <dt className="text-xs font-semibold uppercase tracking-wider text-slate-500">
        {label}
      </dt>
      <dd className="mt-2 font-mono text-lg text-slate-100">{value}</dd>
      <dd className="mt-2 text-xs leading-relaxed text-slate-400">{note}</dd>
    </div>
  );
}

export default async function MethodologyPage() {
  const data = await fetchMethodology();

  if ("error" in data) {
    return (
      <main className="min-h-screen bg-slate-950 px-6 py-10 text-slate-100">
        <div className="mx-auto max-w-3xl rounded-lg border border-red-500/40 bg-red-950/30 p-6">
          <h1 className="text-xl font-bold text-red-200">검출 방법론을 불러올 수 없습니다</h1>
          <p className="mt-2 text-sm text-red-300/80">{data.error}</p>
        </div>
      </main>
    );
  }

  return (
    <main className="min-h-screen bg-slate-950 px-4 py-8 text-slate-100 sm:px-6 sm:py-10">
      <div className="mx-auto w-full max-w-5xl space-y-8">
        <header className="space-y-3">
          <p className="text-sm text-slate-400">ScamGuardian</p>
          <h1 className="text-3xl font-bold text-slate-100">검출 신호 방법론</h1>
          <p className="max-w-3xl text-sm leading-relaxed text-slate-400">
            ScamGuardian은 사기 여부를 판정하지 않고, 입력에서 관찰된 위험 신호와 각 신호의
            학술·법적 근거를 보고합니다. 아래 표는 통합 기업이 자체 정책을 설계할 때 참고할
            수 있는 검출 신호 카탈로그입니다.
          </p>
        </header>

        <section className="rounded-lg border border-slate-800 bg-slate-900/60 p-5">
          <h2 className="text-lg font-semibold text-slate-100">내부 채택 임계값</h2>
          <p className="mt-2 text-sm leading-relaxed text-slate-400">
            이 값들은 모델 출력과 검출 후보를 채택할지 정하는 내부 기준입니다. 사용자에게
            점수나 등급을 제공하기 위한 값이 아닙니다.
          </p>
          <dl className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            <ThresholdCard
              label="LLM 신호 confidence"
              value={data.weights.llm_flag_detection_confidence_threshold}
              note="LLM이 제안한 신호가 이 신뢰도 이상일 때만 검출 신호 후보로 채택됩니다."
            />
            <ThresholdCard
              label="LLM 엔티티 병합"
              value={data.weights.llm_entity_merge_threshold}
              note="LLM 엔티티 제안을 기존 추출 결과와 합칠 때 쓰는 최소 신뢰도입니다."
            />
            <ThresholdCard
              label="유형 추정 override"
              value={data.weights.llm_scam_type_override_threshold}
              note="LLM의 유형 추정이 분류기 출력을 보정할 만큼 충분한지 판단하는 기준입니다."
            />
            <ThresholdCard
              label="분류 confidence"
              value={data.weights.classification_threshold}
              note="mDeBERTa 유형 분류 결과를 내부 파이프라인에서 사용할지 정합니다."
            />
            <ThresholdCard
              label="GLiNER 추출"
              value={data.weights.gliner_threshold}
              note="엔티티 추출 후보의 최소 신뢰도입니다. 재현율을 우선하도록 보수적으로 낮게 둡니다."
            />
            <ThresholdCard
              label="키워드 보정"
              value={data.weights.keyword_boost_weight}
              note="유형 추정이 애매할 때 도메인 키워드 존재를 내부적으로 보정하는 크기입니다."
            />
          </dl>
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900/60 p-5">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h2 className="text-lg font-semibold text-slate-100">
                검출 신호 카탈로그
              </h2>
              <p className="mt-1 text-sm text-slate-400">
                총 {data.flags.length}개 신호. 각 신호는 검출 근거와 출처를 함께 제공합니다.
              </p>
            </div>
            <Link
              href="/evidence"
              className="rounded-md border border-slate-700 px-3 py-2 text-sm text-slate-300 hover:bg-slate-800"
            >
              상세 근거 문서
            </Link>
          </div>

          <div className="mt-5 overflow-x-auto rounded-lg border border-slate-800">
            <table className="w-full text-sm">
              <thead className="bg-slate-800/60 text-xs uppercase tracking-wider text-slate-400">
                <tr>
                  <th className="px-3 py-2 text-left">신호</th>
                  <th className="px-3 py-2 text-left">근거</th>
                  <th className="px-3 py-2 text-left">출처</th>
                </tr>
              </thead>
              <tbody>
                {data.flags.map((flag) => (
                  <tr key={flag.flag} className="border-t border-slate-800 align-top">
                    <td className="w-64 px-3 py-3">
                      <div className="font-semibold text-slate-100">{flag.label_ko}</div>
                      <code className="mt-1 block font-mono text-xs text-slate-500">
                        {flag.flag}
                      </code>
                    </td>
                    <td className="px-3 py-3 text-xs leading-relaxed text-slate-300">
                      {flag.rationale || "근거 설명이 아직 연결되지 않았습니다."}
                    </td>
                    <td className="w-72 px-3 py-3 text-xs leading-relaxed text-slate-500">
                      {flag.source || "출처 미기재"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <section className="rounded-lg border border-slate-800 bg-slate-900/60 p-5">
          <h2 className="text-lg font-semibold text-slate-100">사용 모델</h2>
          <ul className="mt-4 grid gap-2 text-sm sm:grid-cols-2">
            {Object.entries(data.models).map(([key, value]) => (
              <li
                key={key}
                className="flex justify-between gap-4 rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2"
              >
                <span className="text-slate-400">{key}</span>
                <span className="break-all text-right font-mono text-slate-100">{value}</span>
              </li>
            ))}
          </ul>
        </section>

        <footer className="pt-2 text-center text-xs text-slate-500">
          <Link href="/" className="hover:text-slate-300">
            홈으로
          </Link>
        </footer>
      </div>
    </main>
  );
}
