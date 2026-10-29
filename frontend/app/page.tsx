"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  deleteDocument,
  formatWait,
  getLimits,
  listDocuments,
  openChat,
  uploadDocument,
  type Doc,
  type Limits,
  type Source,
  type Turn,
} from "@/lib/api";
import { readEvents } from "@/lib/sse";
import { Message, type ChatMessage } from "@/components/Message";
import { PdfPane, type View } from "@/components/PdfPane";

// The server reads only the last 6 turns of history and rejects a request with more than 20.
const HISTORY_TURNS = 6;

const left = (c: { used: number; limit: number | null }) =>
  c.limit === null ? Infinity : Math.max(c.limit - c.used, 0);

export default function Home() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [limits, setLimits] = useState<Limits | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<View | null>(null);
  const [banner, setBanner] = useState<string | null>(null);
  const [sendError, setSendError] = useState<{ message: string; quota: boolean } | null>(null);
  const [uploading, setUploading] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const nextId = useRef(1);
  const bottom = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    try {
      const [d, l] = await Promise.all([listDocuments(), getLimits()]);
      setDocs(d);
      setLimits(l);
      setBanner(null);
    } catch (e) {
      setBanner((e as Error).message);
    }
  }, []);

  const refreshLimits = useCallback(() => getLimits().then(setLimits).catch(() => {}), []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    // A smooth scroll restarts on every token; only animate when nothing is streaming.
    bottom.current?.scrollIntoView({ behavior: busy ? "auto" : "smooth", block: "end" });
  }, [messages, busy]);

  const questionsLeft = limits ? Math.min(left(limits.questions), left(limits.site_questions)) : Infinity;
  const outOfQuestions = questionsLeft === 0;
  const noDocs = docs.length === 0;
  const canAsk = !busy && !outOfQuestions && !noDocs && input.trim().length >= 2;

  function toggleSelected(id: string, on?: boolean) {
    setSelected((s) => {
      const n = new Set(s);
      if (on ?? !n.has(id)) n.add(id);
      else n.delete(id);
      return n;
    });
  }

  function patch(id: number, fn: (m: ChatMessage) => ChatMessage) {
    setMessages((all) => all.map((m) => (m.id === id ? fn(m) : m)));
  }

  async function ask(question: string) {
    const history: Turn[] = messages
      .filter((m) => !m.streaming && !m.error && m.text)
      .slice(-HISTORY_TURNS)
      .map((m) => ({ role: m.role, content: m.text.slice(0, 4000) }));
    const userMsg: ChatMessage = blank(nextId.current++, "user", question);
    const reply: ChatMessage = { ...blank(nextId.current++, "assistant", ""), streaming: true };
    reply.question = question;
    reply.scope = selected.size;
    setMessages((all) => [...all, userMsg, reply]);
    setInput("");
    setSendError(null);
    setBusy(true);
    const controller = new AbortController();
    abort.current = controller;
    // A question that got no answer at all is taken back, so it can be sent again unchanged.
    const giveBack = (error: { message: string; quota: boolean } | null) => {
      setMessages((all) => all.filter((m) => m.id !== userMsg.id && m.id !== reply.id));
      setInput((cur) => cur || question);
      setSendError(error);
    };
    let streamed = false;
    try {
      const stream = await openChat(
        { question, document_ids: selected.size ? [...selected] : null, history },
        controller.signal,
      );
      for await (const ev of readEvents(stream)) {
        if (ev.type === "sources") patch(reply.id, (m) => ({ ...m, sources: ev.sources, query: ev.query }));
        else if (ev.type === "token") {
          streamed = true;
          patch(reply.id, (m) => ({ ...m, text: m.text + ev.text }));
        } else if (ev.type === "done") patch(reply.id, (m) => ({ ...m, grounded: ev.grounded, refused: ev.refused }));
        else if (ev.type === "error") {
          const error = { message: ev.message, quota: ev.quota };
          if (streamed) patch(reply.id, (m) => ({ ...m, error }));
          else giveBack(error);
        }
      }
    } catch (e) {
      const aborted = (e as Error).name === "AbortError";
      const error = aborted
        ? null
        : { message: (e as Error).message, quota: e instanceof ApiError && e.status === 429 };
      if (streamed) {
        if (error) patch(reply.id, (m) => ({ ...m, error }));
      } else giveBack(error);
    } finally {
      patch(reply.id, (m) => ({ ...m, streaming: false }));
      setBusy(false);
      abort.current = null;
      refreshLimits();
    }
  }

  async function onUpload(file: File | undefined) {
    if (!file) return;
    setUploading(true);
    setBanner(null);
    try {
      const r = await uploadDocument(file);
      await refresh();
      if (r.duplicate) setBanner(`${r.filename} is already in your library.`);
    } catch (e) {
      setBanner((e as Error).message);
      refreshLimits();
    } finally {
      setUploading(false);
    }
  }

  async function onDelete(doc: Doc) {
    if (!confirm(`Delete ${doc.filename}?`)) return;
    try {
      await deleteDocument(doc.id);
      toggleSelected(doc.id, false);
      setView((v) => (v?.documentId === doc.id ? null : v));
      await refresh();
    } catch (e) {
      setBanner((e as Error).message);
    }
  }

  const open = useCallback(
    (s: Source) => setView({ documentId: s.document_id, filename: s.filename, page: s.page }),
    [],
  );

  const uploadOff = !limits?.uploads_enabled;
  const uploadsLeft = limits ? left(limits.uploads) : Infinity;

  return (
    <main className={view ? "layout with-pdf" : "layout"}>
      <nav className="side">
        <h1>Lexio</h1>
        <p className="tag">Ask legal PDFs, get answers with page citations.</p>

        <h2>Documents</h2>
        {noDocs && !banner && <p className="muted">No documents yet.</p>}
        <ul className="docs">
          {docs.map((d) => (
            <li key={d.id}>
              <label>
                <input
                  type="checkbox"
                  checked={selected.has(d.id)}
                  onChange={() => toggleSelected(d.id)}
                />
                <span className="name" title={d.filename}>
                  {d.filename}
                </span>
              </label>
              <span className="meta">{d.pages} pages</span>
              <button className="link" onClick={() => setView({ documentId: d.id, filename: d.filename, page: 1 })}>
                view
              </button>
              {limits?.uploads_enabled && (
                <button className="link danger" onClick={() => onDelete(d)} aria-label={`Delete ${d.filename}`}>
                  delete
                </button>
              )}
            </li>
          ))}
        </ul>
        {docs.length > 1 && (
          <p className="muted small">
            {selected.size ? `Searching ${selected.size} selected.` : "Searching all documents."} Tick boxes to narrow it.
          </p>
        )}

        <label className={`upload ${uploadOff || uploading || uploadsLeft === 0 ? "off" : ""}`}>
          <input
            type="file"
            accept="application/pdf,.pdf"
            disabled={uploadOff || uploading || uploadsLeft === 0}
            onChange={(e) => {
              onUpload(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
          {uploading ? "Reading the PDF…" : "Upload a PDF"}
        </label>
        {limits && uploadOff && <p className="muted small">This demo is read-only: the sample documents are already loaded.</p>}
        {limits?.uploads_enabled && (
          <p className="muted small">
            PDF up to {limits.max_upload_mb} MB
            {limits.max_upload_chunks ? `, about ${limits.max_upload_chunks} sections` : ""}.
            {Number.isFinite(uploadsLeft) && ` ${uploadsLeft} upload${uploadsLeft === 1 ? "" : "s"} left today.`}
          </p>
        )}
        {banner && (
          <p className="notice bad" role="alert">
            {banner}
          </p>
        )}
      </nav>

      <section className="chat">
        <div className="thread">
          {messages.length === 0 && (
            <div className="empty">
              <h2>Ask a question</h2>
              <p>
                Answers come only from your documents. Every claim links to the page it came from. If the answer isn't in
                the documents, Lexio says so.
              </p>
            </div>
          )}
          {messages.map((m) => (
            <Message key={m.id} message={m} onOpen={open} />
          ))}
          <div ref={bottom} />
        </div>

        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault();
            if (canAsk) ask(input.trim());
          }}
        >
          {outOfQuestions && limits && (
            <p className="notice quota" role="status">
              {left(limits.questions) === 0
                ? "You've used all your questions for today."
                : "The demo has answered all the questions the free tier allows today."}{" "}
              Try again in about {formatWait(limits.resets_in_seconds)}.
            </p>
          )}
          {sendError && (
            <p className={`notice ${sendError.quota ? "quota" : "bad"}`} role="alert">
              {sendError.message}
            </p>
          )}
          <div className="row">
            <textarea
              value={input}
              rows={2}
              maxLength={2000}
              placeholder={noDocs ? "Add a document to start" : "Ask about your documents…"}
              disabled={outOfQuestions || noDocs}
              onChange={(e) => {
                setInput(e.target.value);
                setSendError(null);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                  e.preventDefault();
                  if (canAsk) ask(input.trim());
                }
              }}
            />
            {busy ? (
              <button type="button" onClick={() => abort.current?.abort()}>
                Stop
              </button>
            ) : (
              <button type="submit" disabled={!canAsk}>
                Ask
              </button>
            )}
          </div>
          {Number.isFinite(questionsLeft) && !outOfQuestions && (
            <p className="muted small">
              {questionsLeft} question{questionsLeft === 1 ? "" : "s"} left today
              {limits && left(limits.site_questions) < left(limits.questions) ? " (shared by all visitors)" : ""}.
            </p>
          )}
        </form>
      </section>

      {view && <PdfPane view={view} onClose={() => setView(null)} />}
    </main>
  );
}

function blank(id: number, role: ChatMessage["role"], text: string): ChatMessage {
  return { id, role, text, sources: [], question: "", scope: 0, query: null, streaming: false, grounded: null, refused: null, error: null };
}
