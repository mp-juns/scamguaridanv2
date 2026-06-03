import { proxyGet } from "../../../../_lib/backend";

export const runtime = "nodejs";

type Context = { params: Promise<{ jobId: string }> };

export async function GET(_request: Request, context: Context) {
  const { jobId } = await context.params;
  return proxyGet(`/api/admin/apk-dynamic/jobs/${encodeURIComponent(jobId)}`);
}
