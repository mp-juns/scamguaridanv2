"use client";

import { signIn } from "next-auth/react";
import { useEffect, useRef, useState } from "react";

import { GUEST_DAILY_LIMIT, bumpGuestDaily, guestOverDailyLimit } from "../guestLimit";
import type {
  AnalysisResult,
  Mode,
  Phase,
  StreamChunk,
  StreamMatch,
  TranscriptResult,
  Turn,
} from "./liveTypes";
import {
  computeTierFromMatches,
  dedupMergeMatches,
  fireDangerNotification,
  flagLabel,
  fmtTime,
  scanTranscript,
  speakerTag,
} from "./liveSignals";
import {
  CautionBanner,
  ChunkRow,
  Conversation,
  DangerOverlay,
  PhaseBadge,
} from "./liveComponents";
import { useLivePcmHttp } from "./useLivePcmHttp";
import { useLiveWebSocket } from "./useLiveWebSocket";

export default function LiveVoiceUpload({ isGuest = false }: { isGuest?: boolean }) {
  const [guestBlocked, setGuestBlocked] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  // 업로드한 파일의 blob URL — turn 별 ▶️ 재생용 (단일 모드)
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!file) {
      setAudioUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setAudioUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);
  const [mode, setMode] = useState<Mode>("live");
  // 단일 호출 모드 (전사 + 분석 병렬)
  const [transcriptPhase, setTranscriptPhase] = useState<Phase>("idle");
  const [transcript, setTranscript] = useState<TranscriptResult | null>(null);
  const [transcriptError, setTranscriptError] = useState("");
  const [analysisPhase, setAnalysisPhase] = useState<Phase>("idle");
  const [analysis, setAnalysis] = useState<AnalysisResult | null>(null);
  const [analysisError, setAnalysisError] = useState("");
  // 스트리밍 모드 — 청크 history + 선택된 인덱스 (기본 최신 follow)
  const [streamPhase, setStreamPhase] = useState<Phase>("idle");
  const [streamHistory, setStreamHistory] = useState<StreamChunk[]>([]);
  const [selectedChunkIndex, setSelectedChunkIndex] = useState<number | null>(null); // null = latest follow
  const [streamTotal, setStreamTotal] = useState(0);
  const [streamError, setStreamError] = useState("");
  const [cumulativeMatches, setCumulativeMatches] = useState<StreamMatch[]>([]);
  // 계층적 알림 — tier 는 단조 증가, danger 풀스크린은 확인 누르면 dismiss
  const [tier, setTier] = useState(0);
  const [dangerDismissed, setDangerDismissed] = useState(false);
  const streamAbortRef = useRef<AbortController | null>(null);
  // 🎤 실시간 마이크 모드 (스피커폰 양쪽 — 누적 오디오 주기적 통째 재분석)
  const [liveActive, setLiveActive] = useState(false);
  const [liveTranscript, setLiveTranscript] = useState("");
  const [liveTurns, setLiveTurns] = useState<Turn[]>([]); // 화자분리 말풍선
  const [liveAudioUrl, setLiveAudioUrl] = useState<string | null>(null); // 중지 후 재생용 blob URL
  const [liveLatency, setLiveLatency] = useState(0);
  const [liveError, setLiveError] = useState("");
  const [liveFinalizing, setLiveFinalizing] = useState(false); // 중지 후 full 분석 대기
  const [liveStarting, setLiveStarting] = useState(false);
  const [liveStartedAt, setLiveStartedAt] = useState<number | null>(null);
  const [liveElapsedSec, setLiveElapsedSec] = useState(0);
  const [liveFinalAnalysisPhase, setLiveFinalAnalysisPhase] = useState<Phase>("idle");
  const [liveFinalAnalysis, setLiveFinalAnalysis] = useState<AnalysisResult | null>(null);
  const [liveFinalAnalysisError, setLiveFinalAnalysisError] = useState("");
  const liveMatchesRef = useRef<StreamMatch[]>([]); // 누적 dedup match 소스 (tier 계산용)
  const notifiedDangerRef = useRef(false); // danger OS 알림 1회 발사 가드
  const finalAnalyzeStartedRef = useRef(false);
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const LIVE_WINDOW_SEC = 12; // legacy HTTP fallback — webm 재인코딩 경로
  const liveStreamRef = useRef<MediaStream | null>(null);
  const liveChunksRef = useRef<Blob[]>([]);
  const liveTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const usingWsRef = useRef(false);
  const usingPcmRef = useRef(false);
  const liveWs = useLiveWebSocket();
  const livePcm = useLivePcmHttp();
  const [wsEnabled, setWsEnabled] = useState(true);
  const [liveTransport, setLiveTransport] = useState<string>("websocket");
  const [liveTransportMode, setLiveTransportMode] = useState<"ws" | "pcm" | "legacy" | null>(null);
  const [liveChunkSec, setLiveChunkSec] = useState(3);

  useEffect(() => {
    let cancelled = false;
    fetch("/api/live-ws-config")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        if (cancelled || !d) return;
        setWsEnabled(d.ws_enabled !== false);
        setLiveTransport(d.transport ?? "websocket");
        if (typeof d.chunk_sec === "number") setLiveChunkSec(d.chunk_sec);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!liveStarting && !liveActive) {
      setLiveElapsedSec(0);
      return;
    }
    const id = window.setInterval(() => {
      if (!liveStartedAt) return;
      setLiveElapsedSec(Math.max(0, Math.floor((Date.now() - liveStartedAt) / 1000)));
    }, 250);
    return () => window.clearInterval(id);
  }, [liveActive, liveStarting, liveStartedAt]);

  useEffect(() => {
    if (liveTransportMode !== "ws") return;
    setLiveTranscript(liveWs.transcript);
    liveMatchesRef.current = liveWs.matches;
    setCumulativeMatches(liveWs.matches);
    setLiveLatency(liveWs.latencyMs);
    setTier((prev) => Math.max(prev, liveWs.tier));
    if (liveWs.tier >= 3) setDangerDismissed(false);
    if (
      liveTransportMode === "ws" &&
      liveFinalizing &&
      liveWs.phase === "idle" &&
      liveWs.transcript.trim() &&
      !finalAnalyzeStartedRef.current
    ) {
      finalAnalyzeStartedRef.current = true;
      void analyzeLiveFinalTranscript(liveWs.transcript);
    }
    if (liveWs.error) setLiveError(liveWs.error);
    if (liveWs.phase === "live" || liveWs.phase === "connecting") setLiveActive(true);
    if (liveWs.phase === "idle" || liveWs.phase === "error") setLiveActive(false);
  }, [
    liveTransportMode,
    liveWs.transcript,
    liveWs.matches,
    liveWs.tier,
    liveWs.latencyMs,
    liveWs.phase,
    liveWs.error,
    liveFinalizing,
    liveTransportMode,
  ]);

  useEffect(() => {
    if (liveTransportMode !== "pcm") return;
    setLiveTranscript(livePcm.transcript);
    liveMatchesRef.current = livePcm.matches;
    setCumulativeMatches(livePcm.matches);
    setLiveLatency(livePcm.latencyMs);
    setTier((prev) => Math.max(prev, livePcm.tier));
    if (livePcm.tier >= 3) setDangerDismissed(false);
    if (livePcm.error) setLiveError(livePcm.error);
    if (livePcm.phase === "live" || livePcm.phase === "connecting") setLiveActive(true);
    if (livePcm.phase === "idle" || livePcm.phase === "error") setLiveActive(false);
  }, [
    liveTransportMode,
    livePcm.transcript,
    livePcm.matches,
    livePcm.tier,
    livePcm.latencyMs,
    livePcm.phase,
    livePcm.error,
  ]);

  function stopLiveCapture() {
    if (liveTimerRef.current) {
      clearInterval(liveTimerRef.current);
      liveTimerRef.current = null;
    }
    try {
      mediaRecorderRef.current?.stop();
    } catch {
      /* already stopped */
    }
    liveStreamRef.current?.getTracks().forEach((t) => t.stop());
    mediaRecorderRef.current = null;
    liveStreamRef.current = null;
    liveChunksRef.current = [];
  }

  function reset() {
    setTranscriptPhase("idle");
    setTranscript(null);
    setTranscriptError("");
    setAnalysisPhase("idle");
    setAnalysis(null);
    setAnalysisError("");
    setStreamPhase("idle");
    setStreamHistory([]);
    setSelectedChunkIndex(null);
    setStreamTotal(0);
    setStreamError("");
    setCumulativeMatches([]);
    setTier(0);
    setDangerDismissed(false);
    streamAbortRef.current?.abort();
    streamAbortRef.current = null;
    stopLiveCapture();
    setLiveActive(false);
    setLiveTranscript("");
    setLiveTurns([]);
    setLiveAudioUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev);
      return null;
    });
    setLiveLatency(0);
    setLiveError("");
    setLiveFinalizing(false);
    setLiveStarting(false);
    setLiveStartedAt(null);
    setLiveElapsedSec(0);
    setLiveFinalAnalysisPhase("idle");
    setLiveFinalAnalysis(null);
    setLiveFinalAnalysisError("");
    liveMatchesRef.current = [];
    notifiedDangerRef.current = false;
    finalAnalyzeStartedRef.current = false;
    usingWsRef.current = false;
    usingPcmRef.current = false;
    setLiveTransportMode(null);
    liveWs.cleanup();
    livePcm.cleanup();
  }

  async function postFile<T>(endpoint: string, payload: File): Promise<T> {
    const formData = new FormData();
    formData.set("file", payload);
    if (endpoint === "/api/analyze-upload") {
      formData.set("skip_verification", "true");
      formData.set("use_llm", "true");
      formData.set("use_rag", "false");
    }
    const response = await fetch(endpoint, { method: "POST", body: formData });
    const data = (await response.json()) as T | { detail?: string };
    if (!response.ok) {
      const msg =
        data && typeof data === "object" && "detail" in data && typeof data.detail === "string"
          ? data.detail
          : "요청이 실패했습니다.";
      throw new Error(msg);
    }
    return data as T;
  }

  async function analyzeLiveFinalTranscript(text: string) {
    const source = text.trim();
    if (!source) {
      setLiveFinalAnalysisError("전체 전사 텍스트가 비어 있어 최종 분석을 건너뜁니다.");
      setLiveFinalAnalysisPhase("error");
      setLiveFinalizing(false);
      return;
    }

    setLiveFinalAnalysisPhase("running");
    setLiveFinalAnalysisError("");
    try {
      const response = await fetch("/api/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source,
          skip_verification: true,
          use_llm: true,
          use_rag: false,
          deep: true,
        }),
      });
      const data = (await response.json()) as AnalysisResult | { detail?: string };
      if (!response.ok) {
        throw new Error(
          "detail" in data && typeof data.detail === "string"
            ? data.detail
            : "최종 분석 중 오류가 발생했습니다.",
        );
      }
      setLiveFinalAnalysis(data as AnalysisResult);
      setLiveFinalAnalysisPhase("done");
    } catch (err) {
      setLiveFinalAnalysisError(
        err instanceof Error ? err.message : "최종 분석 중 알 수 없는 오류가 발생했습니다.",
      );
      setLiveFinalAnalysisPhase("error");
    } finally {
      setLiveFinalizing(false);
    }
  }

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!file) {
      setAnalysisError("음성 파일을 선택해주세요.");
      return;
    }
    // 비회원 일일 한도(홈+라이브 합산) 초과 시 분석 차단
    if (isGuest && guestOverDailyLimit()) {
      setGuestBlocked(true);
      return;
    }
    reset();
    if (isGuest) bumpGuestDaily(); // 이번 실행을 오늘 카운트에 반영
    if (mode === "stream") {
      await runStreaming(file);
    } else {
      runSingleShot(file);
    }
  }

  function runSingleShot(audio: File) {
    setTranscriptPhase("running");
    setAnalysisPhase("running");

    void postFile<TranscriptResult>("/api/transcribe-upload", audio)
      .then((data) => {
        setTranscript(data);
        setTranscriptPhase("done");
      })
      .catch((err: unknown) => {
        setTranscriptError(err instanceof Error ? err.message : "알 수 없는 오류");
        setTranscriptPhase("error");
      });

    void postFile<AnalysisResult>("/api/analyze-upload", audio)
      .then((data) => {
        setAnalysis(data);
        setAnalysisPhase("done");
      })
      .catch((err: unknown) => {
        setAnalysisError(err instanceof Error ? err.message : "알 수 없는 오류");
        setAnalysisPhase("error");
      });
  }

  async function runStreaming(audio: File) {
    setStreamPhase("running");
    const controller = new AbortController();
    streamAbortRef.current = controller;
    const formData = new FormData();
    formData.set("file", audio);
    formData.set("chunk_seconds", "60");
    try {
      const resp = await fetch("/api/analyze-stream", {
        method: "POST",
        body: formData,
        signal: controller.signal,
      });
      if (!resp.ok || !resp.body) {
        const text = await resp.text();
        try {
          const j = JSON.parse(text);
          throw new Error(j.detail ?? "스트리밍 시작 실패");
        } catch {
          throw new Error(text || "스트리밍 시작 실패");
        }
      }
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let nl: number;
        while ((nl = buffer.indexOf("\n")) >= 0) {
          const line = buffer.slice(0, nl).trim();
          buffer = buffer.slice(nl + 1);
          if (!line) continue;
          let event: { type: string; [k: string]: unknown };
          try {
            event = JSON.parse(line);
          } catch {
            continue;
          }
          handleStreamEvent(event);
        }
      }
      setStreamPhase("done");
    } catch (err) {
      if ((err as DOMException)?.name === "AbortError") {
        // user cancelled
      } else {
        setStreamError(err instanceof Error ? err.message : "스트리밍 오류");
        setStreamPhase("error");
      }
    } finally {
      streamAbortRef.current = null;
    }
  }

  function handleStreamEvent(event: { type: string; [k: string]: unknown }) {
    if (event.type === "start") {
      setStreamTotal((event.total_chunks as number) ?? 0);
    } else if (event.type === "chunk") {
      const chunk = event as unknown as StreamChunk;
      // history 에 append — 사용자가 이전 청크 다시 볼 수 있도록 보존.
      // 메인 패널은 selectedChunkIndex 가 null 이면 자동으로 최신 follow.
      setStreamHistory((prev) => [...prev, chunk]);
      // 계층적 알림 — tier 단조 증가. danger 로 새로 올라가면 풀스크린 재노출.
      const chunkTier = chunk.tier ?? 0;
      setTier((prev) => Math.max(prev, chunkTier));
      if (chunk.tier_changed && chunkTier >= 3) {
        setDangerDismissed(false);
      }
      if (chunk.matches.length > 0) {
        // 누적 — 같은 (flag, snippet) 조합은 한 번만
        setCumulativeMatches((prev) => {
          const seen = new Set(prev.map((m) => `${m.flag}|${m.snippet}`));
          const fresh = chunk.matches.filter(
            (m) => !seen.has(`${m.flag}|${m.snippet}`),
          );
          return [...prev, ...fresh];
        });
      }
    } else if (event.type === "done") {
      setTier((prev) => Math.max(prev, (event.tier as number) ?? 0));
    } else if (event.type === "error") {
      setStreamError((event.message as string) ?? "스트리밍 서버 오류");
      setStreamPhase("error");
    }
  }

  // ── 🎤 실시간 마이크 (스피커폰 양쪽) ──
  async function sendLiveCumulative(
    mimeType: string,
    windowSec: number,
    isFinal: boolean,
  ): Promise<string | undefined> {
    const chunks = liveChunksRef.current;
    if (!chunks.length) return undefined;
    const type = mimeType || "audio/webm";
    const blob = new Blob(chunks, { type });
    const ext = type.includes("ogg") ? "ogg" : type.includes("mp4") ? "mp4" : "webm";
    const fd = new FormData();
    fd.set("file", blob, `cumulative.${ext}`);
    fd.set("window_sec", String(windowSec)); // 0 = full (중지 시), >0 = 최근 N초만 STT
    try {
      const resp = await fetch("/api/live-analyze", { method: "POST", body: fd });
      if (!resp.ok) return;
      const j = (await resp.json()) as {
        transcript_text?: string;
        turns?: Turn[];
        matches?: StreamMatch[];
        latency_ms?: number;
      };
      const incoming = Array.isArray(j.matches) ? j.matches : [];
      setLiveLatency(j.latency_ms ?? 0);

      if (isFinal) {
        // 중지 시 full 분석 — 완전한 전사/화자분리(타임스탬프가 full 오디오와 정합).
        liveMatchesRef.current = incoming; // 전체 집합 authoritative
        setCumulativeMatches(incoming);
        setLiveTranscript(j.transcript_text ?? "");
        setLiveTurns(Array.isArray(j.turns) ? j.turns : []);
        setLiveFinalizing(false);
      } else {
        // 윈도우 tick — match 누적(dedup), tier 는 누적분으로 계산(단조).
        const merged = dedupMergeMatches(liveMatchesRef.current, incoming);
        liveMatchesRef.current = merged;
        setCumulativeMatches(merged);
        setLiveTranscript(j.transcript_text ?? ""); // 최근 윈도우 전사 미리보기
        setLiveTurns(Array.isArray(j.turns) ? j.turns : []);
      }
      const newTier = computeTierFromMatches(liveMatchesRef.current);
      // danger 진입 시 OS 알림 1회 (탭 안 볼 때 화면 위로 경보)
      if (newTier >= 3 && !notifiedDangerRef.current) {
        notifiedDangerRef.current = true;
        fireDangerNotification(liveMatchesRef.current);
      }
      setTier((prev) => Math.max(prev, newTier));
      if (newTier >= 3) setDangerDismissed(false);
      return j.transcript_text ?? "";
    } catch {
      /* 일시적 네트워크 오류 무시 — 다음 tick 에 재시도 */
      return undefined;
    }
  }

  async function startLive() {
    // 비회원 일일 한도(홈+라이브 합산) 초과 시 실시간 분석 차단
    if (isGuest && guestOverDailyLimit()) {
      setGuestBlocked(true);
      return;
    }
    reset();
    setLiveStarting(true);
    setLiveStartedAt(Date.now());
    setLiveTransportMode(wsEnabled ? "ws" : "pcm");
    setLiveTransport(wsEnabled ? "websocket" : "http-pcm");
    setLiveError("");
    try {
      if ("Notification" in window && Notification.permission === "default") {
        void Notification.requestPermission();
      }
    } catch {
      /* 미지원 브라우저 무시 */
    }

    if (wsEnabled) {
      const ok = await liveWs.start();
      if (ok) {
        if (isGuest) bumpGuestDaily();
        usingWsRef.current = true;
        setLiveTransportMode("ws");
        setLiveTransport("websocket");
        setLiveActive(true);
        setLiveStarting(false);
        setLiveError("");
        return;
      }
    }

    setLiveTransportMode("pcm");
    setLiveTransport("http-pcm");
    const pcmOk = await livePcm.start();
    if (pcmOk) {
      if (isGuest) bumpGuestDaily();
      usingPcmRef.current = true;
      setLiveTransportMode("pcm");
      setLiveTransport("http-pcm");
      setLiveActive(true);
      setLiveStarting(false);
      setLiveError("");
      return;
    }

    setLiveError(
      liveWs.error || livePcm.error || "실시간 연결 실패 — 구형 HTTP 모드로 시도합니다",
    );

    usingWsRef.current = false;
    usingPcmRef.current = false;
    setLiveTransportMode("legacy");
    setLiveTransport("http-legacy");
    if (!navigator.mediaDevices?.getUserMedia) {
      setLiveError("이 브라우저는 마이크 캡처를 지원하지 않습니다.");
      setLiveStarting(false);
      setLiveStartedAt(null);
      return;
    }
    try {
      // ⚠️ STT 정확도 핵심: 브라우저 음성 가공을 모두 끈다.
      //  - autoGainControl: AGC 펌핑이 단어 오인식 유발 (업로드 모드에서 dynaudnorm 뺀 것과 동일 이유)
      //  - noiseSuppression: STT 가 필요로 하는 음성 디테일까지 깎음
      //  - echoCancellation: 스피커폰에서 *상대방 목소리를 에코로 착각해 지움* → 양쪽 캡처 불가
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: false,
          noiseSuppression: false,
          autoGainControl: false,
          channelCount: 1,
        },
      });
      liveStreamRef.current = stream;
      // Opus 압축 손실 줄이려 비트레이트 ↑ (미지원 브라우저는 기본값 fallback)
      let mr: MediaRecorder;
      try {
        mr = new MediaRecorder(stream, { audioBitsPerSecond: 128000 });
      } catch {
        mr = new MediaRecorder(stream);
      }
      mediaRecorderRef.current = mr;
      liveChunksRef.current = [];
      mr.ondataavailable = (e) => {
        if (e.data.size > 0) liveChunksRef.current.push(e.data);
      };
      mr.start(1000); // 1초마다 누적 chunk 확보
      if (isGuest) bumpGuestDaily(); // 실시간 세션 시작 = 오늘 1회 소진
      setLiveActive(true);
      setLiveStarting(false);
      const mime = mr.mimeType;
      // legacy fallback: 5초마다 최근 LIVE_WINDOW_SEC 초만 STT (비용·지연 bound)
      liveTimerRef.current = setInterval(() => {
        void sendLiveCumulative(mime, LIVE_WINDOW_SEC, false);
      }, 5000);
    } catch (err) {
      setLiveError(
        err instanceof Error
          ? `마이크 권한이 필요합니다 (${err.message})`
          : "마이크 권한이 필요합니다.",
      );
      stopLiveCapture();
      setLiveStarting(false);
      setLiveStartedAt(null);
      setLiveActive(false);
    }
  }

  async function stopLive() {
    if (usingWsRef.current) {
      setLiveFinalizing(true);
      setLiveFinalAnalysisPhase("running");
      setLiveFinalAnalysis(null);
      setLiveFinalAnalysisError("");
      finalAnalyzeStartedRef.current = false;
      liveWs.stop();
      usingWsRef.current = false;
      setLiveActive(false);
      return;
    }
    if (usingPcmRef.current) {
      setLiveFinalizing(true);
      setLiveFinalAnalysisPhase("running");
      setLiveFinalAnalysis(null);
      setLiveFinalAnalysisError("");
      const transcriptBeforeStop = livePcm.transcript || liveTranscript;
      await livePcm.stop();
      usingPcmRef.current = false;
      setLiveTransportMode(null);
      setLiveActive(false);
      await analyzeLiveFinalTranscript(livePcm.transcript || transcriptBeforeStop);
      return;
    }
    const mr = mediaRecorderRef.current;
    const mime = mr?.mimeType ?? "audio/webm";
    // 중지 = full 분석 1회 (window_sec=0) → 전체 전사·화자분리(타임스탬프 full 오디오 정합).
    // 윈도우 turn 은 타임스탬프가 윈도우 기준이라, full 분석 올 때까지 말풍선 숨김(finalizing).
    setLiveFinalizing(true);
    setLiveFinalAnalysisPhase("running");
    setLiveFinalAnalysis(null);
    setLiveFinalAnalysisError("");
    setLiveTurns([]);
    void sendLiveCumulative(mime, 0, true).then((text) => {
      void analyzeLiveFinalTranscript(text || liveTranscript);
    });
    // 캡처한 누적 오디오로 재생용 blob URL 생성 (cleanup 이 chunks 를 비우기 전에).
    const chunks = liveChunksRef.current;
    if (chunks.length) {
      const url = URL.createObjectURL(new Blob(chunks, { type: mime }));
      setLiveAudioUrl((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return url;
      });
    }
    stopLiveCapture();
    setLiveActive(false);
  }

  const submitting =
    transcriptPhase === "running" ||
    analysisPhase === "running" ||
    streamPhase === "running";

  // 단일 모드 — pipeline 결과 + transcript 의 regex 백업 검출 합치기.
  // classifier/LLM 이 놓친 명백한 보이스피싱 키워드를 surface.
  const singleScan = (() => {
    const text = transcript?.transcript_text ?? analysis?.transcript_text ?? "";
    if (!text) return { matches: [] as StreamMatch[], level: 0 };
    return scanTranscript(text);
  })();

  const signals = analysis?.detected_signals ?? analysis?.triggered_flags ?? [];
  const liveFinalSignals =
    liveFinalAnalysis?.detected_signals ?? liveFinalAnalysis?.triggered_flags ?? [];

  return (
    <section className="rounded-3xl border border-[#bbf7d0] bg-white p-8 shadow-[0_2px_12px_rgba(0,0,0,0.05)]">
      {guestBlocked ? (
        <div
          className="fixed inset-0 z-[80] flex items-center justify-center overflow-y-auto bg-[#191f28]/50 p-4 sm:p-6"
          onClick={() => setGuestBlocked(false)}
          role="dialog"
          aria-modal="true"
        >
          <div
            className="my-auto flex w-full max-w-sm flex-col"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="relative rounded-3xl border border-[#e5e8eb] bg-white p-7 text-center shadow-[0_8px_30px_rgba(0,0,0,0.12)]">
              <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-[#fff1f0] text-3xl">
                ⛔
              </span>
              <h3 className="mt-4 text-lg font-bold text-[#191f28]">
                오늘 비회원 분석 한도를 모두 썼어요
              </h3>
              <p className="mt-2 text-sm leading-6 text-[#4e5968]">
                비회원은 하루 {GUEST_DAILY_LIMIT}회까지 분석할 수 있어요(라이브 음성 포함).
                로그인하면 이어서 계속 이용할 수 있어요.
              </p>
              <div className="mt-6 space-y-2">
                <button
                  type="button"
                  onClick={() => signIn("google", { callbackUrl: "/live" })}
                  className="flex w-full items-center justify-center gap-2 rounded-2xl bg-[#3182f6] px-5 py-3 text-sm font-semibold text-white transition hover:bg-[#1b64da]"
                >
                  <svg className="h-4 w-4" viewBox="0 0 48 48" aria-hidden>
                    <path fill="#fff" d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3 0 5.8 1.1 7.9 3l5.7-5.7C34.1 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
                  </svg>
                  Google 로 로그인
                </button>
                <button
                  type="button"
                  onClick={() => setGuestBlocked(false)}
                  className="inline-flex w-full items-center justify-center rounded-2xl px-5 py-3 text-sm font-semibold text-[#8b95a1] transition hover:bg-[#f2f4f6]"
                >
                  닫기
                </button>
              </div>
            </div>
          </div>
        </div>
      ) : null}
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-semibold text-[#191f28]">
          🎙️ 통화 중 실시간 분석
        </h2>
        <span className="rounded-full border border-amber-300/40 bg-amber-400/10 px-2.5 py-0.5 text-[10px] font-medium tracking-wide text-amber-700 uppercase">
          Live v4 · {liveTransport === "websocket" ? "WebSocket" : liveTransport === "http-pcm" ? "PCM HTTP" : "HTTP"}
        </span>
      </div>
      <p className="mt-2 text-xs leading-6 text-[#8b95a1]">
        핵심은 <strong>통화 중 실시간 감지</strong> — Live v4는 <strong>3초 chunk WebSocket STT</strong>로 더 빠르게 전사합니다.{" "}
        녹음 파일은 <strong>1분씩 스트리밍</strong> 또는 <strong>전체 분석</strong>으로 테스트할 수 있어요.
      </p>

      <div className="mt-4 inline-flex flex-wrap rounded-full border border-[#bbf7d0] bg-white p-1 text-xs">
        {(
          [
            { v: "live" as Mode, label: "🎤 실시간 마이크" },
            { v: "stream" as Mode, label: "🔴 1분씩 스트리밍 + 화면 경고" },
            { v: "single" as Mode, label: "🔍 전체 분석" },
          ] as const
        ).map((opt) => (
          <button
            key={opt.v}
            type="button"
            disabled={submitting}
            onClick={() => {
              setMode(opt.v);
              reset();
            }}
            className={`rounded-full px-4 py-1.5 transition ${
              mode === opt.v
                ? "bg-[#16a34a] text-white shadow"
                : "text-[#4e5968] hover:text-[#191f28]"
            } disabled:cursor-not-allowed disabled:opacity-50`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {mode !== "live" && (
      <form onSubmit={handleSubmit} className="mt-5 space-y-4">
        <label className="flex flex-col gap-2 text-sm text-[#333d4b]">
          <span className="font-medium text-[#15803d]">
            음성 파일 (mp3, wav, m4a 등)
          </span>
          <input
            type="file"
            accept="audio/*,.mp3,.wav,.m4a,.aac,.ogg,.flac,.webm"
            onChange={(e) => {
              setFile(e.target.files?.[0] ?? null);
              reset();
            }}
            disabled={submitting}
            className="block w-full cursor-pointer rounded-2xl border border-[#bbf7d0] bg-white px-4 py-3 text-sm text-[#333d4b] file:mr-4 file:rounded-full file:border-0 file:bg-[#dcfce7] file:px-4 file:py-1.5 file:text-xs file:font-semibold file:text-[#15803d] hover:file:bg-[#bbf7d0] disabled:cursor-not-allowed disabled:opacity-50"
          />
          {file && (
            <span className="text-xs text-[#8b95a1]">
              선택됨: {file.name} ({(file.size / 1024 / 1024).toFixed(2)} MB)
            </span>
          )}
        </label>

        <button
          type="submit"
          disabled={!file || submitting}
          className="rounded-2xl bg-[#16a34a] px-5 py-2.5 text-sm font-semibold text-white shadow-lg transition hover:bg-[#15803d] disabled:cursor-not-allowed disabled:bg-[#e5e8eb] disabled:text-[#8b95a1] disabled:shadow-none"
        >
          {submitting ? "처리 중..." : "🚨 전사 + 신호 검출 시작"}
        </button>
      </form>
      )}

      {/* === 🎤 실시간 마이크 모드 === */}
      {mode === "live" && (
        <section className="mt-5 rounded-2xl border border-[#bbf7d0] bg-white p-5">
          {tier >= 3 && !dangerDismissed && (
            <DangerOverlay
              matches={cumulativeMatches}
              onDismiss={() => setDangerDismissed(true)}
            />
          )}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-base font-semibold text-[#191f28]">
              🎤 실시간 마이크 분석 {liveActive && <span className="animate-pulse text-rose-600">● REC</span>}
            </h3>
            {liveLatency > 0 && (
              <span className="text-[10px] text-[#8b95a1]">분석 {liveLatency}ms</span>
            )}
          </div>
          <p className="mt-2 text-xs leading-5 text-[#8b95a1]">
            통화를 <strong>스피커폰</strong>으로 두고 시작하세요. WebSocket 또는 PCM HTTP로 16kHz 스트림 →
            <strong> 3초마다 Whisper 전사</strong> 후 위험 신호를 표시합니다.
            시작 시 <strong>알림 권한</strong>을 허용하면 OS 알림으로도 경보가 떠요.
          </p>

          {liveError && (
            <div className="mt-3 rounded-xl border border-rose-400/50 bg-rose-500/10 px-4 py-3 text-sm text-rose-700">
              {liveError}
            </div>
          )}

          <div className="mt-4 flex items-center gap-3">
            {!liveActive && !liveStarting ? (
              <button
                type="button"
                onClick={() => void startLive()}
                className="rounded-2xl bg-[#16a34a] px-5 py-2.5 text-sm font-semibold text-white shadow-lg transition hover:bg-[#15803d]"
              >
                🎤 실시간 분석 시작
              </button>
            ) : liveStarting ? (
              <button
                type="button"
                disabled
                className="rounded-2xl bg-[#d1d5db] px-5 py-2.5 text-sm font-semibold text-white"
              >
                마이크 연결 중...
              </button>
            ) : (
              <button
                type="button"
                onClick={stopLive}
                className="rounded-2xl border border-[#e5e8eb] bg-[#f2f4f6] px-5 py-2.5 text-sm font-semibold text-[#4e5968] transition hover:bg-[#eef1f4]"
              >
                ⏹ 중지
              </button>
            )}
          </div>

          {(liveStarting || liveActive) && (
            <div className="mt-4 overflow-hidden rounded-2xl border border-[#bbf7d0] bg-[#f8fff9]">
              <div className="grid gap-0 sm:grid-cols-4">
                <div className="border-b border-[#e5e8eb] p-4 sm:border-b-0 sm:border-r">
                  <div className="text-[10px] font-bold uppercase tracking-wide text-[#8b95a1]">상태</div>
                  <div className="mt-1 flex items-center gap-2 text-sm font-bold text-[#191f28]">
                    <span className={`h-2.5 w-2.5 rounded-full ${liveActive ? "animate-pulse bg-rose-500" : "bg-amber-400"}`} />
                    {liveActive ? "듣는 중" : "연결 중"}
                  </div>
                </div>
                <div className="border-b border-[#e5e8eb] p-4 sm:border-b-0 sm:border-r">
                  <div className="text-[10px] font-bold uppercase tracking-wide text-[#8b95a1]">전송</div>
                  <div className="mt-1 text-sm font-bold text-[#191f28]">
                    {liveTransport === "websocket" ? "WebSocket" : liveTransport === "http-pcm" ? "PCM HTTP" : "Legacy HTTP"}
                  </div>
                </div>
                <div className="border-b border-[#e5e8eb] p-4 sm:border-b-0 sm:border-r">
                  <div className="text-[10px] font-bold uppercase tracking-wide text-[#8b95a1]">첫 전사</div>
                  <div className="mt-1 text-sm font-bold text-[#191f28]">
                    {liveTranscript
                      ? "도착"
                      : liveElapsedSec < liveChunkSec
                        ? `약 ${liveChunkSec - liveElapsedSec}초`
                        : "전사 처리 중"}
                  </div>
                </div>
                <div className="p-4">
                  <div className="text-[10px] font-bold uppercase tracking-wide text-[#8b95a1]">경과</div>
                  <div className="mt-1 text-sm font-bold text-[#191f28]">{liveElapsedSec}초</div>
                </div>
              </div>
              {!liveTranscript ? (
                <div className="border-t border-[#e5e8eb] px-4 py-3 text-xs leading-5 text-[#4e5968]">
                  지금 마이크 입력을 받고 있습니다. 짧게 “검찰청이라고 하는데 이상해요”처럼 말하면
                  첫 chunk 전사 후 바로 아래에 텍스트와 검출 신호가 나타납니다.
                </div>
              ) : null}
            </div>
          )}

          {/* 🔴 dismiss 후 잔류 빨간 바 */}
          {tier >= 3 && (
            <button
              type="button"
              onClick={() => setDangerDismissed(false)}
              className="mt-4 flex w-full items-center gap-3 rounded-2xl border border-rose-400/60 bg-rose-600/25 px-5 py-4 text-left text-rose-50 hover:bg-rose-600/35"
            >
              <span className="text-2xl leading-none">🚨</span>
              <span>
                <span className="block text-base font-bold">위험 신호 감지됨 — 통화를 끊으세요</span>
                <span className="mt-0.5 block text-xs opacity-90">전체 경보 다시 보기</span>
              </span>
            </button>
          )}
          {tier === 2 && <CautionBanner matches={cumulativeMatches} />}

          {/* 화자 분리 대화 (말풍선) — 중지 후 클릭하면 해당 음성 재생 */}
          {liveFinalizing ? (
            <div className="mt-4 rounded-xl border border-dashed border-[#e5e8eb] bg-white px-4 py-6 text-center text-sm text-[#8b95a1]">
              ⏳ 전체 통화 분석 마무리 중… (완료되면 말풍선 클릭으로 음성 재생 가능)
            </div>
          ) : liveTurns.length > 0 ? (
            <div className="mt-4 rounded-xl border border-[#e5e8eb] bg-white px-4 py-3">
              <div className="mb-2 flex items-center justify-between text-[11px] font-semibold text-[#4e5968]">
                <span>화자 분리 대화</span>
                {liveAudioUrl ? (
                  <span className="text-emerald-600">▶️ 말풍선 클릭 → 해당 음성 재생</span>
                ) : (
                  <span className="opacity-60">중지하면 말풍선 클릭으로 음성 재생</span>
                )}
              </div>
              <Conversation turns={liveTurns} audioUrl={liveAudioUrl} />
            </div>
          ) : (
            liveTranscript && (
              <div className="mt-4 rounded-xl border border-[#e5e8eb] bg-white px-4 py-3">
                <div className="mb-1 text-[11px] font-semibold text-[#4e5968]">실시간 전사</div>
                <p className="max-h-40 overflow-y-auto whitespace-pre-wrap text-sm leading-6 text-[#191f28]">
                  {liveTranscript}
                </p>
              </div>
            )
          )}

          {liveFinalAnalysisPhase !== "idle" && (
            <div className="mt-4 rounded-2xl border border-[#bbf7d0] bg-white p-4">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <h4 className="text-sm font-semibold text-[#191f28]">
                  🧠 중지 후 전체 전사 재분석
                </h4>
                <PhaseBadge phase={liveFinalAnalysisPhase} prefix="최종 분석" />
              </div>

              {liveFinalAnalysisPhase === "running" ? (
                <p className="mt-3 text-sm leading-6 text-[#8b95a1]">
                  지금까지 모인 전체 전사 텍스트를 다시 합쳐 분류 · 엔티티 추출 · LLM 보조 분석을 실행 중입니다.
                </p>
              ) : null}

              {liveFinalAnalysisPhase === "error" ? (
                <p className="mt-3 text-sm leading-6 text-rose-700">{liveFinalAnalysisError}</p>
              ) : null}

              {liveFinalAnalysis ? (
                <div className="mt-3 space-y-3">
                  <div className="rounded-xl bg-[#f8fafc] p-3">
                    <div className="text-[11px] font-semibold text-[#8b95a1]">최종 요약</div>
                    <p className="mt-1 text-sm leading-6 text-[#191f28]">
                      {liveFinalAnalysis.summary ??
                        `전체 통화 전사에서 위험 신호 ${liveFinalSignals.length}개가 검출되었습니다.`}
                    </p>
                  </div>

                  <div className="flex flex-wrap gap-2">
                    {liveFinalAnalysis.scam_type ? (
                      <span className="rounded-full bg-[#f2f4f6] px-3 py-1 text-xs font-medium text-[#333d4b]">
                        추정 유형: {liveFinalAnalysis.scam_type}
                      </span>
                    ) : null}
                    {typeof liveFinalAnalysis.classification_confidence === "number" ? (
                      <span className="rounded-full bg-[#f2f4f6] px-3 py-1 text-xs font-medium text-[#4e5968]">
                        신뢰도 {Math.round(liveFinalAnalysis.classification_confidence * 100)}%
                      </span>
                    ) : null}
                    <span className="rounded-full bg-[#dcfce7] px-3 py-1 text-xs font-bold text-[#15803d]">
                      전체 전사 기준 {liveFinalSignals.length}개 신호
                    </span>
                  </div>

                  {liveFinalSignals.length > 0 ? (
                    <ul className="space-y-1.5">
                      {liveFinalSignals.map((signal, index) => (
                        <li
                          key={`${signal.flag}-${index}`}
                          className="rounded-xl border border-[#e5e8eb] bg-[#fafbfc] px-3 py-2 text-xs"
                        >
                          <div className="font-semibold text-rose-700">{flagLabel(signal)}</div>
                          <div className="mt-0.5 text-[#8b95a1]">{signal.flag}</div>
                          {signal.rationale ? (
                            <p className="mt-1 leading-5 text-[#8b95a1]">{signal.rationale}</p>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="text-sm text-[#8b95a1]">전체 전사 기준으로 검출된 위험 신호가 없습니다.</p>
                  )}
                </div>
              ) : null}
            </div>
          )}

          {/* 누적 검출 신호 */}
          {cumulativeMatches.length > 0 && (
            <div className="mt-4 rounded-xl border border-[#e5e8eb] bg-white p-4">
              <h4 className="text-sm font-semibold text-[#191f28]">
                🚨 검출 신호 ({cumulativeMatches.length}개)
              </h4>
              <ul className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
                {cumulativeMatches.map((m, i) => (
                  <li
                    key={`live-${m.flag}-${i}`}
                    className={`rounded-full px-2 py-0.5 ${
                      m.instant
                        ? "border border-rose-400/60 bg-rose-500/20 text-rose-50"
                        : "border border-amber-400/40 bg-amber-500/15 text-amber-700"
                    }`}
                  >
                    {speakerTag(m.speaker) ? speakerTag(m.speaker) + " · " : ""}{m.label_ko}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="mt-4 text-[11px] leading-5 text-[#8b95a1]">
            ⚠️ iOS 는 통화 중 브라우저 마이크 접근이 제한됩니다 — 스피커폰 + 별도 기기 권장.
            ScamGuardian 은 신호만 알려드려요, 최종 판단은 본인이.
          </p>
        </section>
      )}

      {mode === "single" && (transcriptPhase !== "idle" || analysisPhase !== "idle") && (
        <section className="mt-6 rounded-2xl border border-[#bbf7d0] bg-white p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-base font-semibold text-[#191f28]">🔍 검출 결과</h3>
            <div className="flex flex-wrap gap-2 text-[10px]">
              <PhaseBadge phase={transcriptPhase} prefix="전사" />
              <PhaseBadge phase={analysisPhase} prefix="분석" />
            </div>
          </div>

          {/* === 1) 전사된 텍스트 (검출 결과 안에 직접 노출) === */}
          <div className="mt-4 rounded-xl border border-[#e5e8eb] bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-sm font-semibold text-[#191f28]">
                📝 전사된 텍스트
              </h4>
              <code className="rounded bg-[#f2f4f6] px-1.5 py-0.5 text-[10px] text-[#8b95a1]">
                POST /api/transcribe-upload
              </code>
            </div>
            {transcriptPhase === "running" && (
              <p className="mt-3 text-sm text-[#8b95a1]">음성 인식 중...</p>
            )}
            {transcriptPhase === "error" && (
              <p className="mt-3 text-sm text-rose-700">{transcriptError}</p>
            )}
            {transcript && (
              <>
                <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
                  {transcript.language && (
                    <span className="rounded-full bg-white px-2 py-0.5 text-[#4e5968]">
                      lang: {transcript.language}
                    </span>
                  )}
                  {typeof transcript.latency_ms === "number" && (
                    <span className="rounded-full bg-white px-2 py-0.5 text-[#4e5968]">
                      {transcript.latency_ms} ms
                    </span>
                  )}
                  <span className="rounded-full bg-white px-2 py-0.5 text-[#4e5968]">
                    {transcript.transcript_text.length} chars
                  </span>
                </div>
                {transcript.turns && transcript.turns.length > 0 ? (
                  <div className="mt-3 max-h-96 overflow-y-auto rounded-lg border border-[#eef1f4] bg-[#f2f4f6] p-3">
                    <Conversation turns={transcript.turns} audioUrl={audioUrl} />
                  </div>
                ) : (
                  <p className="mt-3 max-h-72 overflow-y-auto whitespace-pre-wrap rounded-lg border border-[#eef1f4] bg-[#f2f4f6] p-3 text-sm leading-7 text-[#191f28]">
                    {transcript.transcript_text || "(빈 텍스트)"}
                  </p>
                )}
              </>
            )}
          </div>

          {/* === 2) 신호 검출 (같은 검출 결과 컨테이너 안) === */}
          <div className="mt-4 rounded-xl border border-[#e5e8eb] bg-white p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-sm font-semibold text-[#191f28]">
                🚨 검출된 신호
              </h4>
              <code className="rounded bg-[#f2f4f6] px-1.5 py-0.5 text-[10px] text-[#8b95a1]">
                POST /api/analyze-upload
              </code>
            </div>
            {analysisPhase === "running" && (
              <p className="mt-3 text-sm text-[#8b95a1]">
                분류 · 엔티티 추출 · 검출 중...
              </p>
            )}
            {analysisPhase === "error" && (
              <p className="mt-3 text-sm text-rose-700">{analysisError}</p>
            )}
            {analysis && (
              <>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {analysis.scam_type && (
                    <span className="rounded-full bg-[#f2f4f6] px-3 py-1 text-xs text-[#333d4b]">
                      추정 유형: {analysis.scam_type}
                    </span>
                  )}
                  {typeof analysis.classification_confidence === "number" && (
                    <span className="rounded-full bg-white px-3 py-1 text-xs text-[#4e5968]">
                      신뢰도 {Math.round(analysis.classification_confidence * 100)}%
                    </span>
                  )}
                </div>

                {singleScan.matches.length > 0 && (
                  <div className="mt-3 rounded-xl border border-rose-400/30 bg-rose-500/10 p-3">
                    <div className="text-xs font-semibold text-rose-700">
                      🔎 키워드 검출 (regex backup · {singleScan.matches.length}개)
                    </div>
                    <ul className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
                      {singleScan.matches.map((m, i) => (
                        <li
                          key={`scan-${m.flag}-${i}`}
                          className="rounded-full border border-rose-400/40 bg-rose-500/15 px-2 py-0.5 text-rose-700"
                        >
                          {speakerTag(m.speaker) ? speakerTag(m.speaker) + " · " : ""}{m.label_ko} · &ldquo;{m.snippet}&rdquo;
                        </li>
                      ))}
                    </ul>
                    <p className="mt-2 text-[10px] text-rose-600/70">
                      pipeline 분류기·LLM 이 놓쳐도 명백한 패턴은 여기로 surface.
                    </p>
                  </div>
                )}

                {signals.length > 0 ? (
                  <ul className="mt-3 space-y-1.5">
                    {signals.map((s, i) => (
                      <li
                        key={`${s.flag}-${i}`}
                        className="rounded-xl border border-[#e5e8eb] bg-white px-3 py-2 text-xs"
                      >
                        <div className="font-semibold text-rose-700">
                          {flagLabel(s)}
                        </div>
                        <div className="text-[#8b95a1]">{s.flag}</div>
                        {s.rationale && (
                          <div className="mt-1 text-[11px] leading-5 text-[#8b95a1]">
                            {s.rationale}
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : singleScan.matches.length === 0 ? (
                  <p className="mt-3 text-sm text-[#8b95a1]">
                    검출된 위험 신호가 없습니다.
                  </p>
                ) : (
                  <p className="mt-3 text-xs text-[#8b95a1]">
                    pipeline 검출 신호 없음 — 위 키워드 검출만 surface 됨.
                  </p>
                )}
                <p className="mt-3 text-[11px] leading-5 text-[#8b95a1]">
                  ScamGuardian 은 신호 검출만 보고합니다. 자세한 근거는{" "}
                  <a
                    href="/evidence"
                    className="text-[#16a34a] underline hover:text-[#15803d]"
                  >
                    EVIDENCE
                  </a>{" "}
                  참조.
                </p>
              </>
            )}
          </div>
        </section>
      )}

      {mode === "stream" && streamPhase !== "idle" && (
        <section className="mt-6 rounded-2xl border border-[#bbf7d0] bg-white p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-base font-semibold text-[#191f28]">
              🔴 실시간 검출 결과 (1분씩 스트리밍)
            </h3>
            <PhaseBadge phase={streamPhase} prefix="스트림" />
          </div>

          {streamError && (
            <div className="mt-3 rounded-xl border border-rose-400/50 bg-rose-500/10 px-4 py-3 text-sm text-rose-700">
              {streamError}
            </div>
          )}

          {/* === 계층적 알림 — tier 단조 증가 === */}
          {/* 🔴 danger 풀스크린 takeover (확인 누르면 dismiss, 다시 누르면 재노출) */}
          {tier >= 3 && !dangerDismissed && (
            <DangerOverlay
              matches={cumulativeMatches}
              onDismiss={() => setDangerDismissed(true)}
            />
          )}
          {/* 🔴 dismiss 후에도 남는 빨간 바 */}
          {tier >= 3 && (
            <button
              type="button"
              onClick={() => setDangerDismissed(false)}
              className="mt-4 flex w-full items-center gap-3 rounded-2xl border border-rose-400/60 bg-rose-600/25 px-5 py-4 text-left text-rose-50 hover:bg-rose-600/35"
            >
              <span className="text-2xl leading-none">🚨</span>
              <span>
                <span className="block text-base font-bold">위험 신호 감지됨 — 통화 중이라면 끊으세요</span>
                <span className="mt-0.5 block text-xs opacity-90">전체 경보 다시 보기</span>
              </span>
            </button>
          )}
          {/* 🟠 caution 배너 (pulse) */}
          {tier === 2 && <CautionBanner matches={cumulativeMatches} />}

          {/* 진행률 */}
          <div className="mt-4 flex items-center gap-3 text-xs text-[#4e5968]">
            <span>
              진행: {streamHistory.length}
              {streamTotal > 0 && ` / ${streamTotal}`} 청크
            </span>
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white">
              <div
                className="h-full bg-rose-400/70 transition-all"
                style={{
                  width:
                    streamTotal > 0
                      ? `${Math.min(100, (streamHistory.length / streamTotal) * 100)}%`
                      : "5%",
                }}
              />
            </div>
          </div>

          {/* === 청크 네비게이션 — 칩 클릭으로 이전 청크 다시 보기 === */}
          {streamHistory.length > 0 && (() => {
            const latestIndex = streamHistory.length - 1;
            const activeIdx = selectedChunkIndex ?? latestIndex;
            const activeChunk = streamHistory[activeIdx];
            return (
              <div className="mt-4">
                <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-[#4e5968]">
                  <span className="font-semibold">청크 보기:</span>
                  <div className="flex flex-wrap gap-1.5">
                    {streamHistory.map((c, idx) => {
                      const isActive = idx === activeIdx;
                      const isLatest = idx === latestIndex;
                      const tone =
                        c.alert_level >= 3
                          ? "border-rose-400/60"
                          : c.alert_level === 2
                          ? "border-amber-400/40"
                          : c.alert_level === 1
                          ? "border-yellow-400/30"
                          : "border-[#e5e8eb]";
                      return (
                        <button
                          key={c.chunk_index}
                          type="button"
                          onClick={() =>
                            setSelectedChunkIndex(isLatest ? null : idx)
                          }
                          className={`rounded-full border px-2.5 py-0.5 transition ${tone} ${
                            isActive
                              ? "bg-rose-500/30 text-rose-50"
                              : "bg-[#f2f4f6]/40 text-[#4e5968] hover:bg-[#eef1f4]"
                          }`}
                          title={`${fmtTime(c.start_sec)} ~ ${fmtTime(c.end_sec)}${
                            c.matches.length > 0
                              ? ` · ${c.matches.length}개 검출`
                              : ""
                          }`}
                        >
                          {idx + 1}
                          {isLatest && streamPhase === "running" && (
                            <span className="ml-1 text-[9px]">🔴</span>
                          )}
                          {c.alert_level >= 2 && <span className="ml-0.5">⚠️</span>}
                        </button>
                      );
                    })}
                  </div>
                  {selectedChunkIndex !== null && (
                    <button
                      type="button"
                      onClick={() => setSelectedChunkIndex(null)}
                      className="rounded-full border border-rose-400/40 bg-rose-500/15 px-2.5 py-0.5 text-rose-700 hover:bg-rose-500/25"
                    >
                      최신 follow ↑
                    </button>
                  )}
                </div>

                <div className="mb-1.5 flex items-center justify-between gap-2">
                  <h4 className="text-sm font-semibold text-[#191f28]">
                    📝 전사 청크 {activeIdx + 1}/{streamHistory.length}
                    {selectedChunkIndex === null ? " (최신 follow)" : " (이전 보기)"}
                  </h4>
                  <span className="text-[10px] text-[#8b95a1]">
                    {fmtTime(activeChunk.start_sec)} ~ {fmtTime(activeChunk.end_sec)}
                    {" · "}
                    {activeChunk.latency_ms} ms
                  </span>
                </div>
                <ChunkRow chunk={activeChunk} />
                {streamPhase === "running" && selectedChunkIndex === null && (
                  <div className="mt-1.5 rounded-xl border border-dashed border-[#e5e8eb] bg-white px-4 py-2 text-[11px] text-[#8b95a1]">
                    다음 청크 처리 중 — 도착 시 자동으로 최신으로 이동. 위 칩에서 이전 청크 클릭하면 거기 머무름.
                  </div>
                )}
              </div>
            );
          })()}
          {streamHistory.length === 0 && (
            <div className="mt-4 rounded-xl border border-dashed border-[#e5e8eb] bg-white px-4 py-3 text-xs text-[#8b95a1]">
              첫 청크 처리 대기 중...
            </div>
          )}

          {/* === 누적 검출 신호 — 청크 사라져도 유지 === */}
          {cumulativeMatches.length > 0 && (
            <div className="mt-4 rounded-xl border border-[#e5e8eb] bg-white p-4">
              <h4 className="text-sm font-semibold text-[#191f28]">
                🚨 누적 검출 신호 ({cumulativeMatches.length}개)
              </h4>
              <ul className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
                {cumulativeMatches.map((m, i) => (
                  <li
                    key={`cum-${m.flag}-${i}`}
                    className={`rounded-full px-2 py-0.5 ${
                      m.level >= 3
                        ? "border border-rose-400/60 bg-rose-500/20 text-rose-50"
                        : m.level === 2
                        ? "border border-amber-400/40 bg-amber-500/15 text-amber-700"
                        : "border border-yellow-400/30 bg-yellow-500/10 text-yellow-700"
                    }`}
                  >
                    {speakerTag(m.speaker) ? speakerTag(m.speaker) + " · " : ""}{m.label_ko} · &ldquo;{m.snippet}&rdquo;
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="mt-4 text-[11px] leading-5 text-[#8b95a1]">
            ScamGuardian 은 신호 검출만 보고합니다 — 판정은 통합 기업의 logic.
            자세한 근거는{" "}
            <a href="/evidence" className="text-[#16a34a] underline hover:text-[#15803d]">
              EVIDENCE
            </a>
            .
          </p>
        </section>
      )}
    </section>
  );
}
