/** Thin, typed client for the SafeFace API (/api/v1). */
import { accessToken } from "./auth";
import type { EvidenceMetadata, UploadResult } from "./types";

export class ApiError extends Error {
  constructor(public status: number, public detail: unknown) {
    super(typeof detail === "string" ? detail : `request failed (${status})`);
  }
}

function headers(extra: Record<string, string> = {}): Record<string, string> {
  const token = accessToken();
  return { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...extra };
}

async function handle<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail: unknown = res.statusText;
    try {
      detail = (await res.json()).detail;
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail);
  }
  const type = res.headers.get("content-type") ?? "";
  return (type.includes("application/json") ? res.json() : res.text()) as Promise<T>;
}

export const api = {
  get: <T>(path: string) => fetch(`/api/v1${path}`, { headers: headers() }).then((r) => handle<T>(r)),
  post: <T>(path: string, body?: unknown) =>
    fetch(`/api/v1${path}`, {
      method: "POST",
      headers: headers({ "Content-Type": "application/json" }),
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then((r) => handle<T>(r)),
  /** Fetch a binary resource (evidence, artefact, PDF) as an object URL. */
  async blobUrl(path: string): Promise<{ url: string; blob: Blob; headers: Headers }> {
    const res = await fetch(`/api/v1${path}`, { headers: headers() });
    if (!res.ok) throw new ApiError(res.status, res.statusText);
    const blob = await res.blob();
    return { url: URL.createObjectURL(blob), blob, headers: res.headers };
  },
};

/** base64url of UTF-8 JSON (metadata header for the streamed upload). */
export function encodeMetadata(meta: EvidenceMetadata): string {
  const bytes = new TextEncoder().encode(JSON.stringify(meta));
  let bin = "";
  bytes.forEach((b) => (bin += String.fromCharCode(b)));
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/** Upload a file as a raw stream with progress callbacks (XHR gives upload progress). */
export function uploadEvidence(
  caseId: string,
  file: File,
  meta: EvidenceMetadata,
  onProgress: (fraction: number) => void,
): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `/api/v1/cases/${caseId}/evidence`);
    Object.entries(headers({ "Content-Type": "application/octet-stream", "X-SafeFace-Metadata": encodeMetadata(meta) }))
      .forEach(([k, v]) => xhr.setRequestHeader(k, v));
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      let body: unknown = xhr.responseText;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* keep text */
      }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body as UploadResult);
      else reject(new ApiError(xhr.status, (body as { detail?: unknown })?.detail ?? body));
    };
    xhr.onerror = () => reject(new ApiError(0, "network error"));
    xhr.send(file);
  });
}

/** SHA-256 of a local file, computed in the browser before upload, to cross-check the server. */
export async function sha256OfFile(file: File): Promise<string | null> {
  if (file.size > 512 * 1024 * 1024 || !crypto?.subtle) return null; // avoid huge memory use
  const digest = await crypto.subtle.digest("SHA-256", await file.arrayBuffer());
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}
