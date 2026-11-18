import { useEffect, useRef } from "react";
import Plotly from "plotly.js-dist-min";
import { api } from "@/lib/api";
import type { ArtefactOut } from "@/lib/types";

/** Renders a module's Plotly JSON artefact (bundled Plotly; no CDN, no logo link-out). */
export function PlotlyArtefact({ artefact }: { artefact: ArtefactOut }) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    let alive = true;
    api.blobUrl(`/artefacts/${artefact.key}`).then(async ({ blob, url }) => {
      URL.revokeObjectURL(url);
      const spec = JSON.parse(await blob.text()) as { data: unknown[]; layout: Record<string, unknown> };
      if (!alive || !el.current) return;
      await Plotly.newPlot(el.current, spec.data, { ...spec.layout, height: 260, margin: { t: 36, l: 50, r: 10, b: 40 } },
        { displaylogo: false, responsive: true, modeBarButtonsToRemove: ["sendDataToCloud"] });
    });
    const node = el.current;
    return () => {
      alive = false;
      if (node) Plotly.purge(node);
    };
  }, [artefact.key]);
  return <div ref={el} className="w-full" />;
}
