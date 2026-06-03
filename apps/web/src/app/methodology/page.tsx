import Link from "next/link";

const API_BASE_URL =
  process.env.SCAMGUARDIAN_API_URL ?? "http://127.0.0.1:8000";

type Flag = {
  flag: string;
  label_ko: string;
  score_delta: number;
  rationale: string;
  source: string;
};

type RiskBand = {
  min: number;
  max: number;
  level: string;
  description: string;
};

type Methodology = {
  flags: Flag[];
  risk_bands: RiskBand[];
  weights: {
    llm_flag_score_ratio: number;
    llm_entity_merge_threshold: number;
    llm_flag_score_threshold: number;
    llm_scam_type_override_threshold: number;
    classification_threshold: number;
    gliner_threshold: number;
    keyword_boost_weight: number;
  };
  models: Record<string, string>;
};

const RISK_BAND_COLORS: Record<string, string> = {
  "매우 위험": "bg-red-700/30 border-red-500 text-red-200",
  "위험": "bg-orange-700/30 border-orange-500 text-orange-200",
  "주의": "bg-yellow-700/30 border-yellow-500 text-yellow-200",
  "안전": "bg-emerald-700/30 border-emerald-500 text-emerald-200",
};

function CitationGroup({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-3 text-sm font-semibold uppercase tracking-wider text-slate-300">
        {title}
      </h3>
      <div className="space-y-3">{children}</div>
    </div>
  );
}

function CitationCard({
  title,
  meta,
  cited,
  why,
  applied,
}: {
  title: string;
  meta: string;
  cited: string;
  why: string;
  applied: { flag: string; note: string }[];
}) {
  return (
    <div className="rounded-xl border border-slate-700/60 bg-slate-950/40 p-4">
      <div className="mb-1 text-sm font-semibold text-slate-100">{title}</div>
      <div className="mb-3 text-xs text-slate-500">{meta}</div>
      <div className="mb-2 grid gap-2 sm:grid-cols-2 text-xs">
        <div className="rounded-lg border border-cyan-400/20 bg-cyan-500/5 p-2">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-cyan-300">인용한 부분</div>
          <div className="mt-1 leading-relaxed text-slate-300">{cited}</div>
        </div>
        <div className="rounded-lg border border-fuchsia-400/20 bg-fuchsia-500/5 p-2">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-fuchsia-300">왜 인용</div>
          <div className="mt-1 leading-relaxed text-slate-300">{why}</div>
        </div>
      </div>
      <div className="rounded-lg border border-emerald-400/20 bg-emerald-500/5 p-2">
        <div className="text-[10px] font-semibold uppercase tracking-wider text-emerald-300">적용 위치 (플래그 → 점수/임계값)</div>
        <ul className="mt-2 space-y-1.5 text-xs">
          {applied.map((a, i) => (
            <li key={i} className="flex flex-wrap items-baseline gap-2">
              <code className="rounded bg-slate-900 px-2 py-0.5 font-mono text-[11px] text-slate-200">
                {a.flag}
              </code>
              <span className="text-slate-400">{a.note}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}


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
  title: "점수 산정 방식 — ScamGuardian",
  description: "위험도 점수 합산식, 등급 기준, 플래그별 정당성과 출처를 설명합니다.",
};

export default async function MethodologyPage() {
  const data = await fetchMethodology();

  if ("error" in data) {
    return (
      <main className="min-h-screen bg-[radial-gradient(circle_at_top,#111827_0%,#020617_60%,#000000_100%)] px-6 py-10 text-slate-100">
        <div className="mx-auto max-w-3xl rounded-2xl border border-red-500/40 bg-red-950/30 p-6">
          <h1 className="text-xl font-bold text-red-200">점수 기준을 불러올 수 없습니다</h1>
          <p className="mt-2 text-sm text-red-300/80">{data.error}</p>
        </div>
      </main>
    );
  }

  const positive = data.flags.filter((f) => f.score_delta > 0);
  const negative = data.flags.filter((f) => f.score_delta < 0);
  // Identity Boundary — 백엔드가 risk_bands(등급)를 더 이상 노출하지 않을 수 있음. 없으면 섹션 숨김(빌드 prerender 크래시 방지).
  const riskBands = data.risk_bands ?? [];

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,#111827_0%,#020617_60%,#000000_100%)] px-4 py-8 text-slate-100 sm:px-6 sm:py-10">
      <div className="mx-auto w-full max-w-4xl space-y-8">
        <header className="space-y-2">
          <p className="text-sm text-slate-400">ScamGuardian</p>
          <h1 className="text-3xl font-bold text-slate-100">📊 위험도 점수 산정 방식</h1>
          <p className="max-w-2xl text-sm leading-relaxed text-slate-400">
            ScamGuardian 은 발화·텍스트에서 사기 신호(플래그)를 탐지하고, 각 플래그에 사전 정의된 점수를 합산해 0~100+ 점의 위험도를 산출합니다.
            아래에서 각 플래그의 점수, 점수의 정당성·출처, 그리고 LLM 보조 가중치 같은 설계 결정을 확인할 수 있습니다.
          </p>
        </header>

        <section className="rounded-2xl border border-slate-700 bg-slate-900/60 p-6">
          <h2 className="mb-3 text-lg font-semibold text-slate-100">합산식</h2>
          <div className="rounded bg-slate-950/60 p-4 font-mono text-sm leading-relaxed text-slate-200">
            <div>총점 = Σ (규칙 기반 플래그 점수) + Σ (LLM 보조 플래그 점수 × {data.weights.llm_flag_score_ratio})</div>
          </div>
          <p className="mt-3 text-sm text-slate-400">
            LLM(Claude) 이 자체적으로 추가 제안한 플래그는 가중치 <span className="text-slate-200">{data.weights.llm_flag_score_ratio}</span> 가 곱해져 절반만 반영됩니다.
            맹신을 막기 위한 보수적 설계입니다.
          </p>
        </section>

        {riskBands.length > 0 ? (
        <section className="rounded-2xl border border-slate-700 bg-slate-900/60 p-6">
          <h2 className="mb-3 text-lg font-semibold text-slate-100">위험도 등급</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            {riskBands.map((band) => (
              <div
                key={band.level}
                className={`rounded-xl border px-4 py-3 ${RISK_BAND_COLORS[band.level] ?? "bg-slate-700/30 border-slate-500 text-slate-200"}`}
              >
                <div className="font-mono text-xs opacity-70">
                  {band.min}~{band.max}점
                </div>
                <div className="mt-1 text-lg font-semibold">{band.level}</div>
                <div className="mt-1 text-xs opacity-80">{band.description}</div>
              </div>
            ))}
          </div>
        </section>
        ) : null}

        <section className="rounded-2xl border border-slate-700 bg-slate-900/60 p-6">
          <h2 className="mb-1 text-lg font-semibold text-slate-100">
            가산 플래그 ({positive.length}개)
          </h2>
          <p className="mb-4 text-sm text-slate-400">
            발견되면 위험 점수에 가산됩니다. 점수가 높을수록 사기 확신도가 큰 신호입니다.
          </p>
          <div className="overflow-x-auto rounded-lg border border-slate-700">
            <table className="w-full text-sm">
              <thead className="bg-slate-800/60 text-xs uppercase tracking-wider text-slate-400">
                <tr>
                  <th className="px-3 py-2 text-left">플래그</th>
                  <th className="px-3 py-2 text-right">점수</th>
                  <th className="px-3 py-2 text-left">정당성</th>
                  <th className="px-3 py-2 text-left">출처</th>
                </tr>
              </thead>
              <tbody>
                {positive.map((f) => (
                  <tr key={f.flag} className="border-t border-slate-800 align-top">
                    <td className="px-3 py-3">
                      <div className="font-semibold text-slate-100">{f.label_ko}</div>
                      <div className="font-mono text-xs text-slate-500">{f.flag}</div>
                    </td>
                    <td className="px-3 py-3 text-right font-mono text-red-300">
                      +{f.score_delta}
                    </td>
                    <td className="px-3 py-3 text-xs text-slate-300">{f.rationale}</td>
                    <td className="px-3 py-3 text-xs text-slate-500">{f.source}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        {negative.length > 0 && (
          <section className="rounded-2xl border border-slate-700 bg-slate-900/60 p-6">
            <h2 className="mb-1 text-lg font-semibold text-slate-100">
              감산 플래그 ({negative.length}개)
            </h2>
            <p className="mb-4 text-sm text-slate-400">
              교차 검증에서 신뢰 신호가 발견되면 위험 점수가 감산됩니다.
            </p>
            <div className="overflow-x-auto rounded-lg border border-slate-700">
              <table className="w-full text-sm">
                <thead className="bg-slate-800/60 text-xs uppercase tracking-wider text-slate-400">
                  <tr>
                    <th className="px-3 py-2 text-left">플래그</th>
                    <th className="px-3 py-2 text-right">점수</th>
                    <th className="px-3 py-2 text-left">정당성</th>
                    <th className="px-3 py-2 text-left">출처</th>
                  </tr>
                </thead>
                <tbody>
                  {negative.map((f) => (
                    <tr key={f.flag} className="border-t border-slate-800 align-top">
                      <td className="px-3 py-3">
                        <div className="font-semibold text-slate-100">{f.label_ko}</div>
                        <div className="font-mono text-xs text-slate-500">{f.flag}</div>
                      </td>
                      <td className="px-3 py-3 text-right font-mono text-emerald-300">
                        {f.score_delta}
                      </td>
                      <td className="px-3 py-3 text-xs text-slate-300">{f.rationale}</td>
                      <td className="px-3 py-3 text-xs text-slate-500">{f.source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}

        <section className="rounded-2xl border border-slate-700 bg-slate-900/60 p-6">
          <h2 className="mb-3 text-lg font-semibold text-slate-100">설계 결정 (Threshold &amp; Weight)</h2>
          <dl className="grid gap-3 text-sm sm:grid-cols-2">
            <div className="rounded bg-slate-950/40 p-3">
              <dt className="text-xs text-slate-400">LLM 플래그 가중치</dt>
              <dd className="mt-1 font-mono text-slate-100">
                {data.weights.llm_flag_score_ratio}
              </dd>
              <dd className="mt-1 text-xs text-slate-500">
                LLM 제안 플래그 점수에 곱해지는 비율. 1.0 미만이면 보수적.
              </dd>
            </div>
            <div className="rounded bg-slate-950/40 p-3">
              <dt className="text-xs text-slate-400">LLM 엔티티 병합 임계값</dt>
              <dd className="mt-1 font-mono text-slate-100">
                {data.weights.llm_entity_merge_threshold}
              </dd>
              <dd className="mt-1 text-xs text-slate-500">
                이 신뢰도 이상의 LLM 엔티티만 추출 결과에 합쳐집니다.
              </dd>
            </div>
            <div className="rounded bg-slate-950/40 p-3">
              <dt className="text-xs text-slate-400">LLM 플래그 신뢰 임계값</dt>
              <dd className="mt-1 font-mono text-slate-100">
                {data.weights.llm_flag_score_threshold}
              </dd>
              <dd className="mt-1 text-xs text-slate-500">
                이 신뢰도 이상이어야 LLM 제안 플래그가 채택됩니다.
              </dd>
            </div>
            <div className="rounded bg-slate-950/40 p-3">
              <dt className="text-xs text-slate-400">LLM 스캠 유형 오버라이드 임계값</dt>
              <dd className="mt-1 font-mono text-slate-100">
                {data.weights.llm_scam_type_override_threshold}
              </dd>
              <dd className="mt-1 text-xs text-slate-500">
                LLM 신뢰도가 이 이상이면 분류기 결과를 덮어씁니다.
              </dd>
            </div>
            <div className="rounded bg-slate-950/40 p-3">
              <dt className="text-xs text-slate-400">분류기 confidence 컷오프</dt>
              <dd className="mt-1 font-mono text-slate-100">
                {data.weights.classification_threshold}
              </dd>
              <dd className="mt-1 text-xs text-slate-500">
                mDeBERTa 분류 신뢰도가 이 이하면 &ldquo;판별 불가&rdquo;.
              </dd>
            </div>
            <div className="rounded bg-slate-950/40 p-3">
              <dt className="text-xs text-slate-400">GLiNER 추출 임계값</dt>
              <dd className="mt-1 font-mono text-slate-100">
                {data.weights.gliner_threshold}
              </dd>
              <dd className="mt-1 text-xs text-slate-500">
                재현율 우선(미탐 방지)으로 낮게 설정.
              </dd>
            </div>
          </dl>
        </section>

        <section className="rounded-2xl border border-slate-700 bg-slate-900/60 p-6">
          <h2 className="mb-2 text-lg font-semibold text-slate-100">📚 인용 학술·공식 출처 — 어떻게 활용했나</h2>
          <p className="mb-5 text-sm text-slate-400">
            각 자료를 단순 나열하지 않고, <strong className="text-slate-200">논문의 어떤 부분</strong>을 <strong className="text-slate-200">왜 인용</strong>했고
            ScamGuardian 의 <strong className="text-slate-200">어느 플래그·점수·임계값</strong>에 어떻게 매핑됐는지 함께 적었습니다.
            플래그 코드는 클릭 후 위 표에서 검색하시면 점수와 정당성을 같이 보실 수 있어요.
          </p>

          <div className="space-y-6">
            <CitationGroup title="🧠 설득·사회공학 심리 (사기범이 어떻게 사람을 속이나)">
              <CitationCard
                title="Influence, New and Expanded: The Psychology of Persuasion"
                meta="Cialdini, R. B. (2021). Harper Business."
                cited="6대 영향력 원리 — 권위(Authority) · 희소성(Scarcity) · 사회적 증거(Social Proof) · 호감(Liking) · 일관성(Commitment) · 상호성(Reciprocity)"
                why="사기범 설득 전략을 체계적으로 분류·진단하는 기본 프레임. 각 플래그가 어느 원리를 악용하는지 매핑하면 점수 책정의 일관성을 확보할 수 있다."
                applied={[
                  { flag: "fake_government_agency", note: "Authority 원리 — 권위 사칭은 가장 강한 신호 → +25" },
                  { flag: "fake_certification", note: "Authority — 위조 인증마크 → +20" },
                  { flag: "ceo_name_mismatch", note: "Authority — 권위 일관성 깨짐 → +15" },
                  { flag: "urgent_transfer_demand", note: "Scarcity — 시간 압박 → +20" },
                  { flag: "medical_claim_unverified", note: "Social Proof — 가짜 후기 → +20" },
                  { flag: "impersonation_family", note: "Liking — 친밀 관계 사칭 → +20" },
                  { flag: "query_c_scam_pattern_found", note: "Social Proof — 동일 패턴 사례 발견 → +15" },
                ]}
              />

              <CitationCard
                title="The Scammers Persuasive Techniques Model"
                meta="Whitty, M. T. (2013). British Journal of Criminology, 53(4), 665–684."
                cited="로맨스·투자 사기의 4단계 모델 — Profile(매력적 신원 위장) → Authority cue(전문성 신호) → Visceral Influence(감정 자극) → Ask(요구)"
                why="단일 신호가 아니라 단계적 흐름으로 사기를 인식해야 정확. '그 단계에서 등장하는 표지'를 플래그로 분해할 수 있다."
                applied={[
                  { flag: "romance_foreign_identity", note: "Profile 단계 — 해외 군인·의사·외교관 신원 패턴 → +15" },
                  { flag: "fake_certification", note: "Authority cue 단계 → +20" },
                  { flag: "urgent_transfer_demand", note: "Visceral Influence 단계 → +20" },
                  { flag: "impersonation_family", note: "감정 조작 흐름 → +20" },
                ]}
              />

              <CitationCard
                title="The online romance scam: a serious cybercrime"
                meta="Whitty, M. T., & Buchanan, T. (2012). Cyberpsychology, Behavior, and Social Networking, 15(3), 181–183."
                cited="로맨스 스캠 피해자의 심리적 손상은 금전 손실 못지않게 크고, 신원 사칭은 단독으로는 의심받지 않아 다른 신호와 결합돼야 함을 실증."
                why="해외 신분 사칭 단독 점수를 보수적으로 책정한 근거 — 다른 단서(송금 요구, 만남 회피 등) 와 결합 시에만 결정적."
                applied={[
                  { flag: "romance_foreign_identity", note: "단독 +15 (낮음) — 결합 시 위험" },
                ]}
              />

              <CitationCard
                title="Understanding scam victims: Seven principles for systems security"
                meta="Stajano, F., & Wilson, P. (2011). Communications of the ACM, 54(3), 70–75."
                cited="피해자가 사기를 인식하지 못하게 하는 7원칙 — Distraction · Social Compliance · Herd · Dishonesty · Kindness · Need and Greed · Time"
                why="사기범 입장이 아닌 피해자 인지 편향 관점 — '왜 합리적 사람도 당하나' 의 메커니즘. 사용자에게 보여줄 정당성 텍스트의 출처."
                applied={[
                  { flag: "business_not_registered", note: "Distraction — 위장된 정상성 → +20" },
                  { flag: "fake_escrow_bypass", note: "Distraction — 정상 절차 무력화 → +15" },
                  { flag: "prepayment_requested", note: "Need and Greed — 절박 표적 → +20" },
                  { flag: "job_deposit_requested", note: "Need and Greed — 구직 절박 → +20" },
                  { flag: "urgent_transfer_demand", note: "Time — 시간 압박 → +20" },
                ]}
              />

              <CitationCard
                title="Scam Compliance and the Psychology of Persuasion"
                meta="Modic, D., & Lea, S. E. G. (2013). SSRN."
                cited="권위·긴급성·희소성이 결합될 때 응답률이 단일 신호 합 이상으로 비선형 상승함을 실증한 회귀 분석."
                why="우리 스코어러가 단일 플래그 점수를 단순 합산하는 설계의 정당화 — 결합 효과는 자연스럽게 합산식으로도 표현되며, 단일 플래그 가중치를 너무 낮추면 결합 신호도 약화된다."
                applied={[
                  { flag: "(전체 SCORING_RULES 합산식)", note: "단일 플래그 직선 합산 — 결합은 자연 반영" },
                ]}
              />

              <CitationCard
                title="Out of control: Visceral influences on behavior"
                meta="Loewenstein, G. (1996). Organizational Behavior and Human Decision Processes, 65(3), 272–292."
                cited="hot–cold empathy gap — 감정 흥분 상태(분노·공포·다급함)에서 합리적 의사결정 능력이 일시적으로 마비된다는 행동경제학 핵심 발견."
                why="긴급성·협박 발화가 단순한 텍스트 신호가 아니라 *판단 마비* 를 유도하는 결정적 위험 신호인 이유. 점수 가중 정당화."
                applied={[
                  { flag: "urgent_transfer_demand", note: "hot state 유도 → +20" },
                  { flag: "threat_or_coercion", note: "공포 유도 + 마비 → +25" },
                ]}
              />

              <CitationCard
                title="Putting the fear back into fear appeals: The Extended Parallel Process Model"
                meta="Witte, K. (1992). Communication Monographs, 59(4), 329–349."
                cited="EPPM — 공포(fear appeal) 메시지가 효능감 인식과 결합될 때 강제 행동 반응을 유발하는 심리 모델."
                why="협박형 사기에서 '돈 보내야 끝난다' 라는 효능감 표현과 공포가 결합되면 정상 판단이 가장 깊게 마비되는 구조 설명."
                applied={[
                  { flag: "threat_or_coercion", note: "공포+효능감 결합 → +25 (단일 플래그 최고)" },
                ]}
              />

              <CitationCard
                title="Social Engineering: The Science of Human Hacking (2nd ed.)"
                meta="Hadnagy, C. (2018). Wiley."
                cited="OSINT 수집·pretexting·정보 추출 단계의 표준 패턴. 민감정보(주민번호·OTP·카드정보) 요구는 사회공학의 가장 확정적 후반 단계."
                why="개인정보 요구가 왜 결정적 단서인지 — 정상 기관은 절대 묻지 않는 항목 리스트의 기준."
                applied={[
                  { flag: "personal_info_request", note: "민감정보 요구 → +20" },
                ]}
              />

              <CitationCard
                title="Security Engineering (2nd ed.) — Ch.2 사용자 보안 행동"
                meta="Anderson, R. (2008). Wiley."
                cited="베이지안 사전확률 — 동일 식별자(전화번호·계좌·도메인) 가 신고 이력이 있을 때 재범 확률이 비조건부 확률보다 훨씬 높다는 보안공학 원칙."
                why="신고 DB 매칭이 단순 인덱싱이 아니라 강한 사전확률 신호인 이유. 단일 플래그로 +25 까지 부여 가능한 정당화."
                applied={[
                  { flag: "phone_scam_reported", note: "재범 확률 사전확률 → +25" },
                  { flag: "account_scam_reported", note: "동일 원리 → +25" },
                  { flag: "website_scam_reported", note: "도메인 재범률 → +20" },
                ]}
              />
            </CitationGroup>

            <CitationGroup title="💸 금융사기·암호자산 사기 도메인 연구">
              <CitationCard
                title="The Ponzi Scheme Puzzle"
                meta="Frankel, T. (2012). Oxford University Press."
                cited="폰지 사기의 구조적 특징 — 보장형 + 비현실적 고수익 + 신규 자본 의존. 정상 펀드 장기 평균 수익률(연 5~10%) 와의 정량적 차이."
                why="'연 20% 이상 보장' 이 자본시장법 위반 신호인 정량적 근거 — 학생 라벨러도 임의 임계값이 아님을 이해할 수 있도록."
                applied={[
                  { flag: "abnormal_return_rate", note: "연 20%+ 수익 보장 → +15" },
                ]}
              />

              <CitationCard
                title="Romance fraud and pig butchering"
                meta="Cross, C. (2023). Trends & Issues in Crime and Criminal Justice. Australian Institute of Criminology."
                cited="pig butchering(殺豬盤) 의 단계 — 신뢰 형성(로맨스/투자 친근감) → 가짜 거래소 가입 유도 → 미등록 플랫폼에 자금 이체 → 출금 차단."
                why="'가짜 거래소' 라는 추상 개념이 어떻게 코인 사기의 결정 단계인지 설명. 신원 사칭만으로는 약하지만 거래소 신호와 결합 시 결정적."
                applied={[
                  { flag: "fake_exchange", note: "미등록 거래소 유도 → +20" },
                  { flag: "romance_foreign_identity", note: "신뢰 형성 단계와 함께 → +15" },
                ]}
              />

              <CitationCard
                title="FBI IC3 Annual Internet Crime Report"
                meta="Federal Bureau of Investigation (annual)."
                cited="연간 사기 유형별 신고 건수·피해액 글로벌 통계. 2023년 로맨스 스캠 피해 6.5억 USD, 암호화폐 사기 39억 USD."
                why="국가별 차이 보정·정량 근거. 로맨스/코인 사기 점수가 보수적이지만 결합 시 위험 등급 직행해야 하는 이유."
                applied={[
                  { flag: "romance_foreign_identity", note: "+15 (단독) + 결합 시 위험" },
                  { flag: "fake_exchange", note: "+20" },
                ]}
              />

              <CitationCard
                title="Consumer Sentinel Network Data Book"
                meta="Federal Trade Commission (annual)."
                cited="피해 유형 카테고리화·연령대별 분포·평균 피해액 통계."
                why="국내 공식 통계(금감원·경찰청) 와 교차 검증해 점수 분포의 합리성 점검."
                applied={[
                  { flag: "(전체 점수 분포 검증)", note: "교차 검증용 baseline" },
                ]}
              />
            </CitationGroup>

            <CitationGroup title="🤖 NLP·임베딩 기반 분석 기법">
              <CitationCard
                title="Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks"
                meta="Reimers, N., & Gurevych, I. (2019). EMNLP."
                cited="문장 단위 의미 임베딩과 코사인 유사도 측정 방법. 발화의 의미를 768차원 벡터로 압축해 직접 비교 가능."
                why="발화자 자기소개와 발화 내용이 의미적으로 일치하는지 판단하는 자동화 기법의 이론적 근거. RAG(유사 사례 검색) 의 백본."
                applied={[
                  { flag: "authority_context_mismatch", note: "임베딩 코사인 < 임계 → +15" },
                  { flag: "authority_context_uncertain", note: "경계선상 → +5" },
                  { flag: "(rag.py)", note: "유사 사례 검색 — LLM prior 보강" },
                ]}
              />

              <CitationCard
                title="SemEval-2017 Task 1: Semantic Textual Similarity"
                meta="Cer, D. et al. (2017). SemEval."
                cited="다국어 의미 유사도 벤치마크 — 한국어 포함 임베딩 모델의 평가 기준."
                why="우리 SBERT 모델 선택(`paraphrase-multilingual-MiniLM-L12-v2`) 의 성능 검증 baseline."
                applied={[
                  { flag: "(SBERT 모델 선정)", note: "다국어 STS 성능 기준" },
                ]}
              />
            </CitationGroup>

            <CitationGroup title="🛡 사이버보안·악성코드 표준">
              <CitationCard
                title="NIST SP 800-83: Guide to Malware Incident Prevention and Handling"
                meta="National Institute of Standards and Technology."
                cited="다중 안티바이러스 엔진 합의(consensus) 가 단일 엔진 탐지보다 신뢰도 높음. 3+ 엔진 탐지 시 사실상 확정."
                why="VirusTotal 의 70+ 엔진 중 3+ 가 악성 판정 시 즉시 '매우 위험' 등급 직행하는 점수 80 의 정당화."
                applied={[
                  { flag: "malware_detected", note: "VT 다중 엔진 악성 → +80 (단독 매우 위험)" },
                ]}
              />

              <CitationCard
                title="APWG Phishing Activity Trends Report"
                meta="Anti-Phishing Working Group (분기 발행)."
                cited="분기별 신생 피싱 도메인·SMS phishing 비율·재범 도메인 통계. 2022 이후 SMS phishing 이 이메일 피싱을 능가."
                why="피싱 URL 신호의 정량 근거 + 스미싱 점수 책정. 신생 도메인의 재범률(80%+) 도 같은 출처."
                applied={[
                  { flag: "phishing_url_confirmed", note: "VT URL 다중 탐지 → +75" },
                  { flag: "smishing_link_detected", note: "SMS 단축 URL → +20" },
                  { flag: "website_scam_reported", note: "재범 도메인 → +20" },
                ]}
              />

              <CitationCard
                title="Google Safe Browsing Transparency Report"
                meta="Google (continuous)."
                cited="신뢰 도메인 평판 점수 + 피싱 도메인 자동 분류 결과 공개."
                why="VT 와 함께 URL 안전성 신호의 다중 출처 합의. 단일 신호 의존 회피."
                applied={[
                  { flag: "phishing_url_confirmed", note: "VT URL Scan 의 보조 신호로" },
                ]}
              />
            </CitationGroup>

            <CitationGroup title="📋 국내 공식 통계·법령 (현행 법 + 통계)">
              <CitationCard
                title="금융감독원 보이스피싱·유사수신 감독사례집 / 메신저피싱 통계"
                meta="금융감독원 (연간)."
                cited="국내 사기 사례 직접 수집 — 발화 패턴, 피해 규모, 가해자 행동 단계."
                why="모든 점수 책정의 1차 국내 baseline. 학술 인용 없이도 점수가 임의가 아님을 증명하는 가장 강한 출처."
                applied={[
                  { flag: "abnormal_return_rate, ceo_name_mismatch, fss_not_registered, account_scam_reported, impersonation_family", note: "직접 매핑" },
                ]}
              />

              <CitationCard
                title="경찰청 사이버수사국 / KISA 보이스피싱·스미싱 동향 보고서"
                meta="경찰청, 한국인터넷진흥원 (연간)."
                cited="국내 신고·차단 통계, 행위 분석, 신고 번호 재범률."
                why="국내 사용자 보호 관점의 통계 — 학술 자료가 다루지 못하는 한국 특수 패턴(메신저피싱 가족 사칭 등) 보강."
                applied={[
                  { flag: "phone_scam_reported, urgent_transfer_demand, smishing_link_detected, threat_or_coercion, fake_escrow_bypass", note: "직접 매핑" },
                ]}
              />

              <CitationCard
                title="자본시장법 / 약사법 / 직업안정법 / 대부업법 / 통신사기피해환급법"
                meta="대한민국 현행 법령."
                cited="법적 위반 행위의 명확한 정의 — '미등록 투자권유', '미인증 의료 효능 광고', '취업 명목 선납' 등."
                why="플래그가 단순 휴리스틱이 아니라 *법적으로 위반인 행위* 임을 명시 — 사용자에게 '왜 위험한가' 의 가장 명확한 답."
                applied={[
                  { flag: "fss_not_registered, medical_claim_unverified, job_deposit_requested, prepayment_requested, account_scam_reported", note: "법령 위반 표지" },
                ]}
              />

              <CitationCard
                title="SNU FactCheck / IFCN Code of Principles"
                meta="서울대 팩트체크센터 / International Fact-Checking Network."
                cited="독립 팩트체크 기관의 검증 프로세스 표준 + 한국 정치·금융 팩트체크 결과 DB."
                why="외부 신뢰 출처 보정 — 팩트체크에서 '사실 확인' 된 케이스는 위험 점수 차감, '의심' 인 케이스는 가산."
                applied={[
                  { flag: "query_b_factcheck_found", note: "팩트체크 의심 단서 → +25" },
                  { flag: "query_b_confirmed", note: "사실 확인 → −15 (감산)" },
                ]}
              />
            </CitationGroup>
          </div>
        </section>

        <section className="rounded-2xl border border-slate-700 bg-slate-900/60 p-6">
          <h2 className="mb-3 text-lg font-semibold text-slate-100">사용 모델</h2>
          <ul className="space-y-2 text-sm">
            {Object.entries(data.models).map(([k, v]) => (
              <li key={k} className="flex justify-between rounded bg-slate-950/40 px-3 py-2">
                <span className="text-slate-400">{k}</span>
                <span className="font-mono text-slate-100">{v}</span>
              </li>
            ))}
          </ul>
        </section>

        <footer className="pt-2 text-center text-xs text-slate-500">
          <Link href="/" className="hover:text-slate-300">
            ← 홈으로
          </Link>
        </footer>
      </div>
    </main>
  );
}
