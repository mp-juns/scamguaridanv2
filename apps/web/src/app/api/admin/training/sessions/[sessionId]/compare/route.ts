import { proxyJsonRequest } from "../../../../../_lib/backend";

export const runtime = "nodejs";

type Context = { params: Promise<{ sessionId: string }> };

export async function POST(request: Request, context: Context) {
  const { sessionId } = await context.params;
  return proxyJsonRequest(
    request,
    `/api/admin/training/sessions/${encodeURIComponent(sessionId)}/compare`,
  );
}
