import Link from "next/link";

const CARDS = [
  {
    href: "/demo/live",
    emoji: "🎙️",
    title: "통화 분석",
    desc: "통화 중 마이크를 켜면 위험 신호를 실시간으로 감지해요. 녹음 파일도 분석할 수 있어요.",
  },
  {
    href: "/demo/content",
    emoji: "💬",
    title: "콘텐츠 분석",
    desc: "의심 문자·메시지 또는 유튜브 URL을 붙여넣으면 위험 신호를 검출해요. 영상·음성 파일도 올릴 수 있어요.",
  },
  {
    href: "/demo/apk",
    emoji: "📱",
    title: "APK 분석",
    desc: "안드로이드 설치 파일(.apk)을 올려 악성 앱 신호를 검출해요. 격리 VM 으로만 분석합니다.",
  },
] as const;

export default function DemoHubCards() {
  return (
    <div className="flex flex-col gap-3.5">
      {CARDS.map((card) => (
        <Link
          key={card.href}
          href={card.href}
          className="group flex items-center gap-5 rounded-2xl border border-[#e5e8eb] bg-white p-6 shadow-[0_2px_12px_rgba(0,0,0,0.05)] transition hover:border-[#3182f6] hover:shadow-[0_6px_20px_rgba(49,130,246,0.12)]"
        >
          <span className="flex h-14 w-14 flex-shrink-0 items-center justify-center rounded-2xl bg-[#e8f3ff] text-3xl">
            {card.emoji}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block text-lg font-bold text-[#191f28]">{card.title}</span>
            <span className="mt-1 block text-sm leading-6 text-[#4e5968]">{card.desc}</span>
          </span>
          <span className="flex flex-shrink-0 items-center gap-1.5 whitespace-nowrap text-sm font-semibold text-[#8b95a1] transition group-hover:text-[#3182f6]">
            시연 + 구조 보기 <span aria-hidden>→</span>
          </span>
        </Link>
      ))}
    </div>
  );
}
