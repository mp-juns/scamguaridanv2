import { NextResponse } from "next/server";

const API_BASE_URL = process.env.SCAMGUARDIAN_API_URL ?? "http://127.0.0.1:8000";
const INTERNAL_API_KEY = (process.env.SCAMGUARDIAN_INTERNAL_API_KEY ?? "").trim();
const LIVE_WS_URL = (process.env.NEXT_PUBLIC_LIVE_WS_URL ?? process.env.LIVE_WS_URL ?? "").trim();

function buildWsUrl(baseHttp: string): string {
  if (baseHttp.startsWith("https://")) {
    return baseHttp.replace("https://", "wss://") + "/ws/live-transcribe";
  }
  return baseHttp.replace("http://", "ws://") + "/ws/live-transcribe";
}

function appendQuery(url: string, key: string, value: string): string {
  const sep = url.includes("?") ? "&" : "?";
  return `${url}${sep}${key}=${encodeURIComponent(value)}`;
}

function inferPublicWsUrlFromRequest(request: Request): string {
  const reqUrl = new URL(request.url);
  const proto = reqUrl.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${reqUrl.host}/ws/live-transcribe`;
}

function isLocalWsUrl(url: string): boolean {
  try {
    const parsed = new URL(url);
    return parsed.hostname === "127.0.0.1" || parsed.hostname === "localhost";
  } catch {
    return false;
  }
}

export async function GET(request: Request) {
  try {
    const sessionToken = new URL(request.url).searchParams.get("session_token")?.trim() || "";
    const inferredPublicWsUrl = inferPublicWsUrlFromRequest(request);
    const runtimeResp = await fetch(`${API_BASE_URL}/api/config/runtime`, { cache: "no-store" });
    const runtime = runtimeResp.ok ? await runtimeResp.json() : {};
    const chunkSec = typeof runtime.live_chunk_sec === "number" ? runtime.live_chunk_sec : 5;
    const wsEnabled = runtime.live_ws_enabled !== false;

    let wsUrl = LIVE_WS_URL || (typeof runtime.live_ws_url === "string" ? runtime.live_ws_url : "");
    if (!wsUrl) {
      wsUrl = buildWsUrl(API_BASE_URL);
    }

    if (sessionToken) {
      const sessionResp = await fetch(
        `${API_BASE_URL}/api/live-session/${encodeURIComponent(sessionToken)}?consume=true`,
        { cache: "no-store" },
      );
      if (!sessionResp.ok) {
        const body = (await sessionResp.json().catch(() => ({}))) as { detail?: string };
        return NextResponse.json(
          { detail: body.detail ?? "라이브 세션 검증에 실패했습니다." },
          { status: sessionResp.status },
        );
      }
      const sessionData = (await sessionResp.json()) as { ws_token?: string; ws_url?: string };
      if (sessionData.ws_url) {
        wsUrl = sessionData.ws_url;
      }
      if (isLocalWsUrl(wsUrl)) {
        wsUrl = inferredPublicWsUrl;
      }
      if (sessionData.ws_token) {
        wsUrl = appendQuery(wsUrl, "live_token", sessionData.ws_token);
        wsUrl = appendQuery(wsUrl, "live_session_token", sessionToken);
      }
    } else {
      const tokenResp = await fetch(`${API_BASE_URL}/api/live-ws-token`, { cache: "no-store" });
      if (tokenResp.ok) {
        const tokenData = (await tokenResp.json()) as { token?: string };
        if (tokenData.token) {
          if (isLocalWsUrl(wsUrl)) {
            wsUrl = inferredPublicWsUrl;
          }
          wsUrl = appendQuery(wsUrl, "live_token", tokenData.token);
        }
      } else if (INTERNAL_API_KEY) {
        if (isLocalWsUrl(wsUrl)) {
          wsUrl = inferredPublicWsUrl;
        }
        wsUrl = appendQuery(wsUrl, "api_key", INTERNAL_API_KEY);
      }
    }

    return NextResponse.json({
      ws_url: wsUrl,
      chunk_sec: chunkSec,
      transport: wsEnabled ? "websocket" : "http",
      ws_enabled: wsEnabled,
    });
  } catch (error) {
    return NextResponse.json(
      { detail: error instanceof Error ? error.message : "config error" },
      { status: 500 },
    );
  }
}
