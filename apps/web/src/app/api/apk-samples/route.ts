import { proxyGet } from "../_lib/backend";

export const runtime = "nodejs";

// 테스트용 실제 APK 샘플(무작위 10개) — 백엔드 /api/apk-samples 프록시
export async function GET() {
  return proxyGet("/api/apk-samples");
}
