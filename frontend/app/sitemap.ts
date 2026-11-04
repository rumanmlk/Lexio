import type { MetadataRoute } from "next";
import { SITE_URL } from "@/lib/site";

// The public pages. Add new marketing or docs pages here.
export default function sitemap(): MetadataRoute.Sitemap {
  return [
    { url: `${SITE_URL}/`, changeFrequency: "monthly", priority: 1 },
    { url: `${SITE_URL}/privacy`, changeFrequency: "yearly", priority: 0.3 },
  ];
}
