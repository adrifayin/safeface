/** Screen 2: case list and create-case form (FR-1.1). */
import { useMemo, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Search, X } from "lucide-react";
import { api } from "@/lib/api";
import type { CaseSummary } from "@/lib/types";
import { formatTime } from "@/lib/utils";
import { hasRole, useMe } from "@/components/Layout";
import { Empty, Loading, PageHeader } from "@/components/page";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, ErrorBox, Input, Label, Textarea } from "@/components/ui";

const PERMISSION_LABEL: Record<string, string> = { view: "View", analyse: "Analyse", approve: "Approve" };

export function CasesPage() {
  const me = useMe();
  const navigate = useNavigate();
  const cases = useQuery({ queryKey: ["cases"], queryFn: () => api.get<CaseSummary[]>("/cases") });
  const canCreate = hasRole(me, "investigator", "examiner", "supervisor");
  const [showForm, setShowForm] = useState(false);
  const [q, setQ] = useState("");
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (cases.data ?? []).filter((c) => !needle ||
      [c.case_no, c.fir_no, c.crime_head, c.investigating_officer].some((v) => v?.toLowerCase().includes(needle)));
  }, [cases.data, q]);

  return (
    <div>
      <PageHeader
        title="Cases"
        subtitle={hasRole(me, "supervisor") ? "All cases in the unit. Open a case to assign examiners and approvers."
          : hasRole(me, "auditor") ? "Cases you have been given access to (read-only)."
          : "Cases you are a member of."}
        actions={canCreate && !showForm && <Button onClick={() => setShowForm(true)}><Plus className="h-4 w-4" /> New case</Button>}
      />
      <div className={showForm ? "grid gap-4 lg:grid-cols-[1fr_400px]" : ""}>
        <Card>
          <CardContent className="space-y-3">
            <div className="relative max-w-sm">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
              <Input className="pl-8" placeholder="Search case no., FIR, crime head, officer" value={q} onChange={(e) => setQ(e.target.value)} />
            </div>
            <ErrorBox error={cases.error} />
            {cases.isLoading ? <Loading /> : rows.length === 0 ? (
              <Empty title={q ? "No cases match your search." : "No cases yet."}>
                {!q && canCreate && "Use “New case” to register one."}
              </Empty>
            ) : (
              <table className="w-full text-sm" data-testid="case-table">
                <thead className="border-b text-left text-xs uppercase tracking-wide text-slate-500">
                  <tr><th className="py-2">Case no.</th><th>FIR</th><th>Crime head</th><th>Investigating officer</th><th>Created</th><th>Status</th><th>Your access</th></tr>
                </thead>
                <tbody>
                  {rows.map((c) => (
                    <tr key={c.id} className="cursor-pointer border-b last:border-0 hover:bg-slate-50" onClick={() => navigate(`/cases/${c.id}`)}>
                      <td className="py-2.5"><a href={`/cases/${c.id}`} onClick={(e) => e.preventDefault()} className="font-medium text-sky-800 hover:underline">{c.case_no}</a></td>
                      <td>{c.fir_no ?? "—"}</td>
                      <td>{c.crime_head}</td>
                      <td>{c.investigating_officer}</td>
                      <td className="whitespace-nowrap text-slate-600">{formatTime(c.created_at)}</td>
                      <td><Badge tone={c.status === "open" ? "info" : "neutral"}>{c.status}</Badge></td>
                      <td>{c.my_permission ? <Badge>{PERMISSION_LABEL[c.my_permission] ?? c.my_permission}</Badge> : <span className="text-xs text-slate-400">not a member</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>
        {showForm && <CreateCase onClose={() => setShowForm(false)} />}
      </div>
    </div>
  );
}

function CreateCase({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [form, setForm] = useState({ case_no: "", fir_no: "", crime_head: "", investigating_officer: "", description: "" });
  const create = useMutation({
    mutationFn: () => api.post<CaseSummary>("/cases", { ...form, fir_no: form.fir_no || null, description: form.description || null }),
    onSuccess: (c) => {
      void qc.invalidateQueries({ queryKey: ["cases"] });
      navigate(`/cases/${c.id}`);
    },
  });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };
  return (
    <Card>
      <CardHeader className="flex items-center">
        <CardTitle>New case</CardTitle>
        <Button variant="ghost" size="sm" className="ml-auto" onClick={onClose} aria-label="Close"><X className="h-4 w-4" /></Button>
      </CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-3">
          <div><Label htmlFor="case_no">Case number *</Label><Input id="case_no" required value={form.case_no} onChange={set("case_no")} placeholder="e.g. CDK/2026/0142" />
            <p className="mt-1 text-xs text-slate-500">Letters, digits and / _ . - only.</p></div>
          <div><Label htmlFor="fir_no">FIR number</Label><Input id="fir_no" value={form.fir_no} onChange={set("fir_no")} /></div>
          <div><Label htmlFor="crime_head">Crime head *</Label><Input id="crime_head" required value={form.crime_head} onChange={set("crime_head")} placeholder="e.g. IT Act s.66E / BNS s.77" /></div>
          <div><Label htmlFor="io">Investigating officer *</Label><Input id="io" required value={form.investigating_officer} onChange={set("investigating_officer")} placeholder="Name and rank" /></div>
          <div><Label htmlFor="desc">Examination request</Label><Textarea id="desc" value={form.description} onChange={set("description")} placeholder="What needs to be established?" /></div>
          <ErrorBox error={create.error} />
          <div className="flex gap-2">
            <Button type="submit" disabled={create.isPending}>Create case</Button>
            <Button type="button" variant="outline" onClick={onClose}>Cancel</Button>
          </div>
          <p className="text-xs text-slate-500">You become a member of the case. A supervisor can add examiners and approvers.</p>
        </form>
      </CardContent>
    </Card>
  );
}
