/** Screen 7: users/roles mirror, model registry with checksums, two-person changes, audit verify. */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { AuditVerify, ModuleInfo, RegistryChange, RegistryEntry } from "@/lib/types";
import { formatTime } from "@/lib/utils";
import { hasRole, useMe } from "@/components/Layout";
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, ErrorBox, Input, Mono } from "@/components/ui";

interface UserRow { id: string; username: string; display_name: string; roles: string[]; active: boolean; last_seen_at: string }

export function AdminPage() {
  const me = useMe();
  return (
    <div className="space-y-4">
      {hasRole(me, "admin") && <Users />}
      <Registry />
      <Modules />
      {hasRole(me, "supervisor", "auditor") && <AuditVerifyCard />}
    </div>
  );
}

function Users() {
  const users = useQuery({ queryKey: ["users"], queryFn: () => api.get<UserRow[]>("/admin/users") });
  return (
    <Card>
      <CardHeader><CardTitle>Users and roles (read-only mirror of Keycloak)</CardTitle></CardHeader>
      <CardContent>
        <p className="mb-2 text-xs text-slate-500">Accounts, roles, 2FA and lockout are managed in Keycloak. Administrators cannot access case media.</p>
        <table className="w-full text-sm">
          <thead className="text-left text-slate-500"><tr><th>User</th><th>Name</th><th>Roles</th><th>Last seen</th></tr></thead>
          <tbody>{users.data?.map((u) => (
            <tr key={u.id} className="border-t"><td className="py-1">{u.username}</td><td>{u.display_name}</td><td>{u.roles.join(", ")}</td><td>{formatTime(u.last_seen_at)}</td></tr>
          ))}</tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function Registry() {
  const me = useMe();
  const qc = useQueryClient();
  const entries = useQuery({ queryKey: ["registry"], queryFn: () => api.get<RegistryEntry[]>("/admin/models") });
  const changes = useQuery({ queryKey: ["registry-changes"], queryFn: () => api.get<RegistryChange[]>("/admin/model-changes") });
  const [reason, setReason] = useState("");
  const request = useMutation({
    mutationFn: (e: RegistryEntry) => api.post(`/admin/models/${e.name}/change-requests`, { enabled: !e.enabled, reason }),
    onSuccess: () => { setReason(""); void qc.invalidateQueries({ queryKey: ["registry-changes"] }); },
  });
  const decide = useMutation({
    mutationFn: ({ id, d }: { id: string; d: "approve" | "reject" }) => api.post(`/admin/model-changes/${id}/${d}`),
    onSuccess: () => { void qc.invalidateQueries({ queryKey: ["registry-changes"] }); void qc.invalidateQueries({ queryKey: ["registry"] }); },
  });
  return (
    <Card>
      <CardHeader><CardTitle>Model registry</CardTitle></CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-xs text-slate-500">Weights are loaded only from the local models directory and only if their SHA-256 matches. Enabling/disabling needs an admin request and a supervisor approval.</p>
        <table className="w-full text-xs">
          <thead className="text-left text-slate-500"><tr><th>Name</th><th>Module</th><th>SHA-256</th><th>Licence</th><th>Status</th><th>Validation</th><th /></tr></thead>
          <tbody>{entries.data?.map((e) => (
            <tr key={e.name} className="border-t align-top">
              <td className="py-1 font-medium">{e.name}<div className="text-slate-500">{e.version}</div></td>
              <td>{e.module_id}</td>
              <td className="max-w-[220px]"><Mono>{e.weights_sha256 ?? "not recorded — refused"}</Mono></td>
              <td>{e.licence}</td>
              <td>{e.enabled ? <Badge tone={e.installed ? "ok" : "neutral"}>{e.installed ? "ready" : "not installed"}</Badge> : <Badge tone="bad">disabled</Badge>}
                <div className="text-slate-500">{e.status}</div></td>
              <td>{String(e.validation_summary.status ?? "—")}</td>
              <td>{hasRole(me, "admin") && <Button size="sm" variant="outline" disabled={reason.length < 10} onClick={() => request.mutate(e)}>
                Request {e.enabled ? "disable" : "enable"}</Button>}</td>
            </tr>
          ))}</tbody>
        </table>
        {hasRole(me, "admin") && <Input placeholder="Reason for the change (required, ≥ 10 characters)" value={reason} onChange={(e) => setReason(e.target.value)} />}
        <h4 className="pt-2 font-semibold">Change requests</h4>
        {changes.data?.map((c) => (
          <div key={c.id} className="flex items-center gap-2 text-xs">
            <Badge tone={c.status === "pending" ? "warn" : c.status === "approved" ? "ok" : "neutral"}>{c.status}</Badge>
            <span>{c.enabled_requested ? "Enable" : "Disable"} <strong>{c.name}</strong> — {c.reason} ({formatTime(c.requested_at)})</span>
            {c.status === "pending" && hasRole(me, "supervisor") && <>
              <Button size="sm" onClick={() => decide.mutate({ id: c.id, d: "approve" })}>Approve</Button>
              <Button size="sm" variant="outline" onClick={() => decide.mutate({ id: c.id, d: "reject" })}>Reject</Button></>}
          </div>
        ))}
        <ErrorBox error={request.error ?? decide.error} />
      </CardContent>
    </Card>
  );
}

function Modules() {
  const modules = useQuery({ queryKey: ["modules"], queryFn: () => api.get<ModuleInfo[]>("/modules") });
  return (
    <Card>
      <CardHeader><CardTitle>Analysis modules</CardTitle></CardHeader>
      <CardContent>
        <table className="w-full text-xs">
          <thead className="text-left text-slate-500"><tr><th>Module</th><th>Family</th><th>Tier</th><th>Status</th></tr></thead>
          <tbody>{modules.data?.map((m) => (
            <tr key={m.id} className="border-t"><td className="py-1"><strong>{m.name}</strong> <Mono>{m.id} v{m.version}</Mono></td><td>{m.family_label}</td><td>{m.tier}</td>
              <td>{m.available ? <Badge tone="ok">available</Badge> : <span><Badge>unavailable</Badge> {m.unavailable_reason}</span>}</td></tr>
          ))}</tbody>
        </table>
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
      <CardContent className="space-y-2 text-sm">
        <Button onClick={() => verify.mutate()} disabled={verify.isPending} data-testid="verify-audit">Verify audit chain</Button>
        {r && (r.ok
          ? <p className="text-emerald-800" data-testid="audit-ok">Intact: {r.entries_checked} entries verified. Head #{r.head_seq} <Mono>{r.head_hash}</Mono></p>
          : <p className="text-red-700">BROKEN at entry #{r.first_bad_seq}: {r.problem}</p>)}
        <ErrorBox error={verify.error} />
      </CardContent>
    </Card>
  );
}
