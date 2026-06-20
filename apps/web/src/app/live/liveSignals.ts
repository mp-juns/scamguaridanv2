import type { DetectedSignal, StreamMatch } from "./liveTypes";

const FLAG_LABELS_KO: Record<string, string> = {
  abnormal_return_rate: "비정상 수익률 약속",
  urgent_transfer_demand: "즉각 송금 요구",
  fake_government_agency: "공공기관 사칭",
  victim_personal_info_request: "민감정보 요구",
  fake_call_center: "가짜 콜센터",
  malware_detected: "악성코드 검출",
  phishing_url_confirmed: "피싱 URL 확정",
};

export function flagLabel(s: DetectedSignal) {
  return s.label_ko ?? FLAG_LABELS_KO[s.flag] ?? s.flag;
}

export function speakerTag(speaker?: string | null): string {
  if (speaker === "본인") return "🙋 본인";
  if (speaker === "상대방") return "🗣️ 상대방";
  return "";
}

export function dedupMergeMatches(
  prev: StreamMatch[],
  incoming: StreamMatch[],
): StreamMatch[] {
  const key = (m: StreamMatch) => `${m.flag}|${m.snippet}|${m.speaker ?? ""}`;
  const seen = new Set(prev.map(key));
  const fresh = incoming.filter((m) => !seen.has(key(m)));
  return fresh.length ? [...prev, ...fresh] : prev;
}

const TIER_CAUTION_SCORE = 3;
const TIER_DANGER_SCORE = 6;

export function computeTierFromMatches(matches: StreamMatch[]): number {
  if (matches.some((m) => m.instant)) return 3;
  const cum = matches
    .filter((m) => !m.instant)
    .reduce((s, m) => s + m.level, 0);
  if (cum >= TIER_DANGER_SCORE) return 3;
  if (cum >= TIER_CAUTION_SCORE) return 2;
  return matches.length ? 1 : 0;
}

export function pickAlertAction(
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

export function fireDangerNotification(matches: StreamMatch[]) {
  if (typeof window === "undefined" || !("Notification" in window)) return;
  if (Notification.permission !== "granted") return;
  try {
    const action = pickAlertAction(matches)?.action ?? "지금 통화를 끊으세요.";
    const noti = new Notification("🚨 위험 신호 감지", {
      body: action,
      tag: "scam-danger",
      requireInteraction: true,
    });
    noti.onclick = () => {
      window.focus();
      noti.close();
    };
  } catch {
    /* SW 필요 브라우저 등 — 무시 (풀스크린 경보는 그대로 동작) */
  }
}

export function fmtTime(sec: number) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

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

export function scanTranscript(text: string) {
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
