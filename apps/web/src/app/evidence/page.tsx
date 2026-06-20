import { marked } from "marked";

export const dynamic = "force-dynamic";

export const metadata = {
  title: "EVIDENCE — ScamGuardian 검출 신호 학술·법적 근거",
  description:
    "ScamGuardian 이 검출하는 모든 위험 신호의 학술 논문 (DOI/URL) · 한국 법령 · 정부·산업 보고서 근거 + 코드 매핑.",
};

async function loadMarkdown(): Promise<string> {
  const apiBaseUrl = process.env.SCAMGUARDIAN_API_URL ?? "http://127.0.0.1:8000";
  try {
    const response = await fetch(`${apiBaseUrl}/api/evidence`, { cache: "no-store" });
    const data = (await response.json()) as { markdown?: string };
    if (response.ok && typeof data.markdown === "string") {
      return data.markdown;
    }
  } catch {
    // fall through to local fallback message
  }
  return "# EVIDENCE.md\n\n파일을 찾을 수 없습니다 (`.scamguardian/EVIDENCE.md`).";
}

export default async function EvidencePage() {
  const md = await loadMarkdown();
  // GitHub Flavored Markdown — 표·체크박스 등
  marked.setOptions({ gfm: true, breaks: false });
  const html = await marked.parse(md);

  return (
    <main className="min-h-screen bg-[radial-gradient(circle_at_top,#111827_0%,#020617_60%,#000000_100%)] px-4 py-8 text-slate-100 sm:px-6 sm:py-10">
      <div className="mx-auto w-full max-w-4xl">
        {/* 상단 안내 — 페이지 정체성 명시 */}
        <header className="mb-6 rounded-2xl border border-fuchsia-500/30 bg-fuchsia-950/20 p-5 text-sm">
          <p className="font-semibold text-fuchsia-200">
            📚 EVIDENCE.md — 검출 신호 학술·법적 근거 (단일 reference book)
          </p>
          <p className="mt-2 text-slate-300">
            ScamGuardian 의 모든 위험 신호 (<code className="rounded bg-slate-800/60 px-1 text-xs">detected_signals</code>)
            각각의 (i) 학술 논문 DOI/URL, (ii) 한국 법령 조항, (iii) 정부·산업 보고서 + 코드 위치.
          </p>
          <p className="mt-2 text-xs text-slate-400">
            정본 위치: <code>.scamguardian/EVIDENCE.md</code> · 자문 미팅·졸업 발표·README 인용 모두 가능.
            마지막 갱신: 2026-05-05.
          </p>
        </header>

        <article
          className="evidence-prose"
          dangerouslySetInnerHTML={{ __html: html }}
        />
      </div>

      {/* 다크 테마 + Pretendard — Tailwind typography 없이 직접 작성 */}
      <style>{`
        .evidence-prose {
          font-family: 'Pretendard Variable', Pretendard, -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
          color: #e2e8f0;
          line-height: 1.75;
          letter-spacing: -0.005em;
        }
        .evidence-prose h1 {
          font-size: 2rem;
          font-weight: 800;
          letter-spacing: -0.02em;
          color: #f8fafc;
          margin: 2.5rem 0 1rem;
          padding-bottom: 0.5rem;
          border-bottom: 1px solid rgba(148, 163, 184, 0.3);
        }
        .evidence-prose h1:first-child { margin-top: 0; }
        .evidence-prose h2 {
          font-size: 1.5rem;
          font-weight: 700;
          letter-spacing: -0.018em;
          color: #f1f5f9;
          margin: 2rem 0 1rem;
          padding-bottom: 0.4rem;
          border-bottom: 1px solid rgba(148, 163, 184, 0.2);
        }
        .evidence-prose h3 {
          font-size: 1.2rem;
          font-weight: 700;
          color: #cbd5e1;
          margin: 1.6rem 0 0.6rem;
        }
        .evidence-prose h4 {
          font-size: 1rem;
          font-weight: 600;
          color: #94a3b8;
          margin: 1rem 0 0.4rem;
        }
        .evidence-prose p {
          margin: 0.6rem 0;
          color: #cbd5e1;
        }
        .evidence-prose ul, .evidence-prose ol {
          margin: 0.6rem 0;
          padding-left: 1.5rem;
        }
        .evidence-prose li {
          margin: 0.3rem 0;
          color: #cbd5e1;
        }
        .evidence-prose a {
          color: #67e8f9;
          text-decoration: underline;
          text-decoration-thickness: 1px;
          text-underline-offset: 2px;
          transition: color 0.15s;
        }
        .evidence-prose a:hover {
          color: #a5f3fc;
        }
        .evidence-prose strong {
          color: #f1f5f9;
          font-weight: 700;
        }
        .evidence-prose em {
          color: #f9a8d4;
          font-style: italic;
        }
        .evidence-prose code {
          font-family: 'JetBrains Mono', SFMono-Regular, Consolas, monospace;
          background: rgba(15, 23, 42, 0.7);
          color: #fde68a;
          border-radius: 4px;
          padding: 1px 6px;
          font-size: 0.88em;
          border: 1px solid rgba(148, 163, 184, 0.15);
        }
        .evidence-prose pre {
          background: #0f172a;
          color: #e2e8f0;
          border-radius: 12px;
          padding: 16px 18px;
          font-family: 'JetBrains Mono', SFMono-Regular, monospace;
          font-size: 0.85rem;
          line-height: 1.6;
          overflow-x: auto;
          border: 1px solid rgba(148, 163, 184, 0.2);
          margin: 1rem 0;
        }
        .evidence-prose pre code {
          background: transparent;
          color: inherit;
          padding: 0;
          border: none;
          font-size: inherit;
        }
        .evidence-prose blockquote {
          border-left: 3px solid #f472b6;
          padding: 0.4rem 1rem;
          margin: 1rem 0;
          background: rgba(244, 114, 182, 0.08);
          color: #f9a8d4;
          border-radius: 0 8px 8px 0;
        }
        .evidence-prose blockquote p { color: #fbcfe8; margin: 0.3rem 0; }
        .evidence-prose hr {
          border: none;
          border-top: 1px solid rgba(148, 163, 184, 0.2);
          margin: 2.5rem 0;
        }
        .evidence-prose table {
          width: 100%;
          border-collapse: collapse;
          margin: 1rem 0;
          font-size: 0.92rem;
          border: 1px solid rgba(148, 163, 184, 0.25);
          border-radius: 8px;
          overflow: hidden;
        }
        .evidence-prose thead {
          background: rgba(30, 41, 59, 0.7);
        }
        .evidence-prose th {
          padding: 0.6rem 0.8rem;
          text-align: left;
          font-weight: 600;
          color: #f1f5f9;
          border-bottom: 1px solid rgba(148, 163, 184, 0.3);
        }
        .evidence-prose td {
          padding: 0.5rem 0.8rem;
          border-bottom: 1px solid rgba(148, 163, 184, 0.12);
          color: #cbd5e1;
          vertical-align: top;
        }
        .evidence-prose tr:last-child td {
          border-bottom: none;
        }
        .evidence-prose tr:hover td {
          background: rgba(30, 41, 59, 0.4);
        }
      `}</style>
    </main>
  );
}
