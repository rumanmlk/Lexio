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

### Earlier run with Gemini embeddings and Groq answers (two UN documents only)

Measured before the other three documents and the `ts_rank` change, so it does not describe the current code. It is kept in [`backend/evals/results/history/`](backend/evals/results/history/). On 38 questions: Gemini hybrid reached hit@3 1.00 and MRR 0.934; every answer was grounded and 38/38 cited a gold page; all 8 out-of-scope questions were refused; and an instruction planted inside a document was ignored. The first version of that eval reported only 34% grounded: the model wrote citations as `【1†L1-L3】` and the parser only knew `[1]`. Fixing the parser is why the answer eval exists.

**Not yet measured:** Gemini embeddings and Groq answers on all five documents. Both free tiers cap what one day can do (see below), so the runs are resumable:

```bash
uv run python -m evals.run --provider gemini --sweep --reuse   # about 900 of Gemini's 1000 daily embeddings, once
uv run python -m evals.answers --provider gemini --reuse       # stops at Groq's daily limit; run again to continue
```

### Free-tier limits that shape the project

- **Gemini embeddings:** 1,000 requests per day per model, and every chunk in a batch counts as one. Ingesting the five documents takes about 800. A demo where visitors upload long PDFs will exhaust this quickly, so Phase 3 and 4 need a plan: pre-ingested samples, reuse of embeddings for identical text, per-user caps, or the paid tier.
- **Groq `gpt-oss-120b`:** 200,000 tokens per day and 8,000 per minute. A full answer eval (about 300,000 tokens) therefore takes two days; finished cases are cached.
- The app stops retrying when a provider reports a daily limit and tells the user when it resets, instead of failing slowly.

## Run the backend

Needs Docker and [uv](https://docs.astral.sh/uv/).

```bash
docker compose up -d db
cp .env.example .env        # add GROQ_API_KEY and GEMINI_API_KEY
cd backend
uv sync --group dev
uv run uvicorn app.main:app --reload
```

API docs at http://localhost:8000/docs.

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
| `POST` | `/api/documents` | multipart PDF upload; deduplicated by SHA-256 |
| `GET` | `/api/documents` | list |
| `DELETE` | `/api/documents/{id}` | delete with its chunks |
| `POST` | `/api/chat` | `{question, document_ids?, history?}`, answers as Server-Sent Events: `sources` (with the `query` actually searched), `token`…, `done`/`error` |

Errors are explicit: unreadable, password-protected or scanned (no text layer) PDFs return `422` with a reason; a rejected API key returns `502` and a rate limit or timeout returns `503`, after retries with backoff. If the LLM fails after streaming has started, the stream ends with an `error` event.

## Known limitations

- No OCR: scanned PDFs are rejected, not read.
- Follow-ups work by rewriting the latest message into a standalone question with the LLM; there is no other conversation memory, and a failed rewrite falls back to searching the raw message.
- The eval set is small (73 answerable questions over five documents, only two of them contracts). Treat the numbers as a regression check, not proof of accuracy on real contracts.
- Free-tier quotas (see above) limit uploads and evals; they are a deployment concern, not a code one.
- Prompt-injection defences (documents are fenced as untrusted data and the prompt says never to obey them) reduce the risk but cannot remove it.
- No authentication or rate limiting yet (Phase 3): every client shares one workspace.

## Roadmap

- [x] Phase 1: FastAPI + pgvector + hybrid retrieval + citations + eval harness
- [ ] Phase 2: Next.js UI with streaming chat and a PDF viewer that jumps to the cited page
- [ ] Phase 3: auth, per-user documents, rate limiting
- [ ] Phase 4: Vercel + Neon deployment, Langfuse tracing, CI evals

Not legal advice. MIT licensed.
