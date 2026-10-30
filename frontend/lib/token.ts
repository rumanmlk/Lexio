/** The API token for the signed-in user, or null for an anonymous visitor. Cached until shortly
 * before it expires; the server mints it from the Auth.js session (see app/token/route.ts). */
let cached: { token: string; expiresAt: number } | null = null;
let anonymousUntil = 0; // a visitor who is not signed in is not asked again for a minute
let pending: Promise<string | null> | null = null;

const SKEW_MS = 30_000;

export function forgetToken(): void {
  cached = null;
  anonymousUntil = 0;
}

export function tokenFresh(c: { expiresAt: number }, now = Date.now()): boolean {
  return c.expiresAt - SKEW_MS > now;
}

async function mint(): Promise<string | null> {
  try {
    const res = await fetch("/token", { cache: "no-store" });
    if (!res.ok) {
      anonymousUntil = Date.now() + 60_000; // 401: not signed in
      return null;
    }
    const body = (await res.json()) as { token: string; expires_at: number };
    cached = { token: body.token, expiresAt: body.expires_at * 1000 };
    return body.token;
  } catch {
    return null;
  }
}

export async function getToken(): Promise<string | null> {
  if (cached && tokenFresh(cached)) return cached.token;
  if (Date.now() < anonymousUntil) return null;
  pending ??= mint().finally(() => {
    pending = null;
  });
  return pending;
}
