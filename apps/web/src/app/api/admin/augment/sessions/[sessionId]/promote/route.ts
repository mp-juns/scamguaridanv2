import { proxyJsonRequest } from "../../../../../_lib/backend";

export const runtime = "nodejs";

type Context = { params: Promise<{ sessionId: string }> };

export async function POST(request: Request, context: Context) {
  const { sessionId } = await context.params;
  const target = new URL(request.url).searchParams.get("target");
  const query = target ? `?target=${encodeURIComponent(target)}` : "";
  return proxyJsonRequest(
    request,
    `/api/admin/augment/sessions/${encodeURIComponent(sessionId)}/promote${query}`,
  );
}
