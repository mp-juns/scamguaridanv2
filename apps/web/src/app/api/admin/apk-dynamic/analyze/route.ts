import { proxyRaw } from "../../../_lib/backend";

export const runtime = "nodejs";

export async function POST(request: Request) {
  // multipart/form-data passthrough — proxyRaw 가 원본 content-type(boundary) + admin 인증 헤더 보존.
  return proxyRaw(request, "/api/admin/apk-dynamic/analyze");
}
