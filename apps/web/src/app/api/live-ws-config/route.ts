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

export async function GET() {
  try {
    const [runtimeResp, tokenResp] = await Promise.all([
      fetch(`${API_BASE_URL}/api/config/runtime`, { cache: "no-store" }),
      fetch(`${API_BASE_URL}/api/live-ws-token`, { cache: "no-store" }),
    ]);
    const runtime = runtimeResp.ok ? await runtimeResp.json() : {};
    const chunkSec = typeof runtime.live_chunk_sec === "number" ? runtime.live_chunk_sec : 5;
    const wsEnabled = runtime.live_ws_enabled !== false;

    let wsUrl = LIVE_WS_URL || (typeof runtime.live_ws_url === "string" ? runtime.live_ws_url : "");
    if (!wsUrl) {
      wsUrl = buildWsUrl(API_BASE_URL);
    }

    if (tokenResp.ok) {
      const tokenData = (await tokenResp.json()) as { token?: string };
      if (tokenData.token) {
        wsUrl = appendQuery(wsUrl, "live_token", tokenData.token);
      }
    } else if (INTERNAL_API_KEY) {
      wsUrl = appendQuery(wsUrl, "api_key", INTERNAL_API_KEY);
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
