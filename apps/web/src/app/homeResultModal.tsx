import type { AnalysisReport } from "./homeTypes";
import { contentTypeBadge } from "./homeUtils";

type ResultSummaryModalProps = {
  report: AnalysisReport | null;
  open: boolean;
  onClose: () => void;
  onShowDetails: () => void;
  /** 현재 결과가 심층 분석(deep) 결과인지 */
  isDeep?: boolean;
  deepLoading?: boolean;
  onDeepAnalyze?: () => void;
};

export function ResultSummaryModal({
  report,
  open,
  onClose,
  onShowDetails,
  isDeep = false,
  deepLoading = false,
  onDeepAnalyze,
}: ResultSummaryModalProps) {
  if (!report || !open) return null;

  const signalCount = (report.detected_signals ?? []).length;
  const deepRecommended = Boolean(report.deep_recommended) && !isDeep;
  // 신호 0개라도 게이트 저신뢰 등으로 심층 권장이면 초록 단정 금지 → amber
  const reassuring = signalCount === 0 && !deepRecommended;
  const scamCategory = (report.scam_category ?? "").trim();
  const scamTypeDetail = (report.scam_type ?? "").trim();
  // 대표 유형 = scam_category (결정적 매핑). 분류 skip 등으로 비면 기존 scam_type 흐름.
  const displayType = deepRecommended
    ? "추가 확인 필요" // 게이트 normal vs 룰 신호 충돌 — 정상 단정 금지
    : report.is_uncertain || (report.classification_confidence ?? 0) < 0.3
      ? "미분류 (추가 확인)"
      : scamCategory || scamTypeDetail || "미분류";
  const ct = contentTypeBadge(report.content_type);
  const contentLabel = ct?.label ?? report.content_type?.label_ko?.trim();

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center overflow-y-auto bg-[#191f28]/40 p-4 sm:p-6"
      onClick={onClose}
      role="dialog"
      aria-modal="true"
    >
      <div className="my-auto flex w-full max-w-md flex-col" onClick={(event) => event.stopPropagation()}>
        <section className="relative rounded-3xl border border-[#e5e8eb] bg-white p-6 shadow-[0_8px_30px_rgba(0,0,0,0.12)]">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <h2 className="text-lg font-bold text-[#191f28]">분석 결과</h2>
              <span
                className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                  isDeep ? "bg-violet-100 text-violet-700" : "bg-[#f2f4f6] text-[#8b95a1]"
                }`}
              >
                {isDeep ? "🔬 심층 분석" : "간단 분석"}
              </span>
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="닫기"
              className="flex h-8 w-8 items-center justify-center rounded-full text-lg text-[#8b95a1] transition hover:bg-[#f2f4f6]"
            >
              ✕
            </button>
          </div>

          <div
            className={`mt-5 flex items-center gap-4 rounded-2xl border px-4 py-4 ${
              reassuring ? "border-emerald-200 bg-emerald-50" : "border-amber-200 bg-amber-50"
            }`}
          >
            <span
              className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-full text-2xl font-bold ${
                reassuring ? "bg-emerald-100 text-emerald-600" : "bg-amber-100 text-amber-600"
              }`}
            >
              {reassuring ? "✓" : "!"}
            </span>
            <div className="min-w-0">
              <div className="text-base font-bold text-[#191f28]">
                {signalCount > 0
                  ? `위험 신호 ${signalCount}개 검출`
                  : deepRecommended
                    ? "추가 확인이 필요해요"
                    : isDeep
                      ? "위험 신호가 검출되지 않았어요"
                      : "간단 분석에서는 뚜렷한 위험 신호가 발견되지 않았어요"}
              </div>
              <div className="mt-0.5 text-sm text-[#8b95a1]">유형 · {displayType}</div>
            </div>
          </div>

          {scamCategory && scamTypeDetail ? (
            <div className="mt-3 flex items-center justify-between gap-4 rounded-2xl bg-[#f2f4f6] px-4 py-3">
              <span className="text-sm text-[#8b95a1]">세부 유형</span>
              <span className="text-right text-sm font-semibold text-[#191f28]">{scamTypeDetail}</span>
            </div>
          ) : null}

          {contentLabel ? (
            <div className="mt-3 flex items-center justify-between gap-4 rounded-2xl bg-[#f2f4f6] px-4 py-3">
              <span className="text-sm text-[#8b95a1]">콘텐츠 유형</span>
              <span className="text-right text-sm font-semibold text-[#191f28]">
                {ct?.icon ? `${ct.icon} ` : ""}
                {contentLabel}
              </span>
            </div>
          ) : null}

          {report.summary ? (
            <p className="mt-4 text-sm leading-6 text-[#4e5968]">{report.summary}</p>
          ) : null}

          {!isDeep && onDeepAnalyze ? (
            deepRecommended ? (
              // 게이트 normal + 룰 신호 충돌 — 원인 표시 + 강한 권장
              <div className="mt-4 rounded-2xl border-2 border-amber-400 bg-amber-50 px-4 py-4">
                <div className="text-sm font-bold text-amber-900">
                  ⚠️ 심층 분석을 권장합니다
                </div>
                <p className="mt-1 text-xs leading-5 text-amber-800">
                  {report.deep_recommended_reason ||
                    "간단 분석에서 의심 신호가 감지되어 심층 분석을 권장합니다."}
                </p>
                <button
                  type="button"
                  onClick={onDeepAnalyze}
                  disabled={deepLoading}
                  className="mt-3 inline-flex w-full animate-pulse items-center justify-center rounded-xl bg-amber-600 px-4 py-3 text-sm font-bold text-white transition hover:bg-amber-700 disabled:cursor-not-allowed disabled:opacity-60 disabled:animate-none"
                >
                  {deepLoading ? "심층 분석 중... (수십 초 걸릴 수 있어요)" : "🔬 지금 심층 분석 실행"}
                </button>
              </div>
            ) : (
              <div className="mt-4 rounded-2xl border border-violet-200 bg-violet-50 px-4 py-4">
                <div className="text-sm font-semibold text-violet-900">
                  🔬 심층 분석을 실행할까요?
                </div>
                <p className="mt-1 text-xs leading-5 text-violet-700">
                  지금 결과는 빠른 간단 분석이에요. 심층 분석은 내부 라우팅과 무관하게 유형
                  분류·엔티티 추출·AI 보조 검출·외부 교차 검증을 전부 수행합니다 (수십 초 소요).
                </p>
                <button
                  type="button"
                  onClick={onDeepAnalyze}
                  disabled={deepLoading}
                  className="mt-3 inline-flex w-full items-center justify-center rounded-xl bg-violet-600 px-4 py-2.5 text-sm font-semibold text-white transition hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {deepLoading ? "심층 분석 중... (수십 초 걸릴 수 있어요)" : "심층 분석 실행"}
                </button>
              </div>
            )
          ) : null}

          <div className="mt-6 space-y-2">
            <button
              type="button"
              onClick={onShowDetails}
              className="inline-flex w-full items-center justify-center rounded-2xl bg-[#3182f6] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#1b64da]"
            >
              세부사항 보기
            </button>
            <button
              type="button"
              onClick={onClose}
              className="inline-flex w-full items-center justify-center rounded-2xl px-5 py-3 text-sm font-semibold text-[#8b95a1] transition hover:bg-[#f2f4f6]"
            >
              닫기
            </button>
          </div>
        </section>
      </div>
    </div>
  );
}
