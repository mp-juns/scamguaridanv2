import { proxyGet } from "../_lib/backend";

export const runtime = "nodejs";

// 동적 분석 VM 가동 상태(LED 용, 읽기 전용) — 백엔드 /api/apk-dynamic-status 프록시
export async function GET() {
  return proxyGet("/api/apk-dynamic-status");
}
