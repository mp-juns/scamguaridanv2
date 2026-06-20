"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { StreamMatch } from "./liveTypes";
import {
  computeTierFromMatches,
  dedupMergeMatches,
  fireDangerNotification,
} from "./liveSignals";

export type LiveWsPhase = "idle" | "connecting" | "live" | "finalizing" | "error";

export type LiveWsConfig = {
  ws_url: string;
  chunk_sec: number;
  transport: string;
};

type WsChunkMessage = {
  type: "chunk";
  transcript?: string;
  full_transcript?: string;
  matches?: StreamMatch[];
  cumulative_matches?: StreamMatch[];
  tier?: number;
  tier_changed?: boolean;
  latency_ms?: number;
};

type WsFinalMessage = {
  type: "final";
  full_transcript?: string;
  cumulative_matches?: StreamMatch[];
  tier?: number;
};

const MAX_AUTO_RECONNECTS = 3;
const STUCK_WINDOW = 4;      // consecutive identical short chunks = stuck
const STUCK_MAX_LEN = 30;    // only track short phrases (hallucination is short)
const STUCK_BACKOFF_MS = 3000; // 3s, 6s, 9s per retry

export function useLiveWebSocket() {
  const [phase, setPhase] = useState<LiveWsPhase>("idle");
  const [error, setError] = useState("");
  const [transcript, setTranscript] = useState("");
  const [matches, setMatches] = useState<StreamMatch[]>([]);
  const [tier, setTier] = useState(0);
  const [latencyMs, setLatencyMs] = useState(0);
  const [transport, setTransport] = useState<string>("websocket");
  const [reconnecting, setReconnecting] = useState(false);

  const wsRef = useRef<WebSocket | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const matchesRef = useRef<StreamMatch[]>([]);
  const notifiedRef = useRef(false);
  const phaseRef = useRef<LiveWsPhase>("idle");
  // Auto-reconnect state (refs to avoid stale closures)
  const reconnectCountRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const recentChunksRef = useRef<string[]>([]); // ring buffer for stuck detection
  const startRef = useRef<() => Promise<boolean>>(async () => false);
  const triggerReconnectRef = useRef<() => void>(() => {});

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  const cleanup = useCallback(() => {
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    wsRef.current?.close();
    wsRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    void audioCtxRef.current?.close();
    audioCtxRef.current = null;
  }, []);

  // Keep triggerReconnect fresh so it always captures the latest cleanup reference.
  useEffect(() => {
    triggerReconnectRef.current = () => {
      recentChunksRef.current = [];
      reconnectCountRef.current += 1;
      if (reconnectCountRef.current > MAX_AUTO_RECONNECTS) {
        setError("라이브 기능에 오류가 반복됩니다. 잠시 후 다시 시작해 주세요.");
        phaseRef.current = "error";
        setPhase("error");
        setReconnecting(false);
        return;
      }
      setError(
        `라이브 기능에 오류 났습니다 — 자동 재연결 중 (${reconnectCountRef.current}/${MAX_AUTO_RECONNECTS})...`,
      );
      setReconnecting(true);
      // Set phase to "connecting" before cleanup so ws.onclose won't flip to "idle"
      phaseRef.current = "connecting";
      setPhase("connecting");
      cleanup();
      const delay = STUCK_BACKOFF_MS * reconnectCountRef.current;
      reconnectTimerRef.current = setTimeout(() => {
        void startRef.current();
      }, delay);
    };
  }, [cleanup]);

  useEffect(() => () => cleanup(), [cleanup]);

  const handleChunk = useCallback((msg: WsChunkMessage) => {
    setLatencyMs(msg.latency_ms ?? 0);

    const chunkText = (msg.transcript ?? "").trim();
    if (msg.full_transcript) {
      setTranscript(msg.full_transcript);
    } else if (chunkText) {
      setTranscript((prev) => (prev ? `${prev} ${chunkText}` : chunkText));
    }

    // Stuck detection: Whisper silence hallucination produces the same short phrase repeatedly.
    if (chunkText && chunkText.length <= STUCK_MAX_LEN) {
      recentChunksRef.current = [
        ...recentChunksRef.current.slice(-(STUCK_WINDOW - 1)),
        chunkText,
      ];
      if (
        recentChunksRef.current.length >= STUCK_WINDOW &&
        recentChunksRef.current.every((t) => t === chunkText)
      ) {
        triggerReconnectRef.current();
        return; // skip match processing for hallucinated chunk
      }
    } else if (chunkText) {
      // Substantive transcript resets the stuck window
      recentChunksRef.current = [];
    }

    const incoming = Array.isArray(msg.matches) ? msg.matches : [];
    const merged = dedupMergeMatches(matchesRef.current, incoming);
    matchesRef.current = merged;
    setMatches(merged);

    const newTier = msg.tier ?? computeTierFromMatches(merged);
    setTier((prev) => Math.max(prev, newTier));
    if (newTier >= 3 && !notifiedRef.current) {
      notifiedRef.current = true;
      fireDangerNotification(merged);
    }
  }, []);

  const start = useCallback(async () => {
    // Fresh user-initiated start resets the reconnect counter; auto-reconnect keeps it.
    if (!reconnecting) {
      reconnectCountRef.current = 0;
      setTranscript("");
      setMatches([]);
      setTier(0);
      matchesRef.current = [];
      notifiedRef.current = false;
    }
    recentChunksRef.current = [];
    cleanup();
    setError("");
    setLatencyMs(0);
    setPhase("connecting");

    let config: LiveWsConfig;
    try {
      const resp = await fetch("/api/live-ws-config");
      if (!resp.ok) throw new Error("WebSocket 설정을 불러올 수 없습니다.");
      config = (await resp.json()) as LiveWsConfig;
      setTransport(config.transport || "websocket");
    } catch (err) {
      setPhase("error");
      setError(err instanceof Error ? err.message : "WebSocket 설정 오류");
      setReconnecting(false);
      return false;
    }

    if (!config.ws_url) {
      setPhase("error");
      setError("live_ws_url 이 설정되지 않았습니다.");
      setReconnecting(false);
      return false;
    }

    if (!navigator.mediaDevices?.getUserMedia) {
      setPhase("error");
      setError("마이크를 지원하지 않는 브라우저입니다.");
      setReconnecting(false);
      return false;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
          channelCount: 1,
        },
      });
      streamRef.current = stream;

      const ws = new WebSocket(config.ws_url);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      await new Promise<void>((resolve, reject) => {
        ws.onopen = () => resolve();
        ws.onerror = () => reject(new Error("WebSocket 연결 실패"));
        setTimeout(() => reject(new Error("WebSocket 연결 시간 초과")), 8000);
      });

      ws.onmessage = (ev) => {
        if (typeof ev.data !== "string") return;
        try {
          const msg = JSON.parse(ev.data) as WsChunkMessage | WsFinalMessage | { type: string; message?: string };
          if (msg.type === "chunk") handleChunk(msg as WsChunkMessage);
          if (msg.type === "final") {
            const fin = msg as WsFinalMessage;
            if (fin.full_transcript) setTranscript(fin.full_transcript);
            if (Array.isArray(fin.cumulative_matches)) {
              matchesRef.current = fin.cumulative_matches;
              setMatches(fin.cumulative_matches);
            }
            setTier((prev) => Math.max(prev, fin.tier ?? 0));
            setReconnecting(false);
            setPhase("idle");
            cleanup();
          }
          if (msg.type === "error") {
            setError(msg.message ?? "서버 오류");
            setPhase("error");
          }
        } catch {
          /* ignore */
        }
      };

      ws.onclose = () => {
        // Only transition to idle for normal live→stop; ignore during reconnect (phase=connecting)
        if (phaseRef.current === "live") setPhase("idle");
      };

      const audioCtx = new AudioContext({ sampleRate: 48000 });
      audioCtxRef.current = audioCtx;
      if (audioCtx.state === "suspended") {
        await audioCtx.resume();
      }

      await audioCtx.audioWorklet.addModule("/live-pcm-processor.js");
      const source = audioCtx.createMediaStreamSource(stream);
      const worklet = new AudioWorkletNode(audioCtx, "live-pcm-processor");
      worklet.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(e.data);
        }
      };
      const silent = audioCtx.createGain();
      silent.gain.value = 0;
      source.connect(worklet);
      worklet.connect(silent);
      silent.connect(audioCtx.destination);

      ws.send(JSON.stringify({ type: "start" }));
      setPhase("live");
      setReconnecting(false);
      return true;
    } catch (err) {
      cleanup();
      setPhase("error");
      setError(err instanceof Error ? err.message : "Live v4 시작 실패");
      setReconnecting(false);
      return false;
    }
  }, [cleanup, handleChunk, reconnecting]);

  // Keep startRef current so triggerReconnect can call it without stale closure.
  useEffect(() => {
    startRef.current = start;
  }, [start]);

  const stop = useCallback(() => {
    // Manual stop cancels any pending auto-reconnect
    reconnectCountRef.current = 0;
    recentChunksRef.current = [];
    setReconnecting(false);
    if (reconnectTimerRef.current) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
    setPhase("finalizing");
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "stop" }));
    } else {
      cleanup();
      setPhase("idle");
    }
  }, [cleanup]);

  return {
    phase,
    error,
    transcript,
    matches,
    tier,
    latencyMs,
    transport,
    reconnecting,
    start,
    stop,
    cleanup,
  };
}
