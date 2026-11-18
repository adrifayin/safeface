/**
 * Screen 4: evidence workbench (FR-5.1 – 5.4, NFR-U1/U2).
 *
 * Findings are grouped by family in a fixed order (Integrity → Provenance →
 * Comparison → Classical → AI detectors). Each finding stands alone with its
 * scores, ranges, plain-language meanings and limitations. Nothing on this
 * screen combines findings into a verdict.
 */
import { useCallback, useMemo, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, ChevronDown, Play, RotateCcw } from "lucide-react";
import { api } from "@/lib/api";
import {
  CONCLUSION_SCALE, type CaseDetail, type Conclusion, type Evidence, type Finding, type FindingsResponse, type Job,
  type ModuleInfo, type Note, type ScreeningResult,
} from "@/lib/types";
import { formatScore, formatTime } from "@/lib/utils";
import { hasRole, useMe } from "@/components/Layout";
import { Reveal } from "@/components/Reveal";
import { ArtefactImage, EvidenceViewer, type Overlay } from "@/components/Viewer";
import { PlotlyArtefact } from "@/components/PlotlyChart";
import { ScreeningBanner } from "@/components/Screening";
import { MediaPlayer } from "@/components/MediaPlayer";
import { GeometryTool } from "@/components/GeometryTool";

import { Empty, Hash, Loading, Notice, PageHeader } from "@/components/page";
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, ErrorBox, Label, Select, Tabs, TabsContent, TabsList,
  TabsTrigger, Textarea,
} from "@/components/ui";

const FAMILY_ORDER = ["INTEGRITY", "PROVENANCE", "COMPARISON", "CLASSICAL", "AI_DETECTOR", "AV", "AUDIO"];
const STATUS_TONE = { queued: "info", running: "info", succeeded: "ok", failed: "bad", unavailable: "neutral" } as const;

export function Workbench() {
  const { evidenceId = "" } = useParams();
  const me = useMe();
  const qc = useQueryClient();
  const evidence = useQuery({ queryKey: ["evidence", evidenceId], queryFn: () => api.get<Evidence>(`/evidence/${evidenceId}`) });
  const caseQ = useQuery({
    queryKey: ["case", evidence.data?.case_id], enabled: !!evidence.data,
    queryFn: () => api.get<CaseDetail>(`/cases/${evidence.data!.case_id}`),
  });
  const modules = useQuery({ queryKey: ["modules"], queryFn: () => api.get<ModuleInfo[]>("/modules") });
  const findings = useQuery({
    queryKey: ["findings", evidenceId],
    queryFn: () => api.get<FindingsResponse>(`/evidence/${evidenceId}/findings`),
    refetchInterval: (q) => (q.state.data?.jobs.some((j) => j.status === "queued" || j.status === "running") ? 3000 : false),
  });
  const screening = useQuery({
    queryKey: ["screening", evidenceId, findings.data?.jobs.map((j) => j.status).join()],
    enabled: !!findings.data,
    queryFn: () => api.get<ScreeningResult>(`/evidence/${evidenceId}/screening`),
  });
  const notes = useQuery({ queryKey: ["notes", evidenceId], queryFn: () => api.get<Note[]>(`/evidence/${evidenceId}/notes`) });
  const run = useMutation({
    mutationFn: (moduleIds: string[]) => api.post<Job[]>(`/evidence/${evidenceId}/analyses`, { module_ids: moduleIds }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["findings", evidenceId] }),
  });

  const player = useRef<HTMLVideoElement>(null);
  const seek = useCallback((t: number) => {
    if (player.current) {
      player.current.currentTime = t;
      player.current.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, []);
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

  if (evidence.isLoading || modules.isLoading) return <Loading />;
  const ev = evidence.data;
  if (!ev) return <ErrorBox error={evidence.error ?? "Evidence not found"} />;
  const isExaminer = hasRole(me, "examiner");
  const canRunTier1 = hasRole(me, "investigator", "examiner");
  const applicable = (modules.data ?? []).filter((m) => m.media_types.includes(ev.media_type));
  // A module is shown in the main list if it can run here or has already produced something.
  const shown = applicable.filter((m) => m.available || latestByModule.has(m.id) || latestJob.has(m.id));
  const hidden = applicable.filter((m) => !shown.includes(m));
  const families = FAMILY_ORDER.map((fam) => ({
    family: fam,
    label: applicable.find((m) => m.family === fam)?.family_label ?? fam,
    modules: shown.filter((m) => m.family === fam),
  })).filter((g) => g.modules.length);
  const caseNo = caseQ.data?.case_no ?? "Case";
  const busy = findings.data?.jobs.filter((j) => j.status === "queued" || j.status === "running").length ?? 0;

  return (
    <div>
      <PageHeader
        crumbs={[{ label: "Cases", to: "/" }, { label: caseNo, to: `/cases/${ev.case_id}` }, { label: ev.original_filename }]}
        title={ev.original_filename}
        subtitle={<span className="flex flex-wrap items-center gap-2">SHA-256 <Hash value={ev.sha256} />
          {ev.last_verification && <Badge tone={ev.last_verification.ok ? "ok" : "bad"}>{ev.last_verification.ok ? "hash verified" : "HASH MISMATCH"}</Badge>}
          {busy > 0 && <Badge tone="info">{busy} analysis job(s) running…</Badge>}
        </span>}
      />
      {screening.data && (
        <div className="mb-3">
          <ScreeningBanner s={screening.data} onJump={(id) => document.getElementById(`module-${id}`)?.scrollIntoView({ behavior: "smooth" })} />
        </div>
      )}
      <div className="mb-4" data-testid="no-verdict-notice">
        <Notice><span className="flex items-start gap-2"><AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          {findings.data?.notice ?? "Each finding is an independent indicator. SafeFace never gives a real/fake verdict."}</span></Notice>
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,5fr)_minmax(0,6fr)]">
        {/* Image stays in view while findings scroll. */}
        <div className="xl:sticky xl:top-4 xl:self-start">
          <Card>
            <CardHeader><CardTitle>{ev.media_type === "image" ? "Image" : ev.media_type === "video" ? "Video" : "Audio"}</CardTitle></CardHeader>
            <CardContent>
              {ev.media_type === "image"
                ? <Reveal label="image"><EvidenceViewer evidenceId={ev.id} overlays={overlays} /></Reveal>
                : <Reveal label={ev.media_type}><MediaPlayer ref={player} evidenceId={ev.id} kind={ev.media_type as "video" | "audio"} /></Reveal>}
              {ev.media_type !== "image" && <p className="mt-2 text-xs text-slate-500">Click a point on any timeline to jump to that moment.</p>}
            </CardContent>
          </Card>
        </div>
        <Tabs defaultValue="findings">
          <TabsList>
            <TabsTrigger value="findings">Findings</TabsTrigger>
            <TabsTrigger value="conclusion" data-testid="tab-conclusion">Notes &amp; conclusion</TabsTrigger>
          </TabsList>
          <TabsContent value="findings" className="space-y-4" data-testid="module-panel">
            <StatusSummary modules={shown} jobs={latestJob} />
            {families.map((g) => (
              <section key={g.family}>
                <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">{g.label}</h2>
                <div className="space-y-3">
                  {g.modules.map((m) => (
                    <ModuleCard key={m.id} module={m} finding={latestByModule.get(m.id)} job={latestJob.get(m.id)}
                                notes={notes.data?.filter((n) => n.finding_id === latestByModule.get(m.id)?.id) ?? []}
                                hasReferences={ev.reference_ids.length > 0}
                                canRun={m.tier === 2 ? isExaminer : canRunTier1} canNote={isExaminer}
                                onRun={() => run.mutate([m.id])} running={run.isPending} onSeek={seek} evidenceId={ev.id} />
                  ))}
                </div>
              </section>
            ))}
            {hidden.length > 0 && <UnavailableList modules={hidden} />}
            <ErrorBox error={run.error} />
          </TabsContent>
          <TabsContent value="conclusion" className="space-y-4">
            <ConclusionPanel evidenceId={ev.id} canWrite={isExaminer && ev.kind === "questioned"} />
            <GeneralNotes evidenceId={ev.id} notes={notes.data?.filter((n) => !n.finding_id) ?? []} canWrite={isExaminer} />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

function StatusSummary({ modules, jobs }: { modules: ModuleInfo[]; jobs: Map<string, Job> }) {
  return (
    <Card>
      <CardContent className="flex flex-wrap gap-x-4 gap-y-2 text-xs">
        {modules.map((m) => {
          const j = jobs.get(m.id);
          return (
            <a key={m.id} href={`#module-${m.id}`} className="flex items-center gap-1.5 hover:underline">
              <span className="text-slate-700">{m.name}</span>
              <Badge tone={j ? STATUS_TONE[j.status] : "neutral"}>{j ? j.status : m.tier === 2 ? "Tier 2 — not run" : "not run"}</Badge>
            </a>
          );
        })}
      </CardContent>
    </Card>
  );
}

function UnavailableList({ modules }: { modules: ModuleInfo[] }) {
  return (
    <details className="rounded-md border border-slate-200 bg-white p-3 text-sm">
      <summary className="flex cursor-pointer items-center gap-2 font-medium text-slate-700">
        <ChevronDown className="h-4 w-4" /> Not available on this system ({modules.length})
      </summary>
      <ul className="mt-2 space-y-2">
        {modules.map((m) => (
          <li key={m.id} className="border-t pt-2">
            <div><strong>{m.name}</strong> <span className="text-xs text-slate-500">{m.id} v{m.version}</span></div>
            <div className="text-xs text-slate-600">{m.unavailable_reason}</div>
          </li>
        ))}
      </ul>
      <p className="mt-2 text-xs text-slate-500">An administrator installs model weights offline (scripts/fetch_models.md).</p>
    </details>
  );
}

function ModuleCard(props: {
  module: ModuleInfo; finding?: Finding; job?: Job; notes: Note[]; hasReferences: boolean;
  canRun: boolean; canNote: boolean; onRun: () => void; running: boolean; onSeek?: (t: number) => void;
  evidenceId: string;
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
    <Card id={`module-${m.id}`} data-testid={`module-${m.id}`} className="scroll-mt-4">
      <CardHeader className="flex flex-wrap items-center gap-2">
        <CardTitle>{m.name}</CardTitle>
        {m.tier === 2 && <Badge tone="warn">Tier 2</Badge>}
        {m.triage_indicator && <Badge tone="warn">triage indicator</Badge>}
        {job ? <Badge tone={STATUS_TONE[job.status]}>{job.status}</Badge> : <Badge>not run</Badge>}
        <div className="ml-auto flex gap-2">
          {props.canRun && m.available && m.id !== "image.geometry" && (
            <Button size="sm" variant={m.tier === 2 && !f ? "default" : "outline"} disabled={props.running || needsRef}
                    title={needsRef ? "Attach a reference item to this evidence first" : undefined} onClick={props.onRun}
                    data-testid={`run-${m.id}`}>
              <Play className="h-3 w-3" /> {m.tier === 2 ? (f ? "Run Tier 2 again" : "Run Tier 2") : f ? "Run again" : "Run"}
            </Button>
          )}
          {f && props.canRun && (
            <Button size="sm" variant="ghost" onClick={() => rerun.mutate()} title="Re-run with the recorded version and parameters and compare">
              <RotateCcw className="h-3 w-3" /> Reproduce
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-xs text-slate-500">{m.description} <span className="font-mono">({m.id} v{m.version})</span></p>
        {m.id === "image.geometry" && props.canRun && m.available && (
          <Reveal label="drawing tool"><GeometryTool evidenceId={f?.evidence_id ?? props.evidenceId} /></Reveal>
        )}
        {needsRef && !f && <p className="text-amber-800">Needs a reference item: attach one on the case page.</p>}
        {!m.available && <p className="text-slate-600">Unavailable: {m.unavailable_reason}</p>}
        {job?.status === "failed" && <p className="text-red-700">Failed: {job.error}</p>}
        {job?.status === "unavailable" && job.error && <p className="text-slate-600">{job.error}</p>}
        {(job?.status === "queued" || job?.status === "running") && <Loading label="Analysis in progress…" />}
        {f && (
          <>
            <p className="font-medium text-slate-900">{f.summary}</p>
            <table className="w-full text-xs">
              <thead className="border-b text-left text-slate-500"><tr><th className="w-1/5 py-1">Score</th><th className="w-1/6">Value</th><th className="w-1/6">Range</th><th>What it means</th></tr></thead>
              <tbody>
                {f.scores.map((s) => (
                  <tr key={s.name} className="border-b align-top last:border-0">
                    <td className="py-1.5 font-medium">{s.name}</td>
                    <td className="font-mono">{formatScore(s.value)}{s.unit ? ` ${s.unit}` : ""}</td>
                    <td>{s.range ? `${s.range[0]} – ${s.range[1]}` : "—"}</td>
                    <td className="text-slate-700">{s.meaning}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {f.artefacts.filter((a) => a.kind === "image").map((a) => (
              <Reveal key={a.key} label={a.name}><ArtefactImage artefact={a} /></Reveal>
            ))}
            {f.artefacts.filter((a) => a.kind === "plot").map((a) => <PlotlyArtefact key={a.key} artefact={a} onPointClick={props.onSeek} />)}
            {f.artefacts.some((a) => a.kind === "heatmap") && (
              <p className="text-xs text-slate-500">Heatmap available: switch it on under “Overlays” below the image.</p>
            )}
            <MetadataDetails f={f} />
          </>
        )}
        <div className="rounded border-l-4 border-amber-500 bg-amber-50 p-2 text-xs text-amber-950">
          <strong>Limitations.</strong> {m.limitations}
        </div>
        {m.validation.length > 0 && (
          <p className="text-xs text-slate-500">Validation: {[...new Set(m.validation.map((v) => String(v.status ?? JSON.stringify(v))))].join("; ")}</p>
        )}
        {f && (
          <>
            <button className="text-xs text-sky-800 hover:underline" onClick={() => setShowProv((s) => !s)}>
              {showProv ? "Hide" : "Show"} provenance (versions, weights, parameters, environment)
            </button>
            {showProv && <pre className="max-h-64 overflow-auto rounded bg-slate-50 p-2 text-[11px]">{JSON.stringify(f.provenance, null, 2)}</pre>}
            <FindingNotes finding={f} notes={props.notes} canWrite={props.canNote} />
          </>
        )}
        <ErrorBox error={rerun.error} />
      </CardContent>
    </Card>
  );
}

function MetadataDetails({ f }: { f: Finding }) {
  const anomalies = (f.details.anomalies as { check: string; tag: string; value: string; explanation: string }[] | undefined) ?? [];
  if (!anomalies.length) return null;
  return (
    <div>
      <p className="mb-1 text-xs font-medium text-slate-700">Observations</p>
      <ul className="list-disc space-y-0.5 pl-5 text-xs">
        {anomalies.map((a, i) => <li key={i}><strong>{a.check.replace(/_/g, " ")}</strong>{a.tag && ` (${a.tag}${a.value ? `: ${a.value}` : ""})`} — {a.explanation}</li>)}
      </ul>
    </div>
  );
}

function FindingNotes({ finding, notes, canWrite }: { finding: Finding; notes: Note[]; canWrite: boolean }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const add = useMutation({
    mutationFn: () => api.post(`/evidence/${finding.evidence_id}/notes`, { text, finding_id: finding.id }),
    onSuccess: () => {
      setText("");
      setOpen(false);
      void qc.invalidateQueries({ queryKey: ["notes", finding.evidence_id] });
    },
  });
  if (!notes.length && !canWrite) return null;
  return (
    <div className="space-y-1 border-t pt-2">
      {notes.map((n) => <p key={n.id} className="text-xs"><strong>{n.author_name}</strong> <span className="text-slate-500">({formatTime(n.created_at)})</span>: {n.text}</p>)}
      {canWrite && !open && <button className="text-xs text-sky-800 hover:underline" onClick={() => setOpen(true)}>+ Add a note on this finding</button>}
      {canWrite && open && (
        <div className="space-y-1">
          <Textarea className="min-h-16 text-xs" autoFocus value={text} onChange={(e) => setText(e.target.value)} placeholder="Examiner note on this finding…" />
          <div className="flex gap-2">
            <Button size="sm" disabled={!text.trim() || add.isPending} onClick={() => add.mutate()}>Save note</Button>
            <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>Cancel</Button>
          </div>
        </div>
      )}
      <ErrorBox error={add.error} />
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
        {notes.length === 0 ? <p className="text-slate-500">No general notes.</p>
          : notes.map((n) => <p key={n.id}><strong>{n.author_name}</strong> <span className="text-slate-500">({formatTime(n.created_at)})</span>: {n.text}</p>)}
        {canWrite && <>
          <Textarea value={text} onChange={(e) => setText(e.target.value)} placeholder="Observations, method, context…" />
          <Button size="sm" variant="outline" disabled={!text.trim() || add.isPending} onClick={() => add.mutate()}>Add note</Button>
        </>}
        <ErrorBox error={add.error} />
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
      setScale("");
      void qc.invalidateQueries({ queryKey: ["conclusions", evidenceId] });
    },
  });
  const latest = list.data?.at(-1);
  const earlier = (list.data ?? []).slice(0, -1).reverse();
  return (
    <Card>
      <CardHeader><CardTitle>Examiner conclusion</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        {latest ? (
          <div className="rounded border p-3" data-testid="latest-conclusion">
            <div className="flex flex-wrap items-center gap-2"><strong>{latest.scale_label}</strong>
              {latest.approved_at ? <Badge tone="ok">approved by {latest.approved_by_name}</Badge> : <Badge tone="warn">awaiting supervisor approval</Badge>}</div>
            <p className="mt-1">{latest.rationale}</p>
            <p className="text-xs text-slate-500">{latest.author_name}, {formatTime(latest.created_at)}</p>
          </div>
        ) : <Empty title="No conclusion recorded yet.">{canWrite ? "Review the findings, then record your conclusion below." : "Only the examiner records the conclusion."}</Empty>}
        {earlier.length > 0 && (
          <details className="text-xs text-slate-600"><summary className="cursor-pointer">Earlier (superseded) conclusions ({earlier.length})</summary>
            {earlier.map((c) => <p key={c.id} className="mt-1">{formatTime(c.created_at)} — {c.scale_label}: {c.rationale}</p>)}
          </details>
        )}
        {canWrite && (
          <div className="space-y-2 border-t pt-3">
            <Label htmlFor="scale">Conclusion (fixed scale)</Label>
            <Select id="scale" value={scale} onChange={(e) => setScale(e.target.value)} data-testid="conclusion-scale">
              <option value="">Select…</option>
              {CONCLUSION_SCALE.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
            </Select>
            <Label htmlFor="rationale">Rationale — which findings support it, and why</Label>
            <Textarea id="rationale" className="min-h-28" value={rationale} onChange={(e) => setRationale(e.target.value)} data-testid="conclusion-rationale" />
            <p className="text-xs text-slate-500">{rationale.trim().length}/20 characters minimum. A new conclusion supersedes the previous one; a supervisor other than you must approve it.</p>
            <ErrorBox error={save.error} />
            <Button disabled={!scale || rationale.trim().length < 20 || save.isPending} onClick={() => save.mutate()} data-testid="conclusion-submit">
              Record conclusion
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
