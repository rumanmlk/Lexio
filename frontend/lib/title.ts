const KNOWN: Record<string, { title: string; source: string }> = {
  "universal_declaration_of_human_rights.pdf": { title: "Universal Declaration of Human Rights", source: "United Nations" },
  "crc.pdf": { title: "Convention on the Rights of the Child", source: "United Nations" },
  "mutual-nda-public-2page.pdf": { title: "Mutual NDA", source: "Common Paper" },
  "celex_32016r0679_en_txt.pdf": { title: "GDPR (Regulation 2016/679)", source: "EUR-Lex" },
  "buyer_guidance_-_msc_v2.2a_2025.pdf": { title: "Model Services Contract guidance", source: "UK Cabinet Office" },
  "common-paper-cloud-service-agreement-v3.0.pdf": { title: "Cloud Service Agreement", source: "Common Paper" },
  "common-paper-data-processing-agreement-v1.1.pdf": { title: "Data Processing Agreement", source: "Common Paper" },
  "common-paper-professional-services-agreement-v1.1.pdf": { title: "Professional Services Agreement", source: "Common Paper" },
  "common-paper-software-license-agreement-v1.0.pdf": { title: "Software License Agreement", source: "Common Paper" },
};

/** A readable name for a document: a curated one for the samples, a tidied filename otherwise. */
export function docTitle(filename: string): string {
  const known = KNOWN[filename.toLowerCase()];
  if (known) return known.title;
  const stem = filename.replace(/\.pdf$/i, "").replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
  return stem || filename;
}

/** Who published a sample document, or null for anything else. */
export function docSource(filename: string): string | null {
  return KNOWN[filename.toLowerCase()]?.source ?? null;
}
