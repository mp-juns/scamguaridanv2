import path from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

// Tailscale Funnel 이 / 전체를 Next.js 로 보내므로,
// FastAPI 의 /docs (Swagger) /redoc /openapi.json 을 외부에서 보려면
// 여기서 백엔드로 rewrite. 백엔드는 같은 머신 8000 포트.
const BACKEND_URL = process.env.SCAMGUARDIAN_API_URL || "http://127.0.0.1:8000";

// Next 16 의 next.config.ts 는 ESM 으로 처리됨 — `__dirname` 은 undefined.
// 이전 버전엔 `path.resolve(__dirname)` 으로 root 박았는데 `__dirname=undefined` →
// `path.resolve(undefined)` 가 cwd fallback → Turbopack root 가 `apps/` 로 잘못
// 추론 → tailwindcss resolve 무한 실패 → next-server 메모리·CPU 폭주 → WSL freeze.
// ESM-safe 한 fileURLToPath(import.meta.url) 패턴으로 정확한 디렉토리 결정.
const CONFIG_DIR = path.dirname(fileURLToPath(import.meta.url));

// 검증용 로그 — frontend.log 에 한 번만 찍혀야 정상. 자동 감지 lockfile 위치
// (apps/web/package-lock.json) 와 일치하는지 사람이 직접 눈으로 확인.
console.log("[next.config.ts] turbopack.root =", CONFIG_DIR);

const nextConfig: NextConfig = {
  turbopack: {
    root: CONFIG_DIR,
  },
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
