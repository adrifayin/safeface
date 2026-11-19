/** Phase 4: run benchmarks on labelled test sets and see the results (Administration → Validation). */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { formatTime } from "@/lib/utils";
import { hasRole, useMe } from "./Layout";
import { Empty, Loading } from "./page";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, ErrorBox, Label, Select, Switch } from "./ui";

interface Metrics { n: number; n_fake: number; n_failed: number; auc?: number; tpr_at_1pct_fpr?: number; tpr_at_5pct_fpr?: number; ece?: number; pixel_f1?: number; pixel_iou?: number }
interface Run {
  id: string; module_id: string; dataset: string; robustness: boolean; status: string;
  requested_at: string; finished_at: string | null; error: string | null;
  results: { clean?: Metrics; jpeg70?: Metrics; resize50?: Metrics; messaging?: Metrics };
}
interface Datasets { datasets: { name: string; items: number; fake: number; masks: boolean }[]; modules: string[]; layout: string }

const fmt = (v: number | undefined) => (v === undefined ? "—" : v.toFixed(2));

export function ValidationPanel() {
  const me = useMe();
  const qc = useQueryClient();
  const ds = useQuery({ queryKey: ["datasets"], queryFn: () => api.get<Datasets>("/admin/datasets") });
  const runs = useQuery({
    queryKey: ["benchmarks"], queryFn: () => api.get<Run[]>("/admin/benchmarks"),
    refetchInterval: (q) => (q.state.data?.some((r) => r.status === "queued" || r.status === "running") ? 5000 : false),
  });
  const [form, setForm] = useState({ module_id: "", dataset: "", robustness: false });
  const start = useMutation({
    mutationFn: () => api.post("/admin/benchmarks", form),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["benchmarks"] }),
  });
  const canRun = hasRole(me, "admin", "supervisor");
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle>Run a validation benchmark</CardTitle></CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p className="text-xs text-slate-500">Measures how well a detector separates known authentic and known manipulated items: AUC,
            detection rate at 1% and 5% false-alarm rate (false accusations matter most), calibration, and pixel F1/IoU where masks exist.
            Test sets are placed on the server under <code>datasets/</code> ({ds.data?.layout ?? "real/ and fake/ folders"}); nothing is downloaded.</p>
          {ds.isLoading ? <Loading /> : ds.data?.datasets.length === 0 ? (
            <Empty title="No test sets found.">Copy a labelled set into the server's <code>datasets/</code> folder (for example Deepfake-Eval-2024 images or the team test set).</Empty>
          ) : (
            <div className="grid gap-3 md:grid-cols-4">
              <div><Label>Detector</Label>
                <Select value={form.module_id} onChange={(e) => setForm({ ...form, module_id: e.target.value })}>
                  <option value="">Choose…</option>{ds.data?.modules.map((m) => <option key={m} value={m}>{m}</option>)}
                </Select></div>
              <div><Label>Test set</Label>
                <Select value={form.dataset} onChange={(e) => setForm({ ...form, dataset: e.target.value })}>
                  <option value="">Choose…</option>
                  {ds.data?.datasets.map((d) => <option key={d.name} value={d.name}>{d.name} ({d.items} items, {d.fake} manipulated{d.masks ? ", masks" : ""})</option>)}
                </Select></div>
              <label className="flex items-end gap-2 pb-2"><Switch checked={form.robustness} onCheckedChange={(v) => setForm({ ...form, robustness: v })} />
                Also test after JPEG 70, 50% resize and messaging-app compression</label>
              <div className="flex items-end">
                <Button disabled={!canRun || !form.module_id || !form.dataset || start.isPending} onClick={() => start.mutate()}>Start benchmark</Button>
              </div>
            </div>
          )}
          <ErrorBox error={start.error ?? ds.error} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Benchmark runs</CardTitle></CardHeader>
        <CardContent>
          {runs.data?.length === 0 && <Empty title="No runs yet." />}
          {!!runs.data?.length && (
            <table className="w-full text-xs">
              <thead className="border-b text-left uppercase tracking-wide text-slate-500">
                <tr><th className="py-2">Detector</th><th>Test set</th><th>Status</th><th>Items</th><th>AUC</th><th>TPR@1%FPR</th><th>TPR@5%FPR</th><th>Pixel F1</th><th>AUC after compression (JPEG70 / resize / messaging)</th><th>Finished</th></tr>
              </thead>
              <tbody>{runs.data.map((r) => {
                const c = r.results.clean;
                return (
                  <tr key={r.id} className="border-b align-top last:border-0">
                    <td className="py-2 font-mono">{r.module_id}</td><td>{r.dataset}</td>
                    <td><Badge tone={r.status === "succeeded" ? "ok" : r.status === "failed" ? "bad" : "info"}>{r.status}</Badge>
                      {r.error && <div className="text-red-800">{r.error}</div>}</td>
                    <td>{c ? `${c.n} (${c.n_fake} manip.)` : "—"}</td>
                    <td>{fmt(c?.auc)}</td><td>{fmt(c?.tpr_at_1pct_fpr)}</td><td>{fmt(c?.tpr_at_5pct_fpr)}</td><td>{fmt(c?.pixel_f1)}</td>
                    <td>{r.robustness ? `${fmt(r.results.jpeg70?.auc)} / ${fmt(r.results.resize50?.auc)} / ${fmt(r.results.messaging?.auc)}` : "—"}</td>
                    <td>{formatTime(r.finished_at)}</td>
                  </tr>
                );
              })}</tbody>
            </table>
          )}
          <p className="mt-2 text-xs text-slate-500">AUC: 0.5 = no better than chance, 1.0 = perfect separation. TPR@1%FPR: share of manipulated items caught when only 1 in 100 authentic items is wrongly flagged.
            Results appear beside each score in the workbench and in reports.</p>
        </CardContent>
      </Card>
    </div>
  );
}
