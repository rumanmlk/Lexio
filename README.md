# Lexio

Ask questions about legal PDFs and get answers with page-level citations. Every claim in an answer links to the page it came from, and the app refuses to answer when the documents don't contain it.

> Rebuild in progress. The original Streamlit + FAISS + Ollama prototype is preserved at [commit `38f8892`](https://github.com/rumanmlk/Lexio/tree/38f8892).

## Architecture

```
PDF ──► pypdf ──► page-bounded chunks ──► embeddings ──► Postgres (pgvector HNSW + tsvector GIN)
                                                                │
question ──► embed ──┬─► vector top-30 ──┐                      │
                     └─► keyword top-30 ─┴─► RRF fusion ──► top-6 ──► LLM (streamed, cited)
```

| Layer | Choice | Why |
|---|---|---|
| API | FastAPI, async psycopg 3, SSE streaming | Deploys on Vercel with zero config |
| Storage | Postgres + pgvector (Neon in production) | One database for vectors, full-text search and metadata |
| Retrieval | Hybrid: cosine similarity + Postgres full-text, fused with Reciprocal Rank Fusion (equal weights) | Keyword search catches exact terms but is noisy on its own; see the numbers below |
| Embeddings | `gemini-embedding-2` at 768 dims (free tier); `bge-base-en-v1.5` locally | Same 768-dim column for both |
| LLM | `openai/gpt-oss-120b` on Groq | Free tier, reasoning kept out of the answer text |
| Chunking | Per page, ~1200 chars, 150 overlap, never crossing a page | Every citation points at exactly one page |

Chunks and citations are the product. If the best chunk's cosine similarity is below the refusal threshold (per embedding model, override with `MIN_SIMILARITY`), `/api/chat` refuses instead of guessing.

## Measured results

Five public documents, 73 answerable questions with a verified gold page each, 8 clearly out-of-scope questions, 14 "near-miss" questions (on-topic, but the document gives no such detail) and 9 follow-ups. A test checks every gold page against the PDFs. Sources and licences: [`data/samples/NOTICE.md`](data/samples/NOTICE.md).

| Document | Pages | Chunks |
|---|---|---|
| Universal Declaration of Human Rights | 8 | 14 |
| UN Convention on the Rights of the Child | 15 | 55 |
| Common Paper Mutual NDA | 2 | 9 |
| GDPR (Regulation 2016/679) | 88 | 405 |
| UK Model Services Contract, guidance for authorities | 132 | 325 |

### Retrieval (local `bge-base-en-v1.5` embeddings, all five documents)

hit@k = the right page is among the top k results.

| retrieval | hit@1 | hit@3 | hit@6 | MRR |
|---|---|---|---|---|
| vector only | 0.66 | 0.84 | 0.88 | 0.752 |
| keyword only | 0.74 | 0.82 | 0.89 | 0.786 |
| hybrid, equal weights (default) | 0.74 | 0.82 | 0.90 | 0.794 |
| hybrid, keyword weight 0.25 | 0.66 | 0.86 | 0.89 | 0.755 |

- **The keyword ranking function mattered more than any weight.** The first version ranked keyword matches with `ts_rank_cd` (cover density). On the five-document corpus it scored MRR 0.539 on its own and dragged hybrid below plain vector search (0.720 vs 0.752). Switching to `ts_rank` (term frequency), which suits questions whose words are OR-ed together, lifted keyword-only to 0.786 and hybrid to 0.794. The ranking was chosen by comparing variants offline on this same question set, so treat the gain as indicative.
- Hybrid's edge over the better single signal is small here (0.794 vs 0.786). Its value is robustness: it does not depend on either signal being good on a given question.
- **The similarity refusal gate does not separate cleanly on this larger corpus with the local model**: answerable questions score down to 0.557 while out-of-scope ones reach 0.641, so any threshold trades missed refusals against wrong ones (at 0.55: 62% of out-of-scope questions refused, no wrong refusals). The near-miss questions are on-topic, so no similarity threshold can catch them; the model has to, and the answer eval measures that.
- Full output: [`backend/evals/results/local.md`](backend/evals/results/local.md).

### Retrieval (Gemini `gemini-embedding-2`, all five documents)

73 answerable and 8 out-of-scope questions, same chunking as above.

| retrieval | hit@1 | hit@3 | hit@6 | MRR |
|---|---|---|---|---|
| vector only | 0.81 | 0.93 | 0.96 | 0.871 |
| keyword only | 0.74 | 0.82 | 0.89 | 0.786 |
| hybrid, keyword weight 1.0 (default) | 0.81 | 0.89 | 0.93 | 0.856 |
| hybrid, keyword weight 0.5 | 0.81 | 0.92 | 0.95 | 0.861 |
| hybrid, keyword weight 0.25 | 0.78 | 0.93 | 0.95 | 0.857 |

- **With Gemini embeddings, hybrid does not beat plain vector search** on this question set (MRR 0.856 vs 0.871). The gap between the hybrid weights is one or two questions out of 73, which is within noise, so the default weight of 1.0 was not changed. Hybrid is kept for the same robustness reason as above (and the local model, where keyword search is the stronger signal).
- **Refusal threshold 0.65 holds up, but with little room.** Answerable questions score from 0.661 to 0.851 (median 0.773); out-of-scope ones from 0.548 to 0.704 (median 0.625). At 0.65, 62% of out-of-scope questions are refused and none of the answerable ones; 0.70 would refuse 88% but also wrongly refuse 10% of answerable ones. The lowest answerable score is only 0.011 above the threshold, so a few more questions could push a correct one under it. The keyword check does not help: all 8 out-of-scope questions had a keyword hit.
- Full output: [`backend/evals/results/gemini.md`](backend/evals/results/gemini.md).

### Earlier run with Gemini embeddings and Groq answers (two UN documents only)

Measured before the other three documents and the `ts_rank` change, so it does not describe the current code. It is kept in [`backend/evals/results/history/`](backend/evals/results/history/). On 38 questions: Gemini hybrid reached hit@3 1.00 and MRR 0.934; every answer was grounded and 38/38 cited a gold page; all 8 out-of-scope questions were refused; and an instruction planted inside a document was ignored. The first version of that eval reported only 34% grounded: the model wrote citations as `【1†L1-L3】` and the parser only knew `[1]`. Fixing the parser is why the answer eval exists.

**Not yet measured:** Groq answers on all five documents with Gemini retrieval. The free tier caps what one day can do (see below), so the run is resumable:

```bash
uv run python -m evals.answers --provider gemini --reuse       # stops at Groq's daily limit; run again to continue
```

The Gemini retrieval eval above was produced with `uv run python -m evals.run --provider gemini --sweep --reuse` (about 920 of Gemini's 1000 daily embeddings, once).

### Free-tier limits that shape the project

- **Gemini embeddings:** about 1,000 requests per day (measured on this project; Google does not publish the embedding figure), and every chunk in a batch counts as one. Daily quotas reset at midnight Pacific time. Ingesting the five documents takes about 800.
- **Groq `gpt-oss-120b`:** 30 requests and 8,000 tokens per minute, 1,000 requests and 200,000 tokens per day ([Groq's rate-limit table](https://console.groq.com/docs/rate-limits)). A full answer eval (about 300,000 tokens) therefore takes two days; finished cases are cached. One answer costs about 3,000 tokens, so **Groq, not Gemini, is the real ceiling for a public demo: roughly 60 answers a day in total.** (That per-answer figure is derived from the eval's token use, not measured on live traffic.)
- The app stops retrying when a provider reports a daily limit and tells the user when it resets, instead of failing slowly.
- Paid Gemini embeddings cost $0.20 per million input tokens ([pricing](https://ai.google.dev/gemini-api/docs/pricing)). By my arithmetic (about 800 chunks of roughly 300 tokens) the whole sample set is around five cents, so the paid tier is the cheap way out if the free quota ever becomes the constraint.

### Accounts and per-user documents

Sign-in is Google only (one provider, so one person cannot end up with two accounts), through Auth.js in the Next.js app. Anonymous visitors can read the sample documents and ask questions about them, but cannot upload or delete. A signed-in user also gets private documents that nobody else can list, read, search or delete: another user's document id returns `404`, as if it did not exist.

- **Token flow:** Auth.js keeps its session in an encrypted cookie that only the Next.js app can read. A small route (`/token`) trades that session for a 5-minute HS256 token (issuer, audience, expiry, `sub`) signed with `API_TOKEN_SECRET`; the browser sends it as `Authorization: Bearer`, and FastAPI verifies it with PyJWT (algorithm pinned, `sub`/`exp`/`iss`/`aud` required). A bad or expired token is a `401`, never a silent fallback to anonymous.
- **What is stored:** the user id (`google:<sub>`) on the user's documents, and nothing else. No email, name or user table. `DELETE /api/me` erases the user's documents, chunks and PDF files. The daily counters are keyed by a salted hash and are not erased on purpose: otherwise deleting and re-creating an account would reset the day's limits. They expire after 7 days.
- **Samples:** the shared documents belong to the owner `samples`. They cannot be deleted through the API (`403`), and uploading a PDF that is byte-identical to one of them just returns the sample, with no embedding and no copy.
- **Caps:** `USER_MAX_DOCUMENTS` (10) and `USER_MAX_MB` (50) per user, because PDFs live in Postgres and Neon's free tier is small. The global daily caps below still apply to everyone together, since extra Google accounts can bypass any per-user limit. The caps are checked before the upload is stored, so two simultaneous uploads can overshoot one slightly.
- **Dev login:** `next dev` offers a fixed `dev:local` user so the app can be run and tested without Google. It exists only in development builds, and the backend accepts `dev:` users only with `ALLOW_DEV_USERS=true` (leave it off in production).
- **Set up:** put the same `API_TOKEN_SECRET` (32+ characters) in the backend's `.env` and the frontend's `.env.local`, plus `AUTH_SECRET`, `AUTH_GOOGLE_ID` and `AUTH_GOOGLE_SECRET` in the frontend ([`frontend/.env.example`](frontend/.env.example)). The Google OAuth client needs the redirect URI `http://localhost:3000/api/auth/callback/google`. Auth.js v5 is still tagged beta on npm; this project pins `5.0.0-beta.32`.

### Running a public demo inside those limits

`DEMO_MODE=true` switches on a preset that keeps a shared deployment inside the free tiers (`UPLOADS_ENABLED=false` still switches uploads and deletes off for everyone). Every number can be overridden on its own (`0` turns a limit off):

| Setting | Demo preset | What it does |
|---|---|---|
| `QUESTION_DAILY_LIMIT` | 60 | Answers per day across everyone (Groq's token budget) |
| `VISITOR_QUESTION_LIMIT` | 10 | Answers per user per day (per hashed IP for anonymous visitors) |
| `VISITOR_UPLOAD_LIMIT` | 2 | New documents per user per day |
| `MAX_UPLOAD_CHUNKS` | 150 | Longest PDF accepted (one chunk is one Gemini request) |
| `EMBED_DAILY_LIMIT` | 1000 (always, with Gemini) | Embedding requests per day; `EMBED_QUERY_RESERVE` (200) of them are kept back, so uploads can never leave the app unable to embed a question |

How it works:

- Counters live in Postgres (`daily_usage`), so every serverless instance shares them, and days roll over at midnight Pacific like Gemini's quota. Reservations are atomic: concurrent requests cannot overshoot a limit (tested with 40 racing claims against a limit of 10).
- A refused request returns **429** with a `Retry-After` header and a plain message ("…It resets in about 5 hours."). It is refused before any provider is called, so it costs nothing, and a request that fails at the provider gives its reservation back (a question whose answer fails before any text is sent does not count against the visitor's daily questions). Duplicate and unreadable PDFs are never charged.
- If Gemini reports its daily quota gone, the counter is set to match, so later uploads are refused immediately instead of failing slowly.
- `GET /api/limits` tells a client what the visitor has left, so a UI can disable controls instead of failing.
- Visitors are told apart by a salted hash of their IP (the IP itself is never stored). Set `VISITOR_SALT`, and `TRUST_FORWARDED_FOR=true` only behind a proxy that sets `X-Forwarded-For` itself, as Vercel does; the last entry is used, so a client cannot choose its own identity by sending the header. Anonymous visitors are counted this way; signed-in users are counted by a salted hash of their user id instead.
- **Seeding the demo:** `uv run python -m evals.seed` loads the sample PDFs into `DATABASE_URL`. It reads vectors from the eval's embedding cache, so after the Gemini retrieval eval has run it needs no Gemini requests at all; anything missing is embedded once and cached. Reruns skip documents already present.

What this does not cover: the counters see only traffic through this API (running the evals on the same Gemini project uses quota they cannot see; the provider's own error is the backstop, and the app then records it). The question cap is a proxy for Groq tokens, not a token meter.

## Run the backend

Needs Docker and [uv](https://docs.astral.sh/uv/).

```bash
docker compose up -d db
cp .env.example .env        # add GROQ_API_KEY and GEMINI_API_KEY (and API_TOKEN_SECRET, see Accounts)
cd backend
uv sync --group dev
uv run uvicorn app.main:app --reload
```

API docs at http://localhost:8000/docs. On Windows keep `--reload`: without it uvicorn uses an event loop that psycopg's async mode cannot run on, and every database call times out.

## Run the web app

```bash
cd frontend
cp .env.example .env.local   # API URL and the sign-in secrets; see Accounts
npm install
npm run dev                  # http://localhost:3000
npm test                     # stream parser and citation tests
```

Streaming chat over the SSE events, `[n]` citations that open the PDF at the cited page, a document filter, upload and delete, and the daily limits (remaining questions shown, controls disabled, `429` explained with the wait). Sign in with Google, or with the dev login under `npm run dev`. To get sample documents into a local database: `cd backend && uv run python -m evals.seed --provider local`.

```bash
uv run pytest               # unit tests + end-to-end against local Postgres, no API keys needed
uv run ruff check .
```

### Evaluate retrieval

```bash
uv sync --group local-embeddings
uv run python -m evals.run --provider local --sweep
```

Results are written to `backend/evals/results/`.

### Evaluate answers (real LLM)

```bash
uv run python -m evals.answers --provider gemini --limit 10   # a sample; drop --limit for everything
```

Sends each question through the same path as `/api/chat` with Groq and checks that answers are grounded, that a cited source is on the gold page, that out-of-scope and near-miss questions are refused or flagged as unspecified, that follow-ups are rewritten into searchable questions, and that an instruction planted inside a document is not obeyed. Groq's free tier allows 200k tokens a day, so a full run spans two days: it stops cleanly when the quota runs out, caches finished cases, and continues on the next run. A run that did not finish is written to `answers-<provider>-partial.md` and marked as partial.

## API

| Method | Path | |
|---|---|---|
| `POST` | `/api/documents` | signed-in only: multipart PDF upload; deduplicated by SHA-256, and a PDF identical to a sample returns the sample |
| `GET` | `/api/documents` | the samples plus the caller's own (`sample: true` marks the shared ones) |
| `GET` | `/api/documents/{id}/file` | the original PDF, for the viewer |
| `DELETE` | `/api/documents/{id}` | signed-in only: delete one of your documents with its chunks (`403` for a sample) |
| `DELETE` | `/api/me` | signed-in only: erase all of your documents and files |
| `GET` | `/api/limits` | what this visitor may still do today (questions, uploads, stored documents, reset time) |
| `POST` | `/api/chat` | `{question, document_ids?, history?}`, answers as Server-Sent Events: `sources` (with the `query` actually searched), `token`…, `done` (`grounded`, `cited`, `refused`) or `error` |

Errors are explicit: a used-up daily budget returns `429` with `Retry-After` (see above); unreadable, password-protected or scanned (no text layer) PDFs return `422` with a reason; a rejected API key returns `502` and a rate limit or timeout returns `503`, after retries with backoff. If the LLM fails after streaming has started, the stream ends with an `error` event.

## Known limitations

- No OCR: scanned PDFs are rejected, not read.
- Follow-ups work by rewriting the latest message into a standalone question with the LLM; there is no other conversation memory, and a failed rewrite falls back to searching the raw message.
- The eval set is small (73 answerable questions over five documents, only two of them contracts). Treat the numbers as a regression check, not proof of accuracy on real contracts.
- Free-tier quotas (see above) limit uploads, evals and how many questions a public demo can answer per day. The budget guard keeps a deployment inside them; it does not raise them.
- Prompt-injection defences (documents are fenced as untrusted data and the prompt says never to obey them) reduce the risk but cannot remove it.
- Anonymous limits count a hashed IP, which people behind one shared address share. Signed-in users are counted per account, but a determined person can make several Google accounts; only the global daily caps stop that.
- The real Google sign-in is checked by hand, not in automated tests (it needs a Google OAuth client); the token, ownership and limit logic is tested against the dev login.

## Roadmap

- [x] Phase 1: FastAPI + pgvector + hybrid retrieval + citations + eval harness
- [x] Phase 2: Next.js UI with streaming chat and a PDF viewer that jumps to the cited page (uses the browser's built-in PDF viewer)
- [x] Phase 3: Google sign-in, per-user documents, per-user limits
- [ ] Phase 4: Vercel + Neon deployment, Langfuse tracing, CI evals

Not legal advice. MIT licensed.
