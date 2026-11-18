/** Screen 2: case list and create-case form (FR-1.1). */
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { CaseSummary } from "@/lib/types";
import { formatTime } from "@/lib/utils";
import { hasRole, useMe } from "@/components/Layout";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, ErrorBox, Input, Label, Textarea } from "@/components/ui";

export function CasesPage() {
  const me = useMe();
  const cases = useQuery({ queryKey: ["cases"], queryFn: () => api.get<CaseSummary[]>("/cases") });
  const canCreate = hasRole(me, "investigator", "examiner", "supervisor");
  return (
    <div className="grid gap-4 lg:grid-cols-[1fr_380px]">
      <Card>
        <CardHeader><CardTitle>Cases</CardTitle></CardHeader>
        <CardContent>
          <ErrorBox error={cases.error} />
          <table className="w-full text-sm" data-testid="case-table">
            <thead className="text-left text-slate-500">
              <tr><th className="py-2">Case no.</th><th>FIR</th><th>Crime head</th><th>Investigating officer</th><th>Created</th><th>Access</th></tr>
            </thead>
            <tbody>
              {cases.data?.map((c) => (
                <tr key={c.id} className="border-t">
                  <td className="py-2"><Link className="font-medium text-sky-800 underline" to={`/cases/${c.id}`}>{c.case_no}</Link></td>
                  <td>{c.fir_no ?? "—"}</td>
                  <td>{c.crime_head}</td>
                  <td>{c.investigating_officer}</td>
                  <td>{formatTime(c.created_at)}</td>
                  <td>{c.my_permission ? <Badge tone="info">{c.my_permission}</Badge> : <Badge>not a member</Badge>}</td>
                </tr>
              ))}
              {cases.data?.length === 0 && <tr><td colSpan={6} className="py-6 text-center text-slate-500">No cases yet.</td></tr>}
            </tbody>
          </table>
        </CardContent>
      </Card>
      {canCreate && <CreateCase />}
    </div>
  );
}

function CreateCase() {
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
      <CardHeader><CardTitle>New case</CardTitle></CardHeader>
      <CardContent>
        <form onSubmit={submit} className="space-y-3">
          <div><Label htmlFor="case_no">Case number *</Label><Input id="case_no" required value={form.case_no} onChange={set("case_no")} placeholder="CDK/2026/0142" /></div>
          <div><Label htmlFor="fir_no">FIR number</Label><Input id="fir_no" value={form.fir_no} onChange={set("fir_no")} /></div>
          <div><Label htmlFor="crime_head">Crime head *</Label><Input id="crime_head" required value={form.crime_head} onChange={set("crime_head")} placeholder="IT Act s.66E / BNS s.77" /></div>
          <div><Label htmlFor="io">Investigating officer *</Label><Input id="io" required value={form.investigating_officer} onChange={set("investigating_officer")} /></div>
          <div><Label htmlFor="desc">Description / examination request</Label><Textarea id="desc" value={form.description} onChange={set("description")} /></div>
          <ErrorBox error={create.error} />
          <Button type="submit" disabled={create.isPending}>Create case</Button>
        </form>
      </CardContent>
    </Card>
  );
}
