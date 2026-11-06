import assert from "node:assert/strict";
import { test } from "node:test";
import type { Piece } from "./api.ts";
import { openDocument, type Deps, type Transport } from "./opendoc.ts";
import { CHUNK, FIRST_BYTES } from "./ranges.ts";

const TOTAL = 4 * 1024 * 1024;
const tick = () => new Promise((r) => setTimeout(r, 5));

/** A stand-in for pdf.js that records what it was given. */
function fake(fetchRange: Deps<string>["fetchRange"]) {
  const seen = { src: null as Record<string, unknown> | null, destroyed: 0, received: [] as [number, number][] };
  class Base implements Transport {
    length: number;
    initial: Uint8Array | null;
    constructor(length: number, initial: Uint8Array | null) {
      this.length = length;
      this.initial = initial;
    }
    onDataRange(begin: number, chunk: Uint8Array) {
      seen.received.push([begin, chunk.length]);
    }
    requestDataRange(_begin: number, _end: number) {}
  }
  const deps: Deps<string> = {
    loadLib: async () => ({
      PDFDataRangeTransport: Base,
      getDocument: (src) => {
        seen.src = src as Record<string, unknown>;
        return { promise: Promise.resolve("doc"), destroy: () => void seen.destroyed++ };
      },
    }),
    fetchRange,
    retryDelayMs: 0,
  };
  return { seen, deps };
}

const head = (total: number | null, bytes = FIRST_BYTES): Piece => ({ bytes: new Uint8Array(bytes), first: 0, total });
const transportOf = (seen: { src: Record<string, unknown> | null }) => seen.src!.range as Transport;

test("a small file arrives whole in the first request and is opened from it", async () => {
  const { seen, deps } = fake(async () => head(1000, 1000));
  const doc = openDocument("a", deps);
  assert.equal(await doc.pdf, "doc");
  assert.ok(seen.src!.data && !seen.src!.range);
});

test("a big file is opened from its first bytes and read in pieces on demand", async () => {
  const calls: [number, number][] = [];
  const { seen, deps } = fake(async (_id, first, last) => {
    calls.push([first, last]);
    return first === 0 ? head(TOTAL) : { bytes: new Uint8Array(last - first + 1), first, total: TOTAL };
  });
  const doc = openDocument("a", deps);
  await doc.pdf;
  assert.equal(seen.src!.rangeChunkSize, CHUNK);
  assert.equal(seen.src!.disableAutoFetch, true);
  transportOf(seen).requestDataRange(FIRST_BYTES, FIRST_BYTES + CHUNK);
  await tick();
  assert.deepEqual(calls, [[0, FIRST_BYTES - 1], [FIRST_BYTES, FIRST_BYTES + CHUNK - 1]]);
  assert.deepEqual(seen.received, [[FIRST_BYTES, CHUNK]]);
});

test("a piece that fails once is fetched again and the document carries on", async () => {
  let fails = 1;
  const { seen, deps } = fake(async (_id, first, last) => {
    if (first === 0) return head(TOTAL);
    if (fails-- > 0) throw new Error("dropped");
    return { bytes: new Uint8Array(last - first + 1), first, total: TOTAL };
  });
  const doc = openDocument("a", deps);
  await doc.pdf;
  transportOf(seen).requestDataRange(FIRST_BYTES, FIRST_BYTES + CHUNK);
  await tick();
  assert.equal(seen.received.length, 1);
  assert.equal(seen.destroyed, 0);
});

test("a piece that fails twice closes the document and tells whoever is showing it", async () => {
  const { seen, deps } = fake(async (_id, first) => {
    if (first === 0) return head(TOTAL);
    throw new Error("down");
  });
  const doc = openDocument("a", deps);
  await doc.pdf;
  transportOf(seen).requestDataRange(FIRST_BYTES, FIRST_BYTES + CHUNK);
  await assert.rejects(doc.failed, /could not be fetched/);
  assert.equal(seen.destroyed, 1);
  assert.deepEqual(seen.received, []);
});

test("a file whose size is not reported is refused, so the pane falls back to the whole file", async () => {
  const { deps } = fake(async () => head(null));
  const doc = openDocument("a", deps);
  await assert.rejects(doc.pdf, /how big/);
});

test("a document closed before its first bytes arrive is never handed to pdf.js", async () => {
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  const { seen, deps } = fake(async () => (await gate, head(TOTAL)));
  const doc = openDocument("a", deps);
  doc.destroy();
  release();
  await assert.rejects(doc.pdf, /closed/);
  assert.equal(seen.src, null);
});
