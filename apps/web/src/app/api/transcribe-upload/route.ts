export const runtime = "nodejs";

const API_BASE_URL =
  process.env.SCAMGUARDIAN_API_URL ?? "http://127.0.0.1:8000";

// 백엔드 PlatformMiddleware 가 /api/transcribe-upload 에 API key 강제 — internal proxy 호출 시 자동 첨부.
const INTERNAL_API_KEY = (process.env.SCAMGUARDIAN_INTERNAL_API_KEY ?? "").trim();

function buildUrl(path: string) {
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

export async function POST(request: Request) {
  const formData = await request.formData();
  const headers: Record<string, string> = {};
  if (INTERNAL_API_KEY) {
    headers["Authorization"] = `Bearer ${INTERNAL_API_KEY}`;
  }
  const response = await fetch(buildUrl("/api/transcribe-upload"), {
    method: "POST",
    body: formData,
    headers,
    cache: "no-store",
  });

  const text = await response.text();
  try {
    const json = text ? JSON.parse(text) : {};
    return new Response(JSON.stringify(json), {
      status: response.status,
      headers: {
        "content-type": "application/json",
      },
    });
  } catch {
    return new Response(
      JSON.stringify({
        detail: text || "전사 API 응답을 해석하지 못했습니다.",
      }),
      {
        status: response.status,
        headers: {
          "content-type": "application/json",
        },
      },
    );
  }
}
