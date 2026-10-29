"""Load the sample PDFs into the configured database, spending as little free-tier quota as
possible. For setting up the public demo's read-only workspace:

    DATABASE_URL=<neon pooled url> EMBEDDING_PROVIDER=gemini uv run python -m evals.seed

Vectors come from the eval's on-disk embedding cache when it has them (the Gemini retrieval eval
embeds exactly these documents with exactly this model), so after that eval the seed costs no
Gemini requests at all. Anything not cached is embedded and cached. Safe to rerun: documents
are matched by SHA-256 and skipped when already present.
"""

import argparse
import asyncio
import os

from evals.common import PATIENT, CachedEmbedder, embedding_cache, sample_pdfs


class Counting:
    """Counts how many texts actually reached the embedding API."""

    def __init__(self, inner):
        self.inner, self.sent = inner, 0

    async def embed_documents(self, texts):
        self.sent += len(texts)
        return await self.inner.embed_documents(texts)

    async def embed_query(self, text):
        return await self.inner.embed_query(text)


async def main(provider: str, owner: str) -> None:
    os.environ["EMBEDDING_PROVIDER"] = provider
    from app.config import get_settings
    from app.db import apply_migrations, open_pool
    from app.embeddings import build_embedder
    from app.ingest import ingest_pdf

    s = get_settings()
    apply_migrations(s.database_url)
    pool = await open_pool(s.database_url)
    live = Counting(build_embedder(s, PATIENT))
    embedder = CachedEmbedder(live, embedding_cache(s, provider))
    try:
        for pdf in sample_pdfs():
            r = await ingest_pdf(
                pool, embedder, owner_id=owner, filename=pdf.name, data=pdf.read_bytes(),
                chunk_chars=s.chunk_chars, overlap=s.chunk_overlap_chars,
            )
            state = "already present" if r.duplicate else f"{r.chunk_count} chunks"
            print(f"{pdf.name}: {r.page_count} pages, {state}")
    finally:
        await pool.close()
    print(f"embedding requests sent to {provider}: {live.sent}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--provider", choices=["gemini", "local"], default="gemini")
    ap.add_argument("--owner", default="public", help="owner_id the API serves (default: public)")
    a = ap.parse_args()
    asyncio.run(main(a.provider, a.owner))
