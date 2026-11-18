/**
 * Evidence media in the browser is held only in memory (an object URL, never cached:
 * the API sends Cache-Control: no-store) and is wiped 7 minutes after it was loaded,
 * or as soon as the component unmounts. Each timed wipe is recorded in the audit chain.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

export const BROWSER_RETENTION_MS = 7 * 60 * 1000;

export interface TimedMedia {
  url: string | null;
  expired: boolean;
  error: string | null;
  reload: () => void;
}

export function useTimedMedia(path: string, evidenceId?: string): TimedMedia {
  const [url, setUrl] = useState<string | null>(null);
  const [expired, setExpired] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nonce, setNonce] = useState(0);
  const current = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setExpired(false);
    setError(null);
    api.blobUrl(path).then(({ url: u }) => {
      if (cancelled) { URL.revokeObjectURL(u); return; }
      current.current = u;
      setUrl(u);
    }).catch((e) => setError(String(e?.message ?? e)));
    const timer = window.setTimeout(() => {
      if (current.current) URL.revokeObjectURL(current.current);
      current.current = null;
      setUrl(null);
      setExpired(true);
      if (evidenceId) void api.post(`/evidence/${evidenceId}/browser-wipe`, { what: path.split("/").slice(-2).join("/") }).catch(() => {});
    }, BROWSER_RETENTION_MS);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      if (current.current) URL.revokeObjectURL(current.current);
      current.current = null;
    };
  }, [path, evidenceId, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  return { url, expired, error, reload };
}
