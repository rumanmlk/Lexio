/** Where a passage sits on a page: the first and last text item it touches, and the character
 * offsets (into each item's own string) where it starts and ends. */
export type Span = { first: number; firstOffset: number; last: number; lastOffset: number };

export type Box = { left: number; top: number; width: number; height: number };

/** Positioned text from the PDF page. Any unit works as long as every item uses the same one. */
export type Placed = { str: string } & Box;

const keep = /[\p{L}\p{N}]/u;

/** Letters and digits only, lower case: the PDF's text and the stored passage differ in spacing,
 * hyphenation and quote characters, but not in these. */
export function squash(s: string): string {
  let out = "";
  for (const ch of s) if (keep.test(ch)) out += ch.toLowerCase();
  return out;
}

/** A page's text squashed to letters and digits, with the (item, offset) each character came from.
 * Build it once per page and search it for as many passages as needed. */
export type PageIndex = { text: string; item: Uint32Array; offset: Uint32Array };

export function buildIndex(items: { str: string }[]): PageIndex {
  let text = "";
  const item: number[] = [];
  const offset: number[] = [];
  items.forEach((it, i) => {
    let o = 0;
    for (const ch of it.str) {
      if (keep.test(ch)) {
        text += ch.toLowerCase();
        item.push(i);
        offset.push(o);
      }
      o += ch.length;
    }
  });
  return { text, item: Uint32Array.from(item), offset: Uint32Array.from(offset) };
}

/**
 * Finds the stored passage (the start of a chunk) in a page index. Tries a long needle first and
 * shorter ones after, since the passage may start mid-sentence or contain characters the PDF renders
 * differently. Returns null when it cannot be placed with confidence.
 */
export function findPassage(index: PageIndex, passage: string): Span | null {
  const wanted = squash(passage);
  if (wanted.length < 12) return null;
  const page = index.text;

  let at = -1;
  for (const len of [60, 40, 24, 14]) {
    if (wanted.length < len) continue;
    at = page.indexOf(wanted.slice(0, len));
    if (at >= 0) break;
  }
  if (at < 0) return null;

  // The passage is cut at a fixed length, so its tail is usually mid-word on the page too.
  let end = Math.min(at + wanted.length, page.length) - 1;
  const tail = wanted.slice(-24);
  if (wanted.length > 60) {
    const t = page.indexOf(tail, at + 24);
    if (t >= 0 && t + tail.length - 1 <= at + wanted.length * 1.4) end = t + tail.length - 1;
  }
  return { first: index.item[at], firstOffset: index.offset[at], last: index.item[end], lastOffset: index.offset[end] + 1 };
}

/** One box per text item the passage covers; the first and last are trimmed to the characters used. */
export function boxesFor(items: Placed[], span: Span): Box[] {
  const out: Box[] = [];
  for (let i = span.first; i <= span.last; i++) {
    const it = items[i];
    const len = Math.max(it.str.length, 1);
    const from = i === span.first ? span.firstOffset : 0;
    const to = i === span.last ? span.lastOffset : len;
    if (to <= from || it.width <= 0) continue;
    out.push({ left: it.left + (it.width * from) / len, top: it.top, width: (it.width * (to - from)) / len, height: it.height });
  }
  return out;
}
