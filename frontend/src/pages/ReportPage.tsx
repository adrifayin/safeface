/** Screen 6: report preview + export, and BSA s.63(4) Part A data view. */
import { useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { CaseDetail, Report } from "@/lib/types";
import { Empty, Hash, PageHeader } from "@/components/page";
import { formatTime } from "@/lib/utils";
import { hasRole, useMe } from "@/components/Layout";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, ErrorBox, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";

async function sha256Hex(blob: Blob): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", await blob.arrayBuffer());
  return Array.from(new Uint8Array(d)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function ReportPage() {
  const { caseId = "" } = useParams();
  const me = useMe();
  const qc = useQueryClient();
  const canGenerate = hasRole(me, "examiner");
  const caseQ = useQuery({ queryKey: ["case", caseId], queryFn: () => api.get<CaseDetail>(`/cases/${caseId}`) });
  const reports = useQuery({ queryKey: ["reports", caseId], queryFn: () => api.get<Report[]>(`/cases/${caseId}/reports`) });
  const preview = useQuery({ queryKey: ["preview", caseId], enabled: canGenerate, queryFn: () => api.get<string>(`/cases/${caseId}/report-preview`) });
  const s63 = useQuery({ queryKey: ["s63", caseId], enabled: canGenerate, queryFn: () => api.get<Record<string, unknown>>(`/cases/${caseId}/s63-data`) });
  const generate = useMutation({
    mutationFn: () => api.post<Report>(`/cases/${caseId}/reports`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["reports", caseId] }),
  });
  const [checks, setChecks] = useState<Record<string, string>>({});

  async function download(r: Report) {
    const { url, blob } = await api.blobUrl(`/reports/${r.id}/pdf`);
    const local = await sha256Hex(blob);
    setChecks((c) => ({ ...c, [r.id]: local === r.pdf_sha256 ? "SHA-256 of the downloaded file matches the register" : `MISMATCH: ${local}` }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `safeface-report-v${r.version}.pdf`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  }

  return (
    <div className="space-y-4">
      <PageHeader crumbs={[{ label: "Cases", to: "/" }, { label: caseQ.data?.case_no ?? "Case", to: `/cases/${caseId}` }, { label: "Reports" }]}
                  title="Reports and s.63(4) data"
                  subtitle="A report is FINAL only when every questioned item has a supervisor-approved conclusion; otherwise it is marked DRAFT." />
      <Card>
        <CardHeader className="flex items-center gap-3">
          <CardTitle>Reports</CardTitle>
          {canGenerate && (
            <Button className="ml-auto" onClick={() => generate.mutate()} disabled={generate.isPending} data-testid="generate-report">
              {generate.isPending ? "Re-verifying hashes and rendering…" : "Generate report (re-verifies all hashes)"}
            </Button>
          )}
        </CardHeader>
        <CardContent className="space-y-2 text-sm">
          <ErrorBox error={generate.error} />
          {reports.data?.length === 0 && <Empty title="No reports yet.">{canGenerate ? "Generating a report first re-verifies every evidence hash." : ""}</Empty>}
          {reports.data?.map((r) => (
            <div key={r.id} className="flex flex-wrap items-center gap-2 rounded border p-2" data-testid={`report-v${r.version}`}>
              <strong>Version {r.version}</strong>
              <Badge tone={r.status === "final" ? "ok" : "warn"}>{r.status}</Badge>
              <span className="text-xs text-slate-500">{formatTime(r.generated_at)}</span>
              <span className="text-xs">PDF SHA-256 <Hash value={r.pdf_sha256} full /></span>
              <Button size="sm" variant="outline" className="ml-auto" onClick={() => void download(r)}>Download PDF</Button>
              {checks[r.id] && <span className="w-full text-xs text-emerald-800" data-testid="pdf-hash-check">{checks[r.id]}</span>}
            </div>
          ))}
        </CardContent>
      </Card>
      {canGenerate && (
        <Tabs defaultValue="preview">
          <TabsList><TabsTrigger value="preview">Report preview</TabsTrigger><TabsTrigger value="s63">s.63(4) Part A data</TabsTrigger></TabsList>
          <TabsContent value="preview">
            <Card><CardContent>
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
