import { forgetToken, getToken } from "./token.ts";

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Doc = {
  id: string;
  filename: string;
  pages: number;
  chunks: number;
  created_at: string;
  /** One of the shared sample documents: everyone can read it, nobody can delete it. */
  sample: boolean;
};

export type Source = {
  n: number;
  document_id: string;
  filename: string;
  page: number;
  snippet: string;
  score: number;
};

export type Counter = { used: number; limit: number | null };

export type Limits = {
  demo_mode: boolean;
  signed_in: boolean;
  documents: Counter;
  storage_mb: Counter;
  uploads_enabled: boolean;
  max_upload_mb: number;
  max_upload_chunks: number | null;
  /** The server keeps PDFs in object storage: upload there first, then register (see below). */
  direct_upload: boolean;
  /** Where this user's direct uploads go; null when not signed in or not direct. */
  upload_prefix: string | null;
  questions: Counter;
  site_questions: Counter;
  uploads: Counter;
  resets_in_seconds: number;
};

export type Turn = { role: "user" | "assistant"; content: string };

/** A failed request, with the server's plain-language message (it includes any wait time). */
export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

/** FastAPI sends `detail` as a string for our own errors and as a list for validation errors. */
export function detailMessage(detail: unknown): string | null {
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return null;
  const parts = detail.flatMap((d: { loc?: unknown[]; msg?: unknown }) => {
    if (typeof d?.msg !== "string") return [];
    const field = (d.loc ?? []).filter((p) => p !== "body").join(".");
    return [field ? `${field}: ${d.msg}` : d.msg];
  });
  return parts.length ? parts.join("; ") : null;
}

async function fail(res: Response): Promise<never> {
  let message = `Request failed (${res.status})`;
  try {
    message = detailMessage((await res.json()).detail) ?? message;
  } catch {
    // not JSON; keep the generic message
  }
  throw new ApiError(message, res.status);
}

async function send(path: string, init: RequestInit | undefined, token: string | null) {
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  try {
    return await fetch(`${API_URL}${path}`, { ...init, headers });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e; // the caller cancelled; not a network failure
    throw new ApiError("Can't reach the server. Is the backend running?", 0);
  }
}

async function request(path: string, init?: RequestInit): Promise<Response> {
  const token = await getToken();
  let res = await send(path, init, token);
  if (res.status === 401 && token) {
    // The token may have just expired (or the backend restarted with a new secret): mint once more.
    forgetToken();
    res = await send(path, init, await getToken());
  }
  if (!res.ok) await fail(res);
  return res;
}

export async function listDocuments(): Promise<Doc[]> {
  return (await request("/api/documents")).json();
}

export async function getLimits(): Promise<Limits> {
  return (await request("/api/limits")).json();
}

export type Uploaded = {
  id: string;
  filename: string;
  pages: number;
  chunks: number;
  duplicate: boolean;
  /** The PDF matched a shared sample, which is used as it is. */
  sample: boolean;
};

/** A storage path under the user's prefix that the server will accept: letters, digits and . _ - */
export function blobPathname(prefix: string, filename: string): string {
  const stem = filename.replace(/\.pdf$/i, "").replace(/[^A-Za-z0-9._-]+/g, "_").replace(/\.{2,}/g, ".").replace(/^[._]+|\.+$/g, "");
  return `${prefix}${stem.slice(0, 100) || "document"}.pdf`;
}

export async function uploadDocument(
  file: File,
  limits?: Pick<Limits, "direct_upload" | "upload_prefix" | "max_upload_mb"> | null,
): Promise<Uploaded> {
  if (limits?.direct_upload && limits.upload_prefix) return uploadDirect(file, limits.upload_prefix, limits.max_upload_mb);
  const form = new FormData();
  form.append("file", file);
  return (await request("/api/documents", { method: "POST", body: form })).json();
}

/** PDF to Vercel Blob straight from the browser (the web app's /blob-upload route authorises it),
 * then the backend is told where it is so it can check, index and keep it. */
async function uploadDirect(file: File, prefix: string, maxMb: number): Promise<Uploaded> {
  if (!/\.pdf$/i.test(file.name)) throw new ApiError("Only PDF files are supported", 415);
  if (file.size > maxMb * 1024 * 1024) throw new ApiError(`File exceeds ${maxMb} MB`, 413);
  const { upload } = await import("@vercel/blob/client");
  let stored;
  try {
    stored = await upload(blobPathname(prefix, file.name), file, {
      access: "private",
      handleUploadUrl: "/blob-upload",
    });
  } catch (e) {
    throw new ApiError((e as Error).message || "The upload failed. Try again.", 0);
  }
  const res = await request("/api/documents/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pathname: stored.pathname, filename: file.name }),
  });
  return res.json();
}

export async function deleteDocument(id: string): Promise<void> {
  await request(`/api/documents/${id}`, { method: "DELETE" });
}

/** Erases the signed-in user's documents and files. */
export async function deleteAccount(): Promise<void> {
  await request("/api/me", { method: "DELETE" });
  forgetToken();
}

export async function fetchDocumentFile(id: string): Promise<Blob> {
  return (await request(`/api/documents/${id}/file`)).blob();
}

/** Opens the chat stream. Errors before the first byte (429, 503, ...) throw an ApiError. */
export async function openChat(
  body: { question: string; document_ids: string[] | null; history: Turn[] },
  signal: AbortSignal,
): Promise<ReadableStream<Uint8Array>> {
  const res = await request("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.body) throw new ApiError("The server sent an empty response.", res.status);
  return res.body;
}

export function formatWait(seconds: number): string {
  const minutes = Math.ceil(seconds / 60);
  if (minutes < 60) return `${Math.max(minutes, 1)} min`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours} h ${rest} min` : `${hours} h`;
}
