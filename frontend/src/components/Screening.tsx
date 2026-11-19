/**
 * Preliminary automated screening (agreed in the Phase 2 plan): tells the officer
 * whether any automated check raised a doubt. Always shown with its caveat.
 * It is not a verdict and never uses the words fake/real/authentic.
 */
import { AlertOctagon, HelpCircle, ShieldQuestion } from "lucide-react";
import type { ScreeningResult } from "@/lib/types";
import { Badge } from "./ui";
import { useLang, useT } from "@/lib/i18n";

const STYLE = {
  doubt_raised: { box: "border-red-300 bg-red-50 text-red-950", icon: AlertOctagon, tone: "bad" as const, short: "Doubt raised" },
  no_doubt_raised: { box: "border-slate-300 bg-slate-50 text-slate-900", icon: ShieldQuestion, tone: "neutral" as const, short: "No doubt raised" },
  incomplete: { box: "border-amber-300 bg-amber-50 text-amber-950", icon: HelpCircle, tone: "warn" as const, short: "Screening incomplete" },
};

export function ScreeningBanner({ s, onJump }: { s: ScreeningResult; onJump?: (moduleId: string) => void }) {
  const st = STYLE[s.status];
  const Icon = st.icon;
  const t = useT();
  const { lang } = useLang();
  return (
    <div className={`rounded-md border-2 p-4 ${st.box}`} data-testid="screening-banner" role="status">
      <div className="flex items-start gap-3">
        <Icon className="mt-0.5 h-6 w-6 shrink-0" />
        <div className="min-w-0 flex-1 space-y-2">
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide opacity-80">{t("Preliminary automated screening")}</div>
            <div className="text-lg font-semibold" data-testid="screening-headline">{t(s.status, s.headline)}</div>
            {lang === "ml" && <div className="text-sm opacity-80">{s.headline}</div>}
          </div>
          {s.flags.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-5 text-sm">
              {s.flags.map((f) => (
                <li key={f.module_id}>
                  {onJump ? <button className="text-left underline-offset-2 hover:underline" onClick={() => onJump(f.module_id)}>{f.reason}</button> : f.reason}
                </li>
              ))}
            </ul>
          )}
          {s.detectors_without_result.length > 0 && (
            <p className="text-sm">Detectors without a result: {s.detectors_without_result.join(", ")}.</p>
          )}
          {s.pending.length > 0 && <p className="text-sm">Still running: {s.pending.length} check(s); this result will update.</p>}
          {lang === "ml" && <p className="border-t border-current/20 pt-2 text-sm leading-relaxed">{t("caveat")}</p>}
          <p className="border-t border-current/20 pt-2 text-xs leading-relaxed opacity-90" data-testid="screening-caveat">{s.caveat}</p>
        </div>
      </div>
    </div>
  );
}

export function ScreeningBadge({ s }: { s: ScreeningResult | undefined }) {
  if (!s) return null;
  const found = s.questions?.filter((q) => q.answer === "signs_found").map((q) => q.short) ?? [];
  const p = s.overall_likelihood !== null && s.overall_likelihood !== undefined ? ` · ${Math.round(s.overall_likelihood * 100)}%` : "";
  const text = (found.length ? `⚠ Signs: ${found.join(", ")}` : s.status === "no_doubt_raised" ? "✓ No signs found" : "… Checks running / incomplete") + p;
  const tone = found.length ? "bad" : s.status === "no_doubt_raised" ? "ok" : "warn";
  return <Badge tone={tone} title={`${s.headline}. Automatic result — can be wrong; an examiner must confirm.`}>{text}</Badge>;
}
