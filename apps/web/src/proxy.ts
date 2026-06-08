import { NextResponse } from "next/server";

import { auth } from "./auth";

const DISABLED = ["1", "true", "yes", "on"].includes(
  (process.env.ADMIN_AUTH_DISABLED ?? "").toLowerCase(),
);

// Next.js 16 proxy (구 middleware) — /admin/* 는 role==="admin" 세션만 진입.
// 로그인은 누구나 가능(user/admin)하지만, allowlist 통과한 admin 만 어드민 진입.
// 미인증·일반 user 면 /admin/login (signIn 페이지) 으로 리다이렉트.
// ADMIN_AUTH_DISABLED=true 면 모든 검사 bypass (개발용).
export default auth((request) => {
  if (DISABLED) return NextResponse.next();
  const { pathname, search } = request.nextUrl;
  if (pathname === "/admin/login") return NextResponse.next();
  if (request.auth?.user?.role === "admin") return NextResponse.next();

  const url = request.nextUrl.clone();
  url.pathname = "/admin/login";
  url.searchParams.set("next", pathname + (search || ""));
  return NextResponse.redirect(url);
});

export const config = {
  matcher: ["/admin/:path*"],
};
