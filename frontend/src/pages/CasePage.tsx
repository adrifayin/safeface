/** Screen 3: case page — evidence with hashes, upload, references, custody, members. */
import { useEffect, useState, type DragEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, FileUp, History, Microscope, Plus, ShieldAlert, ShieldCheck } from "lucide-react";
import { api, sha256OfFile, uploadEvidence } from "@/lib/api";
import type { CaseDetail, CustodyEntry, Evidence, EvidenceMetadata, Me, ScreeningResult } from "@/lib/types";
import { formatBytes, formatTime } from "@/lib/utils";
import { hasRole, useMe } from "@/components/Layout";
import { Empty, Facts, Hash, Loading, Notice, PageHeader } from "@/components/page";
import { ScreeningBadge } from "@/components/Screening";
import { DisposalPanel } from "@/components/Disposal";
import { useT } from "@/lib/i18n";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, ErrorBox, Input, Label, Select } from "@/components/ui";

export function CasePage() {
  const { caseId = "" } = useParams();
  const me = useMe();
  const t = useT();
  const detail = useQuery({ queryKey: ["case", caseId], queryFn: () => api.get<CaseDetail>(`/cases/${caseId}`) });
  const screening = useQuery({
    queryKey: ["case-screening", caseId, detail.data?.evidence.length],
    enabled: !!detail.data?.my_permission && hasRole(me, "investigator", "examiner", "supervisor"),
    queryFn: () => api.get<{ items: Record<string, ScreeningResult> }>(`/cases/${caseId}/screening`),
    refetchInterval: 10_000,
  });
  const [showUpload, setShowUpload] = useState<boolean | null>(null);
  // Decide once, on first load: an empty case opens the upload panel; afterwards only the user closes it.
  useEffect(() => {
    if (detail.data && showUpload === null) setShowUpload(detail.data.evidence.length === 0);
  }, [detail.data, showUpload]);
  if (detail.isLoading) return <Loading />;
  if (detail.error || !detail.data) return <ErrorBox error={detail.error ?? "Case not found"} />;
  const c = detail.data;
  const canUpload = c.status === "open" && !!c.my_permission && c.my_permission !== "view" && hasRole(me, "investigator", "examiner");
  const uploadOpen = canUpload && showUpload === true;
  const questioned = c.evidence.filter((e) => e.kind === "questioned");
  const references = c.evidence.filter((e) => e.kind === "reference");
  return (
    <div>
      <PageHeader
        crumbs={[{ label: "Cases", to: "/" }, { label: c.case_no }]}
        title={`Case ${c.case_no}`}
        subtitle={c.crime_head}
        actions={<>
          {canUpload && !uploadOpen && <Button onClick={() => setShowUpload(true)}><Plus className="h-4 w-4" /> {t("Add evidence")}</Button>}
          {hasRole(me, "examiner", "supervisor", "auditor") && c.my_permission && (
            <Button asChild variant="outline"><Link to={`/cases/${c.id}/report`}><FileText className="h-4 w-4" /> Reports &amp; s.63(4)</Link></Button>
          )}
        </>}
      />
      {!c.my_permission && (
        <div className="mb-4"><Notice>You are viewing this case as a supervisor without membership. Add yourself or others under
          “Case members”; evidence media opens only for members.</Notice></div>
      )}
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_400px]">
        <div className="space-y-4">
          <Card>
            <CardContent>
              <Facts items={[
                ["FIR number", c.fir_no], ["Investigating officer", c.investigating_officer],
                ["Created", formatTime(c.created_at)], ["Status", <Badge key="s" tone="info">{c.status}</Badge>],
                ["Examination request", c.description],
              ]} />
            </CardContent>
          </Card>
          <EvidenceSection title={t("Questioned items")} items={questioned} all={c.evidence} me={me} canLink={canUpload}
                           screening={screening.data?.items}
                           empty={canUpload ? "Upload the image or video to be examined." : "No questioned items yet."} />
          <EvidenceSection title={t("Reference items")} items={references} all={c.evidence} me={me} canLink={false}
                           empty="Optional: the complainant's original photos or images from a suspect device, for comparison." />
        </div>
        <div className="space-y-4">
          {uploadOpen && <UploadPanel caseId={c.id} questioned={questioned} onClose={() => setShowUpload(false)} />}
          <Members c={c} />
          {hasRole(me, "supervisor") && <DisposalPanel c={c} />}
        </div>
      </div>
    </div>
  );
}

function EvidenceSection({ title, items, all, me, canLink, empty, screening }: {
  title: string; items: Evidence[]; all: Evidence[]; me: Me | null; canLink: boolean; empty: string;
  screening?: Record<string, ScreeningResult>;
}) {
  return (
    <Card>
      <CardHeader><CardTitle>{title} <span className="font-normal text-slate-500">({items.length})</span></CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {items.length === 0 ? <Empty title="None">{empty}</Empty>
          : items.map((e) => <EvidenceRow key={e.id} e={e} all={all} me={me} canLink={canLink} screening={screening?.[e.id]} />)}
      </CardContent>
    </Card>
  );
}

function EvidenceRow({ e, all, me, canLink, screening }: {
  e: Evidence; all: Evidence[]; me: Me | null; canLink: boolean; screening?: ScreeningResult;
}) {
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
    onSuccess: () => { setRefPick(""); void qc.invalidateQueries({ queryKey: ["case", e.case_id] }); },
  });
  const t = useT();
  const v = e.last_verification;
  const linked = (e.kind === "questioned" ? e.reference_ids : e.questioned_ids)
    .map((r) => all.find((x) => x.id === r)?.original_filename ?? r);
  return (
    <div className="rounded-md border border-slate-200 p-3" data-testid={`evidence-${e.original_filename}`}>
      <div className="flex flex-wrap items-start gap-3">
        <div className="min-w-0">
          <div className="font-medium text-slate-900">{e.original_filename}</div>
          <div className="text-xs text-slate-500">{e.detected_mime} · {formatBytes(e.size_bytes)} · ingested {formatTime(e.ingested_at)}</div>
        </div>
        {v && (v.ok
          ? <Badge tone="ok" title={`Last verified ${formatTime(v.verified_at)}`}><ShieldCheck className="mr-1 h-3 w-3" />Hash verified</Badge>
          : <Badge tone="bad"><ShieldAlert className="mr-1 h-3 w-3" />HASH MISMATCH</Badge>)}
        <ScreeningBadge s={screening} />
        <div className="ml-auto flex flex-wrap gap-2">
          {e.kind === "questioned" && hasRole(me, "investigator", "examiner", "supervisor") && (
            <Button asChild size="sm"><Link to={`/evidence/${e.id}`}><Microscope className="h-3.5 w-3.5" /> {t("Open workbench")}</Link></Button>
          )}
          {hasRole(me, "examiner", "supervisor") && (
            <Button size="sm" variant="outline" onClick={() => verify.mutate()} disabled={verify.isPending}>
              {verify.isPending ? "Verifying…" : "Re-verify hash"}
            </Button>
          )}
          <Button size="sm" variant="ghost" onClick={() => setShowCustody((s) => !s)}><History className="h-3.5 w-3.5" /> Custody</Button>
        </div>
      </div>
      <div className="mt-2">
        <Facts items={[
          ["SHA-256", <Hash key="s" value={e.sha256} full />],
          ["MD5", <Hash key="m" value={e.md5} full />],
          ["Source", [e.source_platform, e.source_url, e.source_device && `device: ${e.source_device}`].filter(Boolean).join(" · ")],
          ["Collected", [e.collected_by, e.collected_at && formatTime(e.collected_at), e.complainant && `complainant: ${e.complainant}`].filter(Boolean).join(" · ")],
          [e.kind === "questioned" ? "References" : "Reference for", linked.join(", ") || "none"],
        ]} />
      </div>
      {e.kind === "questioned" && canLink && refs.length > 0 && (
        <div className="mt-2 flex gap-2">
          <Select value={refPick} onChange={(ev) => setRefPick(ev.target.value)} className="max-w-xs">
            <option value="">Attach a reference item…</option>
            {refs.map((r) => <option key={r.id} value={r.id}>{r.original_filename}</option>)}
          </Select>
          <Button size="sm" variant="outline" disabled={!refPick || link.isPending} onClick={() => link.mutate()}>Attach</Button>
        </div>
      )}
      <ErrorBox error={verify.error ?? link.error} />
      {showCustody && (
        <div className="mt-3 max-h-72 overflow-auto rounded border bg-slate-50">
          {custody.isLoading ? <Loading /> : (
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-slate-100 text-left text-slate-500"><tr><th className="p-1.5">#</th><th>Time</th><th>Who</th><th>Action</th><th>Entry hash</th></tr></thead>
              <tbody>
                {custody.data?.map((x) => (
                  <tr key={x.seq} className="border-t align-top">
                    <td className="p-1.5">{x.seq}</td><td className="whitespace-nowrap pr-2">{formatTime(x.ts)}</td><td className="pr-2">{x.actor}</td>
                    <td className="pr-2">{x.action}</td><td><Hash value={x.entry_hash} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

interface QueueItem {
  file: File;
  state: "waiting" | "uploading" | "done" | "error";
  progress: number;
  message: string;
}

function UploadPanel({ caseId, questioned, onClose }: { caseId: string; questioned: Evidence[]; onClose: () => void }) {
  const qc = useQueryClient();
  const t = useT();
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [meta, setMeta] = useState<Omit<EvidenceMetadata, "filename">>({
    kind: "questioned", source_platform: "", source_url: "", source_device: "", complainant: "",
    collected_by: "", collected_at: "", upload_method: "web-upload", reference_for: [],
  });
  const set = (k: keyof typeof meta) => (e: { target: { value: string } }) => setMeta({ ...meta, [k]: e.target.value });

  const add = (files: FileList | File[]) => {
    const list = Array.from(files).filter((f) => f.size > 0);
    setQueue((q) => [...q.filter((x) => x.state !== "done"), ...list.map((file) => ({ file, state: "waiting" as const, progress: 0, message: "" }))]);
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDrag(false);
    if (e.dataTransfer.files.length) add(e.dataTransfer.files);
  };
  const patch = (i: number, p: Partial<QueueItem>) => setQueue((q) => q.map((x, j) => (j === i ? { ...x, ...p } : x)));

  async function submit() {
    setBusy(true);
    const clean = Object.fromEntries(Object.entries(meta).map(([k, v]) => [k, v === "" ? null : v]));
    if (clean.collected_at) clean.collected_at = new Date(clean.collected_at as string).toISOString();
    for (let i = 0; i < queue.length; i++) {
      const item = queue[i];
      if (item.state === "done") continue;
      patch(i, { state: "uploading", progress: 0, message: "" });
      try {
        const [local, res] = await Promise.all([
          sha256OfFile(item.file),
          uploadEvidence(caseId, item.file, { ...(clean as unknown as EvidenceMetadata), filename: item.file.name, kind: meta.kind },
            (p) => patch(i, { progress: p })),
        ]);
        const match = local === null ? "browser hash skipped (large file)" : local === res.sha256 ? "matches the hash computed in your browser" : "DOES NOT MATCH the browser hash";
        patch(i, { state: "done", progress: 1, message: `SHA-256 ${res.sha256} — ${match}. ${res.triage_job_ids.length} automatic check(s) started.` });
      } catch (e) {
        patch(i, { state: "error", message: e instanceof Error ? e.message : String(e) });
      }
    }
    setBusy(false);
    void qc.invalidateQueries({ queryKey: ["case", caseId] });
  }

  const pending = queue.filter((x) => x.state !== "done").length;
  return (
    <Card>
      <CardHeader className="flex items-center">
        <CardTitle>Add evidence</CardTitle>
        <Button size="sm" variant="ghost" className="ml-auto" onClick={onClose}>Close</Button>
      </CardHeader>
      <CardContent className="space-y-3">
        <div>
          <Label>{t("1. Kind of item")}</Label>
          <Select value={meta.kind} onChange={(e) => setMeta({ ...meta, kind: e.target.value as "questioned" | "reference" })} data-testid="kind-select">
            <option value="questioned">Questioned item (to be examined)</option>
            <option value="reference">Reference item (e.g. complainant's original photo)</option>
          </Select>
        </div>
        {meta.kind === "reference" && questioned.length > 0 && (
          <div><Label>Reference for (hold Ctrl to select several)</Label>
            <Select multiple value={meta.reference_for} className="h-20" data-testid="reference-for"
                    onChange={(e) => setMeta({ ...meta, reference_for: Array.from(e.target.selectedOptions).map((o) => o.value) })}>
              {questioned.map((q) => <option key={q.id} value={q.id}>{q.original_filename}</option>)}
            </Select></div>
        )}
        <div>
          <Label>{t("2. Files (one or many — photos, videos, audio)")}</Label>
          <label
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={onDrop}
            className={`flex cursor-pointer flex-col items-center gap-1 rounded-md border-2 border-dashed p-5 text-center text-sm ${drag ? "border-slate-700 bg-slate-100" : "border-slate-300 hover:border-slate-500"}`}
          >
            <FileUp className="h-6 w-6 text-slate-500" />
            <span>{t("Drag files or a folder's contents here, or click to choose")}</span>
            <span className="text-xs text-slate-500">JPEG, PNG, HEIC, WEBP · MP4, MOV, MKV, WEBM · WAV, MP3, M4A, OGG · up to 4 GB each</span>
            <input type="file" multiple className="hidden" data-testid="file-input"
                   onChange={(e) => { if (e.target.files) add(e.target.files); e.target.value = ""; }} />
          </label>
        </div>
        {queue.length > 0 && (
          <ul className="space-y-2" data-testid="upload-queue">
            {queue.map((q, i) => (
              <li key={`${q.file.name}-${i}`} className="rounded border p-2 text-sm">
                <div className="flex items-center gap-2">
                  <span className="min-w-0 flex-1 truncate font-medium">{q.file.name}</span>
                  <span className="text-xs text-slate-500">{formatBytes(q.file.size)}</span>
                  <Badge tone={q.state === "done" ? "ok" : q.state === "error" ? "bad" : q.state === "uploading" ? "info" : "neutral"}>{q.state}</Badge>
                  {q.state === "waiting" && !busy && (
                    <button className="text-xs text-slate-500 hover:underline" onClick={() => setQueue((x) => x.filter((_, j) => j !== i))}>remove</button>
                  )}
                </div>
                {q.state === "uploading" && (
                  <div className="mt-1 h-1.5 w-full rounded bg-slate-200"><div className="h-1.5 rounded bg-slate-800 transition-all" style={{ width: `${Math.round(q.progress * 100)}%` }} /></div>
                )}
                {q.message && <div className={`mt-1 break-all text-xs ${q.state === "error" ? "text-red-800" : "text-emerald-900"}`}
                                   data-testid={q.state === "done" ? "upload-result" : undefined}>{q.message}</div>}
              </li>
            ))}
          </ul>
        )}
        <details className="rounded border border-slate-200 p-2 text-sm" open>
          <summary className="cursor-pointer font-medium text-slate-700">3. Source and collection (recommended; applies to every file in this batch)</summary>
          <div className="mt-2 grid grid-cols-2 gap-2">
            <div><Label>Platform</Label><Input value={meta.source_platform ?? ""} onChange={set("source_platform")} placeholder="WhatsApp, Instagram…" /></div>
            <div><Label>Source device</Label><Input value={meta.source_device ?? ""} onChange={set("source_device")} /></div>
            <div className="col-span-2"><Label>Source URL</Label><Input value={meta.source_url ?? ""} onChange={set("source_url")} placeholder="https://…" /></div>
            <div><Label>Complainant</Label><Input value={meta.complainant ?? ""} onChange={set("complainant")} /></div>
            <div><Label>Collected by</Label><Input value={meta.collected_by ?? ""} onChange={set("collected_by")} /></div>
            <div className="col-span-2"><Label>Collected at</Label><Input type="datetime-local" value={meta.collected_at ?? ""} onChange={set("collected_at")} /></div>
          </div>
        </details>
        <Button className="w-full" onClick={() => void submit()} disabled={!pending || busy} data-testid="upload-button">
          {busy ? "Uploading…" : `${t("Hash & ingest")}${pending > 1 ? ` (${pending})` : ""}`}
        </Button>
        <p className="text-xs text-slate-500">Each original is hashed (SHA-256 + MD5) while streaming, stored write-once and never modified, and its automatic checks start as soon as it is stored.</p>
      </CardContent>
    </Card>
  );
}

function Members({ c }: { c: CaseDetail }) {
  const me = useMe();
  const qc = useQueryClient();
  const t = useT();
  const isSup = hasRole(me, "supervisor");
  const dir = useQuery({ queryKey: ["directory"], enabled: isSup, queryFn: () => api.get<Me["user"][]>("/admin/directory") });
  const [pick, setPick] = useState({ user_id: "", permission: "analyse" });
  const add = useMutation({
    mutationFn: () => api.post(`/cases/${c.id}/members`, pick),
    onSuccess: () => { setPick({ user_id: "", permission: "analyse" }); void qc.invalidateQueries({ queryKey: ["case", c.id] }); },
  });
  return (
    <Card>
      <CardHeader><CardTitle>{t("Case members")}</CardTitle></CardHeader>
      <CardContent className="space-y-2 text-sm">
        {c.members.map((m) => (
          <div key={m.user_id} className="flex items-center justify-between gap-2">
            <span>{m.display_name} ({m.username})</span><Badge>{m.permission}</Badge>
          </div>
        ))}
        {isSup && (
          <div className="space-y-2 border-t pt-3">
            <Label>Add or change a member</Label>
            <Select value={pick.user_id} onChange={(e) => setPick({ ...pick, user_id: e.target.value })} data-testid="member-user">
              <option value="">Choose a person…</option>
              {dir.data?.filter((u) => !u.roles.every((r) => r === "admin")).map((u) => <option key={u.id} value={u.id}>{u.display_name} ({u.roles.join(", ")})</option>)}
            </Select>
            <div className="flex gap-2">
              <Select value={pick.permission} onChange={(e) => setPick({ ...pick, permission: e.target.value })} data-testid="member-permission">
                <option value="view">View</option><option value="analyse">Analyse</option><option value="approve">Approve</option>
              </Select>
              <Button size="sm" disabled={!pick.user_id || add.isPending} onClick={() => add.mutate()}>Add</Button>
            </div>
            <p className="text-xs text-slate-500">People appear here after their first sign-in. Administrators cannot be added to cases.</p>
          </div>
        )}
        <ErrorBox error={add.error} />
      </CardContent>
    </Card>
  );
}
