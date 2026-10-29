export type Segment = { kind: "text"; text: string } | { kind: "cite"; n: number };

/**
 * Splits an answer into text and citation markers. Only numbers that match a real source become
 * links, so a stray "[7]" the model invented stays as plain text instead of pointing nowhere.
 * Grouped markers like "[1, 2]" become two links.
 */
export function splitCitations(text: string, sourceCount: number): Segment[] {
  const out: Segment[] = [];
  let last = 0;
  for (const m of text.matchAll(/\[(\d+(?:\s*,\s*\d+)*)\]/g)) {
    const nums = m[1].split(",").map((s) => Number(s.trim()));
    if (!nums.every((n) => n >= 1 && n <= sourceCount)) continue;
    if (m.index > last) out.push({ kind: "text", text: text.slice(last, m.index) });
    nums.forEach((n, i) => {
      if (i > 0) out.push({ kind: "text", text: " " });
      out.push({ kind: "cite", n });
    });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ kind: "text", text: text.slice(last) });
  return out;
}
