export const runtime = "nodejs";

const API_BASE_URL =
  process.env.SCAMGUARDIAN_API_URL ?? "http://127.0.0.1:8000";

// 백엔드 PlatformMiddleware 가 /api/analyze-stream 에 API key 강제 — internal proxy 호출 시 자동 첨부.
const INTERNAL_API_KEY = (process.env.SCAMGUARDIAN_INTERNAL_API_KEY ?? "").trim();

export async function POST(request: Request) {
  const formData = await request.formData();
  const headers: Record<string, string> = {};
  if (INTERNAL_API_KEY) {
    headers["Authorization"] = `Bearer ${INTERNAL_API_KEY}`;
  }
  const upstream = await fetch(`${API_BASE_URL}/api/analyze-stream`, {
    method: "POST",
    body: formData,
    headers,
    // @ts-expect-error — Node 의 fetch 는 duplex 가 필요할 수 있음 (스트리밍 응답 통과)
    duplex: "half",
  });

  // 스트리밍 본문을 그대로 통과 — buffer 하지 않음
  return new Response(upstream.body, {
    status: upstream.status,
    headers: {
      "content-type":
        upstream.headers.get("content-type") ?? "application/x-ndjson",
      "cache-control": "no-store",
      "x-accel-buffering": "no",
    },
  });
}
