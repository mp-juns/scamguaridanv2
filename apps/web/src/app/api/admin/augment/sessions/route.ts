import { proxyGet, proxyJsonRequest } from "../../../_lib/backend";

export const runtime = "nodejs";

export async function GET() {
  return proxyGet("/api/admin/augment/sessions");
}

export async function POST(request: Request) {
  return proxyJsonRequest(request, "/api/admin/augment/sessions");
}
