/** Evidence integrity, shown first and prominently: is this exactly the file that was received? */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Lock, ShieldAlert, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { formatTime } from "@/lib/utils";
import { Hash } from "./page";
import { Button, ErrorBox } from "./ui";
import { useT } from "@/lib/i18n";

interface IntegrityInfo {
  status: "verified" | "FAILED" | "not yet verified";
  statement: string;
  sha256: string;
  md5: string;
  size_bytes: number;
  ingested_at: string;
  last_verified_at: string | null;
  verifications: number;
  failed_verifications: number;
  sealed: { mode: string; retain_until: string } | null;
  working_copy: string;
  custody_entries: number;
  custody_head_hash: string | null;
}

export function IntegrityPanel({ evidenceId, canVerify }: { evidenceId: string; canVerify: boolean }) {
  const qc = useQueryClient();
  const t = useT();
  const q = useQuery({ queryKey: ["integrity", evidenceId], queryFn: () => api.get<IntegrityInfo>(`/evidence/${evidenceId}/integrity`) });
  const verify = useMutation({
    mutationFn: () => api.post(`/evidence/${evidenceId}/verify`),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["integrity", evidenceId] }); void qc.invalidateQueries({ queryKey: ["evidence", evidenceId] }); },
  });
  const d = q.data;
  if (!d) return null;
  const ok = d.status === "verified";
  return (
    <div className={`rounded-md border-2 p-4 ${ok ? "border-emerald-300 bg-emerald-50 text-emerald-950" : "border-red-300 bg-red-50 text-red-950"}`}
         data-testid="integrity-panel">
      <div className="flex flex-wrap items-start gap-3">
        {ok ? <ShieldCheck className="h-6 w-6 shrink-0" /> : <ShieldAlert className="h-6 w-6 shrink-0" />}
        <div className="min-w-0 flex-1 space-y-2">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide opacity-80">{t("Evidence integrity")}</div>
            <div className="text-lg font-semibold" data-testid="integrity-status">
              {ok ? t("Verified — unchanged since it was received") : d.status === "FAILED" ? "INTEGRITY FAILURE" : "Not yet verified"}
            </div>
            <p className="text-sm">{d.statement}</p>
          </div>
          <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
            <dt className="opacity-70">SHA-256</dt><dd><Hash value={d.sha256} full /></dd>
            <dt className="opacity-70">Received</dt><dd>{formatTime(d.ingested_at)}</dd>
            <dt className="opacity-70">Last re-check</dt><dd>{formatTime(d.last_verified_at)} ({d.verifications} check{d.verifications === 1 ? "" : "s"}, {d.failed_verifications} failed)</dd>
            <dt className="opacity-70">Original</dt>
            <dd className="flex items-center gap-1"><Lock className="h-3.5 w-3.5" />
              {d.sealed ? `Sealed, write-once (${d.sealed.mode.toLowerCase()} lock until ${formatTime(d.sealed.retain_until)})` : "Sealed in write-once storage"}</dd>
            <dt className="opacity-70">Working copy</dt><dd>{d.working_copy}</dd>
            <dt className="opacity-70">Custody log</dt><dd>{d.custody_entries} recorded actions; latest entry <Hash value={d.custody_head_hash} /></dd>
          </dl>
        </div>
        {canVerify && <Button size="sm" variant="outline" onClick={() => verify.mutate()} disabled={verify.isPending}>
          {verify.isPending ? "Re-checking…" : "Re-check now"}</Button>}
      </div>
      <ErrorBox error={verify.error} />
    </div>
  );
}
