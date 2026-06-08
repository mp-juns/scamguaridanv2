export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // 상단 이메일·로그아웃 바는 제거 — 로그아웃은 전역 AccountNav(우측 상단 pill)가 제공.
  return <>{children}</>;
}
