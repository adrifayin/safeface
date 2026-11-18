/** Screen 3: case page — evidence with hashes, upload, references, custody, members. */
import { useState, type DragEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp, ShieldAlert, ShieldCheck } from "lucide-react";
import { api, sha256OfFile, uploadEvidence } from "@/lib/api";
import type { CaseDetail, CustodyEntry, Evidence, EvidenceMetadata, Me } from "@/lib/types";
import { formatBytes, formatTime } from "@/lib/utils";
import { hasRole, useMe } from "@/components/Layout";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, ErrorBox, Input, Label, Mono, Select } from "@/components/ui";

export function CasePage() {
  const { caseId = "" } = useParams();
  const me = useMe();
  const detail = useQuery({ queryKey: ["case", caseId], queryFn: () => api.get<CaseDetail>(`/cases/${caseId}`) });
  if (detail.isLoading) return <div>Loading…</div>;
  if (detail.error || !detail.data) return <ErrorBox error={detail.error ?? "not found"} />;
  const c = detail.data;
  const canUpload = c.my_permission !== "view" && hasRole(me, "investigator", "examiner");
  const questioned = c.evidence.filter((e) => e.kind === "questioned");
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-3">
        <h1 className="text-xl font-semibold">Case {c.case_no}</h1>
        <span className="text-sm text-slate-600">{c.crime_head} · FIR {c.fir_no ?? "—"} · IO {c.investigating_officer}</span>
        <div className="ml-auto flex gap-2">
          {hasRole(me, "examiner", "supervisor", "auditor") && (
            <Button asChild variant="outline"><Link to={`/cases/${c.id}/report`}>Reports &amp; s.63(4) data</Link></Button>
          )}
        </div>
      </div>
      <div className="grid gap-4 xl:grid-cols-[1fr_420px]">
        <Card>
          <CardHeader><CardTitle>Evidence</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {c.evidence.length === 0 && <p className="text-sm text-slate-500">No evidence uploaded.</p>}
            {c.evidence.map((e) => <EvidenceRow key={e.id} e={e} all={c.evidence} me={me} canLink={canUpload} />)}
          </CardContent>
        </Card>
        <div className="space-y-4">
          {canUpload && <UploadPanel caseId={c.id} questioned={questioned} />}
          <Members c={c} />
        </div>
      </div>
    </div>
  );
}

function EvidenceRow({ e, all, me, canLink }: { e: Evidence; all: Evidence[]; me: Me | null; canLink: boolean }) {
  const qc = useQueryClient();
  const [showCustody, setShowCustody] = useState(false);
  const custody = useQuery({
    queryKey: ["custody", e.id], enabled: showCustody,
    queryFn: () => api.get<CustodyEntry[]>(`/evidence/${e.id}/custody`),
  });
  const verify = useMutation({
    mutationFn: () => api.post(`/evidence/${e.id}/verify`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["case", e.case_id] }),
  });
  const refs = all.filter((x) => x.kind === "reference" && !e.reference_ids.includes(x.id));
  const [refPick, setRefPick] = useState("");
  const link = useMutation({
    mutationFn: () => api.post(`/evidence/${e.id}/references`, { reference_ids: [refPick] }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["case", e.case_id] }),
  });
  const v = e.last_verification;
  return (
    <div className="rounded-md border p-3" data-testid={`evidence-${e.original_filename}`}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={e.kind === "questioned" ? "warn" : "info"}>{e.kind}</Badge>
        <strong>{e.original_filename}</strong>
        <span className="text-xs text-slate-500">{e.detected_mime} · {formatBytes(e.size_bytes)} · ingested {formatTime(e.ingested_at)}</span>
        {v && (v.ok
          ? <Badge tone="ok"><ShieldCheck className="mr-1 h-3 w-3" />hash verified {formatTime(v.verified_at)}</Badge>
          : <Badge tone="bad"><ShieldAlert className="mr-1 h-3 w-3" />HASH MISMATCH {formatTime(v.verified_at)}</Badge>)}
        <div className="ml-auto flex gap-2">
          {e.kind === "questioned" && hasRole(me, "investigator", "examiner", "supervisor") && (
            <Button asChild size="sm"><Link to={`/evidence/${e.id}`}>Open workbench</Link></Button>
          )}
          {hasRole(me, "examiner", "supervisor") && (
            <Button size="sm" variant="outline" onClick={() => verify.mutate()} disabled={verify.isPending}>Re-verify hash</Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => setShowCustody((s) => !s)}>Custody log</Button>
        </div>
      </div>
      <div className="mt-2 grid grid-cols-[70px_1fr] gap-x-2 text-xs">
        <span className="text-slate-500">SHA-256</span><Mono>{e.sha256}</Mono>
        <span className="text-slate-500">MD5</span><Mono>{e.md5}</Mono>
        <span className="text-slate-500">Source</span>
        <span>{[e.source_platform, e.source_url, e.source_device && `device: ${e.source_device}`, e.collected_by && `collected by ${e.collected_by}`, e.complainant && `complainant: ${e.complainant}`].filter(Boolean).join(" · ") || "—"}</span>
        {e.kind === "questioned" && <><span className="text-slate-500">References</span>
          <span>{e.reference_ids.map((r) => all.find((x) => x.id === r)?.original_filename ?? r).join(", ") || "none"}</span></>}
      </div>
      {e.kind === "questioned" && canLink && refs.length > 0 && (
        <div className="mt-2 flex gap-2">
          <Select value={refPick} onChange={(ev) => setRefPick(ev.target.value)} className="max-w-xs">
            <option value="">Attach reference…</option>
            {refs.map((r) => <option key={r.id} value={r.id}>{r.original_filename}</option>)}
          </Select>
          <Button size="sm" variant="outline" disabled={!refPick || link.isPending} onClick={() => link.mutate()}>Attach</Button>
        </div>
      )}
      <ErrorBox error={verify.error ?? link.error} />
      {showCustody && (
        <div className="mt-2 max-h-72 overflow-auto rounded bg-slate-50 p-2">
          <table className="w-full text-xs">
            <thead className="text-left text-slate-500"><tr><th>#</th><th>Time</th><th>Actor</th><th>Action</th><th>Entry hash</th></tr></thead>
            <tbody>
              {custody.data?.map((x) => (
                <tr key={x.seq} className="border-t align-top">
                  <td>{x.seq}</td><td className="whitespace-nowrap pr-2">{formatTime(x.ts)}</td><td className="pr-2">{x.actor}</td>
                  <td className="pr-2">{x.action}</td><td><Mono>{x.entry_hash.slice(0, 16)}…</Mono></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function UploadPanel({ caseId, questioned }: { caseId: string; questioned: Evidence[] }) {
  const qc = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [drag, setDrag] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [result, setResult] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [meta, setMeta] = useState<Omit<EvidenceMetadata, "filename">>({
    kind: "questioned", source_platform: "", source_url: "", source_device: "", complainant: "",
    collected_by: "", collected_at: "", upload_method: "web-upload", reference_for: [],
  });
  const set = (k: keyof typeof meta) => (e: { target: { value: string } }) => setMeta({ ...meta, [k]: e.target.value });

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]);
  };

  async function submit() {
    if (!file) return;
    setError(null);
    setResult(null);
    setProgress(0);
    const clean = Object.fromEntries(Object.entries(meta).map(([k, v]) => [k, v === "" ? null : v]));
    if (clean.collected_at) clean.collected_at = new Date(clean.collected_at as string).toISOString();
    try {
      const [local, res] = await Promise.all([
        sha256OfFile(file),
        uploadEvidence(caseId, file, { ...(clean as unknown as EvidenceMetadata), filename: file.name, kind: meta.kind }, setProgress),
      ]);
      const match = local === null ? "browser hash skipped (large file)" : local === res.sha256 ? "matches the hash computed in your browser" : "DOES NOT MATCH the browser hash";
      setResult(`Ingested. SHA-256 ${res.sha256} — ${match}. ${res.triage_job_ids.length} Tier 1 job(s) queued.`);
      setFile(null);
      void qc.invalidateQueries({ queryKey: ["case", caseId] });
    } catch (e) {
      setError(e);
    } finally {
      setProgress(null);
    }
  }

  return (
    <Card>
      <CardHeader><CardTitle>Upload evidence</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        <label
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={onDrop}
          className={`flex cursor-pointer flex-col items-center gap-2 rounded-md border-2 border-dashed p-6 text-center text-sm ${drag ? "border-slate-700 bg-slate-100" : "border-slate-300"}`}
        >
          <FileUp className="h-6 w-6" />
          {file ? <span><strong>{file.name}</strong> ({formatBytes(file.size)})</span> : <span>Drag a file here or click to choose (images, video, audio; max 4 GB)</span>}
          <input type="file" className="hidden" data-testid="file-input" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
        </label>
        <div className="grid grid-cols-2 gap-2">
          <div><Label>Kind</Label>
            <Select value={meta.kind} onChange={(e) => setMeta({ ...meta, kind: e.target.value as "questioned" | "reference" })} data-testid="kind-select">
              <option value="questioned">Questioned item</option>
              <option value="reference">Reference (e.g. victim's original)</option>
            </Select></div>
          <div><Label>Source platform</Label><Input value={meta.source_platform ?? ""} onChange={set("source_platform")} placeholder="WhatsApp, Instagram…" /></div>
          <div className="col-span-2"><Label>Source URL</Label><Input value={meta.source_url ?? ""} onChange={set("source_url")} placeholder="https://…" /></div>
          <div><Label>Source device</Label><Input value={meta.source_device ?? ""} onChange={set("source_device")} /></div>
          <div><Label>Complainant</Label><Input value={meta.complainant ?? ""} onChange={set("complainant")} /></div>
          <div><Label>Collected by</Label><Input value={meta.collected_by ?? ""} onChange={set("collected_by")} /></div>
          <div><Label>Collected at</Label><Input type="datetime-local" value={meta.collected_at ?? ""} onChange={set("collected_at")} /></div>
        </div>
        {meta.kind === "reference" && questioned.length > 0 && (
          <div><Label>Reference for</Label>
            <Select multiple value={meta.reference_for} className="h-20" data-testid="reference-for"
                    onChange={(e) => setMeta({ ...meta, reference_for: Array.from(e.target.selectedOptions).map((o) => o.value) })}>
              {questioned.map((q) => <option key={q.id} value={q.id}>{q.original_filename}</option>)}
            </Select></div>
        )}
        {progress !== null && (
          <div className="h-2 w-full rounded bg-slate-200"><div className="h-2 rounded bg-slate-800" style={{ width: `${Math.round(progress * 100)}%` }} /></div>
        )}
        {result && <div className="rounded bg-emerald-50 p-2 text-sm text-emerald-900" data-testid="upload-result">{result}</div>}
        <ErrorBox error={error} />
        <Button onClick={() => void submit()} disabled={!file || progress !== null} data-testid="upload-button">Hash &amp; ingest</Button>
        <p className="text-xs text-slate-500">The original is hashed (SHA-256 + MD5) while streaming, stored write-once, and never modified. Analysis runs on a verified working copy.</p>
      </CardContent>
    </Card>
  );
}

function Members({ c }: { c: CaseDetail }) {
  const me = useMe();
  const qc = useQueryClient();
  const isSup = hasRole(me, "supervisor");
  const dir = useQuery({ queryKey: ["directory"], enabled: isSup, queryFn: () => api.get<Me["user"][]>("/admin/directory") });
  const [pick, setPick] = useState({ user_id: "", permission: "analyse" });
  const add = useMutation({
    mutationFn: () => api.post(`/cases/${c.id}/members`, pick),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["case", c.id] }),
  });
  return (
    <Card>
      <CardHeader><CardTitle>Case members</CardTitle></CardHeader>
      <CardContent className="space-y-2 text-sm">
        {c.members.map((m) => <div key={m.user_id} className="flex justify-between"><span>{m.display_name} ({m.username})</span><Badge>{m.permission}</Badge></div>)}
        {isSup && (
          <div className="flex gap-2 pt-2">
            <Select value={pick.user_id} onChange={(e) => setPick({ ...pick, user_id: e.target.value })} data-testid="member-user">
              <option value="">Add member…</option>
              {dir.data?.filter((u) => !u.roles.every((r) => r === "admin")).map((u) => <option key={u.id} value={u.id}>{u.display_name} ({u.roles.join(", ")})</option>)}
            </Select>
            <Select value={pick.permission} onChange={(e) => setPick({ ...pick, permission: e.target.value })} className="w-28" data-testid="member-permission">
              <option value="view">view</option><option value="analyse">analyse</option><option value="approve">approve</option>
            </Select>
            <Button size="sm" disabled={!pick.user_id} onClick={() => add.mutate()}>Add</Button>
          </div>
        )}
        <ErrorBox error={add.error} />
      </CardContent>
    </Card>
  );
}
