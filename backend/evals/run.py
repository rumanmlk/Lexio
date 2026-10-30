"""Retrieval evaluation: does the right page come back, and do we refuse when we should?

    uv run python -m evals.run --provider local          # offline, no API key
    uv run python -m evals.run --provider gemini         # what production uses

Ingests data/samples/*.pdf into a throwaway database, then scores vector-only, keyword-only
and hybrid retrieval against evals/dataset.json. Writes evals/results/<provider>.md.
"""

import argparse
import asyncio
import json
import statistics
import sys
import time

from evals.common import DATASET, RESULTS, prepare, sample_pdfs

KS = (1, 3, 6)


def score_item(hits, gold_doc: str, gold_pages: set[int]) -> int | None:
    """1-based rank of the first hit on a gold page of the gold document, else None."""
    for rank, h in enumerate(hits, start=1):
        if h.filename == gold_doc and h.page in gold_pages:
            return rank
    return None


async def main(
    provider: str, sweep: bool, reuse: bool, min_mrr: float | None = None
) -> int:
    s, pool, embedder = await prepare(provider, reuse)
    from app.retrieval import retrieve

    items = json.loads(DATASET.read_text(encoding="utf-8"))
    answerable = [i for i in items if i["answerable"]]
    # Near-miss questions are on-topic, so no similarity threshold can separate them; the
    # answer eval covers those. The gate is tested on clearly out-of-scope questions.
    unanswerable = [i for i in items if not i["answerable"] and i.get("kind") != "near_miss"]

    t0 = time.perf_counter()
    for it in items:  # warm the cache so every mode's timing excludes the embedding call
        await embedder.embed_query(it["question"])
    print(f"embedded {len(items)} questions in {time.perf_counter() - t0:.1f}s")

    rows, sims = [], {"answerable": [], "unanswerable": []}
    configs = [
        ("vector", "vector", 1.0),
        ("keyword", "keyword", 1.0),
        ("hybrid, keyword weight 1.0", "hybrid", 1.0),
        ("hybrid, keyword weight 0.5", "hybrid", 0.5),
        ("hybrid, keyword weight 0.25", "hybrid", 0.25),
    ]
    for label, mode, weight in configs:
        ranks, latencies = [], []
        for it in answerable:
            t = time.perf_counter()
            res = await retrieve(pool, embedder, it["question"], owners=["eval"], mode=mode,
                                 candidates=s.retrieve_candidates, top_k=max(KS),
                                 keyword_weight=weight)
            latencies.append(time.perf_counter() - t)
            ranks.append(score_item(res.hits, it["doc"], set(it["gold_pages"])))
            if label == "vector":  # top_similarity is the vector side's, whatever the fusion
                sims["answerable"].append((res.top_similarity, res.has_keyword_match))
        hit = {k: sum(1 for r in ranks if r and r <= k) / len(ranks) for k in KS}
        mrr = sum(1 / r for r in ranks if r) / len(ranks)
        rows.append((label, hit, mrr, statistics.median(latencies) * 1000))

    for it in unanswerable:
        res = await retrieve(pool, embedder, it["question"], owners=["eval"], mode="hybrid",
                             candidates=s.retrieve_candidates, top_k=max(KS))
        sims["unanswerable"].append((res.top_similarity, res.has_keyword_match))

    def refusal(pairs, thr, use_keywords):
        n = sum(1 for sim, kw in pairs if sim < thr and not (use_keywords and kw))
        return n / max(len(pairs), 1)

    lines = [
        f"# Retrieval eval: `{provider}` embeddings",
        "",
        f"{len(answerable)} answerable + {len(unanswerable)} unanswerable questions over "
        f"{len(sample_pdfs())} documents. "
        f"Chunk {s.chunk_chars} chars / {s.chunk_overlap_chars} overlap, "
        f"candidates {s.retrieve_candidates}.",
        "",
        "| mode | hit@1 | hit@3 | hit@6 | MRR | median ms (database only) |",
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
        "`sim-only` refuses when the best cosine similarity is below the threshold. "
        "`sim+keyword` additionally requires zero keyword hits, so any OR-matched term "
        "disables refusal.",
        "",
        "| threshold | sim-only: refused unanswerable | sim-only: wrongly refused "
        "| sim+keyword: refused unanswerable | sim+keyword: wrongly refused |",
        "|---|---|---|---|---|",
    ]
    thresholds = [0.3, 0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7] if sweep else [s.min_similarity]
    ua, an = sims["unanswerable"], sims["answerable"]
    for thr in thresholds:
        lines.append(
            f"| {thr:.2f} | {refusal(ua, thr, False):.0%} | {refusal(an, thr, False):.0%} "
            f"| {refusal(ua, thr, True):.0%} | {refusal(an, thr, True):.0%} |"
        )
    lines += ["", "Best cosine similarity per question (hybrid):", ""]
    for label, pairs in (("answerable", an), ("unanswerable", ua)):
        vals = sorted(round(x, 3) for x, _ in pairs)
        lines.append(f"- {label}: min {vals[0]}, median {vals[len(vals) // 2]}, max {vals[-1]}")
    with_kw = sum(1 for _, k in ua if k)
    lines.append(f"- unanswerable questions with a keyword hit: {with_kw}/{len(ua)}")
    out = "\n".join(lines) + "\n"
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / f"{provider}.md").write_text(out, encoding="utf-8", newline="\n")
    print("\n" + out)
    await pool.close()
    default = next(mrr for label, _, mrr, _ in rows if label == "hybrid, keyword weight 1.0")
    if min_mrr is not None and default < min_mrr:
        print(f"FAIL: hybrid MRR {default:.3f} is below the floor {min_mrr:.3f}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["local", "gemini", "hash"], default="local")
    ap.add_argument("--sweep", action="store_true", help="sweep refusal thresholds")
    ap.add_argument("--reuse", action="store_true", help="keep the ingested eval database")
    ap.add_argument("--min-mrr", type=float, default=None,
                    help="exit 1 when the default hybrid MRR is below this (for CI)")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.provider, a.sweep, a.reuse, a.min_mrr)))
