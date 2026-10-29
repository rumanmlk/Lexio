import { splitCitations } from "./cite.ts";

export type Inline = { kind: "text"; text: string; bold: boolean } | { kind: "cite"; n: number };
export type Block = { kind: "p"; inline: Inline[] } | { kind: "ul"; items: Inline[][] };

/** **bold** and [n] citations; anything else (including an unfinished "**" mid-stream) stays text. */
function inline(line: string, sourceCount: number): Inline[] {
  const out: Inline[] = [];
  line.split(/\*\*(.+?)\*\*/g).forEach((part, i) => {
    if (!part) return;
    for (const seg of splitCitations(part, sourceCount)) {
      out.push(seg.kind === "cite" ? seg : { kind: "text", text: seg.text, bold: i % 2 === 1 });
    }
  });
  return out;
}

/**
 * The model answers in light markdown. Only what it actually uses is understood (paragraphs,
 * "* " or "- " bullets, bold), so the answer never has to be trusted as HTML.
 */
export function parseAnswer(text: string, sourceCount: number): Block[] {
  const blocks: Block[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    const bullet = /^[*-]\s+(.*)$/.exec(line);
    if (bullet) {
      const last = blocks[blocks.length - 1];
      const item = inline(bullet[1], sourceCount);
      if (last?.kind === "ul") last.items.push(item);
      else blocks.push({ kind: "ul", items: [item] });
    } else {
      blocks.push({ kind: "p", inline: inline(line, sourceCount) });
    }
  }
  return blocks;
}
