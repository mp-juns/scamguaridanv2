import { proxyGet } from "../../../../_lib/backend";

export const runtime = "nodejs";

type Context = { params: Promise<{ sessionId: string }> };

export async function GET(_request: Request, context: Context) {
  const { sessionId } = await context.params;
  return proxyGet(`/api/admin/augment/sessions/${encodeURIComponent(sessionId)}`);
}
