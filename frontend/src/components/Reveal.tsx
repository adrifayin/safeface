/**
 * Examiner-wellbeing wrapper (NFR-U1, TDD §5): content is blurred by default and
 * revealed only on an explicit click. Optional greyscale reduces impact further.
 */
import { useState, type ReactNode } from "react";
import { Eye, EyeOff } from "lucide-react";
import { Button, Switch } from "./ui";

export function Reveal({ children, label = "evidence" }: { children: ReactNode; label?: string }) {
  const [revealed, setRevealed] = useState(false);
  const [grey, setGrey] = useState(false);
  const filter = `${revealed ? "" : "blur(28px)"} ${grey ? "grayscale(1)" : ""}`.trim() || "none";
  return (
    <div className="relative">
      <div className="mb-2 flex items-center gap-3 text-sm">
        <Button size="sm" variant={revealed ? "outline" : "default"} onClick={() => setRevealed((r) => !r)}
                data-testid={`reveal-${label}`}>
          {revealed ? <><EyeOff className="h-4 w-4" /> Blur again</> : <><Eye className="h-4 w-4" /> Reveal {label}</>}
        </Button>
        <label className="flex items-center gap-2"><Switch checked={grey} onCheckedChange={setGrey} /> Greyscale</label>
      </div>
      <div style={{ filter }} className="overflow-hidden transition-[filter]" aria-hidden={!revealed}>
        {children}
      </div>
      {!revealed && (
        <div className="pointer-events-none absolute inset-x-0 top-12 text-center text-sm font-medium text-slate-700">
          Blurred by default. Click “Reveal” to view.
        </div>
      )}
    </div>
  );
}
