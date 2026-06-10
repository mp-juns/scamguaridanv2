"use client";

import {
  AUDIO_SUFFIXES,
  IMAGE_SUFFIXES,
  PDF_SUFFIXES,
  VIDEO_SUFFIXES,
  formatBytes,
  isHttpUrl,
  isYoutubeUrl,
  youtubeEmbedUrl,
  type RunMedia,
} from "./runEditorShared";

// 원본 미디어(저장 파일·입력 URL) 미리보기 — STT 외 라벨러 직접 검증용 패널.
export default function RunMediaPanel({
  runId,
  inputSource,
  media,
}: {
  runId: string;
  inputSource: string;
  media: RunMedia | null;
}) {
  const hasMedia = !!media?.stored_path;
  const sourceLooksLikeUrl = !!inputSource && isHttpUrl(inputSource);
  if (!hasMedia && !sourceLooksLikeUrl) return null;

  const mediaUrl = hasMedia ? `/api/admin/runs/${runId}/media` : null;
  const suffix = (media?.suffix ?? "").toLowerCase();
  const isVideo = VIDEO_SUFFIXES.has(suffix);
  const isAudio = AUDIO_SUFFIXES.has(suffix);
  const isImage = IMAGE_SUFFIXES.has(suffix);
  const isPdf = PDF_SUFFIXES.has(suffix);
  const ytEmbed = sourceLooksLikeUrl && isYoutubeUrl(inputSource)
    ? youtubeEmbedUrl(inputSource)
    : null;

  return (
    <section className="rounded-3xl border border-cyan-400/20 bg-cyan-500/5 p-6 backdrop-blur">
      <div className="mb-3 flex items-center gap-2">
        <div className="text-lg font-semibold text-cyan-100">🎞 원본 미디어</div>
        <span className="rounded bg-cyan-500/20 px-2 py-0.5 text-xs text-cyan-100">
          STT 외 라벨러 직접 검증용
        </span>
      </div>

      {sourceLooksLikeUrl ? (
        <div className="mb-4 space-y-2 text-sm">
          <div className="text-xs text-slate-400">입력 URL</div>
          <a
            href={inputSource}
            target="_blank"
            rel="noopener noreferrer"
            className="block break-all text-cyan-200 underline-offset-2 hover:underline"
          >
            {inputSource}
          </a>
          {ytEmbed ? (
            <div className="mt-3 aspect-video w-full overflow-hidden rounded-xl border border-white/10 bg-black">
              <iframe
                src={ytEmbed}
                title="YouTube 미리보기"
                allow="accelerometer; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowFullScreen
                className="h-full w-full"
              />
            </div>
          ) : null}
        </div>
      ) : null}

      {hasMedia && mediaUrl ? (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
            <span>저장된 원본:</span>
            <span className="rounded bg-slate-950/40 px-2 py-0.5 font-mono text-slate-200">
              {media?.original_filename ?? "source"}
            </span>
            <span>· {formatBytes(media?.size_bytes)}</span>
            <a
              href={mediaUrl}
              download={media?.original_filename ?? undefined}
              className="ml-auto rounded-lg border border-white/10 px-2 py-1 text-slate-200 transition hover:bg-white/5"
            >
              다운로드
            </a>
          </div>
          {isVideo ? (
            <video
              controls
              preload="metadata"
              src={mediaUrl}
              className="w-full rounded-xl border border-white/10 bg-black"
            />
          ) : isAudio ? (
            <audio controls preload="metadata" src={mediaUrl} className="w-full" />
          ) : isImage ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={mediaUrl}
              alt={media?.original_filename ?? "uploaded image"}
              className="max-h-[600px] w-full rounded-xl border border-white/10 bg-slate-950/40 object-contain"
            />
          ) : isPdf ? (
            <iframe
              src={mediaUrl}
              title="PDF 미리보기"
              className="h-[80vh] w-full rounded-xl border border-white/10 bg-slate-950/40"
            />
          ) : (
            <div className="rounded-xl border border-white/10 bg-slate-950/40 px-4 py-3 text-xs text-slate-400">
              이 형식({suffix || "?"})은 브라우저 미리보기를 지원하지 않을 수 있어요. 다운로드 후 확인해 주세요.
            </div>
          )}
        </div>
      ) : null}
    </section>
  );
}
