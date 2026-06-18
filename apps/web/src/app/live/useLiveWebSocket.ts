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

export function useLiveWebSocket() {
  const [phase, setPhase] = useState<LiveWsPhase>("idle");
  const [error, setError] = useState("");
  const [transcript, setTranscript] = useState("");
  const [matches, setMatches] = useState<StreamMatch[]>([]);
  const [tier, setTier] = useState(0);
  const [latencyMs, setLatencyMs] = useState(0);
  const [transport, setTransport] = useState<string>("websocket");

  const wsRef = useRef<WebSocket | null>(null);
  const audioCtxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const matchesRef = useRef<StreamMatch[]>([]);
  const notifiedRef = useRef(false);
  const phaseRef = useRef<LiveWsPhase>("idle");

  useEffect(() => {
    phaseRef.current = phase;
  }, [phase]);

  const cleanup = useCallback(() => {
    wsRef.current?.close();
    wsRef.current = null;
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    void audioCtxRef.current?.close();
    audioCtxRef.current = null;
  }, []);

  useEffect(() => () => cleanup(), [cleanup]);

  const handleChunk = useCallback((msg: WsChunkMessage) => {
    setLatencyMs(msg.latency_ms ?? 0);
    if (msg.full_transcript) setTranscript(msg.full_transcript);
    else if (msg.transcript) {
      setTranscript((prev) => (prev ? `${prev} ${msg.transcript}` : msg.transcript ?? ""));
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
    cleanup();
    setError("");
    setTranscript("");
    setMatches([]);
    setTier(0);
    setLatencyMs(0);
    matchesRef.current = [];
    notifiedRef.current = false;
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
      return false;
    }

    if (!config.ws_url) {
      setPhase("error");
      setError("live_ws_url 이 설정되지 않았습니다.");
      return false;
    }

    if (!navigator.mediaDevices?.getUserMedia) {
      setPhase("error");
      setError("마이크를 지원하지 않는 브라우저입니다.");
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
      return true;
    } catch (err) {
      cleanup();
      setPhase("error");
      setError(err instanceof Error ? err.message : "Live v4 시작 실패");
      return false;
    }
  }, [cleanup, handleChunk]);

  const stop = useCallback(() => {
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
    start,
    stop,
    cleanup,
  };
}
