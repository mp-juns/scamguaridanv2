import { proxyJsonRequest } from "../../../../_lib/backend";

export const runtime = "nodejs";

type Context = { params: Promise<{ idx: string }> };

export async function DELETE(request: Request, context: Context) {
  const { idx } = await context.params;
  return proxyJsonRequest(
    request,
    `/api/admin/augment/seeds/${encodeURIComponent(idx)}`,
  );
}
