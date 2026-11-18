/**
 * Visual summary of every check that ran: one bar per check (0–1 scores) with its
 * screening threshold, and a plain-language table of what each result means.
 * The checks are shown side by side and are never combined into one number.
 */
import { useEffect, useRef } from "react";
import Plotly from "plotly.js-dist-min";
import type { ScreeningResult } from "@/lib/types";
import { formatScore } from "@/lib/utils";
import { Badge, Card, CardContent, CardHeader, CardTitle } from "./ui";

type Check = ScreeningResult["checks"][number];

function isUnit(c: Check): boolean {
  return c.value !== null && !!c.range && c.range[0] === 0 && c.range[1] === 1;
}

function Chart({ checks }: { checks: Check[] }) {
  const el = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = el.current;
    if (!node || !checks.length) return;
    const rows = [...checks].reverse();
    void Plotly.newPlot(node, [{
      type: "bar", orientation: "h", x: rows.map((c) => c.value), y: rows.map((c) => c.check),
      marker: { color: rows.map((c) => (c.flagged ? "#b91c1c" : "#64748b")) },
      hovertemplate: "%{y}: %{x:.2f}<extra></extra>",
    }], {
      height: 60 + rows.length * 34, margin: { t: 10, l: 230, r: 20, b: 40 },
      xaxis: { range: [0, 1], title: { text: "score (0 = nothing found … 1 = strongest signal)" } },
      shapes: rows.flatMap((c, i) => (c.threshold !== null && c.threshold <= 1
        ? [{ type: "line", x0: c.threshold, x1: c.threshold, y0: i - 0.4, y1: i + 0.4, line: { color: "#d97706", width: 3 } }] : [])),
    }, { displaylogo: false, responsive: true, displayModeBar: false });
    return () => Plotly.purge(node);
  }, [checks]);
  return <div ref={el} className="w-full" data-testid="results-chart" />;
}

export function ResultsSummary({ s, onJump }: { s: ScreeningResult; onJump?: (moduleId: string) => void }) {
  const unit = s.checks.filter(isUnit);
  return (
    <Card data-testid="results-summary">
      <CardHeader><CardTitle>Results at a glance</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {s.checks.length === 0 && <p className="text-sm text-slate-500">No checks have finished yet.</p>}
        {unit.length > 0 && <>
          <Chart checks={unit} />
          <p className="text-xs text-slate-500">Grey bar = score; orange mark = screening threshold; red bar = this check raised a doubt.
            Each bar is a separate tool; they are never added or averaged together.</p>
        </>}
        <table className="w-full text-sm">
          <thead className="border-b text-left text-xs uppercase tracking-wide text-slate-500">
            <tr><th className="py-2">Check</th><th>What it looks at</th><th>Result</th><th>Doubt?</th></tr>
          </thead>
          <tbody>
            {s.checks.map((c) => (
              <tr key={c.module_id} className="border-b align-top last:border-0">
                <td className="py-2 pr-2">
                  <button className="text-left font-medium text-sky-900 hover:underline" onClick={() => onJump?.(c.module_id)}>{c.check}</button>
                  {c.triage_indicator && <div className="text-xs text-amber-800">AI tool — indicator only</div>}
                </td>
                <td className="pr-2 text-slate-700">{c.plain}</td>
                <td className="pr-2">
                  {c.score_name
                    ? <><span className="font-mono">{formatScore(c.value)}</span> <span className="text-xs text-slate-500">{c.score_name}{c.threshold !== null ? ` (threshold ${c.threshold})` : ""}</span>
                        <div className="text-xs text-slate-500">{c.meaning}</div></>
                    : <span className="text-xs text-slate-500">{c.summary}</span>}
                  {c.reason && <div className="text-xs text-red-800">{c.reason}</div>}
                </td>
                <td>{c.flagged ? <Badge tone="bad">doubt</Badge> : <Badge>none</Badge>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
