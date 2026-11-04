"use client";

import { useEffect, useRef } from "react";

export type Confirm = { title: string; body: string; action: string; onConfirm: () => void };

/** A modal confirmation on the native <dialog>: focus is trapped, Escape cancels, focus returns on close. */
export function ConfirmDialog({ ask, onClose }: { ask: Confirm | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (ask && !d.open) d.showModal();
    if (!ask && d.open) d.close();
  }, [ask]);

  return (
    <dialog ref={ref} className="confirm" aria-labelledby="confirm-title" aria-describedby="confirm-body" onClose={onClose} onClick={(e) => e.target === ref.current && onClose()}>
      {ask && (
        <form method="dialog">
          <h2 id="confirm-title">{ask.title}</h2>
          <p id="confirm-body">{ask.body}</p>
          <div className="confirm-actions">
            <button type="button" className="btn btn-secondary" onClick={onClose} autoFocus>
              Cancel
            </button>
            <button
              type="button"
              className="btn btn-danger"
              onClick={() => {
                ask.onConfirm();
                onClose();
              }}
            >
              {ask.action}
            </button>
          </div>
        </form>
      )}
    </dialog>
  );
}
