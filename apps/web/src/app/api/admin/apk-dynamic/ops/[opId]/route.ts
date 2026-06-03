import { proxyGet } from "../../../../_lib/backend";

export const runtime = "nodejs";

type Context = { params: Promise<{ opId: string }> };

export async function GET(_request: Request, context: Context) {
  const { opId } = await context.params;
  return proxyGet(`/api/admin/apk-dynamic/ops/${encodeURIComponent(opId)}`);
}
