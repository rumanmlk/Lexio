# Lexio

Ask questions about legal PDFs and get answers with page-level citations. Every claim in an answer links to the page it came from, and the app refuses to answer when the documents don't contain it.

> Rebuild in progress (`rebuild/v2`). The original Streamlit prototype lives in [`legacy/`](legacy/).

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
| Retrieval | Hybrid: cosine similarity + Postgres full-text, fused with Reciprocal Rank Fusion | Dense search misses exact terms (article numbers, defined words); keyword search misses paraphrase |
| Embeddings | `gemini-embedding-2` at 768 dims (free tier); `bge-base-en-v1.5` locally | Same 768-dim column for both |
| LLM | `openai/gpt-oss-120b` on Groq | Free tier, reasoning kept out of the answer text |
| Chunking | Per page, ~1200 chars, 150 overlap, never crossing a page | Every citation points at exactly one page |

Chunks and citations are the product. If the best match has no keyword hit and a weak cosine similarity, `/api/chat` refuses instead of guessing.

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

## API

| Method | Path | |
|---|---|---|
| `POST` | `/api/documents` | multipart PDF upload; deduplicated by SHA-256 |
| `GET` | `/api/documents` | list |
| `DELETE` | `/api/documents/{id}` | delete with its chunks |
| `POST` | `/api/chat` | `{question, document_ids?}`, answers as Server-Sent Events: `sources`, `token`…, `done`/`error` |

## Roadmap

- [x] Phase 1: FastAPI + pgvector + hybrid retrieval + citations + eval harness
- [ ] Phase 2: Next.js UI with streaming chat and a PDF viewer that jumps to the cited page
- [ ] Phase 3: auth, per-user documents, rate limiting
- [ ] Phase 4: Vercel + Neon deployment, Langfuse tracing, CI evals

Not legal advice. MIT licensed.
