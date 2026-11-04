// The public origin of the site, used for canonical links, the sitemap and social-card URLs.
// SITE_URL wins (set it when a custom domain is attached); Vercel's production URL is the fallback.
function origin(): string {
  const fromVercel = process.env.VERCEL_PROJECT_PRODUCTION_URL ? `https://${process.env.VERCEL_PROJECT_PRODUCTION_URL}` : "http://localhost:3000";
  const set = process.env.SITE_URL?.trim();
  if (!set) return fromVercel;
  try {
    return new URL(set).origin; // also drops a trailing slash or path
  } catch {
    console.warn(`SITE_URL "${set}" is not a full URL (include https://); using ${fromVercel}`);
    return fromVercel;
  }
}

export const SITE_URL: string = origin();

export const SITE_NAME = "Lexio";
export const SITE_DESCRIPTION =
  "Ask questions about contracts and legal documents. Every answer cites the exact page, and Lexio says so when the documents don't contain the answer.";
