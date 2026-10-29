import { SignJWT } from "jose";

export const TOKEN_LIFETIME_SECONDS = 300;
export const MIN_SECRET_LENGTH = 32;

export type TokenConfig = { secret: string; issuer: string; audience: string };

/** The 5-minute HS256 token the FastAPI backend verifies (see backend/app/auth.py). */
export async function mintApiToken(
  uid: string,
  { secret, issuer, audience }: TokenConfig,
  nowSeconds = Math.floor(Date.now() / 1000),
): Promise<{ token: string; expires_at: number }> {
  const expires = nowSeconds + TOKEN_LIFETIME_SECONDS;
  const token = await new SignJWT({})
    .setProtectedHeader({ alg: "HS256" })
    .setSubject(uid)
    .setIssuer(issuer)
    .setAudience(audience)
    .setIssuedAt(nowSeconds)
    .setExpirationTime(expires)
    .sign(new TextEncoder().encode(secret));
  return { token, expires_at: expires };
}
