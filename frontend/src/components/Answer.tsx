/**
 * The plain answer, at the top of every item: four simple questions, each with a
 * likelihood percentage from the main detector and a plain answer ("Signs found",
 * "No signs found", ...). If the examiner's conclusion has been approved, that is
 * shown as the final answer. Automated answers are preliminary and say so.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CircleDashed, CircleHelp, Gavel } from "lucide-react";
import { api } from "@/lib/api";
import type { Conclusion, ScreeningResult } from "@/lib/types";
import { useLang, useT } from "@/lib/i18n";

type Q = ScreeningResult["questions"][number];

const ANSWER = {
  signs_found: { label: "Signs found", icon: AlertTriangle, cls: "bg-red-100 text-red-900 border-red-300" },
  no_signs: { label: "No signs found", icon: CheckCircle2, cls: "bg-emerald-100 text-emerald-900 border-emerald-300" },
  partly_checked: { label: "Partly checked", icon: CircleHelp, cls: "bg-amber-100 text-amber-950 border-amber-300" },
  not_checked: { label: "Not checked yet", icon: CircleDashed, cls: "bg-slate-100 text-slate-700 border-slate-300" },
} as const;

const BAND = {
  high: { text: "High", bar: "bg-red-600", txt: "text-red-700" },
  medium: { text: "Medium", bar: "bg-amber-500", txt: "text-amber-700" },
  low: { text: "Low", bar: "bg-emerald-600", txt: "text-emerald-700" },
} as const;

const TOP = {
  doubt_raised: "border-red-400 bg-red-50 text-red-950",
  no_doubt_raised: "border-emerald-400 bg-emerald-50 text-emerald-950",
  incomplete: "border-amber-400 bg-amber-50 text-amber-950",
};

const pct = (v: number) => `${Math.round(v * 100)}%`;

function Meter({ value, band, big }: { value: number; band: keyof typeof BAND; big?: boolean }) {
  const b = BAND[band];
  return (
    <div className={big ? "w-full" : "w-44"}>
      <div className={`flex items-baseline justify-between font-bold ${b.txt}`}>
        <span className={big ? "text-4xl" : "text-2xl"}>{pct(value)}</span>
        <span className="text-xs uppercase tracking-wide">{b.text}</span>
      </div>
      <div className={`relative mt-1 overflow-hidden rounded-full bg-slate-200 ${big ? "h-3" : "h-2"}`}>
        <div className={`h-full ${b.bar}`} style={{ width: `${Math.max(2, value * 100)}%` }} />
        <div className="absolute inset-y-0 left-1/2 w-px bg-slate-500" title="50% screening threshold" />
      </div>
    </div>
  );
}

function QuestionRow({ q }: { q: Q }) {
  const a = ANSWER[q.answer];
  const Icon = a.icon;
  const others = q.detector_scores.slice(1);
  return (
    <div className="grid gap-3 p-3 sm:grid-cols-[1fr_auto]" data-testid={`question-${q.key}`}>
      <div className="min-w-0">
        <div className="font-semibold text-slate-900">{q.question}</div>
        <span className={`mt-1 inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-xs font-bold ${a.cls}`} data-testid={`answer-${q.key}`}>
          <Icon className="h-3.5 w-3.5" /> {a.label}
        </span>
        <div className="mt-1 text-xs text-slate-600">
          {q.answer === "signs_found" && q.reasons.map((r, i) => <div key={i}>• {r}</div>)}
          {q.answer === "no_signs" && `Checked by: ${q.checks.join(", ")}.`}
          {q.answer === "partly_checked" && `Only supporting checks ran (${q.checks.join(", ")}); the main detector has no result yet.`}
          {q.answer === "not_checked" && "No check for this has run on this item yet."}
          {others.length > 0 && <div className="mt-1 text-slate-500">Other detectors: {others.map((o) => `${o.detector} ${pct(o.likelihood)}`).join(" · ")}</div>}
        </div>
      </div>
      <div className="flex flex-col items-start sm:items-end" data-testid={`likelihood-${q.key}`}>
        {q.likelihood !== null && q.likelihood_band ? <>
          <Meter value={q.likelihood} band={q.likelihood_band} />
          <span className="mt-0.5 text-[11px] text-slate-500">likelihood · {q.likelihood_source}</span>
        </> : <span className="text-sm text-slate-500">no % for this question</span>}
      </div>
    </div>
  );
}

export function AnswerCard({ s, evidenceId, onJump }: { s: ScreeningResult; evidenceId: string; onJump?: (moduleId: string) => void }) {
  const [more, setMore] = useState(false);
  const t = useT();
  const { lang } = useLang();
  const conclusions = useQuery({ queryKey: ["conclusions", evidenceId], queryFn: () => api.get<Conclusion[]>(`/evidence/${evidenceId}/conclusions`) });
  const final = conclusions.data?.at(-1);
  const approved = final?.approved_at ? final : null;
  return (
    <div className="space-y-3" data-testid="answer-card">
      {approved && (
        <div className="flex items-start gap-3 rounded-md border-2 border-slate-800 bg-white p-4" data-testid="final-answer">
          <Gavel className="mt-0.5 h-6 w-6 shrink-0" />
          <div>
            <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">Final answer — examiner's conclusion, approved by a supervisor</div>
            <div className="text-xl font-bold">{approved.scale_label}</div>
            <p className="text-sm text-slate-700">{approved.rationale}</p>
            <p className="text-xs text-slate-500">By {approved.author_name}; approved by {approved.approved_by_name}.</p>
          </div>
        </div>
      )}
      <div className={`rounded-md border-2 p-4 ${TOP[s.status]}`} data-testid="screening-banner" role="status">
        <div className="text-xs font-semibold uppercase tracking-wide opacity-80">
          {approved ? "Automatic check results (supporting the examiner)" : t("Preliminary automated screening", "Automatic check result")}
        </div>
        <div className="mt-1 grid gap-4 sm:grid-cols-[1fr_16rem] sm:items-center">
          <div>
            <div className="text-2xl font-bold" data-testid="screening-headline">{t(s.status, s.headline)}</div>
            {lang === "ml" && <div className="text-sm opacity-80">{s.headline}</div>}
            <div className="text-base" data-testid="answer-line">{s.answer_line}</div>
          </div>
          {s.overall_likelihood !== null && s.overall_band && (
            <div className="rounded-md border border-current/20 bg-white/80 p-3" data-testid="overall-likelihood">
              <div className="text-xs font-semibold text-slate-600">Likelihood of AI manipulation</div>
              <Meter value={s.overall_likelihood} band={s.overall_band} big />
              <div className="mt-1 text-[11px] text-slate-500">highest of the questions below ({s.overall_question})</div>
            </div>
          )}
        </div>

        <div className="mt-3 divide-y divide-current/10 rounded-md border border-current/20 bg-white/70">
          {s.questions.map((q) => <QuestionRow key={q.key} q={q} />)}
        </div>

        <div className="mt-3 text-sm font-medium">
          ⚠ These percentages are detector estimates and can be wrong in both directions. Use them to decide whether to send the item to a trained examiner — they are not proof.
        </div>
        <p className="text-xs opacity-80">Low (under 40%) · Medium (40–69%) · High (70% and above). The line in each bar marks the 50% screening threshold.</p>
        <button className="mt-1 text-xs underline" onClick={() => setMore((m) => !m)}>{more ? "Hide" : "Why can it be wrong?"}</button>
        {more && <>
          {lang === "ml" && <p className="mt-1 text-sm">{t("caveat")}</p>}
          <p className="mt-1 text-xs leading-relaxed" data-testid="screening-caveat">{s.caveat}</p>
        </>}
        {!more && <span className="hidden" data-testid="screening-caveat">{s.caveat}</span>}
        {onJump && s.flags.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2 text-xs">
            See details: {s.flags.map((f) => <button key={f.module_id} className="underline" onClick={() => onJump(f.module_id)}>{f.check}</button>)}
          </div>
        )}
      </div>
    </div>
  );
}
