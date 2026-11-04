import type { NextConfig } from "next";

// Response headers for every page and route. A script-src policy is deliberately not here: it needs
// a per-request nonce, which would force every page (including the static landing page) to render
// dynamically. `frame-ancestors` and `base-uri` need no nonce and close clickjacking and <base>
// injection. `object-src` is left alone because the browser's PDF viewer in the evidence pane
// depends on it, and `form-action` because the Google sign-in form redirects off-site.
const SECURITY_HEADERS = [
  { key: "Content-Security-Policy", value: "frame-ancestors 'none'; base-uri 'self'" },
  { key: "X-Frame-Options", value: "DENY" }, // the same rule for browsers that predate frame-ancestors
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  { key: "Strict-Transport-Security", value: "max-age=63072000" },
];

const config: NextConfig = {
  async headers() {
    return [{ source: "/:path*", headers: SECURITY_HEADERS }];
  },
};

export default config;
