/** Screen 5b: supervisor approval view (FR-5.5). */
import { useState } from "react";
import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Conclusion } from "@/lib/types";
import { formatTime } from "@/lib/utils";
import { useMe } from "@/components/Layout";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, ErrorBox, Textarea } from "@/components/ui";

export function ApprovalsPage() {
  const pending = useQuery({ queryKey: ["pending"], queryFn: () => api.get<Conclusion[]>("/approvals/pending") });
  return (
    <Card>
      <CardHeader><CardTitle>Conclusions awaiting your approval</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <ErrorBox error={pending.error} />
        {pending.data?.length === 0 && <p className="text-sm text-slate-500">Nothing pending.</p>}
        {pending.data?.map((c) => <ApprovalItem key={c.id} c={c} />)}
      </CardContent>
    </Card>
  );
}

function ApprovalItem({ c }: { c: Conclusion }) {
  const me = useMe();
  const qc = useQueryClient();
  const [comment, setComment] = useState("");
  const approve = useMutation({
    mutationFn: () => api.post(`/conclusions/${c.id}/approve`, { comment: comment || null }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["pending"] }),
  });
  const own = me?.user.id === c.author_id;
  return (
    <div className="rounded-md border p-3 text-sm" data-testid={`approval-${c.id}`}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="warn">Case {c.case_no}</Badge>
        <strong>{c.evidence_filename}</strong>
        <span>— {c.scale_label}</span>
        <Link className="ml-auto text-sky-800 underline" to={`/evidence/${c.evidence_id}`}>Review findings</Link>
      </div>
      <p className="mt-2">{c.rationale}</p>
      <p className="text-xs text-slate-500">Recorded by {c.author_name}, {formatTime(c.created_at)}</p>
      {own ? <p className="mt-2 text-xs text-red-700">You wrote this conclusion; another supervisor must approve it.</p> : (
        <div className="mt-2 flex gap-2">
          <Textarea className="min-h-9" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Approval comment (optional)" />
          <Button onClick={() => approve.mutate()} disabled={approve.isPending} data-testid="approve-button">Approve</Button>
        </div>
      )}
      <ErrorBox error={approve.error} />
    </div>
  );
}
