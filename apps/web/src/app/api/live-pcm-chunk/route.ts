export const runtime = "nodejs";

const API_BASE_URL = process.env.SCAMGUARDIAN_API_URL ?? "http://127.0.0.1:8000";
const INTERNAL_API_KEY = (process.env.SCAMGUARDIAN_INTERNAL_API_KEY ?? "").trim();

export async function POST(request: Request) {
  const formData = await request.formData();
  const headers: Record<string, string> = {};
  if (INTERNAL_API_KEY) {
    headers["Authorization"] = `Bearer ${INTERNAL_API_KEY}`;
  }
  const upstream = await fetch(`${API_BASE_URL}/api/live-pcm-chunk`, {
    method: "POST",
    body: formData,
    headers,
  });
  const text = await upstream.text();
  return new Response(text, {
    status: upstream.status,
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/json",
      "cache-control": "no-store",
    },
  });
}
