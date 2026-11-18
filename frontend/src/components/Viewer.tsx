/**
 * Zoomable evidence viewer (OpenSeadragon) with artefact heatmaps as toggleable
 * overlays and a per-overlay opacity slider. Images are fetched with the bearer
 * token and handed to OpenSeadragon as in-memory object URLs (no credentials in
 * URLs, nothing cached). After 7 minutes the viewer and all its images are wiped
 * from the browser. Overlays are stretched to the image width (same pixel grid).
 */
import { useEffect, useRef, useState } from "react";
import OpenSeadragon, { type TiledImage, type Viewer as OsdViewer } from "openseadragon";
import { api } from "@/lib/api";
import { useTimedMedia } from "@/lib/useTimedMedia";
import type { ArtefactOut } from "@/lib/types";
import { Expired } from "./Expired";
import { Label, Slider, Switch } from "./ui";

export interface Overlay {
  artefact: ArtefactOut;
  moduleName: string;
}

export function EvidenceViewer({ evidenceId, overlays }: { evidenceId: string; overlays: Overlay[] }) {
  const media = useTimedMedia(`/evidence/${evidenceId}/content`, evidenceId);
  const el = useRef<HTMLDivElement>(null);
  const viewer = useRef<OsdViewer | null>(null);
  const items = useRef<Map<string, TiledImage>>(new Map());
  const urls = useRef<string[]>([]);
  const [active, setActive] = useState<Record<string, boolean>>({});
  const [opacity, setOpacity] = useState<Record<string, number>>({});
  const [overlayError, setOverlayError] = useState<string | null>(null);

  useEffect(() => {
    if (!media.url || !el.current) return;
    viewer.current = OpenSeadragon({
      element: el.current,
      // Nav buttons need image assets from a prefixUrl; we ship none (no CDN), so use
      // mouse/touch: wheel or pinch to zoom, drag to pan, plus the mini-map navigator.
      showNavigationControl: false,
      showNavigator: true,
      tileSources: { type: "image", url: media.url, buildPyramid: false },
      gestureSettingsMouse: { clickToZoom: false },
      crossOriginPolicy: false,
    });
    return () => {
      viewer.current?.destroy();
      viewer.current = null;
      items.current.clear();
      urls.current.forEach((u) => URL.revokeObjectURL(u));
      urls.current = [];
      setActive({});
    };
  }, [media.url]);

  async function toggle(o: Overlay, on: boolean) {
    setOverlayError(null);
    setActive((a) => ({ ...a, [o.artefact.key]: on }));
    const v = viewer.current;
    if (!v) return;
    const existing = items.current.get(o.artefact.key);
    if (!on && existing) {
      v.world.removeItem(existing);
      items.current.delete(o.artefact.key);
      return;
    }
    if (on && !existing) {
      try {
        const { url } = await api.blobUrl(`/artefacts/${o.artefact.key}`);
        urls.current.push(url);
        v.addTiledImage({
          tileSource: { type: "image", url, buildPyramid: false },
          x: 0, y: 0, width: 1,
          opacity: opacity[o.artefact.key] ?? 0.6,
          success: (e) => items.current.set(o.artefact.key, e.item),
        });
      } catch {
        setActive((a) => ({ ...a, [o.artefact.key]: false }));
        setOverlayError("This heatmap was deleted after the 7-minute retention period. Re-run the check to regenerate it.");
      }
    }
  }

  function changeOpacity(key: string, value: number) {
    setOpacity((s) => ({ ...s, [key]: value }));
    items.current.get(key)?.setOpacity(value);
  }

  if (media.expired) return <Expired onReload={media.reload} label="the image" />;
  return (
    <div>
      {media.error && <div className="mb-2 text-sm text-red-700">Could not load image: {media.error}</div>}
      <div ref={el} className="h-[560px] w-full rounded-md border border-slate-300 bg-slate-800" data-testid="osd-viewer" />
      {overlays.length > 0 && (
        <div className="mt-3 space-y-2">
          <Label>Overlays (same pixel grid as the image)</Label>
          {overlays.map((o) => (
            <div key={o.artefact.key} className="grid grid-cols-[auto_1fr_140px] items-center gap-3 text-sm">
              <Switch checked={!!active[o.artefact.key]} onCheckedChange={(on) => void toggle(o, on)}
                      aria-label={`overlay ${o.artefact.name}`} />
              <span><strong>{o.moduleName}</strong> — {o.artefact.description}</span>
              <Slider min={0} max={1} step={0.05} value={[opacity[o.artefact.key] ?? 0.6]}
                      onValueChange={([v]) => changeOpacity(o.artefact.key, v)} disabled={!active[o.artefact.key]} />
            </div>
          ))}
          {overlayError && <p className="text-xs text-amber-800">{overlayError}</p>}
        </div>
      )}
    </div>
  );
}

/** Stand-alone artefact image (e.g. side-by-side, top frames), in memory for at most 7 minutes. */
export function ArtefactImage({ artefact }: { artefact: ArtefactOut }) {
  const media = useTimedMedia(`/artefacts/${artefact.key}`);
  if (media.expired) return <Expired onReload={media.reload} label="this figure" />;
  if (media.error) {
    return <p className="text-xs text-amber-800">Figure not available (deleted after the 7-minute retention period; its SHA-256 is kept). Re-run the check to regenerate it.</p>;
  }
  return media.url ? <img src={media.url} alt={artefact.description} className="max-w-full rounded border" /> : <div className="text-sm">Loading…</div>;
}
