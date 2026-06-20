import { Suspense } from "react";

import DemoContentClient from "./DemoContentClient";

export const metadata = {
  title: "시연 · 콘텐츠 분석",
  description: "텍스트·URL·미디어 분석 데모 + 7-Phase 파이프라인 구조 설명",
};

export default function DemoContentPage() {
  return (
    <Suspense fallback={null}>
      <DemoContentClient />
    </Suspense>
  );
}
