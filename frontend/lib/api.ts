export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type Doc = {
  id: string;
  filename: string;
  pages: number;
  chunks: number;
  created_at: string;
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
  uploads_enabled: boolean;
  max_upload_mb: number;
  max_upload_chunks: number | null;
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

async function request(path: string, init?: RequestInit): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, init);
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e; // the caller cancelled; not a network failure
    throw new ApiError("Can't reach the server. Is the backend running?", 0);
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

export async function uploadDocument(
  file: File,
): Promise<{ id: string; filename: string; pages: number; chunks: number; duplicate: boolean }> {
  const form = new FormData();
  form.append("file", file);
  return (await request("/api/documents", { method: "POST", body: form })).json();
}

export async function deleteDocument(id: string): Promise<void> {
  await request(`/api/documents/${id}`, { method: "DELETE" });
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
