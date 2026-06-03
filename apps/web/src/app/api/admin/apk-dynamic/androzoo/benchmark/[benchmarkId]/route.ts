import { proxyGet } from "../../../../../_lib/backend";

export const runtime = "nodejs";

type Context = { params: Promise<{ benchmarkId: string }> };

export async function GET(_request: Request, context: Context) {
  const { benchmarkId } = await context.params;
  return proxyGet(`/api/admin/apk-dynamic/androzoo/benchmark/${encodeURIComponent(benchmarkId)}`);
}
