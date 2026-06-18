import { proxyGet } from "../../../_lib/backend";

export const runtime = "nodejs";

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const params = new URLSearchParams();
  ["q", "scam_type", "labeled", "limit", "offset"].forEach((key) => {
    const val = searchParams.get(key);
    if (val !== null) params.set(key, val);
  });
  const qs = params.toString();
  return proxyGet(`/api/admin/runs/search${qs ? `?${qs}` : ""}`);
}
