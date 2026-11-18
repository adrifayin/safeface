/**
 * Zoomable evidence viewer (OpenSeadragon) with artefact heatmaps as toggleable
 * overlays and a per-overlay opacity slider. Images are fetched with the bearer
 * token and handed to OpenSeadragon as object URLs, so no credentials ever
 * appear in URLs. Overlays are stretched to the image width (same pixel grid).
 */
import { useEffect, useRef, useState } from "react";
import OpenSeadragon, { type TiledImage, type Viewer as OsdViewer } from "openseadragon";
import { api } from "@/lib/api";
import type { ArtefactOut } from "@/lib/types";
import { Label, Slider, Switch } from "./ui";

export interface Overlay {
  artefact: ArtefactOut;
  moduleName: string;
}

export function EvidenceViewer({ evidenceId, overlays }: { evidenceId: string; overlays: Overlay[] }) {
  const el = useRef<HTMLDivElement>(null);
  const viewer = useRef<OsdViewer | null>(null);
  const items = useRef<Map<string, TiledImage>>(new Map());
  const urls = useRef<string[]>([]);
  const [active, setActive] = useState<Record<string, boolean>>({});
  const [opacity, setOpacity] = useState<Record<string, number>>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    api.blobUrl(`/evidence/${evidenceId}/content`).then(({ url }) => {
      if (cancelled || !el.current) return;
      urls.current.push(url);
      viewer.current = OpenSeadragon({
        element: el.current,
        // Nav buttons need image assets from a prefixUrl; we ship none (no CDN), so use
        // mouse/touch: wheel or pinch to zoom, drag to pan, plus the mini-map navigator.
        showNavigationControl: false,
        showNavigator: true,
        tileSources: { type: "image", url, buildPyramid: false },
        gestureSettingsMouse: { clickToZoom: false },
        crossOriginPolicy: false,
      });
    }).catch((e) => setError(String(e)));
    return () => {
      cancelled = true;
      viewer.current?.destroy();
      viewer.current = null;
      items.current.clear();
      urls.current.forEach((u) => URL.revokeObjectURL(u));
      urls.current = [];
    };
  }, [evidenceId]);

  async function toggle(o: Overlay, on: boolean) {
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
      const { url } = await api.blobUrl(`/artefacts/${o.artefact.key}`);
      urls.current.push(url);
      v.addTiledImage({
        tileSource: { type: "image", url, buildPyramid: false },
        x: 0, y: 0, width: 1,
        opacity: opacity[o.artefact.key] ?? 0.6,
        success: (e) => items.current.set(o.artefact.key, e.item),
      });
    }
  }

  function changeOpacity(key: string, value: number) {
    setOpacity((s) => ({ ...s, [key]: value }));
    items.current.get(key)?.setOpacity(value);
  }

  return (
    <div>
      {error && <div className="mb-2 text-sm text-red-700">Could not load image: {error}</div>}
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
        </div>
      )}
    </div>
  );
}

/** Stand-alone artefact image (e.g. side-by-side), loaded with auth. */
export function ArtefactImage({ artefact }: { artefact: ArtefactOut }) {
  const [url, setUrl] = useState<string | null>(null);
  useEffect(() => {
    let u: string | null = null;
    api.blobUrl(`/artefacts/${artefact.key}`).then((r) => setUrl((u = r.url)));
    return () => { if (u) URL.revokeObjectURL(u); };
  }, [artefact.key]);
  return url ? <img src={url} alt={artefact.description} className="max-w-full rounded border" /> : <div className="text-sm">Loading…</div>;
}
