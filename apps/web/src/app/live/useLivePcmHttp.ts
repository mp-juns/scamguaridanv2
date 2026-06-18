"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import type { StreamMatch } from "./liveTypes";
import {
  computeTierFromMatches,
  dedupMergeMatches,
  fireDangerNotification,
} from "./liveSignals";

export type LivePcmPhase = "idle" | "connecting" | "live" | "error";

function int16ToWavBlob(samples: number[], sampleRate = 16000): Blob {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeStr = (offset: number, str: string) => {
    for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
  };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, samples.length * 2, true);
  let offset = 44;
  for (const s of samples) {
    view.setInt16(offset, s, true);
    offset += 2;
  }
  return new Blob([buffer], { type: "audio/wav" });
}

class ClientPcmBuffer {
  private samples: number[] = [];
  private readonly chunkSamples: number;

  constructor(chunkSec: number) {
    this.chunkSamples = 16000 * chunkSec;
  }

  append(buf: ArrayBuffer) {
    const view = new Int16Array(buf);
    for (let i = 0; i < view.length; i++) this.samples.push(view[i]);
  }

  ready() {
    return this.samples.length >= this.chunkSamples;
  }

  flush(): Blob | null {
    if (this.samples.length < this.chunkSamples) return null;
    const chunk = this.samples.splice(0, this.chunkSamples);
    return int16ToWavBlob(chunk);
  }

  flushRemainder(minSamples = 11200): Blob | null {
    if (this.samples.length < minSamples) return null;
    const chunk = this.samples.splice(0, this.samples.length);
    return int16ToWavBlob(chunk);
  }
}

type ChunkMsg = {
  type: "chunk";
  transcript?: string;
  matches?: StreamMatch[];
  tier?: number;
  latency_ms?: number;
};

export function useLivePcmHttp() {
  const [phase, setPhase] = useState<LivePcmPhase>("idle");
  const [error, setError] = useState("");
  const [transcript, setTranscript] = useState("");
  const [matches, setMatches] = useState<StreamMatch[]>([]);
  const [tier, setTier] = useState(0);
  const [latencyMs, setLatencyMs] = useState(0);

  const audioCtxRef = useRef<AudioContext | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const bufferRef = useRef<ClientPcmBuffer | null>(null);
  const matchesRef = useRef<StreamMatch[]>([]);
  const notifiedRef = useRef(false);
  const flushingRef = useRef(false);
  const chunkSecRef = useRef(3);

  const cleanup = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    void audioCtxRef.current?.close();
    audioCtxRef.current = null;
    bufferRef.current = null;
    flushingRef.current = false;
  }, []);

  useEffect(() => () => cleanup(), [cleanup]);

  const applyChunk = useCallback((msg: ChunkMsg) => {
    setLatencyMs(msg.latency_ms ?? 0);
    if (msg.transcript) {
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

  const flushChunk = useCallback(async () => {
    const buf = bufferRef.current;
    if (!buf || flushingRef.current) return;
    const blob = buf.flush();
    if (!blob) return;
    flushingRef.current = true;
    try {
      const fd = new FormData();
      fd.set("file", blob, "chunk.wav");
      const resp = await fetch("/api/live-pcm-chunk", { method: "POST", body: fd });
      if (!resp.ok) return;
      const msg = (await resp.json()) as ChunkMsg;
      if (msg.type === "chunk") applyChunk(msg);
    } catch {
      /* next chunk retry */
    } finally {
      flushingRef.current = false;
    }
  }, [applyChunk]);

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

    let chunkSec = 3;
    try {
      const cfg = await fetch("/api/live-ws-config");
      if (cfg.ok) {
        const j = await cfg.json();
        chunkSec = typeof j.chunk_sec === "number" ? j.chunk_sec : 3;
      }
    } catch {
      /* default 3 */
    }
    chunkSecRef.current = chunkSec;
    bufferRef.current = new ClientPcmBuffer(chunkSec);

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

      const audioCtx = new AudioContext({ sampleRate: 48000 });
      audioCtxRef.current = audioCtx;
      if (audioCtx.state === "suspended") {
        await audioCtx.resume();
      }

      await audioCtx.audioWorklet.addModule("/live-pcm-processor.js");
      const source = audioCtx.createMediaStreamSource(stream);
      const worklet = new AudioWorkletNode(audioCtx, "live-pcm-processor");
      worklet.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
        bufferRef.current?.append(e.data);
        if (bufferRef.current?.ready()) {
          void flushChunk();
        }
      };
      const silent = audioCtx.createGain();
      silent.gain.value = 0;
      source.connect(worklet);
      worklet.connect(silent);
      silent.connect(audioCtx.destination);

      setPhase("live");
      return true;
    } catch (err) {
      cleanup();
      setPhase("error");
      setError(err instanceof Error ? err.message : "PCM Live 시작 실패");
      return false;
    }
  }, [cleanup, flushChunk]);

  const stop = useCallback(async () => {
    const tail = bufferRef.current?.flushRemainder();
    if (tail) {
      try {
        const fd = new FormData();
        fd.set("file", tail, "tail.wav");
        const resp = await fetch("/api/live-pcm-chunk", { method: "POST", body: fd });
        if (resp.ok) {
          const msg = (await resp.json()) as ChunkMsg;
          if (msg.type === "chunk") applyChunk(msg);
        }
      } catch {
        /* ignore */
      }
    }
    cleanup();
    setPhase("idle");
  }, [applyChunk, cleanup]);

  return {
    phase,
    error,
    transcript,
    matches,
    tier,
    latencyMs,
    transport: "http-pcm" as const,
    start,
    stop,
    cleanup,
  };
}
