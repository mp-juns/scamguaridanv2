import type { AnalysisReport } from "./homeTypes";

type SubmitAnalysisParams = {
  source: string;
  uploadFile: File | null;
  skipVerification: boolean;
  useRag: boolean;
  /** 심층 분석 — 게이트 라우팅 무시, 풀 파이프라인(분류·추출·LLM·Serper) 무조건 실행 */
  deep?: boolean;
};

export async function submitAnalysis({
  source,
  uploadFile,
  skipVerification,
  useRag,
  deep = false,
}: SubmitAnalysisParams): Promise<AnalysisReport> {
  const response = uploadFile
    ? await submitUpload(uploadFile, skipVerification, useRag, deep)
    : await submitText(source, skipVerification, useRag, deep);

  const data = (await response.json()) as AnalysisReport | { detail?: string };
  if (!response.ok) {
    const message =
      "detail" in data && typeof data.detail === "string"
        ? data.detail
        : "분석 중 오류가 발생했습니다.";
    throw new Error(message);
  }

  return data as AnalysisReport;
}

async function submitUpload(
  uploadFile: File,
  skipVerification: boolean,
  useRag: boolean,
  deep: boolean,
) {
  const formData = new FormData();
  formData.set("file", uploadFile);
  formData.set("skip_verification", String(skipVerification));
  formData.set("use_llm", "true");
  formData.set("use_rag", String(useRag));
  formData.set("deep", String(deep));
  return await fetch("/api/analyze-upload", {
    method: "POST",
    body: formData,
  });
}

async function submitText(
  source: string,
  skipVerification: boolean,
  useRag: boolean,
  deep: boolean,
) {
  return await fetch("/api/analyze", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      source,
      skip_verification: skipVerification,
      use_llm: true,
      use_rag: useRag,
      deep,
    }),
  });
}
