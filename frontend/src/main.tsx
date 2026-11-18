import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes, useNavigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import "./index.css";
import { AuthGate, Home, Layout } from "@/components/Layout";
import { userManager } from "@/lib/auth";
import { CasesPage } from "@/pages/CasesPage";
import { CasePage } from "@/pages/CasePage";
import { Workbench } from "@/pages/Workbench";
import { ApprovalsPage } from "@/pages/ApprovalsPage";
import { ReportPage } from "@/pages/ReportPage";
import { AdminPage } from "@/pages/AdminPage";
import { AuditPage } from "@/pages/AuditPage";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 5_000 } },
});

/** OIDC redirect target: completes login, records the audited session, returns to the app. */
function Callback() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return; // the authorization code may be redeemed only once
    started.current = true;
    userManager
      .signinRedirectCallback()
      .then(async (user) => {
        await fetch("/api/v1/session", { method: "POST", headers: { Authorization: `Bearer ${user.access_token}` } });
        const back = typeof user.state === "string" && user.state.startsWith("/") ? user.state : "/";
        navigate(back === "/callback" ? "/" : back, { replace: true });
      })
      .catch((e) => setError(String(e)));
  }, [navigate]);
  return <div className="p-8">{error ? `Sign-in failed: ${error}` : "Completing sign-in…"}</div>;
}

function App() {
  return (
    <Routes>
      <Route path="/callback" element={<Callback />} />
      <Route element={<AuthGate><Layout /></AuthGate>}>
        <Route path="/" element={<Home cases={<CasesPage />} />} />
        <Route path="/cases/:caseId" element={<CasePage />} />
        <Route path="/cases/:caseId/report" element={<ReportPage />} />
        <Route path="/evidence/:evidenceId" element={<Workbench />} />
        <Route path="/approvals" element={<ApprovalsPage />} />
        <Route path="/audit" element={<AuditPage />} />
        <Route path="/admin" element={<AdminPage />} />
      </Route>
    </Routes>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
