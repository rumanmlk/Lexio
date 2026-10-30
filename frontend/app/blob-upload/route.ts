import { handleUpload, type HandleUploadBody } from "@vercel/blob/client";

import { auth } from "@/auth";
import { apiTokenConfig, mintApiToken } from "@/lib/apitoken";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const TOKEN_LIFETIME_MS = 10 * 60 * 1000;

/**
 * Hands the browser a one-use token to upload a PDF straight to Vercel Blob (a Vercel function
 * refuses request bodies over 4.5 MB). Only the JavaScript SDK can mint these tokens, which is why
 * this lives here and not in the FastAPI backend. Everything that decides whether the user may
 * upload (sign-in, document and storage caps, the uploads switch, tickets per day) is asked of the
 * backend, so there is one set of rules. Afterwards the browser calls POST /api/documents/register
 * on the backend, which reads the file, indexes it, and deletes it if it is rejected.
 */
export async function POST(request: Request) {
  const body = (await request.json()) as HandleUploadBody;
  try {
    const result = await handleUpload({
      body,
      request,
      // Runs only for the browser's token request; Blob's own completion callback (which has no
      // session) is not used.
      onBeforeGenerateToken: async (pathname) => {
        const session = await auth();
        if (!session?.uid) throw new Error("Sign in to upload your own PDFs.");
        const ticket = await takeTicket(session.uid);
        if (!pathname.startsWith(ticket.prefix) || pathname.includes("..")) {
          throw new Error("That upload path is not yours.");
        }
        return {
          allowedContentTypes: ["application/pdf"],
          maximumSizeInBytes: ticket.max_bytes,
          addRandomSuffix: true,
          validUntil: Date.now() + TOKEN_LIFETIME_MS,
        };
      },
    });
    return Response.json(result);
  } catch (error) {
    return Response.json({ error: (error as Error).message }, { status: 400 });
  }
}

async function takeTicket(uid: string): Promise<{ prefix: string; max_bytes: number }> {
  const config = apiTokenConfig();
  if (!config) throw new Error("API_TOKEN_SECRET is not set on the web app.");
  const { token } = await mintApiToken(uid, config);
  let res: Response;
  try {
    res = await fetch(`${API_URL}/api/upload-ticket`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
    });
  } catch {
    throw new Error("Can't reach the server. Is the backend running?");
  }
  if (!res.ok) {
    let detail = `Upload refused (${res.status})`;
    try {
      const d = (await res.json()).detail;
      if (typeof d === "string") detail = d;
    } catch {
      // keep the generic message
    }
    throw new Error(detail);
  }
  return res.json();
}
