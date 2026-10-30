import { auth } from "@/auth";
import { MIN_SECRET_LENGTH, apiTokenConfig, mintApiToken } from "@/lib/apitoken";

const NO_STORE = { "Cache-Control": "no-store" };

/**
 * Trades the Auth.js session (an encrypted cookie only this app can read) for a 5-minute token the
 * FastAPI backend can verify with the shared API_TOKEN_SECRET. The browser sends it as
 * `Authorization: Bearer`.
 */
export async function GET() {
  const session = await auth();
  if (!session?.uid) return Response.json({ detail: "Not signed in" }, { status: 401, headers: NO_STORE });

  const config = apiTokenConfig();
  if (!config) {
    return Response.json(
      { detail: `API_TOKEN_SECRET is not set (${MIN_SECRET_LENGTH}+ characters).` },
      { status: 500, headers: NO_STORE },
    );
  }
  const minted = await mintApiToken(session.uid, config);
  return Response.json(minted, { headers: NO_STORE });
}
