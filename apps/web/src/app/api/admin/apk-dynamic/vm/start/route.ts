import { proxyJsonRequest } from "../../../../_lib/backend";

export const runtime = "nodejs";

export async function POST(request: Request) {
  return proxyJsonRequest(request, "/api/admin/apk-dynamic/vm/start");
}
