"""Retrieval evaluation: does the right page come back, and do we refuse when we should?

    uv run python -m evals.run --provider local          # offline, no API key
    uv run python -m evals.run --provider gemini         # what production uses

Ingests data/samples/*.pdf into a throwaway database, then scores vector-only, keyword-only
and hybrid retrieval against evals/dataset.json. Writes evals/results/<provider>.md.
"""

import argparse
import asyncio
import json
import os
import statistics
import time
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[2]
DATASET = Path(__file__).parent / "dataset.json"
RESULTS = Path(__file__).parent / "results"
KS = (1, 3, 6)


def score_item(hits, gold_doc: str, gold_pages: set[int]) -> int | None:
    """1-based rank of the first hit on a gold page of the gold document, else None."""
    for rank, h in enumerate(hits, start=1):
        if h.filename == gold_doc and h.page in gold_pages:
            return rank
    return None


async def main(provider: str, sweep: bool) -> None:
    os.environ["EMBEDDING_PROVIDER"] = provider
    base = os.environ.get("DATABASE_URL", "postgresql://lexio:lexio@localhost:5433/lexio")
    admin, eval_db = base.rsplit("/", 1)[0] + "/postgres", "lexio_eval"
    os.environ["DATABASE_URL"] = base.rsplit("/", 1)[0] + f"/{eval_db}"

    from app.config import get_settings
    from app.db import apply_migrations, open_pool
    from app.embeddings import build_embedder
    from app.ingest import ingest_pdf
    from app.retrieval import retrieve

    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {eval_db} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {eval_db}")
    s = get_settings()
    apply_migrations(s.database_url)
    pool = await open_pool(s.database_url)
    embedder = build_embedder(s)

    t0 = time.perf_counter()
    for pdf in sorted((ROOT / "data" / "samples").glob("*.pdf")):
        r = await ingest_pdf(
            pool, embedder, owner_id="eval", filename=pdf.name, data=pdf.read_bytes(),
            chunk_chars=s.chunk_chars, overlap=s.chunk_overlap_chars,
        )
        print(f"ingested {pdf.name}: {r.page_count} pages, {r.chunk_count} chunks")
    print(f"ingest took {time.perf_counter() - t0:.1f}s")

    items = json.loads(DATASET.read_text(encoding="utf-8"))
    answerable = [i for i in items if i["answerable"]]
    unanswerable = [i for i in items if not i["answerable"]]

    rows, sims = [], {"answerable": [], "unanswerable": []}
    for mode in ("vector", "keyword", "hybrid"):
        ranks, latencies = [], []
        for it in answerable:
            t = time.perf_counter()
            res = await retrieve(pool, embedder, it["question"], owner_id="eval", mode=mode,
                                 candidates=s.retrieve_candidates, top_k=max(KS))
            latencies.append(time.perf_counter() - t)
            ranks.append(score_item(res.hits, it["doc"], set(it["gold_pages"])))
            if mode == "hybrid":
                sims["answerable"].append((res.top_similarity, res.has_keyword_match))
        hit = {k: sum(1 for r in ranks if r and r <= k) / len(ranks) for k in KS}
        mrr = sum(1 / r for r in ranks if r) / len(ranks)
        rows.append((mode, hit, mrr, statistics.median(latencies) * 1000))

    for it in unanswerable:
        res = await retrieve(pool, embedder, it["question"], owner_id="eval", mode="hybrid",
                             candidates=s.retrieve_candidates, top_k=max(KS))
        sims["unanswerable"].append((res.top_similarity, res.has_keyword_match))

    def refusal(pairs, thr):
        return sum(1 for sim, kw in pairs if not kw and sim < thr) / max(len(pairs), 1)

    lines = [
        f"# Retrieval eval: `{provider}` embeddings",
        "",
        f"{len(answerable)} answerable + {len(unanswerable)} unanswerable questions over "
        f"{len(list((ROOT / 'data' / 'samples').glob('*.pdf')))} documents. "
        f"Chunk {s.chunk_chars} chars / {s.chunk_overlap_chars} overlap, "
        f"candidates {s.retrieve_candidates}.",
        "",
        "| mode | hit@1 | hit@3 | hit@6 | MRR | median ms |",
        "|---|---|---|---|---|---|",
    ]
    for mode, hit, mrr, ms in rows:
        lines.append(
            f"| {mode} | {hit[1]:.2f} | {hit[3]:.2f} | {hit[6]:.2f} | {mrr:.3f} | {ms:.0f} |"
        )
    lines += [
        "",
        "## Refusal gate (hybrid)",
        "",
        "Refuse when there is no keyword hit and best cosine similarity < threshold.",
        "",
        "| threshold | correctly refused (unanswerable) | wrongly refused (answerable) |",
        "|---|---|---|",
    ]
    thresholds = [0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7] if sweep else [s.min_similarity]
    for thr in thresholds:
        lines.append(
            f"| {thr:.2f} | {refusal(sims['unanswerable'], thr):.0%} "
            f"| {refusal(sims['answerable'], thr):.0%} |"
        )
    out = "\n".join(lines) + "\n"
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{provider}.md").write_text(out, encoding="utf-8")
    print("\n" + out)
    await pool.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["local", "gemini", "hash"], default="local")
    ap.add_argument("--sweep", action="store_true", help="sweep refusal thresholds")
    a = ap.parse_args()
    asyncio.run(main(a.provider, a.sweep))
