import { NextResponse } from "next/server";

import { auth } from "../../../auth";

export const runtime = "nodejs";

const API_BASE_URL =
  process.env.SCAMGUARDIAN_API_URL ?? "http://127.0.0.1:8000";

const ADMIN_AUTH_DISABLED = ["1", "true", "yes", "on"].includes(
  (process.env.ADMIN_AUTH_DISABLED ?? "").toLowerCase(),
);

function buildUrl(path: string) {
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

function errorToMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  try {
    return JSON.stringify(error);
  } catch {
    return String(error);
  }
}

function parseJsonSafely(text: string) {
  if (!text) {
    return {};
  }

  try {
    return JSON.parse(text);
  } catch {
    return { detail: text };
  }
}

function isAdminPath(path: string) {
  return path.startsWith("/api/admin/");
}

/**
 * 백엔드 `/api/analyze` 와 `/api/analyze-upload` 는 PlatformMiddleware 가
 * API key 강제. Next.js 가 internal proxy 로 호출할 때만 자동 첨부.
 *
 * env: `SCAMGUARDIAN_INTERNAL_API_KEY=sg_...` (없으면 백엔드가 401 반환)
 */
const INTERNAL_API_KEY = (process.env.SCAMGUARDIAN_INTERNAL_API_KEY ?? "").trim();

function isAnalyzePath(path: string) {
  return path === "/api/analyze" || path === "/api/analyze-upload";
}

/**
 * 어드민 경로일 때 세션 검증 후 서버 env 의 SCAMGUARDIAN_ADMIN_TOKEN 을
 * X-Admin-Token 헤더로 백엔드에 forward.
 *
 * 반환:
 * - { ok: true, headers }  — 통과
 * - { ok: false, response } — 401/500 응답 (호출자는 그대로 return)
 */
export async function adminAuthHeader(): Promise<
  | { ok: true; headers: Record<string, string> }
  | { ok: false; response: NextResponse }
> {
  if (ADMIN_AUTH_DISABLED) {
    // 개발 모드 — 백엔드도 ADMIN_AUTH_DISABLED 켜야 통과 (둘이 짝).
    return { ok: true, headers: {} };
  }
  // 세션 존재 = signIn 게이트(백엔드 master+DB) 통과 = 승인됨. allowlist 재확인 불필요.
  const session = await auth();
  const email = session?.user?.email?.toLowerCase();
  if (!email) {
    return {
      ok: false,
      response: NextResponse.json(
        { detail: "어드민 인증이 필요합니다.", code: "admin_unauthorized" },
        { status: 401 },
      ),
    };
  }
  const adminToken = process.env.SCAMGUARDIAN_ADMIN_TOKEN;
  if (!adminToken) {
    return {
      ok: false,
      response: NextResponse.json(
        {
          detail:
            "SCAMGUARDIAN_ADMIN_TOKEN 이 서버에 설정되지 않았습니다 (.env.local 확인).",
          code: "admin_token_missing",
        },
        { status: 500 },
      ),
    };
  }
  // X-Admin-Email 로 백엔드가 master 여부 판정 (승인/거부 권한)
  return { ok: true, headers: { "X-Admin-Token": adminToken, "X-Admin-Email": email } };
}

export async function proxyJsonRequest(request: Request, path: string) {
  const body = await request.text();
  const targetUrl = buildUrl(path);
  const headers: Record<string, string> = { "Content-Type": "application/json" };

  if (isAdminPath(path)) {
    const guard = await adminAuthHeader();
    if (!guard.ok) return guard.response;
    Object.assign(headers, guard.headers);
  }
  if (isAnalyzePath(path) && INTERNAL_API_KEY) {
    headers["Authorization"] = `Bearer ${INTERNAL_API_KEY}`;
  }

  try {
    const response = await fetch(targetUrl, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
    });

    const text = await response.text();
    return NextResponse.json(parseJsonSafely(text), {
      status: response.status,
    });
  } catch (error) {
    return NextResponse.json(
      {
        detail:
          "분석 API에 연결하지 못했습니다. Python 서버와 환경 변수를 확인해주세요.",
        debug: {
          target_url: targetUrl,
          error: errorToMessage(error),
        },
      },
      { status: 502 },
    );
  }
}

export async function proxyRaw(request: Request, path: string) {
  const targetUrl = buildUrl(path);
  try {
    const body = await request.arrayBuffer();
    const headers = new Headers();
    request.headers.forEach((value, key) => {
      const lower = key.toLowerCase();
      if (!["host", "connection", "transfer-encoding"].includes(lower)) {
        headers.set(key, value);
      }
    });
    if (isAdminPath(path)) {
      const guard = await adminAuthHeader();
      if (!guard.ok) return guard.response;
      for (const [k, v] of Object.entries(guard.headers)) headers.set(k, v);
    }
    const response = await fetch(targetUrl, {
      method: request.method,
      headers,
      body: body.byteLength > 0 ? body : undefined,
      cache: "no-store",
    });
    const text = await response.text();
    return new Response(text, {
      status: response.status,
      headers: { "Content-Type": response.headers.get("Content-Type") ?? "application/json" },
    });
  } catch (error) {
    return NextResponse.json(
      {
        detail: "분석 API에 연결하지 못했습니다.",
        debug: { target_url: targetUrl, error: errorToMessage(error) },
      },
      { status: 502 },
    );
  }
}

export async function proxyGet(path: string) {
  const targetUrl = buildUrl(path);
  const headers: Record<string, string> = {};
  if (isAdminPath(path)) {
    const guard = await adminAuthHeader();
    if (!guard.ok) return guard.response;
    Object.assign(headers, guard.headers);
  }
  try {
    const response = await fetch(targetUrl, {
      cache: "no-store",
      headers,
    });
    const text = await response.text();
    return NextResponse.json(parseJsonSafely(text), {
      status: response.status,
    });
  } catch (error) {
    return NextResponse.json(
      {
        detail:
          "분석 API에 연결하지 못했습니다. Python 서버와 환경 변수를 확인해주세요.",
        debug: {
          target_url: targetUrl,
          error: errorToMessage(error),
        },
      },
      { status: 502 },
    );
  }
}
