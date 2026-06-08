// 프롬프트 우회(인젝션) 클라이언트 1차 탐지 + 즉시 접근 제한.
// 백엔드 platform_layer/abuse_guard.detect_prompt_injection 과 동일 의도의 거울 —
// 서버가 최종 권위(423 INJECTION)지만, 웹에서 즉시 "접근 제한" UX 를 주기 위함.
// ⚠️ 실제 사기 본문의 일반 "무시" 가 아니라 AI/시스템 프롬프트·역할 조작 패턴만 매칭(오탐 최소화).
const PATTERNS: RegExp[] = [
  /(?:기존|이전|위의?|모든|시스템)?\s*(?:프롬프트|지시(?:사항)?|명령(?:어)?|규칙)\s*(?:을|를|은|는|들)?\s*(?:전부|모두|싹)?\s*(?:무시|잊어|잊고|덮어|초기화|리셋)/i,
  /시스템\s*프롬프트/i,
  /(?:지금|이제)\s*부터\s*(?:너|네|당신|챗봇|ai|assistant)\s*(?:는|은|를)?/i,
  /(?:너|네|당신)\s*(?:는|은)\s*이제(?:부터)?/i,
  /(?:역할|규칙|제약|설정)\s*(?:을|를)?\s*(?:잊|무시|벗어)/i,
  /ignore\s+(?:all\s+|the\s+)?(?:previous|prior|above|earlier|preceding)\s+(?:instructions?|prompts?|messages?|rules?|context)/i,
  /disregard\s+(?:all\s+|the\s+)?(?:previous|prior|above|system)/i,
  /(?:system\s*prompt|developer\s*mode|jailbreak|dan\s*mode)/i,
  /you\s+are\s+now\s+(?:a|an|the)\b/i,
  /(?:act|pretend|behave)\s+as\s+(?:if\s+)?(?:you|an|a)\b/i,
  /override\s+(?:the\s+)?(?:system|previous|safety)/i,
];

export function looksLikeInjection(text: string | null | undefined): boolean {
  if (!text) return false;
  return PATTERNS.some((re) => re.test(text));
}

const BLOCK_KEY = "sg_injection_block_until";
const BLOCK_DURATION_MS = 60 * 60 * 1000; // 1시간

// 프롬프트 우회 감지 시 호출 — 1시간 접근 제한 기록
export function blockForInjection(): void {
  try {
    window.localStorage.setItem(BLOCK_KEY, String(Date.now() + BLOCK_DURATION_MS));
  } catch {
    /* localStorage 불가 시 무시 */
  }
}

// 남은 제한 시간(ms). 0 이면 제한 없음.
export function injectionBlockRemainingMs(): number {
  try {
    const until = Number(window.localStorage.getItem(BLOCK_KEY) || "0") || 0;
    return Math.max(0, until - Date.now());
  } catch {
    return 0;
  }
}
