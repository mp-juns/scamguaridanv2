import { proxyGet } from "../../_lib/backend";

export const runtime = "nodejs";

export async function GET() {
  return proxyGet("/api/admin/users");
}
