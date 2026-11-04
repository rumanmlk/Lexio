"use client";

import { useEffect, useRef, useState } from "react";
import type { PDFDocumentLoadingTask, PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import { fetchDocumentFile } from "@/lib/api";
import { boxesFor, buildIndex, findPassage, type Box, type Placed } from "@/lib/highlight";
import { docSource, docTitle } from "@/lib/title";
import { Icon } from "./Icon";

/** A page to show. `snippet` (the start of the cited passage) turns on highlighting; `n` is its citation number. */
export type View = { documentId: string; filename: string; page: number; snippet?: string; sentence?: string; n?: number };

type PdfJs = typeof import("pdfjs-dist");
let pdfjs: Promise<PdfJs> | null = null;
function loadPdfjs(): Promise<PdfJs> {
  pdfjs ??= import("pdfjs-dist").then((m) => {
    m.GlobalWorkerOptions.workerSrc = new URL("pdfjs-dist/build/pdf.worker.min.mjs", import.meta.url).toString();
    return m;
  });
  return pdfjs;
}

// The last few documents opened, so reopening one (or flipping between two cited documents) does not
// download it again. A page reload, which is also what signing out does, empties it.
const KEEP_DOCUMENTS = 3;
// Holds the request itself, so two components asking at once share one download.
const blobs = new Map<string, Promise<Blob>>();
function documentBlob(id: string): Promise<Blob> {
  const hit = blobs.get(id) ?? fetchDocumentFile(id);
  hit.catch(() => blobs.delete(id)); // a failed download is not worth keeping
  blobs.delete(id);
  blobs.set(id, hit); // most recently used goes last
  if (blobs.size > KEEP_DOCUMENTS) blobs.delete(blobs.keys().next().value!);
  return hit;
}

const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

type Load =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; pdf: PDFDocumentProxy; url: string }
  /** pdf.js could not open or draw the file; the browser's own viewer takes over. */
  | { status: "fallback"; url: string };

/** What was found on one page. Boxes are in page units (scale 1), so they stay valid at any width. */
type Found = { key: string; width: number; height: number; boxes: Box[]; context: Box[]; text: string; narrow: boolean };

/**
 * Shows one page of a document drawn by pdf.js, with the cited passage highlighted when it can be
 * found in the page's text. If pdf.js cannot open the file, falls back to the browser's own viewer.
 */
export function EvidencePane({ view, onPage, onClose }: { view: View; onPage: (page: number) => void; onClose: () => void }) {
  const [load, setLoad] = useState<Load>({ status: "loading" });
  const [width, setWidth] = useState(0);
  const [found, setFound] = useState<Found | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const closeBtn = useRef<HTMLButtonElement>(null);
  const widthNow = useRef(0);
  widthNow.current = width;

  useEffect(() => closeBtn.current?.focus(), []);

  // Load the file once per document.
  useEffect(() => {
    let dead = false;
    let loading: PDFDocumentLoadingTask | null = null;
    let url: string | null = null;
    setLoad({ status: "loading" });
    (async () => {
      let blob: Blob;
      try {
        blob = await documentBlob(view.documentId);
      } catch (e) {
        if (!dead) setLoad({ status: "error", message: (e as Error).message });
        return;
      }
      if (dead) return;
      url = URL.createObjectURL(blob);
      try {
        const lib = await loadPdfjs();
        loading = lib.getDocument({ data: new Uint8Array(await blob.arrayBuffer()) });
        const pdf = await loading.promise;
        if (!dead) setLoad({ status: "ready", pdf, url });
      } catch {
        if (!dead) setLoad({ status: "fallback", url });
      }
    })();
    return () => {
      dead = true;
      void loading?.destroy();
      if (url) URL.revokeObjectURL(url);
    };
  }, [view.documentId]);

  // Draw at the pane's width, so the page is readable without zooming. Measured once per frame.
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    let frame = 0;
    const measure = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => setWidth(Math.max(0, Math.floor(el.clientWidth - 32))));
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => {
      cancelAnimationFrame(frame);
      ro.disconnect();
    };
  }, []);

  const pdf = load.status === "ready" ? load.pdf : null;
  const fail = () => setLoad((l) => (l.status === "ready" ? { status: "fallback", url: l.url } : l));

  // Read the page's text and place the passage. Does not depend on the width.
  useEffect(() => {
    if (!pdf) return;
    let dead = false;
    (async () => {
      const lib = await loadPdfjs();
      const page = await pdf.getPage(Math.min(Math.max(view.page, 1), pdf.numPages));
      const base = page.getViewport({ scale: 1 });
      const text = await page.getTextContent();
      if (dead) return;
      const items = text.items.filter((it): it is Extract<typeof it, { str: string }> => "str" in it);
      const placed: Placed[] = items.map((it) => {
        const t = lib.Util.transform(base.transform, it.transform);
        const h = Math.hypot(t[2], t[3]);
        return { str: it.str, left: t[4], top: t[5] - h * 0.95, width: it.width, height: h * 1.2 };
      });
      // Prefer the sentence closest to the claim; fall back to the whole retrieved passage. The sentence is a
      // best guess, so when it is shown the passage around it stays lightly marked and the guess cannot hide the evidence.
      const index = buildIndex(items);
      const sentenceSpan = view.sentence ? findPassage(index, view.sentence) : null;
      const passageSpan = view.snippet ? findPassage(index, view.snippet) : null;
      const span = sentenceSpan ?? passageSpan;
      const boxes = span ? boxesFor(placed, span) : [];
      const context = sentenceSpan && passageSpan ? boxesFor(placed, passageSpan) : [];
      // Screen readers get the page text with the cited passage marked, since they cannot see the highlight.
      const marked = items
        .map((it, i) => (span && i === span.first ? "[Highlighted passage starts] " : "") + it.str + (span && i === span.last ? " [Highlighted passage ends]" : ""))
        .join(" ");
      setFound({ key: `${view.documentId}:${view.page}`, width: base.width, height: base.height, boxes, context, text: marked, narrow: Boolean(sentenceSpan) && boxes.length > 0 });
      if (boxes.length) {
        const top = (Math.min(...boxes.map((b) => b.top)) * widthNow.current) / base.width;
        requestAnimationFrame(() => scroller.current?.scrollTo({ top: Math.max(top - 80, 0), behavior: reduceMotion() ? "auto" : "smooth" }));
      } else scroller.current?.scrollTo({ top: 0 });
    })().catch(() => !dead && fail());
    return () => {
      dead = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pdf, view.page, view.snippet, view.sentence]);

  // Draw the canvas. Only this reruns when the pane is resized.
  useEffect(() => {
    if (!pdf || !width) return;
    let dead = false;
    let task: RenderTask | null = null;
    (async () => {
      const page = await pdf.getPage(Math.min(Math.max(view.page, 1), pdf.numPages));
      const scale = width / page.getViewport({ scale: 1 }).width;
      const dpr = window.devicePixelRatio || 1;
      const el = canvas.current;
      if (!el || dead) return;
      const css = page.getViewport({ scale });
      el.width = Math.floor(css.width * dpr);
      el.height = Math.floor(css.height * dpr);
      task = page.render({ canvas: el, viewport: page.getViewport({ scale: scale * dpr }) });
      await task.promise;
    })().catch((e: Error) => {
      if (!dead && e.name !== "RenderingCancelledException") fail();
    });
    return () => {
      dead = true;
      task?.cancel();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pdf, view.page, width]);

  const pages = pdf?.numPages ?? null;
  const title = docTitle(view.filename);
  const source = docSource(view.filename);
  const url = load.status === "ready" || load.status === "fallback" ? load.url : null;
  // What was found applies only to the document page now showing; the previous page's size is kept meanwhile so the pane does not jump.
  const here = found && found.key === `${view.documentId}:${view.page}` ? found : null;
  const asked = Boolean(view.snippet || view.sentence);

  return (
    <aside className="evi" aria-labelledby="evi-title" onKeyDown={(e) => e.key === "Escape" && onClose()}>
      <header>
        <div className="hrow">
          <div className="title">
            <b id="evi-title" title={view.filename}>
              {title}
            </b>
            <span>{[view.n ? `Cited as [${view.n}]` : null, source].filter(Boolean).join(" · ") || "Source document"}</span>
          </div>
          <button ref={closeBtn} type="button" className="icon-btn" onClick={onClose} aria-label="Close source">
            <Icon name="x" />
          </button>
        </div>
        <div className="hrow">
          <span className="pager" role="group" aria-label="Page">
            <button type="button" aria-label="Previous page" disabled={view.page <= 1} onClick={() => onPage(view.page - 1)}>
              <Icon name="left" />
            </button>
            <span aria-live="polite">
              Page {view.page} / {pages ?? "…"}
            </span>
            <button type="button" aria-label="Next page" disabled={!pages || view.page >= pages} onClick={() => onPage(view.page + 1)}>
              <Icon name="right" />
            </button>
          </span>
          {here && here.boxes.length > 0 && (
            <span className="pill">
              <Icon name="shield" />
              {here.narrow ? "Closest sentence highlighted" : "Passage highlighted"}
            </span>
          )}
        </div>
      </header>

      {load.status === "error" ? (
        <p className="notice bad">Couldn&apos;t load this document: {load.message}</p>
      ) : load.status === "fallback" ? (
        <iframe key={view.page} src={`${load.url}#page=${view.page}`} title={title} />
      ) : (
        <div ref={scroller} className="evi-page" tabIndex={0} role="region" aria-label={`Page ${view.page} of ${title}`}>
          {!pdf && <p className="muted small">Loading the document…</p>}
          <div className="paper-wrap" style={{ width: width || undefined, aspectRatio: found && pdf ? `${found.width} / ${found.height}` : undefined, display: pdf && found ? undefined : "none" }}>
            <canvas ref={canvas} aria-hidden="true" />
            {here && [...here.context.map((b) => ({ b, soft: true })), ...here.boxes.map((b) => ({ b, soft: false }))].map(({ b, soft }, i) => (
              <span
                key={i}
                className={soft ? "hl-box soft" : "hl-box"}
                style={{ left: `${(b.left / here.width) * 100}%`, top: `${(b.top / here.height) * 100}%`, width: `${(b.width / here.width) * 100}%`, height: `${(b.height / here.height) * 100}%` }}
              />
            ))}
          </div>
          {here && <div className="sr-only">Text of page {view.page}: {here.text}</div>}
        </div>
      )}

      <div className="evi-foot">
        <span>
          {here && asked && here.boxes.length === 0
            ? "Couldn't pinpoint the passage; it is somewhere on this page."
            : here && here.boxes.length > 0
              ? here.narrow
                ? "Strong highlight: the sentence closest in wording to the answer, a best guess. Light highlight: the rest of the retrieved passage. Check the claim against the passage."
                : "The highlight marks the retrieved passage."
              : "Pick a citation to see its passage highlighted."}
        </span>
        {url && (
          <a href={`${url}#page=${view.page}`} target="_blank" rel="noreferrer" className="btn-text evi-link">
            <Icon name="external" /> Full PDF
          </a>
        )}
      </div>
    </aside>
  );
}
