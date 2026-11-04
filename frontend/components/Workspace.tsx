"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { signOut } from "next-auth/react";
import {
  ApiError,
  deleteAccount,
  deleteDocument,
  formatWait,
  getLimits,
  left,
  listDocuments,
  openChat,
  uploadDocument,
  type Doc,
  type Limits,
  type Source,
  type Turn,
} from "@/lib/api";
import { readEvents } from "@/lib/sse";
import { SAMPLE_QUESTIONS } from "@/lib/samples";
import { docTitle } from "@/lib/title";
import { ConfirmDialog, type Confirm } from "./ConfirmDialog";
import { EvidencePane, type View } from "./EvidencePane";
import { Icon } from "./Icon";
import { Library, type Banner } from "./Library";
import { Message, type ChatMessage } from "./Message";

// The server reads only the last 6 turns of history and rejects a request with more than 20.
const HISTORY_TURNS = 6;

export function Workspace() {
  const [docs, setDocs] = useState<Doc[]>([]);
  const [limits, setLimits] = useState<Limits | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [view, setView] = useState<View | null>(null);
  const [banner, setBanner] = useState<Banner>(null);
  const [sendError, setSendError] = useState<{ message: string; quota: boolean } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [libOpen, setLibOpen] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [confirmAsk, setConfirmAsk] = useState<Confirm | null>(null);
  const [status, setStatus] = useState("");
  const abort = useRef<AbortController | null>(null);
  const nextId = useRef(1);
  const bottom = useRef<HTMLDivElement>(null);
  const box = useRef<HTMLTextAreaElement>(null);
  const opener = useRef<HTMLElement | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [d, l] = await Promise.all([listDocuments(), getLimits()]);
      setDocs(d);
      setLimits(l);
      setBanner(null);
    } catch (e) {
      setBanner({ text: (e as Error).message, kind: "bad" });
    } finally {
      setLoaded(true);
    }
  }, []);

  const refreshLimits = useCallback(() => getLimits().then(setLimits).catch(() => {}), []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  // A question carried over from the landing page is filled in, not sent.
  useEffect(() => {
    const q = new URLSearchParams(location.search).get("q");
    if (!q) return;
    setInput(q.slice(0, 2000));
    history.replaceState(null, "", "/chat");
    box.current?.focus();
  }, []);

  // "/" jumps to the question box from anywhere on the page, like most chat and search tools.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null;
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey || t?.closest("input, textarea, select, [contenteditable]")) return;
      e.preventDefault();
      box.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    // A smooth scroll restarts on every token; only animate when nothing is streaming.
    bottom.current?.scrollIntoView({ behavior: busy ? "auto" : "smooth", block: "end" });
  }, [messages, busy]);

  useEffect(() => {
    const el = box.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [input]);

  useEffect(() => {
    if (!libOpen) return;
    // The library is a drawer on narrow screens: move focus into it, and back to the chip on close.
    const chip = document.querySelector<HTMLElement>(".scope");
    document.querySelector<HTMLElement>("#library .rail-close")?.focus();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setLibOpen(false);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
      chip?.focus();
    };
  }, [libOpen]);

  const questionsLeft = limits ? Math.min(left(limits.questions), left(limits.site_questions)) : Infinity;
  const outOfQuestions = questionsLeft === 0;
  const noDocs = docs.length === 0;
  const canPick = !busy && !outOfQuestions && !noDocs;
  const canAsk = canPick && input.trim().length >= 2;

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
    setStatus("Searching your documents…");
    const controller = new AbortController();
    abort.current = controller;
    // A question that got no answer at all is taken back, so it can be sent again unchanged.
    const giveBack = (error: { message: string; quota: boolean } | null) => {
      setMessages((all) => all.filter((m) => m.id !== userMsg.id && m.id !== reply.id));
      setInput((cur) => cur || question);
      setSendError(error);
    };
    let streamed = false;
    let sourceCount = 0;
    let full = "";
    try {
      const stream = await openChat(
        { question, document_ids: selected.size ? [...selected] : null, history },
        controller.signal,
      );
      for await (const ev of readEvents(stream)) {
        if (ev.type === "sources") {
          sourceCount = ev.sources.length;
          patch(reply.id, (m) => ({ ...m, sources: ev.sources, query: ev.query }));
        } else if (ev.type === "token") {
          streamed = true;
          full += ev.text;
          patch(reply.id, (m) => ({ ...m, text: m.text + ev.text }));
        } else if (ev.type === "done") patch(reply.id, (m) => ({ ...m, grounded: ev.grounded, refused: ev.refused, evidence: ev.evidence }));
        else if (ev.type === "error") {
          const error = { message: ev.message, quota: ev.quota };
          if (streamed) patch(reply.id, (m) => ({ ...m, error }));
          else giveBack(error);
        }
      }
      // One announcement when the answer is complete, not one per token.
      if (streamed) setStatus(`Answer ready. ${spoken(full)} ${sourceCount} ${sourceCount === 1 ? "passage" : "passages"} searched.`);
    } catch (e) {
      const aborted = (e as Error).name === "AbortError";
      const error = aborted
        ? null
        : { message: (e as Error).message, quota: e instanceof ApiError && e.status === 429 };
      if (streamed) {
        if (error) patch(reply.id, (m) => ({ ...m, error }));
      } else giveBack(error);
      setStatus(aborted ? "Stopped." : "The question could not be answered.");
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
      const r = await uploadDocument(file, limits);
      await refresh();
      if (r.sample) setBanner({ text: `${docTitle(r.filename)} is one of the sample documents, so it is ready to use as it is.`, kind: "info" });
      else if (r.duplicate) setBanner({ text: `${docTitle(r.filename)} is already in your library.`, kind: "info" });
      else setBanner({ text: `${docTitle(r.filename)} is ready: ${r.pages} pages.`, kind: "info" });
    } catch (e) {
      setBanner({ text: (e as Error).message, kind: "bad" });
      refreshLimits();
    } finally {
      setUploading(false);
    }
  }

  function onDelete(doc: Doc) {
    setConfirmAsk({
      title: `Delete ${docTitle(doc.filename)}?`,
      body: "The file and its searchable text are removed. This cannot be undone.",
      action: "Delete",
      onConfirm: async () => {
        try {
          await deleteDocument(doc.id);
          toggleSelected(doc.id, false);
          setView((v) => (v?.documentId === doc.id ? null : v));
          await refresh();
        } catch (e) {
          setBanner({ text: (e as Error).message, kind: "bad" });
        }
      },
    });
  }

  function onDeleteAccount() {
    const mine = docs.filter((d) => !d.sample).length;
    setConfirmAsk({
      title: "Delete your data?",
      body: `This erases your ${mine} document${mine === 1 ? "" : "s"} and signs you out. It cannot be undone.`,
      action: "Delete my data",
      onConfirm: async () => {
        try {
          await deleteAccount();
          await signOut({ redirect: false });
          location.reload();
        } catch (e) {
          setBanner({ text: (e as Error).message, kind: "bad" });
        }
      },
    });
  }

  // Remember what opened the pane so closing it can hand focus back.
  const show = useCallback((v: View) => {
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setLibOpen(false);
    setView(v);
  }, []);

  const openSource = useCallback(
    (s: Source, sentence?: string) =>
      show({ documentId: s.document_id, filename: s.filename, page: s.page, snippet: s.snippet, sentence, n: s.n }),
    [show],
  );

  const openDocument = (d: Doc) => show({ documentId: d.id, filename: d.filename, page: 1 });

  function closeView() {
    setView(null);
    opener.current?.focus();
  }

  // Stable between tokens, so a streaming answer does not re-render every earlier message.
  const openPage = useMemo(() => (view ? { documentId: view.documentId, page: view.page } : null), [view?.documentId, view?.page]);

  const scope = !loaded
    ? "Loading documents…"
    : noDocs
    ? "No documents"
    : selected.size
      ? `Searching ${selected.size} of ${docs.length} documents`
      : `Searching ${docs.length === 1 ? "1 document" : `all ${docs.length} documents`}`;

  return (
    <div className="app" data-evidence={view ? "open" : "closed"}>
      <a
        className="skip"
        href="#composer"
        onClick={(e) => {
          e.preventDefault();
          box.current?.focus();
        }}
      >
        Skip to the question box
      </a>
      <Library
        docs={docs}
        limits={limits}
        selected={selected}
        open={libOpen}
        loaded={loaded}
        uploading={uploading}
        banner={banner}
        onToggle={toggleSelected}
        onClearSelection={() => setSelected(new Set())}
        onView={openDocument}
        onDelete={onDelete}
        onUpload={onUpload}
        onDeleteAccount={onDeleteAccount}
        onClose={() => setLibOpen(false)}
      />
      <div className="scrim" hidden={!libOpen && !view} onClick={() => (libOpen ? setLibOpen(false) : closeView())} aria-hidden="true" />

      <main className="chat">
        <div className="bar">
          <div className="bar-left">
            <button type="button" className="chip scope" onClick={() => setLibOpen(true)} aria-controls="library" aria-label={`${scope}. Open the library`}>
              <Icon name="library" />
              <span className="t">{scope}</span>
            </button>
          </div>
          {messages.length > 0 && (
            <button type="button" className="btn-text" onClick={() => !busy && setMessages([])} disabled={busy}>
              New chat
            </button>
          )}
        </div>

        <div className="thread">
          <section className="thread-in" aria-label="Conversation">
            {messages.length === 0 && (
              <div className="empty">
                <h1>What do you want to know?</h1>
                <p>
                  Answers come only from the selected documents. Every claim links to the page it came from, and Lexio says so when the
                  answer isn&apos;t there.
                </p>
                <div className="suggest">
                  {SAMPLE_QUESTIONS.map((q) => (
                    <button key={q} type="button" disabled={!canPick} onClick={() => ask(q)}>
                      <span>{q}</span>
                      <Icon name="arrow" />
                    </button>
                  ))}
                </div>
              </div>
            )}
            {messages.map((m) => (
              <Message key={m.id} message={m} onOpen={openSource} openPage={openPage} />
            ))}
            <div ref={bottom} />
          </section>
        </div>

        <div className="composer-wrap" id="composer">
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
                Try again in about {formatWait(limits.resets_in_seconds)}. You can still read the documents.
              </p>
            )}
            {sendError && (
              <p className={`notice ${sendError.quota ? "quota" : "bad"}`} role="alert">
                {sendError.message}
              </p>
            )}
            <div className="cbox">
              <textarea
                ref={box}
                value={input}
                rows={1}
                maxLength={2000}
                aria-label="Your question"
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
                <button type="button" className="send stop" onClick={() => abort.current?.abort()} aria-label="Stop answering">
                  <Icon name="stop" />
                </button>
              ) : (
                <button type="submit" className="send" disabled={!canAsk} aria-label="Ask">
                  <Icon name="send" />
                </button>
              )}
            </div>
            <div className="foot-note">
              <span className="hide-sm">Check the highlighted page before you rely on an answer. Not legal advice. Press / to ask.</span>
              {Number.isFinite(questionsLeft) && !outOfQuestions && (
                <span>
                  {questionsLeft} question{questionsLeft === 1 ? "" : "s"} left today
                  {limits && left(limits.site_questions) < left(limits.questions) ? " (shared by all visitors)" : ""}
                </span>
              )}
            </div>
          </form>
        </div>
        <p className="sr-only" role="status">
          {status}
        </p>
      </main>

      <ConfirmDialog ask={confirmAsk} onClose={() => setConfirmAsk(null)} />

      {view && (
        <EvidencePane
          view={view}
          onPage={(page) => setView((v) => (v ? { documentId: v.documentId, filename: v.filename, page } : v))}
          onClose={closeView}
        />
      )}
    </div>
  );
}

/** The answer as a screen reader should hear it: no markdown, no [n] markers, cut at a word. */
function spoken(text: string): string {
  const plain = text.replace(/\*\*/g, "").replace(/\[\d+(?:\s*,\s*\d+)*\]/g, "").replace(/\s+/g, " ").trim();
  if (plain.length <= 500) return plain;
  return `${plain.slice(0, 500).replace(/\s+\S*$/, "")} … The rest is in the conversation.`;
}

function blank(id: number, role: ChatMessage["role"], text: string): ChatMessage {
  return { id, role, text, sources: [], question: "", scope: 0, query: null, streaming: false, grounded: null, refused: null, error: null, evidence: {} };
}
