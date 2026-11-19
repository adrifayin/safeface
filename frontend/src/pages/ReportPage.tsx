/**
 * Screen 6: reports, report preview and BSA s.63(4) Part A data.
 *
 * Two kinds of report: one combined report for the whole case, and a separate
 * report for each questioned evidence item (covering that item and the
 * reference items linked to it). Each kind has its own version history.
 */
import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText } from "lucide-react";
import { api } from "@/lib/api";
import type { CaseDetail, Evidence, PerItemReports, Report } from "@/lib/types";
import { Empty, Hash, PageHeader } from "@/components/page";
import { formatTime } from "@/lib/utils";
import { hasRole, useMe } from "@/components/Layout";
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, ErrorBox, Select, Tabs, TabsContent, TabsList, TabsTrigger,
} from "@/components/ui";

async function sha256Hex(blob: Blob): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return Array.from(new Uint8Array(d)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

function fileName(r: Report, items: Map<string, Evidence>): string {
  if (!r.evidence_id) return `safeface-report-v${r.version}.pdf`;
  const stem = (items.get(r.evidence_id)?.original_filename ?? r.evidence_id).replace(/\.[^.]*$/, "");
  return `safeface-report-${stem.replace(/[^A-Za-z0-9_-]/g, "_").slice(0, 60) || "item"}-v${r.version}.pdf`;
}

export function ReportPage() {
  const { caseId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const me = useMe();
  const qc = useQueryClient();
  const canGenerate = hasRole(me, "examiner");
  const caseQ = useQuery({ queryKey: ["case", caseId], queryFn: () => api.get<CaseDetail>(`/cases/${caseId}`) });
  const reports = useQuery({ queryKey: ["reports", caseId], queryFn: () => api.get<Report[]>(`/cases/${caseId}/reports`) });
  const questioned = (caseQ.data?.evidence ?? []).filter((e) => e.kind === "questioned");
  const items = new Map((caseQ.data?.evidence ?? []).map((e) => [e.id, e]));

  // Preview scope: "" = whole case, otherwise one questioned item.
  const scope = params.get("item") ?? "";
  const setScope = (v: string) => setParams(v ? { item: v } : {}, { replace: true });
  const preview = useQuery({
    queryKey: ["preview", caseId, scope], enabled: canGenerate,
    queryFn: () => api.get<string>(scope ? `/evidence/${scope}/report-preview` : `/cases/${caseId}/report-preview`),
  });
  const s63 = useQuery({ queryKey: ["s63", caseId], enabled: canGenerate, queryFn: () => api.get<Record<string, unknown>>(`/cases/${caseId}/s63-data`) });

  const refresh = () => void qc.invalidateQueries({ queryKey: ["reports", caseId] });
  const generateCase = useMutation({ mutationFn: () => api.post<Report>(`/cases/${caseId}/reports`), onSuccess: refresh });
  const generateAll = useMutation({ mutationFn: () => api.post<PerItemReports>(`/cases/${caseId}/reports/per-item`), onSuccess: refresh });
  const generateOne = useMutation({ mutationFn: (id: string) => api.post<Report>(`/evidence/${id}/reports`), onSuccess: refresh });
  const [checks, setChecks] = useState<Record<string, string>>({});

  async function download(r: Report) {
    const { url, blob } = await api.blobUrl(`/reports/${r.id}/pdf`);
    const local = await sha256Hex(blob);
    setChecks((c) => ({ ...c, [r.id]: local === r.pdf_sha256 ? "SHA-256 of the downloaded file matches the register" : `MISMATCH: ${local}` }));
    const a = document.createElement("a");
    a.href = url;
    a.download = fileName(r, items);
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  const caseReports = (reports.data ?? []).filter((r) => !r.evidence_id);
  const byItem = (id: string) => (reports.data ?? []).filter((r) => r.evidence_id === id).sort((a, b) => b.version - a.version);

  const row = (r: Report) => (
    <div key={r.id} className="flex flex-wrap items-center gap-2 rounded border p-2" data-testid={`report-${r.evidence_id ?? "case"}-v${r.version}`}>
      <strong>Version {r.version}</strong>
      <Badge tone={r.status === "final" ? "ok" : "warn"}>{r.status}</Badge>
      <span className="text-xs text-slate-500">{formatTime(r.generated_at)}</span>
      <span className="text-xs">PDF SHA-256 <Hash value={r.pdf_sha256} full /></span>
      <Button size="sm" variant="outline" className="ml-auto" onClick={() => void download(r)}>Download PDF</Button>
      {checks[r.id] && <span className="w-full text-xs text-emerald-800" data-testid="pdf-hash-check">{checks[r.id]}</span>}
    </div>
  );

  return (
    <div className="space-y-4">
      <PageHeader crumbs={[{ label: "Cases", to: "/" }, { label: caseQ.data?.case_no ?? "Case", to: `/cases/${caseId}` }, { label: "Reports" }]}
                  title="Reports and s.63(4) data"
                  subtitle="A report is FINAL only when every questioned item it covers has a supervisor-approved conclusion; otherwise it is marked DRAFT." />

      <Card>
        <CardHeader className="flex flex-wrap items-center gap-3">
          <div>
            <CardTitle>Separate report for each evidence item</CardTitle>
            <p className="mt-0.5 text-xs text-slate-500">Each questioned item gets its own PDF, covering that item and the reference items linked to it.</p>
          </div>
          {canGenerate && questioned.length > 0 && (
            <Button className="ml-auto" onClick={() => generateAll.mutate()} disabled={generateAll.isPending} data-testid="generate-per-item">
              {generateAll.isPending ? `Re-verifying and rendering ${questioned.length} report(s)…` : `Generate all ${questioned.length} item reports`}
            </Button>
          )}
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          <ErrorBox error={generateAll.error ?? generateOne.error} />
          {generateAll.data && (
            <div className="rounded border border-emerald-300 bg-emerald-50 p-2 text-xs text-emerald-900" data-testid="per-item-result">
              {generateAll.data.generated.length} report(s) generated.
              {generateAll.data.refused.length > 0 && (
                <span className="text-red-800"> Refused (hash verification failed): {generateAll.data.refused.map((x) => x.filename).join(", ")}.</span>
              )}
            </div>
          )}
          {questioned.length === 0 && <Empty title="No questioned items in this case yet." />}
          {questioned.map((e) => {
            const versions = byItem(e.id);
            const refs = e.reference_ids.map((id) => items.get(id)?.original_filename ?? id);
            return (
              <div key={e.id} className="rounded-md border p-3" data-testid={`item-reports-${e.id}`}>
                <div className="mb-2 flex flex-wrap items-center gap-2">
                  <FileText className="h-4 w-4 text-slate-500" />
                  <Link to={`/evidence/${e.id}`} className="font-medium hover:underline">{e.original_filename}</Link>
                  <span className="text-xs text-slate-500">{e.media_type}</span>
                  {refs.length > 0 && <span className="text-xs text-slate-500">· with reference(s): {refs.join(", ")}</span>}
                  <div className="ml-auto flex gap-2">
                    {canGenerate && <Button size="sm" variant="ghost" onClick={() => setScope(e.id)}>Preview</Button>}
                    {canGenerate && (
                      <Button size="sm" onClick={() => generateOne.mutate(e.id)}
                              disabled={generateOne.isPending && generateOne.variables === e.id} data-testid={`generate-item-${e.id}`}>
                        {generateOne.isPending && generateOne.variables === e.id ? "Rendering…" : "Generate report"}
                      </Button>
                    )}
                  </div>
                </div>
                <div className="space-y-1.5">
                  {versions.length === 0 ? <p className="text-xs text-slate-500">No report for this item yet.</p> : versions.map(row)}
                </div>
              </div>
            );
          })}
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="flex items-center gap-3">
          <CardTitle>Combined case report</CardTitle>
          {canGenerate && (
            <Button variant="outline" className="ml-auto" onClick={() => generateCase.mutate()} disabled={generateCase.isPending} data-testid="generate-report">
              {generateCase.isPending ? "Re-verifying hashes and rendering…" : "Generate combined report (re-verifies all hashes)"}
            </Button>
          )}
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <ErrorBox error={generateCase.error} />
          {reports.data && caseReports.length === 0 && <Empty title="No combined report yet.">{canGenerate ? "Generating a report first re-verifies every evidence hash." : ""}</Empty>}
          {caseReports.map(row)}
        </CardContent>
      </Card>

      {canGenerate && (
        <Tabs defaultValue="preview">
          <TabsList><TabsTrigger value="preview">Report preview</TabsTrigger><TabsTrigger value="s63">s.63(4) Part A data</TabsTrigger></TabsList>
          <TabsContent value="preview">
            <Card><CardContent className="space-y-2">
              <label className="flex items-center gap-2 text-sm">
                <span className="shrink-0">Preview of</span>
                <Select value={scope} onChange={(ev) => setScope(ev.target.value)} className="max-w-md" data-testid="preview-scope">
                  <option value="">Combined case report</option>
                  {questioned.map((e) => <option key={e.id} value={e.id}>Item report: {e.original_filename}</option>)}
                </Select>
              </label>
              {/* Sandboxed: no scripts, no network; the server also sends a strict CSP. */}
              {preview.data && <iframe title="report preview" sandbox="" srcDoc={preview.data} className="h-[900px] w-full rounded border bg-white" />}
              <ErrorBox error={preview.error} />
            </CardContent></Card>
          </TabsContent>
          <TabsContent value="s63">
            <Card><CardContent>
              <p className="mb-2 text-sm text-slate-600">Pre-filled facts for the Bharatiya Sakshya Adhiniyam s.63(4) certificate, Part A. Null fields must be completed manually by the person responsible for the device/record.</p>
              <pre className="max-h-[700px] overflow-auto rounded bg-slate-50 p-3 text-xs" data-testid="s63-json">{JSON.stringify(s63.data, null, 2)}</pre>
            </CardContent></Card>
          </TabsContent>
        </Tabs>
      )}
    </div>
  );
}
