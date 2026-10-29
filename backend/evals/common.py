"""Shared setup for the eval scripts: a throwaway database with the sample PDFs ingested, and
on-disk caches so a free-tier quota is never spent twice on the same work."""

import hashlib
import json
import os
import time
from pathlib import Path

import psycopg

import app  # noqa: F401  (sets the Windows event-loop policy before asyncio.run creates a loop)
from app.errors import RetryPolicy

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "data" / "samples"
EVALS = Path(__file__).parent
DATASET = EVALS / "dataset.json"
FOLLOWUPS = EVALS / "followups.json"
RESULTS = EVALS / "results"
CACHE = EVALS / ".cache"
EVAL_DB = "lexio_eval"

# An eval can afford to wait out a per-minute free-tier cap that a web request cannot.
PATIENT = RetryPolicy(attempts=8, backoff=4.0, max_wait=70.0)


def sample_pdfs() -> list[Path]:
    return sorted(SAMPLES.glob("*.pdf"))


def _digest(*parts: str) -> str:
    return hashlib.sha256("\0".join(parts).encode()).hexdigest()


class JsonlCache:
    """key -> value kept on disk as append-only JSON lines: read once, one line written per new
    entry. (Rewriting one big JSON file after every embedding would be quadratic.)"""

    def __init__(self, path: Path):
        self.path, self.data = path, {}
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                key, value = json.loads(line)
                self.data[key] = value

    def get(self, key: str):
        return self.data.get(key)

    def put(self, key: str, value) -> None:
        self.data[key] = value
        CACHE.mkdir(exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps([key, value]) + "\n")


class CachedEmbedder:
    """Each text is embedded once, ever: re-ingesting costs one API request per chunk and the
    Gemini free tier allows only 1000 a day, so an embedding is never bought twice."""

    def __init__(self, inner, cache: JsonlCache):
        self.inner, self.cache = inner, cache

    async def embed_documents(self, texts):
        missing = [t for t in dict.fromkeys(texts) if self.cache.get("D" + _digest(t)) is None]
        for i in range(0, len(missing), 50):  # saved per batch, so a quota error loses nothing
            part = missing[i : i + 50]
            for t, v in zip(part, await self.inner.embed_documents(part), strict=True):
                self.cache.put("D" + _digest(t), v)
        return [self.cache.get("D" + _digest(t)) for t in texts]

    async def embed_query(self, text):
        key = "Q" + _digest(text)
        if (hit := self.cache.get(key)) is None:
            hit = await self.inner.embed_query(text)
            self.cache.put(key, hit)
        return hit


class CachedLLM:
    """Remembers every completion by its exact prompt. Any change that matters (the prompts,
    the retrieved sources, the question, the model) changes the prompt and so misses the
    cache; nothing else does. Groq's free tier allows 200k tokens a day, so an interrupted
    eval resumes for free instead of paying for finished cases again."""

    def __init__(self, inner, cache: JsonlCache):
        self.inner, self.cache = inner, cache

    async def complete(self, system: str, user: str) -> str:
        key = _digest("complete", system, user)
        if (hit := self.cache.get(key)) is None:
            hit = await self.inner.complete(system, user)
            self.cache.put(key, hit)
        return hit

    async def stream(self, system: str, user: str):
        key = _digest("stream", system, user)
        if (hit := self.cache.get(key)) is not None:
            yield hit
            return
        text = ""
        async for piece in self.inner.stream(system, user):
            text += piece
            yield piece
        self.cache.put(key, text)  # only reached when the stream finished without an error


def eval_llm(s) -> CachedLLM:
    from app.llm import GroqLLM

    safe = "".join(c if c.isalnum() else "-" for c in s.groq_model)
    return CachedLLM(
        GroqLLM(s.groq_api_key, s.groq_model, PATIENT), JsonlCache(CACHE / f"llm-{safe}.jsonl")
    )


def _already_ingested(db_url: str) -> bool:
    """True when the eval database exists and already holds every PDF now in data/samples
    (other owners' documents, like the injection test's, do not matter: queries are scoped)."""
    want = {hashlib.sha256(p.read_bytes()).hexdigest() for p in sample_pdfs()}
    try:
        with psycopg.connect(db_url) as conn:
            have = {r[0] for r in conn.execute("SELECT sha256 FROM documents")}
    except psycopg.Error:
        return False
    return want <= have


async def prepare(provider: str, reuse: bool = False):
    """Recreate the eval database and ingest data/samples/*.pdf (or, with reuse, keep an
    existing one that already holds those files). Returns (settings, pool, embedder)."""
    os.environ["EMBEDDING_PROVIDER"] = provider
    base = os.environ.get("DATABASE_URL", "postgresql://lexio:lexio@localhost:5433/lexio")
    admin = base.rsplit("/", 1)[0] + "/postgres"
    eval_db = f"{EVAL_DB}_{provider}"  # per provider, so runs for different providers can overlap
    os.environ["DATABASE_URL"] = base.rsplit("/", 1)[0] + f"/{eval_db}"

    from app.config import get_settings
    from app.db import apply_migrations, open_pool
    from app.embeddings import build_embedder
    from app.ingest import ingest_pdf

    s = get_settings()
    keep = reuse and _already_ingested(s.database_url)
    if not keep:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f"DROP DATABASE IF EXISTS {eval_db} WITH (FORCE)")
            conn.execute(f"CREATE DATABASE {eval_db}")
    apply_migrations(s.database_url)
    pool = await open_pool(s.database_url)
    model = s.gemini_embedding_model if provider == "gemini" else s.local_embedding_model
    safe = "".join(c if c.isalnum() else "-" for c in f"{provider}-{model}-{s.embedding_dim}")
    embedder = CachedEmbedder(
        build_embedder(s, PATIENT), JsonlCache(CACHE / f"embeddings-{safe}.jsonl")
    )

    if keep:
        print(f"reusing {eval_db} (already holds the {len(sample_pdfs())} PDFs)")
        return s, pool, embedder
    t0 = time.perf_counter()
    for pdf in sample_pdfs():
        r = await ingest_pdf(
            pool, embedder, owner_id="eval", filename=pdf.name, data=pdf.read_bytes(),
            chunk_chars=s.chunk_chars, overlap=s.chunk_overlap_chars,
        )
        print(f"ingested {pdf.name}: {r.page_count} pages, {r.chunk_count} chunks")
    print(f"ingest took {time.perf_counter() - t0:.1f}s")
    return s, pool, embedder
