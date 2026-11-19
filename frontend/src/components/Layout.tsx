import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { Link, Navigate, NavLink, Outlet, useLocation } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { LogOut, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { getUser, login, logout, watchIdle } from "@/lib/auth";
import type { Me } from "@/lib/types";
import { Button } from "./ui";
import { Loading } from "./page";
import { useLang, useT } from "@/lib/i18n";

const MeContext = createContext<Me | null>(null);
export const useMe = () => useContext(MeContext);
export const hasRole = (me: Me | null, ...roles: string[]) => !!me && roles.some((r) => me.roles.includes(r));
/** Roles that work on cases. Administrators never do (SRS NFR-S3). */
export const CASE_ROLES = ["investigator", "examiner", "supervisor", "auditor"];

const ROLE_LABEL: Record<string, string> = {
  investigator: "Investigator", examiner: "Examiner", supervisor: "Supervisor", admin: "Administrator", auditor: "Auditor",
};

/** Ensures the user is logged in (Keycloak redirect) and starts the idle timer. */
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
  if (!ready) return <Loading label="Redirecting to sign-in…" />;
  return <MeLoader>{children}</MeLoader>;
}

function MeLoader({ children }: { children: ReactNode }) {
  const me = useQuery({ queryKey: ["me"], queryFn: () => api.get<Me>("/me") });
  if (me.isLoading) return <Loading />;
  if (me.error) {
    return <div className="p-8 text-red-700">Your account has no SafeFace role. Contact the system administrator.</div>;
  }
  return <MeContext.Provider value={me.data ?? null}>{children}</MeContext.Provider>;
}

/** "/" — each role starts where its work is. */
export function Home({ cases }: { cases: ReactNode }) {
  const me = useMe();
  if (!hasRole(me, ...CASE_ROLES)) return <Navigate to="/admin" replace />;
  return <>{cases}</>;
}

export function Layout() {
  const me = useMe();
  const t = useT();
  const { lang, setLang } = useLang();
  const isAdminOnly = !hasRole(me, ...CASE_ROLES);
  const link = ({ isActive }: { isActive: boolean }) =>
    `rounded px-3 py-1.5 text-sm ${isActive ? "bg-white/15 text-white" : "text-slate-300 hover:bg-white/10 hover:text-white"}`;
  return (
    <div className="flex min-h-screen flex-col">
      <header className="bg-slate-900 text-white">
        <div className="mx-auto flex max-w-[1600px] items-center gap-6 px-4 py-2">
          <Link to="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <ShieldCheck className="h-5 w-5 text-sky-300" /> SafeFace
            <span className="hidden font-normal text-slate-400 sm:inline">Forensic Workbench</span>
          </Link>
          <nav className="flex gap-1" aria-label="Main">
            {!isAdminOnly && <NavLink to="/" end className={link}>{t("Cases")}</NavLink>}
            {hasRole(me, "supervisor") && <NavLink to="/approvals" className={link}>Approvals</NavLink>}
            {hasRole(me, "supervisor", "auditor") && <NavLink to="/audit" className={link}>Audit log</NavLink>}
            <NavLink to="/admin" className={link}>{hasRole(me, "admin") ? "Administration" : "Models"}</NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <div className="text-right leading-tight" data-testid="whoami">
              <div>{me?.user.display_name}</div>
              <div className="text-xs text-slate-400">{me?.roles.map((r) => ROLE_LABEL[r] ?? r).join(", ")} · {me?.user.username}</div>
            </div>
            <button type="button" className="rounded border border-white/30 px-2 py-1 text-xs hover:bg-white/10" data-testid="lang-toggle"
                    onClick={() => setLang(lang === "en" ? "ml" : "en")} title="English / മലയാളം">{lang === "en" ? "മലയാളം" : "English"}</button>
            <Button size="sm" variant="secondary" onClick={() => void logout()}><LogOut className="h-3.5 w-3.5" /> {t("Sign out")}</Button>
          </div>
        </div>
      </header>
      <div className="border-b border-amber-200 bg-amber-50 px-4 py-1 text-center text-xs text-amber-900">
        Restricted police system. Automated scores are indicators, not determinations. All actions are logged.
      </div>
      <main className="mx-auto w-full max-w-[1600px] flex-1 p-4"><Outlet /></main>
      <footer className="border-t bg-white px-4 py-2 text-center text-xs text-slate-500">
        SafeFace Forensic Workbench · session ends after 15 minutes of inactivity
      </footer>
    </div>
  );
}
