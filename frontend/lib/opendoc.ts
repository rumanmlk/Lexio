import type { Piece } from "./api.ts";
import { CHUNK, clampRange, FIRST_BYTES } from "./ranges.ts";

/** The part of pdf.js this needs, so the opening logic can be exercised without the real library. */
export type Transport = {
  onDataRange(begin: number, chunk: Uint8Array): void;
  requestDataRange(begin: number, end: number): void;
};
export type Task<D> = { promise: Promise<D>; destroy(): unknown };
export type PdfLib<D> = {
  PDFDataRangeTransport: new (length: number, initialData: Uint8Array | null) => Transport;
  getDocument(src: {
    data?: Uint8Array;
    range?: Transport;
    rangeChunkSize?: number;
    disableAutoFetch?: boolean;
    disableStream?: boolean;
  }): Task<D>;
};
export type Deps<D> = {
  loadLib: () => Promise<PdfLib<D>>;
  fetchRange: (id: string, first: number, last: number) => Promise<Piece>;
  /** How long to wait before fetching a failed piece again; a dropped connection often needs a moment. */
  retryDelayMs?: number;
};

/** A document being opened. `failed` settles if a piece could not be fetched after it opened. */
export type Opened<D> = { pdf: Promise<D>; destroy: () => void; failed: Promise<never> };

function fail(message: string): never {
  throw new Error(message);
}

/**
 * Opens a document by fetching only the first FIRST_BYTES up front (a smaller file is then complete);
 * pdf.js asks for the rest piece by piece, and only the pieces the shown page needs.
 *
 * pdf.js has no hook for a piece that cannot be fetched: it waits for it forever, whether the document
 * is still opening or already showing. So a piece that fails twice destroys the document and settles
 * `failed`, which is how the pane (and the cache) learn it is unusable and fall back to the whole file.
 */
export function openDocument<D>(id: string, deps: Deps<D>): Opened<D> {
  let task: Task<D> | null = null;
  let closed = false;
  const destroy = () => {
    closed = true;
    void task?.destroy();
  };
  let breakIt: (e: Error) => void = () => {};
  const failed = new Promise<never>((_, reject) => (breakIt = reject));
  failed.catch(() => {});
  const broken = () => {
    destroy();
    breakIt(new Error("A part of the document could not be fetched"));
  };

  const pdf = (async () => {
    const lib = await deps.loadLib();
    const head = await deps.fetchRange(id, 0, FIRST_BYTES - 1);
    if (closed) throw new Error("closed");
    // No size means a proxy hid Content-Range: the pane then falls back to reading the whole file.
    const total = head.total ?? fail("The server did not say how big the document is");
    if (head.bytes.length >= total) {
      task = lib.getDocument({ data: head.bytes });
      return task.promise;
    }

    const attempt = async (begin: number, end: number): Promise<Piece> => {
      const [first, last] = clampRange(begin, end, total);
      try {
        return await deps.fetchRange(id, first, last);
      } catch {
        // Once more, after a moment: one dropped request should not cost the page.
        await new Promise((r) => setTimeout(r, deps.retryDelayMs ?? 300));
        return deps.fetchRange(id, first, last);
      }
    };
    class Pieces extends lib.PDFDataRangeTransport {
      requestDataRange(begin: number, end: number) {
        attempt(begin, end).then(
          (p) => !closed && this.onDataRange(p.first, p.bytes),
          () => !closed && broken(),
        );
      }
    }
    task = lib.getDocument({
      range: new Pieces(total, head.bytes),
      rangeChunkSize: CHUNK,
      disableAutoFetch: true, // the rest of the file is not wanted until a page needs it
      disableStream: true,
    });
    return task.promise;
  })();
  pdf.catch(() => {}); // each holder handles its own copy of the failure
  return { pdf, destroy, failed };
}
