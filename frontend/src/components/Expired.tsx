import { Clock } from "lucide-react";
import { Button } from "./ui";

/** Shown where evidence media was wiped from the browser after 7 minutes. */
export function Expired({ onReload, label = "this item" }: { onReload: () => void; label?: string }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-md border border-dashed border-slate-300 p-6 text-center text-sm text-slate-600"
         data-testid="media-expired">
      <Clock className="h-5 w-5" />
      <span>For privacy, {label} was removed from this browser 7 minutes after it was opened.</span>
      <Button size="sm" variant="outline" onClick={onReload}>Load again</Button>
    </div>
  );
}
