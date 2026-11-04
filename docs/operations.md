# Operations: limits, accounts and tracing

How the app stays inside free tiers, how sign-in and per-user documents work, and how to trace chats.

## Free-tier limits that shape the project

- **Gemini embeddings:** about 1,000 requests per day (measured on this project; Google does not publish the embedding figure), and every chunk in a batch counts as one. Daily quotas reset at midnight Pacific time. Ingesting the nine documents (979 chunks) takes about 980, which is the whole day's quota: on a machine without the eval's embedding cache the first ingest has to be spread over two days.
- **Groq `gpt-oss-120b`:** 30 requests and 8,000 tokens per minute, 1,000 requests and 200,000 tokens per day ([Groq's rate-limit table](https://console.groq.com/docs/rate-limits)). A full 105-case answer eval is roughly 170,000 tokens, most of a day's budget, and the per-minute cap makes it slow (it took two sessions); finished cases are cached. **An answer costs about 1,750 tokens**: measured on 10 questions through the app's own prompts, the mean was 1,744 (range 1,497 to 2,024: about 1,660 for the prompt with its six passages, about 85 for the answer), and a follow-up adds about 260 for the query rewrite. So 200,000 tokens is about 110 answers, and **Groq, not Gemini, is the real ceiling for a public demo**; the demo preset allows 80 a day in total, which leaves headroom for long answers, follow-ups and evals. The per-minute limit (about four answers a minute across all visitors) is the tighter one in a burst: the app waits and retries, then shows an error. The measurement is from ten questions, not live traffic; Langfuse traces (below) are the way to re-check it.
- The app stops retrying when a provider reports a daily limit and tells the user when it resets, instead of failing slowly.
- Paid Gemini embeddings cost $0.20 per million input tokens ([pricing](https://ai.google.dev/gemini-api/docs/pricing)). By my arithmetic (about 980 chunks of roughly 300 tokens) the whole sample set is around six cents, so the paid tier is the cheap way out if the free quota ever becomes the constraint.

## Accounts and per-user documents

Sign-in is Google only (one provider, so one person cannot end up with two accounts), through Auth.js in the Next.js app. Anonymous visitors can read the sample documents and ask questions about them, but cannot upload or delete. A signed-in user also gets private documents that nobody else can list, read, search or delete: another user's document id returns `404`, as if it did not exist.

- **Token flow:** Auth.js keeps its session in an encrypted cookie that only the Next.js app can read. A small route (`/token`) trades that session for a 5-minute HS256 token (issuer, audience, expiry, `sub`) signed with `API_TOKEN_SECRET`; the browser sends it as `Authorization: Bearer`, and FastAPI verifies it with PyJWT (algorithm pinned, `sub`/`exp`/`iss`/`aud` required). A bad or expired token is a `401`, never a silent fallback to anonymous.
- **What is stored:** the user id (`google:<sub>`) on the user's documents, and nothing else. No email, name or user table. `DELETE /api/me` erases the user's documents, chunks and PDF files. The daily counters are keyed by a salted hash and are not erased on purpose: otherwise deleting and re-creating an account would reset the day's limits. They expire after 7 days.
- **Samples:** the shared documents belong to the owner `samples`. They cannot be deleted through the API (`403`), and uploading a PDF that is byte-identical to one of them just returns the sample, with no embedding and no copy.
- **Caps:** `USER_MAX_DOCUMENTS` (10) and `USER_MAX_MB` (50) per user, because PDFs live in Postgres and Neon's free tier is small. The global daily caps below still apply to everyone together, since extra Google accounts can bypass any per-user limit. The caps are checked before the upload is stored, so two simultaneous uploads can overshoot one slightly.
- **Dev login:** `next dev` offers a fixed `dev:local` user so the app can be run and tested without Google. It exists only in development builds, and the backend accepts `dev:` users only with `ALLOW_DEV_USERS=true` (leave it off in production).
- **Set up:** put the same `API_TOKEN_SECRET` (32+ characters) in the backend's `.env` and the frontend's `.env.local`, plus `AUTH_SECRET`, `AUTH_GOOGLE_ID` and `AUTH_GOOGLE_SECRET` in the frontend ([`frontend/.env.example`](../frontend/.env.example)). The Google OAuth client needs the redirect URI `http://localhost:3000/api/auth/callback/google`. Auth.js v5 is still tagged beta on npm; this project pins `5.0.0-beta.32`.

## Running a public demo inside those limits

`DEMO_MODE=true` switches on a preset that keeps a shared deployment inside the free tiers (`UPLOADS_ENABLED=false` still switches uploads and deletes off for everyone). Every number can be overridden on its own (`0` turns a limit off):

| Setting | Demo preset | What it does |
| --- | --- | --- |
| `QUESTION_DAILY_LIMIT` | 80 | Answers per day across everyone (Groq's token budget) |
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

## Tracing

Set `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` and every chat sends one trace to Langfuse as OpenTelemetry spans (retrieval span, query-rewrite and answer generations, outcome). By default it holds timings, counts, similarity and flags and a salted visitor hash, never the question, the passages or the answer; `LANGFUSE_CAPTURE_CONTENT=true` adds them. The trace is sent inside the request, with a 3-second timeout, because a serverless instance can be frozen before a background flush; a slow or failing Langfuse never affects an answer.
