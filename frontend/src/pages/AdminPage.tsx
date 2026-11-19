/** Screen 7: users/roles mirror, model registry with checksums, two-person changes, audit verify. */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AuditVerify, ModuleInfo, RegistryChange, RegistryEntry } from "@/lib/types";
import { formatTime } from "@/lib/utils";
import { hasRole, useMe } from "@/components/Layout";
import { Empty, Hash, Loading, Notice, PageHeader } from "@/components/page";
import { ValidationPanel } from "@/components/Validation";
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle, ErrorBox, Input, Tabs, TabsContent, TabsList, TabsTrigger,
} from "@/components/ui";

interface UserRow { id: string; username: string; display_name: string; roles: string[]; active: boolean; last_seen_at: string }

export function AdminPage() {
  const me = useMe();
  const isAdmin = hasRole(me, "admin");
  const canVerify = hasRole(me, "supervisor", "auditor");
  const first = isAdmin ? "users" : "registry";
  return (
    <div>
      <PageHeader
        title={isAdmin ? "Administration" : "Models"}
        subtitle={isAdmin ? "Users, analysis models and system status." : "Installed analysis models, their checksums and validation status."}
      />
      {isAdmin && (
        <div className="mb-4">
          <Notice>
            Administrators manage accounts and models only. By policy (SRS NFR-S3) they cannot create or open cases or view
            evidence. Cases are created by investigators, examiners or supervisors. Accounts, roles and two-factor
            authentication are managed in the Keycloak admin console.
          </Notice>
        </div>
      )}
      <Tabs defaultValue={first}>
        <TabsList>
          {isAdmin && <TabsTrigger value="users">Users &amp; roles</TabsTrigger>}
          <TabsTrigger value="registry">Model registry</TabsTrigger>
          <TabsTrigger value="modules">Analysis modules</TabsTrigger>
          <TabsTrigger value="validation">Validation</TabsTrigger>
          {canVerify && <TabsTrigger value="audit">Audit chain</TabsTrigger>}
        </TabsList>
        {isAdmin && <TabsContent value="users"><Users /></TabsContent>}
        <TabsContent value="registry"><Registry /></TabsContent>
        <TabsContent value="modules"><Modules /></TabsContent>
        <TabsContent value="validation"><ValidationPanel /></TabsContent>
        {canVerify && <TabsContent value="audit"><AuditVerifyCard /></TabsContent>}
      </Tabs>
    </div>
  );
}

function Users() {
  const users = useQuery({ queryKey: ["users"], queryFn: () => api.get<UserRow[]>("/admin/users") });
  return (
    <Card>
      <CardHeader><CardTitle>Users and roles</CardTitle></CardHeader>
      <CardContent>
        <p className="mb-3 text-xs text-slate-500">Read-only mirror of Keycloak, updated when each person signs in.
          To add a user or change roles, use <a className="text-sky-800 underline" href="/auth/admin/safeface/console/">the Keycloak admin console</a>.</p>
        {users.isLoading ? <Loading /> : (
          <table className="w-full text-sm">
            <thead className="border-b text-left text-xs uppercase tracking-wide text-slate-500"><tr><th className="py-2">User</th><th>Name</th><th>Roles</th><th>Status</th><th>Last seen</th></tr></thead>
            <tbody>{users.data?.map((u) => (
              <tr key={u.id} className="border-b last:border-0"><td className="py-2 font-mono text-xs">{u.username}</td><td>{u.display_name}</td>
                <td>{u.roles.map((r) => <Badge key={r} className="mr-1">{r}</Badge>)}</td>
                <td>{u.active ? <Badge tone="ok">active</Badge> : <Badge tone="bad">disabled</Badge>}</td>
                <td className="text-slate-600">{formatTime(u.last_seen_at)}</td></tr>
            ))}</tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}

function Registry() {
  const me = useMe();
  const qc = useQueryClient();
  const entries = useQuery({ queryKey: ["registry"], queryFn: () => api.get<RegistryEntry[]>("/admin/models") });
  const changes = useQuery({ queryKey: ["registry-changes"], queryFn: () => api.get<RegistryChange[]>("/admin/model-changes") });
  const [target, setTarget] = useState<RegistryEntry | null>(null);
  const [reason, setReason] = useState("");
  const request = useMutation({
    mutationFn: () => api.post(`/admin/models/${target!.name}/change-requests`, { enabled: !target!.enabled, reason }),
    onSuccess: () => { setReason(""); setTarget(null); void qc.invalidateQueries({ queryKey: ["registry-changes"] }); },
  });
  const decide = useMutation({
    mutationFn: ({ id, d }: { id: string; d: "approve" | "reject" }) => api.post(`/admin/model-changes/${id}/${d}`),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["registry-changes"] }); void qc.invalidateQueries({ queryKey: ["registry"] }); },
  });
  const isAdmin = hasRole(me, "admin");
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader><CardTitle>Model weights</CardTitle></CardHeader>
        <CardContent className="space-y-3 text-sm">
          <p className="text-xs text-slate-500">Weights are loaded only from the local models directory, and only if their SHA-256 matches
            the registry. Nothing is ever downloaded. Enabling or disabling a model needs an administrator's request and a supervisor's approval.</p>
          {entries.isLoading ? <Loading /> : (
            <table className="w-full text-xs">
              <thead className="border-b text-left uppercase tracking-wide text-slate-500"><tr><th className="py-2">Name</th><th>Used by</th><th>SHA-256</th><th>Licence</th><th>Status</th>{isAdmin && <th />}</tr></thead>
              <tbody>{entries.data?.map((e) => (
                <tr key={e.name} className="border-b align-top last:border-0">
                  <td className="py-2 font-medium">{e.name}<div className="font-normal text-slate-500">{e.version}</div></td>
                  <td className="font-mono">{e.module_id}</td>
                  <td>{e.weights_sha256 ? <Hash value={e.weights_sha256} /> : <span className="text-amber-800">not recorded — file refused</span>}</td>
                  <td className="max-w-[220px]">{e.licence}</td>
                  <td className="max-w-[260px]">
                    {!e.enabled ? <Badge tone="bad">disabled</Badge> : e.installed ? <Badge tone="ok">ready</Badge> : <Badge>not installed</Badge>}
                    {!e.installed && e.enabled && <div className="mt-1 text-slate-500">{e.status}</div>}
                  </td>
                  {isAdmin && <td><Button size="sm" variant="outline" onClick={() => setTarget(e)}>{e.enabled ? "Request disable" : "Request enable"}</Button></td>}
                </tr>
              ))}</tbody>
            </table>
          )}
          {target && (
            <div className="space-y-2 rounded border border-slate-300 bg-slate-50 p-3">
              <p className="font-medium">Request to {target.enabled ? "disable" : "enable"} <span className="font-mono">{target.name}</span></p>
              <Input autoFocus placeholder="Reason (at least 10 characters)" value={reason} onChange={(e) => setReason(e.target.value)} />
              <div className="flex gap-2">
                <Button size="sm" disabled={reason.trim().length < 10 || request.isPending} onClick={() => request.mutate()}>Submit for supervisor approval</Button>
                <Button size="sm" variant="ghost" onClick={() => setTarget(null)}>Cancel</Button>
              </div>
            </div>
          )}
          <ErrorBox error={request.error} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Change requests</CardTitle></CardHeader>
        <CardContent className="space-y-2 text-sm">
          {changes.data?.length === 0 && <Empty title="No change requests." />}
          {changes.data?.map((c) => (
            <div key={c.id} className="flex flex-wrap items-center gap-2 border-b pb-2 last:border-0">
              <Badge tone={c.status === "pending" ? "warn" : c.status === "approved" ? "ok" : "neutral"}>{c.status}</Badge>
              <span>{c.enabled_requested ? "Enable" : "Disable"} <strong className="font-mono">{c.name}</strong> — {c.reason}</span>
              <span className="text-xs text-slate-500">{formatTime(c.requested_at)}</span>
              {c.status === "pending" && hasRole(me, "supervisor") && <span className="ml-auto flex gap-2">
                <Button size="sm" onClick={() => decide.mutate({ id: c.id, d: "approve" })}>Approve</Button>
                <Button size="sm" variant="outline" onClick={() => decide.mutate({ id: c.id, d: "reject" })}>Reject</Button></span>}
            </div>
          ))}
          <ErrorBox error={decide.error} />
        </CardContent>
      </Card>
    </div>
  );
}

function Modules() {
  const modules = useQuery({ queryKey: ["modules"], queryFn: () => api.get<ModuleInfo[]>("/modules") });
  return (
    <Card>
      <CardHeader><CardTitle>Analysis modules</CardTitle></CardHeader>
      <CardContent>
        <p className="mb-3 text-xs text-slate-500">Availability is reported by the analysis workers (tools and model files present) and by the registry checks.</p>
        {modules.isLoading ? <Loading /> : (
          <table className="w-full text-xs">
            <thead className="border-b text-left uppercase tracking-wide text-slate-500"><tr><th className="py-2">Module</th><th>Family</th><th>Tier</th><th>Status</th></tr></thead>
            <tbody>{modules.data?.map((m) => (
              <tr key={m.id} className="border-b align-top last:border-0">
                <td className="py-2"><div className="font-medium text-slate-900">{m.name}</div><div className="font-mono text-slate-500">{m.id} v{m.version}</div></td>
                <td>{m.family_label}</td><td>{m.tier}</td>
                <td>{m.available ? <Badge tone="ok">available</Badge> : <><Badge>unavailable</Badge><div className="mt-1 text-slate-500">{m.unavailable_reason}</div></>}</td></tr>
            ))}</tbody>
          </table>
        )}
      </CardContent>
    </Card>
  );
}

function AuditVerifyCard() {
  const verify = useMutation({ mutationFn: () => api.get<AuditVerify>("/audit/verify") });
  const r = verify.data;
  return (
    <Card>
      <CardHeader><CardTitle>Audit chain verification</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-slate-600">Recomputes every entry's hash from the first entry onwards. Any edited, inserted or deleted entry breaks the chain.</p>
        <Button onClick={() => verify.mutate()} disabled={verify.isPending} data-testid="verify-audit">
          {verify.isPending ? "Verifying…" : "Verify audit chain"}
        </Button>
        {r && (r.ok
          ? <div className="rounded bg-emerald-50 p-3 text-emerald-900" data-testid="audit-ok">Intact: {r.entries_checked} entries verified at {formatTime(r.verified_at)}.
              <div className="mt-1 text-xs">Head entry #{r.head_seq} · <Hash value={r.head_hash} full /></div></div>
          : <div className="rounded bg-red-50 p-3 text-red-800">BROKEN at entry #{r.first_bad_seq}: {r.problem}</div>)}
        <ErrorBox error={verify.error} />
      </CardContent>
    </Card>
  );
}
