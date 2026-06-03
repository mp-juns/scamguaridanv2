import NextAuth from "next-auth";
import Google from "next-auth/providers/google";

// 허용 판정은 백엔드(master env + admin_users DB)에 위임 — signIn 콜백이 단일 게이트.
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
      // master(env) 또는 approved(DB) 만 통과. 모르는 계정은 백엔드가 pending 적재 후 거부.
      const email = user?.email?.toLowerCase();
      if (!email) return false;
      return backendAllows(email);
    },
    async jwt({ token, user }) {
      if (user?.email) token.email = user.email;
      return token;
    },
    async session({ session, token }) {
      if (token?.email && typeof token.email === "string") {
        session.user = { ...session.user, email: token.email };
      }
      return session;
    },
    async authorized({ auth: session }) {
      // 세션 존재 = signIn 게이트 통과 = 승인됨. (allowlist 재확인 불필요)
      return Boolean(session?.user?.email);
    },
  },
});
