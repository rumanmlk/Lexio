"use client";

import { useEffect, useId, useRef, useState } from "react";
import type { Source } from "@/lib/api";
import { docTitle } from "@/lib/title";

const POP_WIDTH = 330;

type Pos = { left: number; top?: number; bottom?: number; width: number };

/**
 * A numbered citation. Hovering or focusing it previews the retrieved passage; clicking opens the
 * page. The preview is fixed-positioned so the scrolling thread cannot clip it.
 */
export function CiteChip({ source, active, onOpen }: { source: Source; active: boolean; onOpen: (s: Source) => void }) {
  const ref = useRef<HTMLButtonElement>(null);
  const id = useId();
  const [pos, setPos] = useState<Pos | null>(null);

  function show() {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const width = Math.min(POP_WIDTH, window.innerWidth - 16);
    const left = Math.min(Math.max(r.left + r.width / 2 - width / 2, 8), window.innerWidth - width - 8);
    const below = r.bottom + 160 < window.innerHeight;
    setPos(below ? { left, top: r.bottom + 8, width } : { left, bottom: window.innerHeight - r.top + 8, width });
  }
  const hide = () => setPos(null);

  useEffect(() => {
    if (!pos) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && hide();
    window.addEventListener("keydown", onKey);
    window.addEventListener("scroll", hide, true);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener("scroll", hide, true);
    };
  }, [pos]);

  const title = docTitle(source.filename);
  const excerpt = source.snippet.replace(/\s+/g, " ").trim();
  return (
    <>
      <button
        ref={ref}
        type="button"
        className={active ? "cite on" : "cite"}
        aria-label={`Source ${source.n}: ${title}, page ${source.page}`}
        aria-describedby={pos ? id : undefined}
        onClick={() => onOpen(source)}
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
      >
        {source.n}
      </button>
      {pos && (
        <span id={id} role="tooltip" className="cite-pop" style={pos}>
          <span className="h">
            <b>{title}</b>
            <span className="mono">p. {source.page}</span>
          </span>
          <span className="q">{excerpt}</span>
          <span className="go">Click to open page {source.page}</span>
        </span>
      )}
    </>
  );
}
