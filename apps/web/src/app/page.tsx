import { cookies } from "next/headers";

import { auth } from "../auth";
import EntryGate from "./EntryGate";
import HomeClient from "./HomeClient";
import { GUEST_COOKIE, GUEST_VALUE } from "./guest";

// 홈 진입점 — 로그인 세션도, 비회원 쿠키도 없으면 선택 게이트.
// 둘 중 하나라도 있으면 기존 랜딩(HomeClient) 렌더.
export default async function Home() {
  const session = await auth();
  const store = await cookies();
  const isGuest = store.get(GUEST_COOKIE)?.value === GUEST_VALUE;

  if (!session?.user?.email && !isGuest) {
    return <EntryGate />;
  }

  // 여기 도달 = 로그인 세션 또는 비회원 쿠키. 로그인 안 했으면 비회원.
  return <HomeClient isGuest={!session?.user?.email} />;
}
