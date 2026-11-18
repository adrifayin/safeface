/** Page-level building blocks used by every screen, so they all look and behave alike. */
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Check, ChevronRight, Copy, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";

export interface Crumb {
  label: string;
  to?: string;
}

export function PageHeader({ crumbs = [], title, subtitle, actions }: {
  crumbs?: Crumb[]; title: ReactNode; subtitle?: ReactNode; actions?: ReactNode;
}) {
  return (
    <div className="mb-4 border-b border-slate-200 pb-3">
      {crumbs.length > 0 && (
        <nav aria-label="Breadcrumb" className="mb-1 flex items-center gap-1 text-xs text-slate-500">
          {crumbs.map((c, i) => (
            <span key={i} className="flex items-center gap-1">
              {i > 0 && <ChevronRight className="h-3 w-3" />}
              {c.to ? <Link to={c.to} className="hover:text-slate-900 hover:underline">{c.label}</Link> : <span>{c.label}</span>}
            </span>
          ))}
        </nav>
      )}
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-0">
          <h1 className="truncate text-xl font-semibold text-slate-900">{title}</h1>
          {subtitle && <div className="mt-0.5 text-sm text-slate-600">{subtitle}</div>}
        </div>
        {actions && <div className="ml-auto flex flex-wrap gap-2">{actions}</div>}
      </div>
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-slate-500" role="status">
      <Loader2 className="h-4 w-4 animate-spin" /> {label}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="rounded-md border border-dashed border-slate-300 p-6 text-center">
      <p className="text-sm font-medium text-slate-700">{title}</p>
      {children && <div className="mt-1 text-sm text-slate-500">{children}</div>}
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn"; children: ReactNode }) {
  return (
    <div className={cn("rounded-md border p-3 text-sm",
      tone === "info" ? "border-sky-200 bg-sky-50 text-sky-900" : "border-amber-200 bg-amber-50 text-amber-950")}>
      {children}
    </div>
  );
}

/** Key/value grid for case and evidence facts. */
export function Facts({ items }: { items: [string, ReactNode][] }) {
  return (
    <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
      {items.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-slate-500">{k}</dt>
          <dd className="min-w-0 text-slate-900">{v || "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

/** A hash shown shortened, with the full value on hover and a copy button. */
export function Hash({ value, full = false }: { value: string | null | undefined; full?: boolean }) {
  const [copied, setCopied] = useState(false);
  if (!value) return <span className="text-slate-400">—</span>;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable (non-secure context): the value is still selectable */
    }
  };
  return (
    <span className="inline-flex max-w-full items-center gap-1 align-middle">
      <code title={value} className="break-all font-mono text-xs text-slate-800">
        {full ? value : `${value.slice(0, 12)}…${value.slice(-8)}`}
      </code>
      <button type="button" onClick={() => void copy()} title="Copy full value"
              className="rounded p-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700">
        {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
      </button>
    </span>
  );
}
