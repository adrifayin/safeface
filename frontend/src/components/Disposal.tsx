/** FR-6.5: close a case and dispose of its derived data with two-supervisor approval. */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { CaseDetail } from "@/lib/types";
import { formatTime } from "@/lib/utils";
import { useMe } from "./Layout";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, ErrorBox, Input, Label, Textarea } from "./ui";

interface Disposal {
  id: string; reason: string; authority: string; requested_by_id: string; requested_at: string;
  status: string; decided_at: string | null; result: { derived_objects_deleted?: number; note?: string };
}

export function DisposalPanel({ c }: { c: CaseDetail }) {
  const me = useMe();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["disposals", c.id], queryFn: () => api.get<Disposal[]>(`/cases/${c.id}/disposals`) });
  const [form, setForm] = useState({ reason: "", authority: "" });
  const refresh = () => {
    void qc.invalidateQueries({ queryKey: ["disposals", c.id] });
    void qc.invalidateQueries({ queryKey: ["case", c.id] });
  };
  const close = useMutation({ mutationFn: () => api.post(`/cases/${c.id}/close`), onSuccess: refresh });
  const request = useMutation({ mutationFn: () => api.post(`/cases/${c.id}/disposals`, form), onSuccess: () => { setForm({ reason: "", authority: "" }); refresh(); } });
  const decide = useMutation({ mutationFn: ({ id, d }: { id: string; d: string }) => api.post(`/disposals/${id}/${d}`), onSuccess: refresh });
  const pending = list.data?.find((r) => r.status === "pending");
  return (
    <Card>
      <CardHeader><CardTitle>Case closure and disposal</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-xs text-slate-500">Status: <Badge>{c.status}</Badge>. Closing stops new evidence, analyses and notes. Disposal deletes working
          copies and figures after a second supervisor approves; hashes, findings, reports and the audit log are kept, and originals
          stay sealed until their write-once lock expires.</p>
        {c.status === "open" && (
          <Button size="sm" variant="outline" disabled={close.isPending}
                  onClick={() => { if (window.confirm(`Close case ${c.case_no}? No new evidence or analyses can be added afterwards.`)) close.mutate(); }}>
            Close case
          </Button>
        )}
        {c.status === "closed" && !pending && (
          <div className="space-y-2 border-t pt-2">
            <Label>Request disposal</Label>
            <Input placeholder="Authority (retention order / court direction)" value={form.authority} onChange={(e) => setForm({ ...form, authority: e.target.value })} />
            <Textarea placeholder="Reason (at least 10 characters)" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
            <Button size="sm" disabled={form.reason.trim().length < 10 || form.authority.trim().length < 5 || request.isPending} onClick={() => request.mutate()}>
              Submit for a second supervisor's approval
            </Button>
          </div>
        )}
        {list.data?.map((r) => (
          <div key={r.id} className="rounded border p-2 text-xs">
            <div className="flex items-center gap-2"><Badge tone={r.status === "approved" ? "ok" : r.status === "pending" ? "warn" : "neutral"}>{r.status}</Badge>
              <span>{r.authority}</span><span className="ml-auto text-slate-500">{formatTime(r.requested_at)}</span></div>
            <p className="mt-1">{r.reason}</p>
            {r.result?.note && <p className="mt-1 text-slate-600">{r.result.derived_objects_deleted} derived file(s) deleted. {r.result.note}</p>}
            {r.status === "pending" && (r.requested_by_id === me?.user.id
              ? <p className="mt-1 text-slate-500">Waiting for another supervisor to decide.</p>
              : <div className="mt-2 flex gap-2">
                  <Button size="sm" onClick={() => { if (window.confirm("Approve disposal? Working copies and figures of every item will be deleted.")) decide.mutate({ id: r.id, d: "approve" }); }}>Approve</Button>
                  <Button size="sm" variant="outline" onClick={() => decide.mutate({ id: r.id, d: "reject" })}>Reject</Button>
                </div>)}
          </div>
        ))}
        <ErrorBox error={close.error ?? request.error ?? decide.error} />
      </CardContent>
    </Card>
  );
}
