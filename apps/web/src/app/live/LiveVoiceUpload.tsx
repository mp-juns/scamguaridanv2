"use client";

import { useEffect, useRef, useState } from "react";

type DetectedSignal = {
  flag: string;
  score_delta?: number;
  label_ko?: string;
  rationale?: string;
  source?: string;
  evidence?: Record<string, unknown>;
};

type AnalysisResult = {
  scam_type?: string;
  classification_confidence?: number;
  detected_signals?: DetectedSignal[];
  triggered_flags?: DetectedSignal[];
  transcript_text?: string;
  analysis_run_id?: string;
  summary?: string;
  disclaimer?: string;
};

type TurnEntity = {
  label: string;
  text: string;
};

type Turn = {
  speaker: string; // "상대방" | "본인"
  text: string;
  entities?: TurnEntity[];
  start_sec?: number; // CLOVA 가 준 segment 시작 (초) — 재생용
  end_sec?: number;
};

type TranscriptResult = {
  transcript_text: string;
  turns?: Turn[];
  language?: string;
  source_type?: string;
  latency_ms?: number;
  stt_ms?: number;
  diarize_ms?: number;
  source_filename?: string;
};

const FLAG_LABELS_KO: Record<string, string> = {
  abnormal_return_rate: "비정상 수익률 약속",
  urgent_transfer_demand: "즉각 송금 요구",
  fake_government_agency: "공공기관 사칭",
  victim_personal_info_request: "민감정보 요구",
  fake_call_center: "가짜 콜센터",
  malware_detected: "악성코드 검출",
  phishing_url_confirmed: "피싱 URL 확정",
};

function flagLabel(s: DetectedSignal) {
  return s.label_ko ?? FLAG_LABELS_KO[s.flag] ?? s.flag;
}

type Phase = "idle" | "running" | "done" | "error";

type StreamMatch = {
  flag: string;
  label_ko: string;
  level: number;
  snippet: string;
  instant?: boolean; // 돌이킬 수 없는 결정적 신호 (민감정보·송금동의)
  action?: string; // 안전 행동 안내
  speaker?: string | null; // "본인"(피해자) / "상대방"(사기범) / null — 화자별 심각도
};

// 화자 태그 — 같은 신호라도 누가 말했나로 의미가 다름 (본인 발설 = 결정적).
function speakerTag(speaker?: string | null): string {
  if (speaker === "본인") return "🙋 본인";
  if (speaker === "상대방") return "🗣️ 상대방";
  return "";
}

// 라이브 슬라이딩 윈도우용 — 누적 match 를 (flag,snippet,speaker) 로 dedup 병합.
// 같은 발화가 겹치는 윈도우에 중복 등장하는 것 + 동일 flag 반복 부풀림을 함께 방지.
function dedupMergeMatches(
  prev: StreamMatch[],
  incoming: StreamMatch[],
): StreamMatch[] {
  const key = (m: StreamMatch) => `${m.flag}|${m.snippet}|${m.speaker ?? ""}`;
  const seen = new Set(prev.map(key));
  const fresh = incoming.filter((m) => !seen.has(key(m)));
  return fresh.length ? [...prev, ...fresh] : prev;
}

// 누적 dedup match → tier (백엔드 _compute_tier 와 동일 임계). 윈도우 분할로 backend tier
// 가 윈도우 한정이 되므로, 누적 tier 는 프론트가 전체 match 로 계산한다.
const TIER_CAUTION_SCORE = 3;
const TIER_DANGER_SCORE = 6;
function computeTierFromMatches(matches: StreamMatch[]): number {
  if (matches.some((m) => m.instant)) return 3; // 본인 발설·송금동의 = 즉시 danger
  const cum = matches
    .filter((m) => !m.instant)
    .reduce((s, m) => s + m.level, 0);
  if (cum >= TIER_DANGER_SCORE) return 3;
  if (cum >= TIER_CAUTION_SCORE) return 2;
  return matches.length ? 1 : 0;
}

// 🔔 OS 시스템 알림 (크롬 등) — 탭을 안 보고 있을 때 화면 위로 경보. 서버·PII 불필요.
// danger 진입 시 1회. 일부 모바일 브라우저는 SW 없이 생성자를 막으므로 try/catch.
function fireDangerNotification(matches: StreamMatch[]) {
  if (typeof window === "undefined" || !("Notification" in window)) return;
  if (Notification.permission !== "granted") return;
  try {
    const action = pickAlertAction(matches)?.action ?? "지금 통화를 끊으세요.";
    const noti = new Notification("🚨 위험 신호 감지", {
      body: action,
      tag: "scam-danger", // 같은 tag → 중복 알림 안 쌓임
      requireInteraction: true, // 사용자가 닫을 때까지 유지
    });
    noti.onclick = () => {
      window.focus(); // 클릭하면 우리 탭으로 → 풀스크린 경보 노출
      noti.close();
    };
  } catch {
    /* SW 필요 브라우저 등 — 무시 (풀스크린 경보는 그대로 동작) */
  }
}

type StreamChunk = {
  chunk_index: number;
  start_sec: number;
  end_sec: number;
  transcript: string;
  turns?: Turn[];
  alert_level: number;
  matches: StreamMatch[];
  tier?: number; // 0 watch / 1 / 2 caution / 3 danger (단조 증가)
  tier_changed?: boolean; // 이 window 에서 tier 가 올라갔는가
  latency_ms: number;
};

type Mode = "single" | "stream" | "live";

function fmtTime(sec: number) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

// stream_analyze.py 의 regex 패턴과 동기화. pipeline classifier/LLM 이 놓쳤을 때
// 클라이언트 측 backup 검출로 보완 — 명백한 보이스피싱 신호는 무조건 surface.
const SIGNAL_PATTERNS: Array<{
  flag: string;
  regex: RegExp;
  level: number;
  label_ko: string;
}> = [
  { flag: "urgent_transfer_demand", regex: /(즉시|지금|당장|빨리|얼른)[\s\S]{0,12}(송금|이체|보내|입금)/g, level: 3, label_ko: "즉각 송금 요구" },
  { flag: "safe_account_phrase", regex: /안전\s*(계좌|입금|보관)/g, level: 3, label_ko: "안전계좌 사기 키워드" },
  { flag: "fake_government_agency", regex: /(중앙지검|검찰청|금융감독원|경찰청|국정원|금감원|검사|수사관|합동수사본부)/g, level: 2, label_ko: "공공기관 사칭" },
  { flag: "ssn_request", regex: /주민(등록)?\s*번호/g, level: 3, label_ko: "주민번호 요구" },
  { flag: "otp_request", regex: /(OTP|일회용\s*비밀번호|보안카드|인증번호)/g, level: 3, label_ko: "OTP/보안카드/인증번호 요구" },
  { flag: "transfer_agree", regex: /(보내드릴|이체할|송금할|입금할)[\s\S]{0,10}(요|게요|겠습니다|드릴)/g, level: 2, label_ko: "송금 동의 발화" },
  { flag: "meta_aware", regex: /(사기[\s\S]{0,5}같|이상한데|진짜[\s\S]{0,3}인가|이거[\s\S]{0,3}사기)/g, level: 1, label_ko: "메타인식 의심" },
  { flag: "password_request", regex: /비밀번호[\s\S]{0,5}(알려|입력|뭐|뭘|어떻)/g, level: 2, label_ko: "비밀번호 요구" },
  { flag: "app_install_lure", regex: /(앱|어플|어플리케이션|보안[\s\S]{0,3}프로그램|업데이트)[\s\S]{0,8}(설치|다운로드)/g, level: 1, label_ko: "앱 설치 유도" },
  { flag: "urgent_call_demand", regex: /(끊지\s*마|전화\s*끊지|통화\s*유지)/g, level: 2, label_ko: "통화 유지 압박" },
  { flag: "court_summons_threat", regex: /(소환장|소환|조사를?\s*받|해명|출석)/g, level: 2, label_ko: "수사·소환 압박" },
  { flag: "personal_info_leak", regex: /개인정보[\s\S]{0,5}(유출|도용|누출)/g, level: 2, label_ko: "개인정보 유출 협박" },
  { flag: "central_investigation", regex: /(중앙수사|합동수사|특별수사)/g, level: 2, label_ko: "특별/중앙 수사 사칭" },
];

function scanTranscript(text: string) {
  const matches: StreamMatch[] = [];
  let maxLevel = 0;
  for (const p of SIGNAL_PATTERNS) {
    for (const m of text.matchAll(p.regex)) {
      matches.push({ flag: p.flag, label_ko: p.label_ko, level: p.level, snippet: m[0] });
      if (p.level > maxLevel) maxLevel = p.level;
    }
  }
  return { matches, level: maxLevel };
}

export default function LiveVoiceUpload() {
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
  const [mode, setMode] = useState<Mode>("stream");
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
  const liveMatchesRef = useRef<StreamMatch[]>([]); // 누적 dedup match 소스 (tier 계산용)
  const notifiedDangerRef = useRef(false); // danger OS 알림 1회 발사 가드
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const LIVE_WINDOW_SEC = 45; // 실시간 tick 윈도우 (지배 비용 bound)
  const liveStreamRef = useRef<MediaStream | null>(null);
  const liveChunksRef = useRef<Blob[]>([]);
  const liveTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

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
    liveMatchesRef.current = [];
    notifiedDangerRef.current = false;
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

  async function handleSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!file) {
      setAnalysisError("음성 파일을 선택해주세요.");
      return;
    }
    reset();
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
  ) {
    const chunks = liveChunksRef.current;
    if (!chunks.length) return;
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
    } catch {
      /* 일시적 네트워크 오류 무시 — 다음 tick 에 재시도 */
    }
  }

  async function startLive() {
    reset();
    setLiveError("");
    // 🔔 크롬 알림 권한 요청 — 시작 버튼 제스처 안에서. 탭 안 볼 때 OS 토스트로 경보.
    try {
      if ("Notification" in window && Notification.permission === "default") {
        void Notification.requestPermission();
      }
    } catch {
      /* 미지원 브라우저 무시 */
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setLiveError("이 브라우저는 마이크 캡처를 지원하지 않습니다.");
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
      setLiveActive(true);
      const mime = mr.mimeType;
      // ~7초마다 전송 — 백엔드가 최근 LIVE_WINDOW_SEC 초만 STT (비용·지연 bound)
      liveTimerRef.current = setInterval(() => {
        void sendLiveCumulative(mime, LIVE_WINDOW_SEC, false);
      }, 7000);
    } catch (err) {
      setLiveError(
        err instanceof Error
          ? `마이크 권한이 필요합니다 (${err.message})`
          : "마이크 권한이 필요합니다.",
      );
      stopLiveCapture();
      setLiveActive(false);
    }
  }

  function stopLive() {
    const mr = mediaRecorderRef.current;
    const mime = mr?.mimeType ?? "audio/webm";
    // 중지 = full 분석 1회 (window_sec=0) → 전체 전사·화자분리(타임스탬프 full 오디오 정합).
    // 윈도우 turn 은 타임스탬프가 윈도우 기준이라, full 분석 올 때까지 말풍선 숨김(finalizing).
    setLiveFinalizing(true);
    setLiveTurns([]);
    void sendLiveCumulative(mime, 0, true);
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

  return (
    <section className="rounded-3xl border border-rose-400/30 bg-rose-500/5 p-8 backdrop-blur">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-xl font-semibold text-white">
          🎧 녹음 파일로 미리 테스트
        </h2>
        <span className="rounded-full border border-amber-300/40 bg-amber-400/10 px-2.5 py-0.5 text-[10px] font-medium tracking-wide text-amber-200 uppercase">
          Preview · 사전 녹음 sandbox
        </span>
      </div>
      <p className="mt-2 text-xs leading-6 text-slate-400">
        모드 선택 — <strong>전체 분석</strong>: 전사 + 분석 두 API 병렬 1회 호출,{" "}
        <strong>스트리밍 분석</strong>: 1분씩 잘라 각 청크 도착 즉시 표시 + 위험 신호 시 경보음 (v4 시뮬).
      </p>

      <div className="mt-4 inline-flex rounded-full border border-rose-400/30 bg-slate-950/60 p-1 text-xs">
        {(
          [
            { v: "single" as Mode, label: "🔍 전체 분석" },
            { v: "stream" as Mode, label: "🔴 1분씩 스트리밍 + 화면 경고" },
            { v: "live" as Mode, label: "🎤 실시간 마이크" },
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
                ? "bg-rose-500/80 text-white shadow"
                : "text-slate-300 hover:text-white"
            } disabled:cursor-not-allowed disabled:opacity-50`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {mode !== "live" && (
      <form onSubmit={handleSubmit} className="mt-5 space-y-4">
        <label className="flex flex-col gap-2 text-sm text-slate-200">
          <span className="font-medium text-rose-100">
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
            className="block w-full cursor-pointer rounded-2xl border border-rose-400/30 bg-slate-950/40 px-4 py-3 text-sm text-slate-200 file:mr-4 file:rounded-full file:border-0 file:bg-rose-500/20 file:px-4 file:py-1.5 file:text-xs file:font-semibold file:text-rose-100 hover:file:bg-rose-500/30 disabled:cursor-not-allowed disabled:opacity-50"
          />
          {file && (
            <span className="text-xs text-slate-400">
              선택됨: {file.name} ({(file.size / 1024 / 1024).toFixed(2)} MB)
            </span>
          )}
        </label>

        <button
          type="submit"
          disabled={!file || submitting}
          className="rounded-2xl bg-rose-500/80 px-5 py-2.5 text-sm font-semibold text-white shadow-lg shadow-rose-950/30 transition hover:bg-rose-500 disabled:cursor-not-allowed disabled:bg-slate-700/50 disabled:text-slate-400 disabled:shadow-none"
        >
          {submitting ? "처리 중..." : "🚨 전사 + 신호 검출 시작"}
        </button>
      </form>
      )}

      {/* === 🎤 실시간 마이크 모드 === */}
      {mode === "live" && (
        <section className="mt-5 rounded-2xl border border-rose-400/20 bg-slate-950/60 p-5">
          {tier >= 3 && !dangerDismissed && (
            <DangerOverlay
              matches={cumulativeMatches}
              onDismiss={() => setDangerDismissed(true)}
            />
          )}
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-base font-semibold text-white">
              🎤 실시간 마이크 분석 {liveActive && <span className="animate-pulse text-rose-400">● REC</span>}
            </h3>
            {liveLatency > 0 && (
              <span className="text-[10px] text-slate-400">분석 {liveLatency}ms</span>
            )}
          </div>
          <p className="mt-2 text-xs leading-5 text-slate-400">
            통화를 <strong>스피커폰</strong>으로 두고 시작하세요. ~7초마다 최근 음성을 분석해
            화자별 위험 신호를 표시하고, 결정적 신호(본인 민감정보 발설·송금 동의) 시 🔴 경보합니다.
            시작 시 <strong>알림 권한</strong>을 허용하면, 다른 화면을 보고 있어도 🔔 OS 알림으로 경보가 떠요.
          </p>

          {liveError && (
            <div className="mt-3 rounded-xl border border-rose-400/50 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
              {liveError}
            </div>
          )}

          <div className="mt-4 flex items-center gap-3">
            {!liveActive ? (
              <button
                type="button"
                onClick={() => void startLive()}
                className="rounded-2xl bg-rose-500/80 px-5 py-2.5 text-sm font-semibold text-white shadow-lg transition hover:bg-rose-500"
              >
                🎤 실시간 분석 시작
              </button>
            ) : (
              <button
                type="button"
                onClick={stopLive}
                className="rounded-2xl border border-rose-400/50 bg-slate-900/60 px-5 py-2.5 text-sm font-semibold text-rose-100 transition hover:bg-slate-800/60"
              >
                ⏹ 중지
              </button>
            )}
          </div>

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
            <div className="mt-4 rounded-xl border border-dashed border-white/15 bg-slate-950/40 px-4 py-6 text-center text-sm text-slate-400">
              ⏳ 전체 통화 분석 마무리 중… (완료되면 말풍선 클릭으로 음성 재생 가능)
            </div>
          ) : liveTurns.length > 0 ? (
            <div className="mt-4 rounded-xl border border-white/10 bg-slate-950/40 px-4 py-3">
              <div className="mb-2 flex items-center justify-between text-[11px] font-semibold text-slate-300">
                <span>화자 분리 대화</span>
                {liveAudioUrl ? (
                  <span className="text-emerald-300">▶️ 말풍선 클릭 → 해당 음성 재생</span>
                ) : (
                  <span className="opacity-60">중지하면 말풍선 클릭으로 음성 재생</span>
                )}
              </div>
              <Conversation turns={liveTurns} audioUrl={liveAudioUrl} />
            </div>
          ) : (
            liveTranscript && (
              <div className="mt-4 rounded-xl border border-white/10 bg-slate-950/40 px-4 py-3">
                <div className="mb-1 text-[11px] font-semibold text-slate-300">실시간 전사</div>
                <p className="max-h-40 overflow-y-auto whitespace-pre-wrap text-sm leading-6 text-slate-100">
                  {liveTranscript}
                </p>
              </div>
            )
          )}

          {/* 누적 검출 신호 */}
          {cumulativeMatches.length > 0 && (
            <div className="mt-4 rounded-xl border border-rose-400/30 bg-rose-500/5 p-4">
              <h4 className="text-sm font-semibold text-rose-100">
                🚨 검출 신호 ({cumulativeMatches.length}개)
              </h4>
              <ul className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
                {cumulativeMatches.map((m, i) => (
                  <li
                    key={`live-${m.flag}-${i}`}
                    className={`rounded-full px-2 py-0.5 ${
                      m.instant
                        ? "border border-rose-400/60 bg-rose-500/20 text-rose-50"
                        : "border border-amber-400/40 bg-amber-500/15 text-amber-100"
                    }`}
                  >
                    {speakerTag(m.speaker) ? speakerTag(m.speaker) + " · " : ""}{m.label_ko}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="mt-4 text-[11px] leading-5 text-slate-500">
            ⚠️ iOS 는 통화 중 브라우저 마이크 접근이 제한됩니다 — 스피커폰 + 별도 기기 권장.
            ScamGuardian 은 신호만 알려드려요, 최종 판단은 본인이.
          </p>
        </section>
      )}

      {mode === "single" && (transcriptPhase !== "idle" || analysisPhase !== "idle") && (
        <section className="mt-6 rounded-2xl border border-rose-400/20 bg-slate-950/60 p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-base font-semibold text-white">🔍 검출 결과</h3>
            <div className="flex flex-wrap gap-2 text-[10px]">
              <PhaseBadge phase={transcriptPhase} prefix="전사" />
              <PhaseBadge phase={analysisPhase} prefix="분석" />
            </div>
          </div>

          {/* === 1) 전사된 텍스트 (검출 결과 안에 직접 노출) === */}
          <div className="mt-4 rounded-xl border border-white/10 bg-slate-950/80 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-sm font-semibold text-rose-100">
                📝 전사된 텍스트
              </h4>
              <code className="rounded bg-slate-900 px-1.5 py-0.5 text-[10px] text-slate-400">
                POST /api/transcribe-upload
              </code>
            </div>
            {transcriptPhase === "running" && (
              <p className="mt-3 text-sm text-slate-400">음성 인식 중...</p>
            )}
            {transcriptPhase === "error" && (
              <p className="mt-3 text-sm text-rose-200">{transcriptError}</p>
            )}
            {transcript && (
              <>
                <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
                  {transcript.language && (
                    <span className="rounded-full bg-white/5 px-2 py-0.5 text-slate-300">
                      lang: {transcript.language}
                    </span>
                  )}
                  {typeof transcript.latency_ms === "number" && (
                    <span className="rounded-full bg-white/5 px-2 py-0.5 text-slate-300">
                      {transcript.latency_ms} ms
                    </span>
                  )}
                  <span className="rounded-full bg-white/5 px-2 py-0.5 text-slate-300">
                    {transcript.transcript_text.length} chars
                  </span>
                </div>
                {transcript.turns && transcript.turns.length > 0 ? (
                  <div className="mt-3 max-h-96 overflow-y-auto rounded-lg border border-white/5 bg-black/40 p-3">
                    <Conversation turns={transcript.turns} audioUrl={audioUrl} />
                  </div>
                ) : (
                  <p className="mt-3 max-h-72 overflow-y-auto whitespace-pre-wrap rounded-lg border border-white/5 bg-black/40 p-3 text-sm leading-7 text-slate-100">
                    {transcript.transcript_text || "(빈 텍스트)"}
                  </p>
                )}
              </>
            )}
          </div>

          {/* === 2) 신호 검출 (같은 검출 결과 컨테이너 안) === */}
          <div className="mt-4 rounded-xl border border-white/10 bg-slate-950/80 p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className="text-sm font-semibold text-rose-100">
                🚨 검출된 신호
              </h4>
              <code className="rounded bg-slate-900 px-1.5 py-0.5 text-[10px] text-slate-400">
                POST /api/analyze-upload
              </code>
            </div>
            {analysisPhase === "running" && (
              <p className="mt-3 text-sm text-slate-400">
                분류 · 엔티티 추출 · 검출 중...
              </p>
            )}
            {analysisPhase === "error" && (
              <p className="mt-3 text-sm text-rose-200">{analysisError}</p>
            )}
            {analysis && (
              <>
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {analysis.scam_type && (
                    <span className="rounded-full bg-white/10 px-3 py-1 text-xs text-slate-200">
                      추정 유형: {analysis.scam_type}
                    </span>
                  )}
                  {typeof analysis.classification_confidence === "number" && (
                    <span className="rounded-full bg-white/5 px-3 py-1 text-xs text-slate-300">
                      신뢰도 {Math.round(analysis.classification_confidence * 100)}%
                    </span>
                  )}
                </div>

                {singleScan.matches.length > 0 && (
                  <div className="mt-3 rounded-xl border border-rose-400/30 bg-rose-500/10 p-3">
                    <div className="text-xs font-semibold text-rose-100">
                      🔎 키워드 검출 (regex backup · {singleScan.matches.length}개)
                    </div>
                    <ul className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
                      {singleScan.matches.map((m, i) => (
                        <li
                          key={`scan-${m.flag}-${i}`}
                          className="rounded-full border border-rose-400/40 bg-rose-500/15 px-2 py-0.5 text-rose-100"
                        >
                          {speakerTag(m.speaker) ? speakerTag(m.speaker) + " · " : ""}{m.label_ko} · "{m.snippet}"
                        </li>
                      ))}
                    </ul>
                    <p className="mt-2 text-[10px] text-rose-200/70">
                      pipeline 분류기·LLM 이 놓쳐도 명백한 패턴은 여기로 surface.
                    </p>
                  </div>
                )}

                {signals.length > 0 ? (
                  <ul className="mt-3 space-y-1.5">
                    {signals.map((s, i) => (
                      <li
                        key={`${s.flag}-${i}`}
                        className="rounded-xl border border-white/10 bg-white/5 px-3 py-2 text-xs"
                      >
                        <div className="font-semibold text-rose-100">
                          {flagLabel(s)}
                        </div>
                        <div className="text-slate-400">{s.flag}</div>
                        {s.rationale && (
                          <div className="mt-1 text-[11px] leading-5 text-slate-400">
                            {s.rationale}
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                ) : singleScan.matches.length === 0 ? (
                  <p className="mt-3 text-sm text-slate-400">
                    검출된 위험 신호가 없습니다.
                  </p>
                ) : (
                  <p className="mt-3 text-xs text-slate-500">
                    pipeline 검출 신호 없음 — 위 키워드 검출만 surface 됨.
                  </p>
                )}
                <p className="mt-3 text-[11px] leading-5 text-slate-500">
                  ScamGuardian 은 신호 검출만 보고합니다. 자세한 근거는{" "}
                  <a
                    href="/evidence"
                    className="text-rose-300 underline hover:text-rose-200"
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
        <section className="mt-6 rounded-2xl border border-rose-400/20 bg-slate-950/60 p-5">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3 className="text-base font-semibold text-white">
              🔴 실시간 검출 결과 (1분씩 스트리밍)
            </h3>
            <PhaseBadge phase={streamPhase} prefix="스트림" />
          </div>

          {streamError && (
            <div className="mt-3 rounded-xl border border-rose-400/50 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
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
          <div className="mt-4 flex items-center gap-3 text-xs text-slate-300">
            <span>
              진행: {streamHistory.length}
              {streamTotal > 0 && ` / ${streamTotal}`} 청크
            </span>
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-white/5">
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
                <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-300">
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
                          : "border-white/20";
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
                              : "bg-slate-900/40 text-slate-300 hover:bg-slate-800/60"
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
                      className="rounded-full border border-rose-400/40 bg-rose-500/15 px-2.5 py-0.5 text-rose-100 hover:bg-rose-500/25"
                    >
                      최신 follow ↑
                    </button>
                  )}
                </div>

                <div className="mb-1.5 flex items-center justify-between gap-2">
                  <h4 className="text-sm font-semibold text-rose-100">
                    📝 전사 청크 {activeIdx + 1}/{streamHistory.length}
                    {selectedChunkIndex === null ? " (최신 follow)" : " (이전 보기)"}
                  </h4>
                  <span className="text-[10px] text-slate-400">
                    {fmtTime(activeChunk.start_sec)} ~ {fmtTime(activeChunk.end_sec)}
                    {" · "}
                    {activeChunk.latency_ms} ms
                  </span>
                </div>
                <ChunkRow chunk={activeChunk} />
                {streamPhase === "running" && selectedChunkIndex === null && (
                  <div className="mt-1.5 rounded-xl border border-dashed border-white/10 bg-slate-950/40 px-4 py-2 text-[11px] text-slate-500">
                    다음 청크 처리 중 — 도착 시 자동으로 최신으로 이동. 위 칩에서 이전 청크 클릭하면 거기 머무름.
                  </div>
                )}
              </div>
            );
          })()}
          {streamHistory.length === 0 && (
            <div className="mt-4 rounded-xl border border-dashed border-white/10 bg-slate-950/40 px-4 py-3 text-xs text-slate-400">
              첫 청크 처리 대기 중...
            </div>
          )}

          {/* === 누적 검출 신호 — 청크 사라져도 유지 === */}
          {cumulativeMatches.length > 0 && (
            <div className="mt-4 rounded-xl border border-rose-400/30 bg-rose-500/5 p-4">
              <h4 className="text-sm font-semibold text-rose-100">
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
                        ? "border border-amber-400/40 bg-amber-500/15 text-amber-100"
                        : "border border-yellow-400/30 bg-yellow-500/10 text-yellow-100"
                    }`}
                  >
                    {speakerTag(m.speaker) ? speakerTag(m.speaker) + " · " : ""}{m.label_ko} · "{m.snippet}"
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="mt-4 text-[11px] leading-5 text-slate-500">
            ScamGuardian 은 신호 검출만 보고합니다 — 판정은 통합 기업의 logic.
            자세한 근거는{" "}
            <a href="/evidence" className="text-rose-300 underline hover:text-rose-200">
              EVIDENCE
            </a>
            .
          </p>
        </section>
      )}
    </section>
  );
}

// 누적 match 중 가장 우선순위 높은(instant 먼저, 그다음 level 높은) 것의 행동 안내를 고른다.
function pickAlertAction(
  matches: StreamMatch[],
): { action: string; label: string; speaker?: string | null } | null {
  if (!matches.length) return null;
  const sorted = [...matches].sort((a, b) => {
    if (!!b.instant !== !!a.instant) return b.instant ? 1 : -1;
    return b.level - a.level;
  });
  const top = sorted[0];
  return {
    action: top.action ?? "통화를 멈추고, 해당 기관 대표번호로 직접 확인하세요.",
    label: top.label_ko,
    speaker: top.speaker,
  };
}

// 🟠 caution — 누적 주의 신호. 부드러운 pulse 로 시선 유도 (비차단).
function CautionBanner({ matches }: { matches: StreamMatch[] }) {
  const labels = Array.from(
    new Set(matches.map((m) => m.label_ko)),
  ).slice(0, 4);
  return (
    <div
      role="alert"
      className="mt-4 flex animate-pulse items-start gap-3 rounded-2xl border border-amber-400/50 bg-amber-500/15 px-5 py-4 text-amber-100"
    >
      <div className="text-2xl leading-none">⚠️</div>
      <div>
        <div className="text-base font-bold">주의 신호가 쌓이고 있어요</div>
        <div className="mt-1 text-xs leading-5 opacity-90">
          {labels.length ? labels.join(" · ") : "사기 의심 신호"} 감지됨 — 발화 맥락을 다시 확인하세요.
        </div>
      </div>
    </div>
  );
}

// 🔴 danger — 풀스크린 takeover + flash. 행동 안내 + 근거, 확인 버튼으로 dismiss.
function DangerOverlay({
  matches,
  onDismiss,
}: {
  matches: StreamMatch[];
  onDismiss: () => void;
}) {
  const picked = pickAlertAction(matches);
  return (
    <div
      role="alertdialog"
      aria-modal="true"
      className="animate-danger-flash fixed inset-0 z-50 flex flex-col items-center justify-center px-6 text-center"
    >
      <div className="mb-3 text-6xl">🚨</div>
      <div className="text-3xl font-black text-white drop-shadow-lg">
        지금 전화를 끊으세요
      </div>
      {picked && (
        <div className="mt-4 inline-block rounded-full bg-white/15 px-3 py-1 text-sm font-semibold text-white">
          {speakerTag(picked.speaker) ? speakerTag(picked.speaker) + " · " : ""}
          {picked.label}
        </div>
      )}
      {picked && (
        <div className="mt-3 max-w-md text-lg font-semibold text-rose-50">
          {picked.action}
        </div>
      )}
      <div className="mt-3 max-w-md text-sm text-rose-100/90">
        위험 신호가 감지되었습니다. ScamGuardian 은 신호만 알려드려요 — 최종 판단은 본인이 하세요.
      </div>
      <button
        type="button"
        onClick={onDismiss}
        className="mt-8 rounded-full bg-white/95 px-7 py-3 text-base font-bold text-rose-700 shadow-lg hover:bg-white"
      >
        확인했어요
      </button>
    </div>
  );
}

function ChunkRow({ chunk }: { chunk: StreamChunk }) {
  const tone =
    chunk.alert_level >= 3
      ? "border-rose-400/60 bg-rose-500/10"
      : chunk.alert_level === 2
      ? "border-amber-400/40 bg-amber-500/10"
      : chunk.alert_level === 1
      ? "border-yellow-400/30 bg-yellow-500/5"
      : "border-white/10 bg-white/5";
  const badge =
    chunk.alert_level >= 3
      ? { label: "DANGER", tone: "bg-rose-500/80 text-white" }
      : chunk.alert_level === 2
      ? { label: "WARN", tone: "bg-amber-500/80 text-white" }
      : chunk.alert_level === 1
      ? { label: "WATCH", tone: "bg-yellow-400/60 text-slate-900" }
      : { label: "OK", tone: "bg-emerald-500/30 text-emerald-100" };
  return (
    <li className={`rounded-xl border px-4 py-3 ${tone}`}>
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
        <div className="flex items-center gap-2 text-slate-200">
          <span className="font-semibold">청크 {chunk.chunk_index + 1}</span>
          <span className="text-slate-400">
            {fmtTime(chunk.start_sec)} ~ {fmtTime(chunk.end_sec)}
          </span>
          <span className="text-slate-500">· {chunk.latency_ms} ms</span>
        </div>
        <span
          className={`rounded-full px-2 py-0.5 text-[10px] font-bold tracking-wide ${badge.tone}`}
        >
          {badge.label}
        </span>
      </div>
      {chunk.turns && chunk.turns.length > 0 ? (
        <div className="mt-2">
          <Conversation turns={chunk.turns} />
        </div>
      ) : chunk.transcript ? (
        <p className="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-100">
          {chunk.transcript}
        </p>
      ) : (
        <p className="mt-2 text-sm italic text-slate-500">(빈 전사)</p>
      )}
      {chunk.matches.length > 0 && (
        <ul className="mt-2 flex flex-wrap gap-1.5 text-[11px]">
          {chunk.matches.map((m, i) => (
            <li
              key={`${m.flag}-${i}`}
              className="rounded-full border border-rose-400/40 bg-rose-500/10 px-2 py-0.5 text-rose-100"
            >
              {speakerTag(m.speaker) ? speakerTag(m.speaker) + " · " : ""}{m.label_ko} · "{m.snippet}"
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

function PhaseBadge({ phase, prefix }: { phase: Phase; prefix: string }) {
  const badge = (() => {
    switch (phase) {
      case "running":
        return { label: "처리 중", tone: "border-amber-300/40 bg-amber-400/10 text-amber-100" };
      case "done":
        return { label: "완료", tone: "border-emerald-300/40 bg-emerald-400/10 text-emerald-100" };
      case "error":
        return { label: "오류", tone: "border-rose-400/50 bg-rose-500/15 text-rose-100" };
      default:
        return { label: "대기", tone: "border-white/10 bg-white/5 text-slate-300" };
    }
  })();
  return (
    <span
      className={`rounded-full border px-2 py-0.5 uppercase ${badge.tone}`}
    >
      {prefix} · {badge.label}
    </span>
  );
}

function Conversation({
  turns,
  audioUrl,
}: {
  turns: Turn[];
  audioUrl?: string | null;
}) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const pauseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [playingIndex, setPlayingIndex] = useState<number | null>(null);

  const playSegment = (index: number, turn: Turn) => {
    if (!audioRef.current || turn.start_sec == null || turn.end_sec == null)
      return;
    if (pauseTimerRef.current) {
      clearTimeout(pauseTimerRef.current);
      pauseTimerRef.current = null;
    }
    audioRef.current.currentTime = turn.start_sec;
    void audioRef.current.play().catch(() => {});
    setPlayingIndex(index);
    const durationMs = Math.max(200, (turn.end_sec - turn.start_sec) * 1000);
    pauseTimerRef.current = setTimeout(() => {
      audioRef.current?.pause();
      setPlayingIndex(null);
    }, durationMs);
  };

  const stopPlayback = () => {
    if (pauseTimerRef.current) {
      clearTimeout(pauseTimerRef.current);
      pauseTimerRef.current = null;
    }
    audioRef.current?.pause();
    setPlayingIndex(null);
  };

  return (
    <div className="space-y-2">
      {audioUrl && (
        <audio
          ref={audioRef}
          src={audioUrl}
          preload="metadata"
          onEnded={stopPlayback}
        />
      )}
      {turns.map((t, i) => {
        const isOther = t.speaker === "상대방";
        const canPlay = !!audioUrl && t.start_sec != null && t.end_sec != null;
        const isPlaying = playingIndex === i;
        return (
          <div
            key={i}
            className={`flex ${isOther ? "justify-start" : "justify-end"}`}
          >
            <div
              onClick={
                canPlay
                  ? () => (isPlaying ? stopPlayback() : playSegment(i, t))
                  : undefined
              }
              title={canPlay ? "클릭하면 이 발화 음성 재생" : undefined}
              className={`max-w-[80%] rounded-2xl px-3 py-2 text-sm leading-6 ${
                canPlay ? "cursor-pointer" : ""
              } ${
                isOther
                  ? "rounded-tl-sm bg-rose-500/15 text-rose-50"
                  : "rounded-tr-sm bg-sky-500/15 text-sky-50"
              }`}
            >
              <div
                className={`mb-0.5 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-wider ${
                  isOther ? "text-rose-200/70" : "text-sky-200/70"
                }`}
              >
                <span>{t.speaker}</span>
                {canPlay && (
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      if (isPlaying) stopPlayback();
                      else playSegment(i, t);
                    }}
                    className={`rounded-full px-1.5 py-0.5 text-[10px] normal-case tracking-normal transition ${
                      isPlaying
                        ? isOther
                          ? "bg-rose-400/40 text-rose-50"
                          : "bg-sky-400/40 text-sky-50"
                        : isOther
                        ? "bg-rose-400/20 text-rose-100 hover:bg-rose-400/30"
                        : "bg-sky-400/20 text-sky-100 hover:bg-sky-400/30"
                    }`}
                    title={`${t.start_sec?.toFixed(1)}s ~ ${t.end_sec?.toFixed(1)}s`}
                  >
                    {isPlaying ? "⏸️ 정지" : "▶️ 듣기"}
                  </button>
                )}
                {t.start_sec != null && (
                  <span className="opacity-60">{fmtTime(Math.floor(t.start_sec))}</span>
                )}
              </div>
              <div className="whitespace-pre-wrap">{t.text}</div>
              {t.entities && t.entities.length > 0 && (
                <ul className="mt-1.5 flex flex-wrap gap-1 text-[10px]">
                  {t.entities.map((e, j) => (
                    <li
                      key={`${e.label}-${j}`}
                      className={`rounded-full border px-1.5 py-0.5 ${
                        isOther
                          ? "border-rose-300/40 bg-rose-500/10 text-rose-100"
                          : "border-sky-300/40 bg-sky-500/10 text-sky-100"
                      }`}
                      title={e.label}
                    >
                      <span className="opacity-70">{e.label}</span>
                      <span className="mx-1 opacity-50">:</span>
                      {e.text}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
