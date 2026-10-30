"use client";

import { useEffect, useState } from "react";
import { fetchDocumentFile } from "@/lib/api";

export type View = { documentId: string; filename: string; page: number };

/**
 * Shows a document at a page using the browser's own PDF viewer. The file is fetched once per
 * document and kept as a blob URL; changing the page only changes the URL fragment, which the
 * viewer follows (the `key` forces a fresh viewer, since some browsers ignore a fragment change).
 */
export function PdfPane({ view, onClose }: { view: View; onClose: () => void }) {
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let revoked = false;
    let created: string | null = null;
    setUrl(null);
    setError(null);
    fetchDocumentFile(view.documentId)
      .then((blob) => {
        if (revoked) return;
        created = URL.createObjectURL(blob);
        setUrl(created);
      })
      .catch((e: Error) => !revoked && setError(e.message));
    return () => {
      revoked = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [view.documentId]);

  return (
    <aside className="pdf">
      <header>
        <div>
          <strong title={view.filename}>{view.filename}</strong>
          <span>page {view.page}</span>
        </div>
        <button onClick={onClose} aria-label="Close document">
          ×
        </button>
      </header>
      {error ? (
        <p className="notice">Couldn't load this document: {error}</p>
      ) : url ? (
        <iframe key={`${view.documentId}-${view.page}`} src={`${url}#page=${view.page}`} title={view.filename} />
      ) : (
        <p className="notice">Loading…</p>
      )}
    </aside>
  );
}
