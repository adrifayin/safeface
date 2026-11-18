/** Video/audio player for evidence: in-memory only, wiped from the browser after 7 minutes. */
import { forwardRef } from "react";
import { useTimedMedia } from "@/lib/useTimedMedia";
import { Expired } from "./Expired";

export const MediaPlayer = forwardRef<HTMLVideoElement, { evidenceId: string; kind: "video" | "audio" }>(
  ({ evidenceId, kind }, ref) => {
    const { url, expired, error, reload } = useTimedMedia(`/evidence/${evidenceId}/content`, evidenceId);
    if (expired) return <Expired onReload={reload} label={`the ${kind}`} />;
    if (error) return <div className="text-sm text-red-700">Could not load media: {error}</div>;
    if (!url) return <div className="text-sm text-slate-500">Loading media…</div>;
    return kind === "video"
      ? <video ref={ref} src={url} controls preload="metadata" className="max-h-[560px] w-full rounded-md bg-black" data-testid="video-player" />
      : <audio ref={ref as unknown as React.Ref<HTMLAudioElement>} src={url} controls className="w-full" data-testid="audio-player" />;
  },
);
MediaPlayer.displayName = "MediaPlayer";
