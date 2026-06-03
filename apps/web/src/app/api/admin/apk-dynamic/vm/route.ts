import { proxyGet } from "../../../_lib/backend";

export const runtime = "nodejs";

export async function GET(request: Request) {
  const force = new URL(request.url).searchParams.get("force") === "true";
  return proxyGet(`/api/admin/apk-dynamic/vm${force ? "?force=true" : ""}`);
}
