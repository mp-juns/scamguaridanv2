import type { DefaultSession } from "next-auth";
import "next-auth/jwt";

// 세션·JWT 에 역할(role) 추가 — admin(allowlist 통과) / user(그 외 로그인).
declare module "next-auth" {
  interface Session {
    user: {
      role?: "admin" | "user";
    } & DefaultSession["user"];
  }
}

declare module "next-auth/jwt" {
  interface JWT {
    role?: "admin" | "user";
  }
}
