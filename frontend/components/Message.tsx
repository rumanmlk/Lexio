"use client";

import { memo, useMemo } from "react";
import { parseAnswer, type Inline } from "@/lib/answer";
import { answerHint } from "@/lib/hint";
import type { Source } from "@/lib/api";

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
};

export const Message = memo(function Message({
  message,
  onOpen,
}: {
  message: ChatMessage;
  onOpen: (s: Source) => void;
}) {
  const { text, sources } = message;
  const byNumber = useMemo(() => new Map(sources.map((s) => [s.n, s])), [sources]);
  const blocks = useMemo(
    () => (message.role === "user" ? [] : parseAnswer(text, sources.length)),
    [message.role, text, sources.length],
  );
  if (message.role === "user") return <div className="bubble user">{text}</div>;

  const render = (parts: Inline[]) =>
    parts.map((seg, i) => {
      if (seg.kind === "text") return seg.bold ? <strong key={i}>{seg.text}</strong> : <span key={i}>{seg.text}</span>;
      const src = byNumber.get(seg.n)!;
      return (
        <button key={i} className="cite" onClick={() => onOpen(src)} title={`${src.filename}, page ${src.page}`}>
          {seg.n}
        </button>
      );
    });
  const hint = answerHint(message);
  const rewritten = message.query && message.query.trim() !== message.question.trim();

  return (
    <div className="bubble assistant">
      {rewritten && <p className="searched">Searched for: “{message.query}”</p>}
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
        {message.streaming && <span className="caret" aria-hidden />}
      </div>
      {message.error && (
        <p className={`notice ${message.error.quota ? "quota" : "bad"}`} role="alert">
          {message.error.message}
        </p>
      )}
      {hint && <p className="hint">{hint}</p>}
      {message.sources.length > 0 && !message.streaming && (
        <details className="sources">
          <summary>{message.sources.length} sources searched</summary>
          <ol>
            {message.sources.map((s) => (
              <li key={s.n}>
                <button className="source" onClick={() => onOpen(s)}>
                  <span className="n">{s.n}</span>
                  <span className="where">
                    {s.filename} · p. {s.page}
                  </span>
                  <span className="snippet">{s.snippet}</span>
                </button>
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
});
