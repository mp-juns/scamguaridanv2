import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

// 로그인은 누구나(Google) 가능 — 관리자 여부(allowlist)는 백엔드(master env + admin_users DB)
// 에 위임해 role 로만 구분. admin 게이트는 proxy.ts 가 role==="admin" 으로 단독 차단.
const API_BASE = process.env.SCAMGUARDIAN_API_URL ?? "http://127.0.0.1:8000";

async function backendAllows(email: string): Promise<boolean> {
  try {
    const res = await fetch(`${API_BASE}/api/admin/access/check`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email }),
      cache: "no-store",
    });
    if (!res.ok) return false;
    const data = await res.json();
    return Boolean(data?.allowed);
  } catch {
    return false; // 백엔드 불가 시 fail-closed (로그인 거부)
  }
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [Google],
  session: { strategy: "jwt", maxAge: 60 * 60 * 24 * 30 }, // 30일
  pages: { signIn: "/admin/login", error: "/admin/login" },
  callbacks: {
    async signIn({ user }) {
      // 모든 Google 계정 로그인 허용 — 역할(admin/user)은 jwt 콜백에서 allowlist 로 결정.
      return Boolean(user?.email);
    },
    async jwt({ token, user }) {
      // 최초 로그인 시점에만 allowlist 조회 → 역할 확정 후 토큰에 고정.
      if (user?.email) {
        token.email = user.email;
        token.role = (await backendAllows(user.email.toLowerCase())) ? "admin" : "user";
      }
      return token;
    },
    async session({ session, token }) {
      if (token?.email && typeof token.email === "string") {
        session.user = {
          ...session.user,
          email: token.email,
          role: token.role ?? "user",
        };
      }
      return session;
    },
    async authorized({ auth: session }) {
      // 기본 미들웨어 fallback — 실제 /admin 게이트는 proxy.ts 가 role 로 판정.
      return session?.user?.role === "admin";
    },
  },
});
