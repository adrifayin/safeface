/**
 * Screen 4: evidence workbench (FR-5.1 – 5.4, NFR-U1/U2).
 *
 * Findings are grouped by family in a fixed order (Integrity → Provenance →
 * Comparison → Classical → AI detectors). Each finding stands alone with its
 * scores, ranges, plain-language meanings and limitations. Nothing on this
 * screen combines findings into a verdict.
 */
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Play, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import {
  CONCLUSION_SCALE, type Conclusion, type Evidence, type Finding, type FindingsResponse, type Job,
  type ModuleInfo, type Note,
} from "@/lib/types";
import { formatScore, formatTime } from "@/lib/utils";
import { hasRole, useMe } from "@/components/Layout";
import { Reveal } from "@/components/Reveal";
import { ArtefactImage, EvidenceViewer, type Overlay } from "@/components/Viewer";
import { PlotlyArtefact } from "@/components/PlotlyChart";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, ErrorBox, Label, Mono, Select, Textarea } from "@/components/ui";

const FAMILY_ORDER = ["INTEGRITY", "PROVENANCE", "COMPARISON", "CLASSICAL", "AI_DETECTOR", "AV", "AUDIO"];

export function Workbench() {
  const { evidenceId = "" } = useParams();
  const me = useMe();
  const qc = useQueryClient();
  const evidence = useQuery({ queryKey: ["evidence", evidenceId], queryFn: () => api.get<Evidence>(`/evidence/${evidenceId}`) });
  const modules = useQuery({ queryKey: ["modules"], queryFn: () => api.get<ModuleInfo[]>("/modules") });
  const findings = useQuery({
    queryKey: ["findings", evidenceId],
    queryFn: () => api.get<FindingsResponse>(`/evidence/${evidenceId}/findings`),
    refetchInterval: (q) => (q.state.data?.jobs.some((j) => j.status === "queued" || j.status === "running") ? 3000 : false),
  });
  const notes = useQuery({ queryKey: ["notes", evidenceId], queryFn: () => api.get<Note[]>(`/evidence/${evidenceId}/notes`) });
  const run = useMutation({
    mutationFn: (moduleIds: string[]) => api.post<Job[]>(`/evidence/${evidenceId}/analyses`, { module_ids: moduleIds }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["findings", evidenceId] }),
  });

  const allFindings = useMemo(() => findings.data?.groups.flatMap((g) => g.findings) ?? [], [findings.data]);
  const latestByModule = useMemo(() => {
    const m = new Map<string, Finding>();
    allFindings.forEach((f) => m.set(f.module_id, f));
    return m;
  }, [allFindings]);
  const latestJob = useMemo(() => {
    const m = new Map<string, Job>();
    findings.data?.jobs.forEach((j) => m.set(j.module_id, j));
    return m;
  }, [findings.data]);
  const overlays: Overlay[] = [...latestByModule.values()].flatMap((f) =>
    f.artefacts.filter((a) => a.kind === "heatmap").map((a) => ({ artefact: a, moduleName: f.module_name })));

  if (evidence.isLoading || modules.isLoading) return <div>Loading…</div>;
  const ev = evidence.data;
  if (!ev) return <ErrorBox error={evidence.error ?? "not found"} />;
  const isExaminer = hasRole(me, "examiner");
  const canRunTier1 = hasRole(me, "investigator", "examiner");
  const families = FAMILY_ORDER.map((fam) => ({
    family: fam,
    label: modules.data?.find((m) => m.family === fam)?.family_label ?? fam,
    modules: (modules.data ?? []).filter((m) => m.family === fam && m.media_types.includes(ev.media_type)),
  })).filter((g) => g.modules.length);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-baseline gap-3">
        <Link to={`/cases/${ev.case_id}`} className="text-sm text-sky-800 underline">← Case</Link>
        <h1 className="text-xl font-semibold">{ev.original_filename}</h1>
        <span className="text-xs">SHA-256 <Mono>{ev.sha256}</Mono></span>
        {ev.last_verification && <Badge tone={ev.last_verification.ok ? "ok" : "bad"}>{ev.last_verification.ok ? "hash verified" : "HASH MISMATCH"}</Badge>}
      </div>
      <div className="flex items-start gap-2 rounded-md border border-sky-200 bg-sky-50 p-3 text-sm text-sky-900" data-testid="no-verdict-notice">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
        <span>{findings.data?.notice ?? "Each finding is an independent indicator. SafeFace never gives a real/fake verdict."}</span>
      </div>
      <div className="grid gap-4 2xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)] xl:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        <div className="space-y-4">
          <Card>
            <CardHeader><CardTitle>Image</CardTitle></CardHeader>
            <CardContent><Reveal label="image"><EvidenceViewer evidenceId={ev.id} overlays={overlays} /></Reveal></CardContent>
          </Card>
          <ConclusionPanel evidenceId={ev.id} canWrite={isExaminer && ev.kind === "questioned"} />
          <GeneralNotes evidenceId={ev.id} notes={notes.data?.filter((n) => !n.finding_id) ?? []} canWrite={isExaminer} />
        </div>
        <div className="space-y-4" data-testid="module-panel">
          {families.map((g) => (
            <section key={g.family}>
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-slate-600">{g.label}</h2>
              <div className="space-y-3">
                {g.modules.map((m) => (
                  <ModuleCard key={m.id} module={m} finding={latestByModule.get(m.id)} job={latestJob.get(m.id)}
                              notes={notes.data?.filter((n) => n.finding_id === latestByModule.get(m.id)?.id) ?? []}
                              hasReferences={ev.reference_ids.length > 0}
                              canRun={m.tier === 2 ? isExaminer : canRunTier1} canNote={isExaminer}
                              onRun={() => run.mutate([m.id])} running={run.isPending} />
                ))}
              </div>
            </section>
          ))}
          <ErrorBox error={run.error} />
        </div>
      </div>
    </div>
  );
}

function statusBadge(job: Job | undefined, module: ModuleInfo) {
  if (!module.available && (!job || job.status === "unavailable")) return <Badge tone="neutral">unavailable</Badge>;
  if (!job) return <Badge>not run</Badge>;
  const tone = { queued: "info", running: "info", succeeded: "ok", failed: "bad", unavailable: "neutral" }[job.status] as
    "info" | "ok" | "bad" | "neutral";
  return <Badge tone={tone}>{job.status}</Badge>;
}

function ModuleCard(props: {
  module: ModuleInfo; finding?: Finding; job?: Job; notes: Note[]; hasReferences: boolean;
  canRun: boolean; canNote: boolean; onRun: () => void; running: boolean;
}) {
  const { module: m, finding: f, job } = props;
  const qc = useQueryClient();
  const [showProv, setShowProv] = useState(false);
  const rerun = useMutation({
    mutationFn: () => api.post(`/findings/${f!.id}/rerun`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["findings", f!.evidence_id] }),
  });
  const needsRef = m.requires_reference && !props.hasReferences;
  return (
    <Card data-testid={`module-${m.id}`}>
      <CardHeader className="flex flex-wrap items-center gap-2">
        <CardTitle>{m.name}</CardTitle>
        <Badge>{m.id} v{m.version}</Badge>
        <Badge tone={m.tier === 2 ? "warn" : "neutral"}>Tier {m.tier}</Badge>
        {m.triage_indicator && <Badge tone="warn">triage indicator</Badge>}
        {statusBadge(job, m)}
        <div className="ml-auto flex gap-2">
          {props.canRun && m.available && (
            <Button size="sm" variant={m.tier === 2 ? "default" : "outline"} disabled={props.running || needsRef}
                    title={needsRef ? "Attach a reference image first" : undefined} onClick={props.onRun}
                    data-testid={`run-${m.id}`}>
              <Play className="h-3 w-3" /> {m.tier === 2 ? "Run Tier 2" : f ? "Run again" : "Run"}
            </Button>
          )}
          {f && props.canRun && (
            <Button size="sm" variant="ghost" onClick={() => rerun.mutate()} title="Re-run with the recorded version and parameters">
              <RotateCcw className="h-3 w-3" /> Reproduce
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {!m.available && <p className="text-slate-600">Unavailable: {m.unavailable_reason}</p>}
        {job?.status === "failed" && <p className="text-red-700">Failed: {job.error}</p>}
        {job?.status === "unavailable" && job.error && <p className="text-slate-600">{job.error}</p>}
        {f && (
          <>
            <p>{f.summary}</p>
            <table className="w-full text-xs">
              <thead className="text-left text-slate-500"><tr><th className="w-1/5">Score</th><th className="w-1/6">Value</th><th className="w-1/6">Range</th><th>What it means</th></tr></thead>
              <tbody>
                {f.scores.map((s) => (
                  <tr key={s.name} className="border-t align-top">
                    <td className="py-1 font-medium">{s.name}</td>
                    <td className="font-mono">{formatScore(s.value)}{s.unit ? ` ${s.unit}` : ""}</td>
                    <td>{s.range ? `${s.range[0]} – ${s.range[1]}` : "—"}</td>
                    <td>{s.meaning}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {f.artefacts.filter((a) => a.kind === "image").map((a) => (
              <Reveal key={a.key} label={a.name}><ArtefactImage artefact={a} /></Reveal>
            ))}
            {f.artefacts.filter((a) => a.kind === "plot").map((a) => <PlotlyArtefact key={a.key} artefact={a} />)}
            {f.artefacts.some((a) => a.kind === "heatmap") && (
              <p className="text-xs text-slate-500">Heatmaps are available as overlays on the image viewer.</p>
            )}
            <MetadataDetails f={f} />
            <button className="text-xs text-sky-800 underline" onClick={() => setShowProv((s) => !s)}>
              {showProv ? "Hide" : "Show"} provenance (versions, weights, parameters, environment)
            </button>
            {showProv && <pre className="max-h-64 overflow-auto rounded bg-slate-50 p-2 text-[11px]">{JSON.stringify(f.provenance, null, 2)}</pre>}
          </>
        )}
        <div className="rounded border-l-4 border-amber-500 bg-amber-50 p-2 text-xs text-amber-950">
          <strong>Limitations.</strong> {m.limitations}
        </div>
        {m.validation.length > 0 && (
          <p className="text-xs text-slate-500">Validation: {m.validation.map((v) => String(v.status ?? JSON.stringify(v))).join("; ")}</p>
        )}
        {f && <FindingNotes finding={f} notes={props.notes} canWrite={props.canNote} />}
        <ErrorBox error={rerun.error} />
      </CardContent>
    </Card>
  );
}

function MetadataDetails({ f }: { f: Finding }) {
  const anomalies = (f.details.anomalies as { check: string; tag: string; value: string; explanation: string }[] | undefined) ?? [];
  if (!anomalies.length) return null;
  return (
    <ul className="list-disc pl-5 text-xs">
      {anomalies.map((a, i) => <li key={i}><strong>{a.check}</strong>{a.tag && ` (${a.tag}${a.value ? `: ${a.value}` : ""})`} — {a.explanation}</li>)}
    </ul>
  );
}

function FindingNotes({ finding, notes, canWrite }: { finding: Finding; notes: Note[]; canWrite: boolean }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const add = useMutation({
    mutationFn: () => api.post(`/evidence/${finding.evidence_id}/notes`, { text, finding_id: finding.id }),
    onSuccess: () => {
      setText("");
      void qc.invalidateQueries({ queryKey: ["notes", finding.evidence_id] });
    },
  });
  return (
    <div className="space-y-1 border-t pt-2">
      {notes.map((n) => <p key={n.id} className="text-xs"><strong>{n.author_name}</strong> ({formatTime(n.created_at)}): {n.text}</p>)}
      {canWrite && (
        <div className="flex gap-2">
          <Textarea className="min-h-9 text-xs" value={text} onChange={(e) => setText(e.target.value)} placeholder="Examiner note on this finding…" />
          <Button size="sm" variant="outline" disabled={!text.trim() || add.isPending} onClick={() => add.mutate()}>Add note</Button>
        </div>
      )}
    </div>
  );
}

function GeneralNotes({ evidenceId, notes, canWrite }: { evidenceId: string; notes: Note[]; canWrite: boolean }) {
  const qc = useQueryClient();
  const [text, setText] = useState("");
  const add = useMutation({
    mutationFn: () => api.post(`/evidence/${evidenceId}/notes`, { text }),
    onSuccess: () => {
      setText("");
      void qc.invalidateQueries({ queryKey: ["notes", evidenceId] });
    },
  });
  return (
    <Card>
      <CardHeader><CardTitle>Examiner notes</CardTitle></CardHeader>
      <CardContent className="space-y-2 text-sm">
        {notes.map((n) => <p key={n.id}><strong>{n.author_name}</strong> ({formatTime(n.created_at)}): {n.text}</p>)}
        {notes.length === 0 && <p className="text-slate-500">No general notes.</p>}
        {canWrite && <>
          <Textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Observations, method, context…" />
          <Button size="sm" variant="outline" disabled={!text.trim()} onClick={() => add.mutate()}>Add note</Button>
        </>}
      </CardContent>
    </Card>
  );
}

/** Screen 5a: conclusion on the fixed scale (only the examiner concludes). */
function ConclusionPanel({ evidenceId, canWrite }: { evidenceId: string; canWrite: boolean }) {
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["conclusions", evidenceId], queryFn: () => api.get<Conclusion[]>(`/evidence/${evidenceId}/conclusions`) });
  const [scale, setScale] = useState("");
  const [rationale, setRationale] = useState("");
  const save = useMutation({
    mutationFn: () => api.post(`/evidence/${evidenceId}/conclusion`, { scale_value: scale, rationale }),
    onSuccess: () => {
      setRationale("");
      void qc.invalidateQueries({ queryKey: ["conclusions", evidenceId] });
    },
  });
  const latest = list.data?.at(-1);
  return (
    <Card>
      <CardHeader><CardTitle>Examiner conclusion</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        {latest ? (
          <div className="rounded border p-2" data-testid="latest-conclusion">
            <div className="flex items-center gap-2"><strong>{latest.scale_label}</strong>
              {latest.approved_at ? <Badge tone="ok">approved by {latest.approved_by_name}</Badge> : <Badge tone="warn">awaiting supervisor approval</Badge>}</div>
            <p className="mt-1">{latest.rationale}</p>
            <p className="text-xs text-slate-500">{latest.author_name}, {formatTime(latest.created_at)}</p>
          </div>
        ) : <p className="text-slate-500">No conclusion recorded.</p>}
        {canWrite && (
          <div className="space-y-2 border-t pt-2">
            <Label htmlFor="scale">Conclusion (fixed scale)</Label>
            <Select id="scale" value={scale} onChange={(e) => setScale(e.target.value)} data-testid="conclusion-scale">
              <option value="">Select…</option>
              {CONCLUSION_SCALE.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </Select>
            <Label htmlFor="rationale">Rationale (which findings, and why; at least 20 characters)</Label>
            <Textarea id="rationale" value={rationale} onChange={(e) => setRationale(e.target.value)} data-testid="conclusion-rationale" />
            <ErrorBox error={save.error} />
            <Button disabled={!scale || rationale.trim().length < 20 || save.isPending} onClick={() => save.mutate()} data-testid="conclusion-submit">
              Record conclusion
            </Button>
            <p className="text-xs text-slate-500">A new conclusion supersedes the previous one. Only a supervisor other than you can approve it.</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
