import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { getUser, login, logout, watchIdle } from "@/lib/auth";
import type { Me } from "@/lib/types";
import { Button } from "./ui";

const MeContext = createContext<Me | null>(null);
export const useMe = () => useContext(MeContext);
export const hasRole = (me: Me | null, ...roles: string[]) => !!me && roles.some((r) => me.roles.includes(r));

/** Ensures the user is logged in (Keycloak redirect) and audits the session start once. */
export function AuthGate({ children }: { children: ReactNode }) {
  const [ready, setReady] = useState(false);
  const location = useLocation();
  useEffect(() => {
    getUser().then((u) => {
      if (!u) void login();
      else setReady(true);
    });
  }, [location.pathname]);
  useEffect(() => watchIdle(() => void logout()), []);
  if (!ready) return <div className="p-8 text-slate-600">Redirecting to sign-in…</div>;
  return <MeLoader>{children}</MeLoader>;
}

function MeLoader({ children }: { children: ReactNode }) {
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/me") });
  if (me.isLoading) return <div className="p-8">Loading…</div>;
  if (me.error) return <div className="p-8 text-red-700">Your account has no SafeFace role. Contact the administrator.</div>;
  return <MeContext.Provider value={me.data ?? null}>{children}</MeContext.Provider>;
}

export function Layout() {
  const me = useMe();
  const link = ({ isActive }: { isActive: boolean }) =>
    `rounded px-3 py-1.5 text-sm ${isActive ? "bg-slate-800 text-white" : "text-slate-200 hover:bg-slate-700"}`;
  return (
    <div className="min-h-screen">
      <header className="bg-slate-900 text-white">
        <div className="mx-auto flex max-w-[1600px] items-center gap-4 px-4 py-2">
          <Link to="/" className="flex items-center gap-2 font-semibold">
            <ShieldCheck className="h-5 w-5" /> SafeFace Forensic Workbench
          </Link>
          <nav className="flex gap-1">
            {hasRole(me, "investigator", "examiner", "supervisor", "auditor") && <NavLink to="/" end className={link}>Cases</NavLink>}
            {hasRole(me, "supervisor") && <NavLink to="/approvals" className={link}>Approvals</NavLink>}
            {hasRole(me, "supervisor", "auditor") && <NavLink to="/audit" className={link}>Audit</NavLink>}
            {hasRole(me, "admin", "supervisor", "auditor", "examiner") && <NavLink to="/admin" className={link}>Models &amp; admin</NavLink>}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <span data-testid="whoami">{me?.user.display_name} · {me?.roles.join(", ")}</span>
            <Button size="sm" variant="secondary" onClick={() => void logout()}>Sign out</Button>
          </div>
        </div>
      </header>
      <div className="border-b border-amber-200 bg-amber-50 px-4 py-1 text-center text-xs text-amber-900">
        Restricted police system. Automated scores are indicators, not determinations. All actions are logged.
      </div>
      <main className="mx-auto max-w-[1600px] p-4"><Outlet /></main>
    </div>
  );
}
