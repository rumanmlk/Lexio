import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

// /chat is deliberately NOT disallowed: it carries a noindex tag, and a crawler blocked by robots.txt
// never sees that tag (the URL could then still be indexed from links). Only the non-page routes
// (auth, token, upload) are blocked.
export default function robots(): MetadataRoute.Robots {
  return {
    rules: { userAgent: "*", allow: "/", disallow: ["/api/", "/token", "/blob-upload"] },
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
