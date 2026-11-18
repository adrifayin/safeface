import { useEffect, useRef, useState } from "react";
import Plotly from "plotly.js-dist-min";
import { api } from "@/lib/api";
import type { ArtefactOut } from "@/lib/types";

/** Renders a module's Plotly JSON artefact (bundled Plotly; no CDN, no logo link-out). */
export function PlotlyArtefact({ artefact, onPointClick }: { artefact: ArtefactOut; onPointClick?: (x: number) => void }) {
  const el = useRef<HTMLDivElement>(null);
  const [gone, setGone] = useState(false);
  useEffect(() => {
    let alive = true;
    api.blobUrl(`/artefacts/${artefact.key}`).then(async ({ blob, url }) => {
      URL.revokeObjectURL(url);
      const spec = JSON.parse(await blob.text()) as { data: unknown[]; layout: Record<string, unknown> };
      if (!alive || !el.current) return;
      await Plotly.newPlot(el.current, spec.data, { ...spec.layout, height: 260, margin: { t: 36, l: 50, r: 10, b: 40 } },
        { displaylogo: false, responsive: true, modeBarButtonsToRemove: ["sendDataToCloud"] });
      if (onPointClick) {
        (el.current as unknown as { on: (ev: string, cb: (e: { points: { x: number }[] }) => void) => void })
          .on("plotly_click", (e) => { const x = e.points?.[0]?.x; if (typeof x === "number") onPointClick(x); });
      }
    }).catch(() => setGone(true));
    const node = el.current;
    return () => {
      alive = false;
      if (node) Plotly.purge(node);
    };
  }, [artefact.key, onPointClick]);
  if (gone) return <p className="text-xs text-amber-800">Chart data deleted after the 7-minute retention period. Re-run the check to regenerate it.</p>;
  return <div ref={el} className="w-full" />;
}
