/**
 * Examiner-assisted perspective/shadow tool: click two points per line on the image.
 * Coordinates are converted to the image's own pixel grid and sent as parameters,
 * so the run is reproducible from the recorded parameters.
 */
import { useRef, useState, type MouseEvent } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { useTimedMedia } from "@/lib/useTimedMedia";
import { Expired } from "./Expired";
import { Button, ErrorBox, Select } from "./ui";

type Line = [number, number, number, number];

export function GeometryTool({ evidenceId }: { evidenceId: string }) {
  const qc = useQueryClient();
  const media = useTimedMedia(`/evidence/${evidenceId}/content`, evidenceId);
  const url = media.url;
  const [mode, setMode] = useState<"perspective" | "shadow">("perspective");
  const [lines, setLines] = useState<Line[]>([]);
  const [pending, setPending] = useState<[number, number] | null>(null);
  const img = useRef<HTMLImageElement>(null);
  const run = useMutation({
    mutationFn: () => api.post(`/evidence/${evidenceId}/analyses`, {
      module_ids: ["image.geometry"], params: { "image.geometry": { mode, lines } },
    }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["findings", evidenceId] }),
  });

  function click(e: MouseEvent<HTMLDivElement>) {
    const el = img.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const x = Math.round(((e.clientX - rect.left) / rect.width) * el.naturalWidth);
    const y = Math.round(((e.clientY - rect.top) / rect.height) * el.naturalHeight);
    if (pending) {
      setLines([...lines, [pending[0], pending[1], x, y]]);
      setPending(null);
    } else setPending([x, y]);
  }
  if (media.expired) return <Expired onReload={media.reload} label="the image" />;
  const w = img.current?.naturalWidth || 1;
  const h = img.current?.naturalHeight || 1;
  return (
    <div className="space-y-2 rounded border border-slate-200 p-2">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <Select value={mode} onChange={(e) => setMode(e.target.value as "perspective" | "shadow")} className="h-8 w-44">
          <option value="perspective">Perspective (parallel edges)</option>
          <option value="shadow">Shadow (shadow → object point)</option>
        </Select>
        <span className="text-slate-600">{lines.length} line(s){pending ? " — click the second point" : " — click two points per line"}</span>
        <Button size="sm" variant="ghost" onClick={() => { setLines(lines.slice(0, -1)); setPending(null); }} disabled={!lines.length}>Undo</Button>
        <Button size="sm" variant="ghost" onClick={() => { setLines([]); setPending(null); }} disabled={!lines.length}>Clear</Button>
        <Button size="sm" className="ml-auto" disabled={lines.length < 3 || run.isPending} onClick={() => run.mutate()}>Check consistency</Button>
      </div>
      {url && (
        <div className="relative cursor-crosshair select-none" onClick={click}>
          <img ref={img} src={url} alt="evidence for line drawing" className="w-full" draggable={false} />
          <svg className="pointer-events-none absolute inset-0 h-full w-full" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none">
            {lines.map((l, i) => <line key={i} x1={l[0]} y1={l[1]} x2={l[2]} y2={l[3]} stroke="#0ea5e9" strokeWidth={Math.max(2, w / 300)} />)}
            {pending && <circle cx={pending[0]} cy={pending[1]} r={Math.max(4, w / 150)} fill="#0ea5e9" />}
          </svg>
        </div>
      )}
      <p className="text-xs text-slate-500">Draw at least 4 lines spread across the scene. The lines are stored with the result.</p>
      <ErrorBox error={run.error} />
    </div>
  );
}
