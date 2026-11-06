/** What the first request for a document asks for. A file no bigger than this arrives whole in that one
 * request; a bigger one is then read in pieces of CHUNK, only where the page being shown needs them. */
export const FIRST_BYTES = 512 * 1024;
/** The piece size pdf.js asks for. Large enough that a page costs a few round trips, not dozens. */
export const CHUNK = 256 * 1024;

export type ContentRange = { first: number; last: number; total: number };

/** Reads `Content-Range: bytes 0-99/1234`. null for anything else, including an unknown total (`/*`). */
export function parseContentRange(header: string | null): ContentRange | null {
  const m = /^bytes (\d+)-(\d+)\/(\d+)$/i.exec((header ?? "").trim());
  if (!m) return null;
  const [first, last, total] = [Number(m[1]), Number(m[2]), Number(m[3])];
  return first <= last && last < total ? { first, last, total } : null;
}

export function rangeHeader(first: number, lastInclusive: number): string {
  return `bytes=${first}-${lastInclusive}`;
}

/** pdf.js asks for [begin, end) and may overshoot the end of the file; HTTP wants the last byte, inclusive. */
export function clampRange(begin: number, end: number, total: number): [number, number] {
  const last = Math.min(end, total) - 1;
  if (!(begin >= 0 && begin <= last)) throw new RangeError(`Bad range ${begin}-${end} of ${total}`);
  return [begin, last];
}
