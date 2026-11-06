import type { PDFDocumentProxy } from "pdfjs-dist";
import { fetchDocumentFile, fetchDocumentRange } from "./api.ts";
import { openDocument, type Opened as OpenedDoc, type PdfLib } from "./opendoc.ts";
import { RefCache } from "./refcache.ts";

type PdfJs = typeof import("pdfjs-dist");
let pdfjs: Promise<PdfJs> | null = null;
export function loadPdfjs(): Promise<PdfJs> {
  pdfjs ??= import("pdfjs-dist").then((m) => {
    m.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
    return m;
  });
  return pdfjs;
}

// ---- whole files, for the browser's own viewer and the "Full PDF" link -------------------------

// The last few whole files fetched. Holds the request itself, so two callers asking at once share one download.
const KEEP_FILES = 2;
const files = new RefCache<Promise<Blob>>(fetchDocumentFile, () => {}, KEEP_FILES);
export function documentBlob(id: string): Promise<Blob> {
  const { value, release } = files.acquire(id);
  release(); // nothing is held while it downloads: the cache only remembers the most recent few
  value.catch(() => files.forget(id, value)); // a failed download is not worth keeping
  return value;
}

// One address per whole file for "Full PDF", so clicking again does not make another. It lives until
// the page is closed: a tab opened from it may be reloaded at any time.
const urls = new Map<string, Promise<string>>();
export function documentUrl(id: string): Promise<string> {
  let url = urls.get(id);
  if (!url) {
    url = documentBlob(id).then((blob) => URL.createObjectURL(blob));
    url.catch(() => urls.delete(id));
    urls.set(id, url);
  }
  return url;
}

// ---- documents opened in pieces ----------------------------------------------------------------

type Opened = OpenedDoc<PDFDocumentProxy>;

const deps = { loadLib: loadPdfjs as () => Promise<PdfLib<PDFDocumentProxy>>, fetchRange: fetchDocumentRange };

const KEEP_DOCUMENTS = 3;
const opened: RefCache<Opened> = new RefCache(
  (id) => {
    const doc: Opened = openDocument(id, deps);
    // A document that failed to open, or broke after it opened, is not worth keeping.
    doc.pdf.catch(() => opened.forget(id, doc));
    doc.failed.catch(() => opened.forget(id, doc));
    return doc;
  },
  (doc) => doc.destroy(),
  KEEP_DOCUMENTS,
);

/** The document, shared with anyone else showing it. Call `release` when done; it is then kept for a while. */
export function acquireDocument(id: string): {
  pdf: Promise<PDFDocumentProxy>;
  /** Rejects if the document stops being readable after it opened (a piece could not be fetched). */
  failed: Promise<never>;
  release: () => void;
} {
  const { value, release } = opened.acquire(id);
  return { pdf: value.pdf, failed: value.failed, release };
}

/**
 * Starts opening a cited document and reading its cited page while the answer is still being written, so
 * a click on the citation usually finds both ready. Costs at most FIRST_BYTES plus the page's own pieces.
 */
export function prefetchDocument(id: string, page: number): void {
  const { pdf, release } = acquireDocument(id);
  pdf
    .then(async (doc) => {
      const p = await doc.getPage(Math.min(Math.max(page, 1), doc.numPages));
      await Promise.all([p.getTextContent(), p.getOperatorList()]);
    })
    .catch(() => {}) // only a head start; the pane reports a real failure itself
    .finally(release);
}
