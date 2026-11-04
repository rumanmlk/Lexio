"use client";

import { memo, useMemo, useState } from "react";
import { parseAnswer, type Inline } from "@/lib/answer";
import { answerHint } from "@/lib/hint";
import type { Source } from "@/lib/api";
import { docTitle } from "@/lib/title";
import { CiteChip } from "./CiteChip";
import { Icon } from "./Icon";
import { Mark } from "./Logo";

export type ChatMessage = {
  id: number;
  role: "user" | "assistant";
  text: string;
  sources: Source[];
  /** What the user asked (assistant messages) and what the search actually used, once known. */
  question: string;
  /** How many documents the search was narrowed to (0 = all of them). */
  scope: number;
  query: string | null;
  streaming: boolean;
  grounded: boolean | null;
  refused: boolean | null;
  error: { message: string; quota: boolean } | null;
  /** Per cited source number, the sentence of that passage closest to the claim citing it (may be missing). */
  evidence: Record<string, string>;
};

/** The page currently open in the evidence pane, so its citation chips can show as selected. */
export type OpenPage = { documentId: string; page: number } | null;

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

export const Message = memo(function Message({
  message,
  onOpen,
  openPage,
}: {
  message: ChatMessage;
  onOpen: (s: Source, sentence?: string) => void;
  openPage: OpenPage;
}) {
  const { text, sources } = message;
  const [copied, setCopied] = useState(false);
  const byNumber = useMemo(() => new Map(sources.map((s) => [s.n, s])), [sources]);
  const blocks = useMemo(
    () => (message.role === "user" ? [] : parseAnswer(text, sources.length)),
    [message.role, text, sources.length],
  );
  const cited = useMemo(() => {
    const seen = new Set<number>();
    const note = (parts: Inline[]) => parts.forEach((p) => p.kind === "cite" && seen.add(p.n));
    for (const b of blocks) b.kind === "p" ? note(b.inline) : b.items.forEach(note);
    return sources.filter((s) => seen.has(s.n));
  }, [blocks, sources]);

  if (message.role === "user") return <div className="msg-user">{text}</div>;

  const open = (s: Source) => onOpen(s, message.evidence[String(s.n)]);
  const isOpen = (s: Source) => openPage?.documentId === s.document_id && openPage.page === s.page;
  const render = (parts: Inline[]) =>
    parts.map((seg, i) => {
      if (seg.kind === "text") return seg.bold ? <strong key={i}>{seg.text}</strong> : <span key={i}>{seg.text}</span>;
      const src = byNumber.get(seg.n)!;
      return <CiteChip key={i} source={src} active={isOpen(src)} onOpen={open} />;
    });
  const hint = answerHint(message);
  const rewritten = message.query && message.query.trim() !== message.question.trim();
  const done = !message.streaming;
  const others = sources.filter((s) => !cited.includes(s));
  const docCount = new Set(cited.map((s) => s.document_id)).size;

  async function copy() {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      // clipboard blocked: nothing to fall back to that is better than doing nothing
    }
  }

  const row = (s: Source) => (
    <li key={s.n}>
      <button type="button" className={isOpen(s) ? "cited-row on" : "cited-row"} onClick={() => open(s)}>
        <span className="cite on" aria-hidden="true">
          {s.n}
        </span>
        <span className="tt">
          <b>
            {docTitle(s.filename)} · p. {s.page}
          </b>
          <span>{s.snippet.replace(/\s+/g, " ")}</span>
        </span>
        <Icon name="right" />
      </button>
    </li>
  );

  return (
    <div className="msg-bot">
      <div className="who">
        <Mark />
        Lexio
      </div>
      {rewritten && <p className="searched">Searched for: “{message.query}”</p>}
      {message.streaming && !text && (
        <div className="thinking" aria-hidden="true">
          <p className="muted small">{sources.length ? `Found ${plural(sources.length, "passage")}, writing the answer…` : "Searching the documents…"}</p>
          <div className="skel" style={{ width: "92%" }} />
          <div className="skel" style={{ width: "78%" }} />
          <div className="skel" style={{ width: "60%" }} />
        </div>
      )}
      <div className="answer">
        {blocks.map((b, i) =>
          b.kind === "p" ? (
            <p key={i}>{render(b.inline)}</p>
          ) : (
            <ul key={i}>
              {b.items.map((item, j) => (
                <li key={j}>{render(item)}</li>
              ))}
            </ul>
          ),
        )}
        {message.streaming && text && <span className="caret" aria-hidden="true" />}
      </div>
      {message.error && (
        <p className={`notice ${message.error.quota ? "quota" : "bad"}`} role="alert">
          {message.error.message}
        </p>
      )}
      {done && text && !message.error && (
        <div className="meta">
          {message.refused ? (
            <span className="pill warn">Not found in the selected documents</span>
          ) : message.grounded === false ? (
            <span className="pill warn">No source cited</span>
          ) : cited.length > 0 ? (
            <span className="pill">
              <Icon name="shield" />
              Grounded · {plural(docCount, "document")}, {plural(cited.length, "passage")}
            </span>
          ) : null}
          <button type="button" className="btn-text" onClick={copy}>
            <Icon name="copy" /> {copied ? "Copied" : "Copy"}
          </button>
        </div>
      )}
      {hint && <p className="hint">{hint}</p>}
      {done && cited.length > 0 && <ul className="cited">{cited.map(row)}</ul>}
      {done && others.length > 0 && (
        <details className="more">
          <summary>
            {cited.length ? `${plural(others.length, "other passage")} searched` : `${plural(others.length, "passage")} searched`}
          </summary>
          <ul className="cited">
            {others.map(row)}
          </ul>
        </details>
      )}
    </div>
  );
});
