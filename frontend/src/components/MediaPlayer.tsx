/** Video/audio player for evidence (fetched with auth as a blob; blurred until revealed by the parent). */
import { forwardRef, useEffect, useState } from "react";
import { api } from "@/lib/api";

export const MediaPlayer = forwardRef<HTMLVideoElement, { evidenceId: string; kind: "video" | "audio" }>(
  ({ evidenceId, kind }, ref) => {
    const [url, setUrl] = useState<string | null>(null);
    const [error, setError] = useState<string | null>(null);
    useEffect(() => {
      let u: string | null = null;
      api.blobUrl(`/evidence/${evidenceId}/content`).then((r) => setUrl((u = r.url))).catch((e) => setError(String(e)));
      return () => { if (u) URL.revokeObjectURL(u); };
    }, [evidenceId]);
    if (error) return <div className="text-sm text-red-700">Could not load media: {error}</div>;
    if (!url) return <div className="text-sm text-slate-500">Loading media…</div>;
    return kind === "video"
      ? <video ref={ref} src={url} controls preload="metadata" className="max-h-[560px] w-full rounded-md bg-black" data-testid="video-player" />
      : <audio ref={ref as unknown as React.Ref<HTMLAudioElement>} src={url} controls className="w-full" data-testid="audio-player" />;
  },
);
MediaPlayer.displayName = "MediaPlayer";
