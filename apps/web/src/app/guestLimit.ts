// 비회원 일일 분석 한도 — 홈(텍스트/URL/파일) + 라이브 음성 분석 합산.
// 현재는 요청에 따라 하드 한도 체크를 비활성화한다.
export const GUEST_DAILY_LIMIT = 5;
export const GUEST_DAILY_LIMIT_ENABLED = false;

const PREFIX = "sg_guest_daily_";

function todayKey(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${PREFIX}${y}-${m}-${day}`;
}

export function guestDailyCount(): number {
  try {
    return Number(window.localStorage.getItem(todayKey()) || "0") || 0;
  } catch {
    return 0;
  }
}

// 오늘 한도를 이미 모두 소진했는지 (이번 실행을 막아야 하는지)
export function guestOverDailyLimit(): boolean {
  if (!GUEST_DAILY_LIMIT_ENABLED) return false;
  return guestDailyCount() >= GUEST_DAILY_LIMIT;
}

// 이번 실행을 오늘 카운트에 반영, 갱신된 값 반환
export function bumpGuestDaily(): number {
  const next = guestDailyCount() + 1;
  try {
    window.localStorage.setItem(todayKey(), String(next));
  } catch {
    /* localStorage 불가 시 무시 */
  }
  return next;
}
