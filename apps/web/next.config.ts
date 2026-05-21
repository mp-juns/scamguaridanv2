import type { NextConfig } from "next";

// Tailscale Funnel 이 / 전체를 Next.js 로 보내므로,
// FastAPI 의 /docs (Swagger) /redoc /openapi.json 을 외부에서 보려면
// 여기서 백엔드로 rewrite. 백엔드는 같은 머신 8000 포트.
const BACKEND_URL = process.env.SCAMGUARDIAN_API_URL || "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  reactCompiler: true,
  allowedDevOrigins: [
    "111.91.153.117",
    "scamguardian.tail7e5dfc.ts.net",
    "scribble-failing-ludicrous.ngrok-free.dev",
    "*.ngrok-free.dev",
    "*.trycloudflare.com",
  ],
  async rewrites() {
    // Next.js 의 /api/{analyze,analyze-upload,admin,result,auth} 는 자체 핸들러가
    // 우선 매칭되므로 (filesystem > rewrites), 아래 rule 은 *Next 에 없는* 백엔드
    // 전용 경로만 직접 프록시한다. Swagger UI 의 "Try it out" 에서도 동작.
    return [
      // Docs UI
      { source: "/docs", destination: `${BACKEND_URL}/docs` },
      { source: "/docs/:path*", destination: `${BACKEND_URL}/docs/:path*` },
      { source: "/redoc", destination: `${BACKEND_URL}/redoc` },
      { source: "/openapi.json", destination: `${BACKEND_URL}/openapi.json` },
      // 백엔드 전용 경로 — Next 핸들러 없는 것들
      { source: "/health", destination: `${BACKEND_URL}/health` },
      { source: "/api/methodology", destination: `${BACKEND_URL}/api/methodology` },
      { source: "/api/v4/:path*", destination: `${BACKEND_URL}/api/v4/:path*` },
      { source: "/webhook/:path*", destination: `${BACKEND_URL}/webhook/:path*` },
    ];
  },
};

export default nextConfig;
