/** Audit log browser for supervisors and auditors, with JSONL export for court. */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "@/lib/api";
import { formatTime } from "@/lib/utils";
import { Button, Card, CardContent, CardHeader, CardTitle, ErrorBox, Input, Mono } from "@/components/ui";

interface Entry { seq: number; ts: string; actor: string; action: string; target_type: string; target_id: string; entry_hash: string; details: Record<string, unknown> }

export function AuditPage() {
  const [after, setAfter] = useState(0);
  const [target, setTarget] = useState("");
  const q = useQuery({
    queryKey: ["audit", after, target],
    queryFn: () => api.get<Entry[]>(`/audit/entries?after_seq=${after}&limit=200${target ? `&target_id=${encodeURIComponent(target)}` : ""}`),
  });
  async function exportChain() {
    const { url } = await api.blobUrl("/audit/export");
    const a = document.createElement("a");
    a.href = url;
    a.download = "safeface-audit.jsonl";
    a.click();
  }
  return (
    <Card>
      <CardHeader className="flex items-center gap-2"><CardTitle>Audit log</CardTitle>
        <Button size="sm" variant="outline" className="ml-auto" onClick={() => void exportChain()}>Export chain (JSONL)</Button></CardHeader>
      <CardContent>
        <div className="mb-2 flex gap-2">
          <Input placeholder="Filter by target id (case / evidence UUID)" value={target} onChange={(e) => setTarget(e.target.value)} />
          <Button variant="outline" onClick={() => setAfter(Math.max(0, after - 200))}>Previous</Button>
          <Button variant="outline" onClick={() => setAfter(q.data?.at(-1)?.seq ?? after)}>Next</Button>
        </div>
        <ErrorBox error={q.error} />
        <table className="w-full text-xs">
          <thead className="text-left text-slate-500"><tr><th>#</th><th>Time</th><th>Actor</th><th>Action</th><th>Target</th><th>Hash</th></tr></thead>
          <tbody>{q.data?.map((e) => (
            <tr key={e.seq} className="border-t align-top" title={JSON.stringify(e.details)}>
              <td className="py-1">{e.seq}</td><td className="whitespace-nowrap pr-2">{formatTime(e.ts)}</td><td className="pr-2">{e.actor}</td>
              <td className="pr-2">{e.action}</td><td className="pr-2">{e.target_type}:{e.target_id.slice(0, 8)}</td><td><Mono>{e.entry_hash.slice(0, 16)}…</Mono></td>
            </tr>
          ))}</tbody>
        </table>
      </CardContent>
    </Card>
  );
}
