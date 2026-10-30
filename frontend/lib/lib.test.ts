import assert from "node:assert/strict";
import { test } from "node:test";

import { blobPathname, detailMessage, openChat } from "./api.ts";
import { answerHint } from "./hint.ts";
import { parseAnswer } from "./answer.ts";
import { splitCitations } from "./cite.ts";
import { parseBlock, readEvents } from "./sse.ts";
import { jwtVerify } from "jose";
import { mintApiToken } from "./apitoken.ts";
import { tokenFresh } from "./token.ts";

function streamOf(...parts: string[]): ReadableStream<Uint8Array> {
  const enc = new TextEncoder();
  return new ReadableStream({
    start(c) {
      for (const p of parts) c.enqueue(enc.encode(p));
      c.close();
    },
  });
}

async function collect(stream: ReadableStream<Uint8Array>) {
  const out = [];
  for await (const e of readEvents(stream)) out.push(e);
  return out;
}

test("parseBlock reads typed events and ignores unknown ones", () => {
  assert.deepEqual(parseBlock('event: token\ndata: {"text":"hi"}'), { type: "token", text: "hi" });
  assert.deepEqual(parseBlock('event: error\ndata: {"message":"x","quota":true}'), {
    type: "error",
    message: "x",
    quota: true,
  });
  assert.equal(parseBlock('event: ping\ndata: {}'), null);
  assert.equal(parseBlock("event: token\ndata: not json"), null);
});

test("readEvents reassembles events split across chunks, including inside a multibyte character", async () => {
  const full = 'event: token\ndata: {"text":"café"}\n\nevent: done\ndata: {"grounded":true,"cited":[1]}\n\n';
  const bytes = new TextEncoder().encode(full);
  const cut = full.indexOf("é");
  const split = new TextEncoder().encode(full.slice(0, cut)).length + 1; // mid-character
  const enc = new ReadableStream<Uint8Array>({
    start(c) {
      c.enqueue(bytes.slice(0, split));
      c.enqueue(bytes.slice(split));
      c.close();
    },
  });
  assert.deepEqual(await collect(enc), [
    { type: "token", text: "café" },
    { type: "done", grounded: true, cited: [1], refused: false },
  ]);
});

test("readEvents handles CRLF and a final block without a trailing blank line", async () => {
  const events = await collect(streamOf('event: token\r\ndata: {"text":"a"}\r\n\r\n', 'event: token\r\ndata: {"text":"b"}'));
  assert.deepEqual(events, [
    { type: "token", text: "a" },
    { type: "token", text: "b" },
  ]);
});

test("splitCitations links only real sources and expands groups", () => {
  assert.deepEqual(splitCitations("Yes [1]. Also [2, 3] and [9].", 3), [
    { kind: "text", text: "Yes " },
    { kind: "cite", n: 1 },
    { kind: "text", text: ". Also " },
    { kind: "cite", n: 2 },
    { kind: "text", text: " " },
    { kind: "cite", n: 3 },
    { kind: "text", text: " and [9]." },
  ]);
  assert.deepEqual(splitCitations("no cites", 0), [{ kind: "text", text: "no cites" }]);
});

test("parseAnswer understands bullets, bold and citations, and nothing else", () => {
  const blocks = parseAnswer("Intro **key** [1]:\n\n* one [2]\n- two <b>x</b>\nAfter", 2);
  assert.deepEqual(blocks, [
    {
      kind: "p",
      inline: [
        { kind: "text", text: "Intro ", bold: false },
        { kind: "text", text: "key", bold: true },
        { kind: "text", text: " ", bold: false },
        { kind: "cite", n: 1 },
        { kind: "text", text: ":", bold: false },
      ],
    },
    {
      kind: "ul",
      items: [
        [{ kind: "text", text: "one ", bold: false }, { kind: "cite", n: 2 }],
        [{ kind: "text", text: "two <b>x</b>", bold: false }],
      ],
    },
    { kind: "p", inline: [{ kind: "text", text: "After", bold: false }] },
  ]);
  assert.deepEqual(parseAnswer("half **open", 0), [
    { kind: "p", inline: [{ kind: "text", text: "half **open", bold: false }] },
  ]);
});

test("readEvents survives a CRLF block terminator split across chunks", async () => {
  const events = await collect(
    streamOf('event: token\r\ndata: {"text":"a"}\r\n\r', '\nevent: token\r\ndata: {"text":"b"}\r\n\r\n'),
  );
  assert.deepEqual(events, [
    { type: "token", text: "a" },
    { type: "token", text: "b" },
  ]);
});

test("detailMessage reads our string errors and FastAPI validation lists", () => {
  assert.equal(detailMessage("You have used your 10 questions."), "You have used your 10 questions.");
  assert.equal(
    detailMessage([{ loc: ["body", "history"], msg: "List should have at most 20 items" }]),
    "history: List should have at most 20 items",
  );
  assert.equal(detailMessage([{ msg: "bad" }, { loc: ["body", "question"], msg: "too short" }]), "bad; question: too short");
  assert.equal(detailMessage(undefined), null);
  assert.equal(detailMessage([]), null);
});

test("cancelling a chat request is an AbortError, not a connection failure", async () => {
  const controller = new AbortController();
  controller.abort();
  await assert.rejects(
    openChat({ question: "hello", document_ids: null, history: [] }, controller.signal),
    (e: Error) => e.name === "AbortError",
  );
});

test("answerHint advises on refusals and uncited answers only", () => {
  const base = { streaming: false, error: null, refused: false, grounded: true, scope: 0 };
  assert.equal(answerHint(base), null);
  assert.equal(answerHint({ ...base, refused: true, grounded: false }), "Try a more specific question, using terms from the document.");
  assert.match(answerHint({ ...base, refused: true, grounded: false, scope: 1 })!, /^Only the selected document was searched; untick/);
  assert.match(answerHint({ ...base, refused: true, grounded: false, scope: 3 })!, /^Only the 3 selected documents were searched/);
  assert.match(answerHint({ ...base, grounded: false })!, /doesn't cite a source/);
  assert.equal(answerHint({ ...base, refused: true, streaming: true }), null);
  assert.equal(answerHint({ ...base, refused: true, error: { message: "x" } }), null);
  assert.equal(answerHint({ ...base, refused: null, grounded: null }), null); // stopped before done
});

test("a cached API token is reused until 30 seconds before it expires", () => {
  const now = 1_000_000;
  assert.equal(tokenFresh({ expiresAt: now + 31_000 }, now), true);
  assert.equal(tokenFresh({ expiresAt: now + 29_000 }, now), false);
  assert.equal(tokenFresh({ expiresAt: now - 1 }, now), false);
});

test("the API token carries what the backend requires and expires in 5 minutes", async () => {
  const config = { secret: "s".repeat(40), issuer: "lexio-web", audience: "lexio-api" };
  const now = 1_800_000_000;
  const { token, expires_at } = await mintApiToken("google:123", config, now);
  assert.equal(expires_at, now + 300);

  const { payload, protectedHeader } = await jwtVerify(token, new TextEncoder().encode(config.secret), {
    issuer: config.issuer,
    audience: config.audience,
    algorithms: ["HS256"],
    currentDate: new Date((now + 1) * 1000),
  });
  assert.equal(protectedHeader.alg, "HS256");
  assert.equal(payload.sub, "google:123");
  assert.equal(payload.exp, now + 300);

  // a token signed with another secret, or checked after expiry, is refused
  await assert.rejects(jwtVerify(token, new TextEncoder().encode("x".repeat(40))));
  await assert.rejects(
    jwtVerify(token, new TextEncoder().encode(config.secret), { currentDate: new Date((now + 400) * 1000) }),
  );
});

test("blobPathname keeps uploads inside the user's prefix with a name the server accepts", () => {
  const prefix = "u/0123456789abcdef01234567/";
  assert.equal(blobPathname(prefix, "My Contract (final).PDF"), `${prefix}My_Contract_final_.pdf`);
  assert.equal(blobPathname(prefix, "../../etc/passwd.pdf"), `${prefix}etc_passwd.pdf`);
  assert.equal(blobPathname(prefix, "x..pdf"), `${prefix}x.pdf`);
  assert.equal(blobPathname(prefix, "a..b.pdf"), `${prefix}a.b.pdf`); // the server refuses ".."
  assert.equal(blobPathname(prefix, "договор.pdf"), `${prefix}document.pdf`);
  assert.equal(blobPathname(prefix, ".pdf"), `${prefix}document.pdf`);
  assert.ok(blobPathname(prefix, "a".repeat(500) + ".pdf").length <= prefix.length + 104);
  for (const name of ["a/b.pdf", "a\b.pdf", "x.y.pdf"]) {
    const rest = blobPathname(prefix, name).slice(prefix.length);
    assert.match(rest, /^[A-Za-z0-9._-]+$/);
    assert.ok(!rest.includes("/"));
  }
});
