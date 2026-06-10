"use client";

import type { RunMetadata } from "./runEditorShared";

// 사용자 제공 정보(챗봇 Q&A prior) + 챗봇 대화 전체 — 라벨링 참고용 컨텍스트 패널.
export default function RunContextPanel({ metadata }: { metadata: RunMetadata }) {
  const userCtx = metadata.user_context ?? null;
  const chatHistory = metadata.chat_history ?? [];
  const qaPairs = userCtx?.qa_pairs ?? [];
  const hasUserCtx = qaPairs.length > 0;
  const hasChat = chatHistory.length > 0;
  if (!hasUserCtx && !hasChat) return null;
  return (
    <section className="space-y-4">
      {hasUserCtx ? (
        <div className="rounded-3xl border border-fuchsia-400/30 bg-fuchsia-500/5 p-6 backdrop-blur">
          <div className="mb-3 flex items-center gap-2">
            <div className="text-lg font-semibold text-fuchsia-200">
              💡 사용자 제공 정보
            </div>
            <span className="rounded bg-fuchsia-500/20 px-2 py-0.5 text-xs text-fuchsia-200">
              분석에 prior 로 반영됨
            </span>
          </div>
          <p className="mb-3 text-xs text-fuchsia-200/70">
            사용자가 챗봇과 대화하며 직접 알려준 컨텍스트입니다. 라벨링 시 참고하세요.
          </p>
          <ol className="space-y-2">
            {qaPairs.map((qa, idx) => (
              <li key={idx} className="rounded-lg bg-fuchsia-950/40 p-3">
                {qa.question ? (
                  <div className="text-xs text-fuchsia-300/80">Q. {qa.question}</div>
                ) : null}
                <div className="mt-1 text-sm text-fuchsia-100">A. {qa.answer ?? ""}</div>
              </li>
            ))}
          </ol>
        </div>
      ) : null}
      {hasChat ? (
        <div className="rounded-3xl border border-white/10 bg-white/5 p-6 backdrop-blur">
          <div className="mb-3 text-lg font-semibold text-white">
            💬 챗봇 대화 전체
            <span className="ml-2 text-xs text-slate-400">({chatHistory.length}턴)</span>
          </div>
          <details>
            <summary className="cursor-pointer text-sm text-slate-400 hover:text-slate-200">
              펼쳐서 보기
            </summary>
            <ol className="mt-3 space-y-2">
              {chatHistory.map((t, idx) => (
                <li
                  key={idx}
                  className={
                    t.role === "user"
                      ? "ml-8 rounded bg-blue-900/30 p-2 text-sm text-blue-100"
                      : "rounded bg-slate-800/40 p-2 text-sm text-slate-200"
                  }
                >
                  <div className="text-xs text-slate-400">
                    {t.role === "user" ? "👤 사용자" : "🤖 챗봇"}
                  </div>
                  <div className="mt-1 whitespace-pre-wrap">{t.message ?? ""}</div>
                </li>
              ))}
            </ol>
          </details>
        </div>
      ) : null}
    </section>
  );
}
