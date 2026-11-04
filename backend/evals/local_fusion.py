"""Would a local embedding model add to keyword search + LLM passage for visitors without Gemini?

Fuses rankings with reciprocal rank fusion: keyword(question), keyword(LLM-written passage), and the
vector search of a local model (bge-base) on the question and on the passage. Reuses the cached
Groq passages and bge vectors, so it costs nothing.

    uv run python -m evals.local_fusion
"""

import asyncio
import json
import sys

from app.rag import PASSAGE_PROMPT
from app.retrieval import retrieve, rrf
from evals.common import DATASET, eval_llm, paired_diff_ci, prepare
from evals.run import KS, score_item


async def main() -> int:
    s, pool, embedder = await prepare("local", reuse=True)
    llm = eval_llm(s)
    items = [i for i in json.loads(DATASET.read_text(encoding="utf-8")) if i["answerable"]]

    async def ranked(text: str, mode: str):
        res = await retrieve(pool, embedder, text, owners=["eval"], mode=mode,
                             candidates=s.retrieve_candidates, top_k=30)
        return res.hits

    combos = {
        "keyword(question) + keyword(passage)  [what is deployed]": ("kq", "kp"),
        "local vectors(question) + keyword(question)  [local hybrid]": ("vq", "kq"),
        "vectors(question) + keyword(question) + keyword(passage)": ("vq", "kq", "kp"),
        "vectors(question) + vectors(passage) + keyword(question) + keyword(passage)":
            ("vq", "vp", "kq", "kp"),
        "vectors(passage) + keyword(question) + keyword(passage)": ("vp", "kq", "kp"),
    }
    ranks = {name: [] for name in combos}
    for it in items:
        q = it["question"]
        p = (await llm.complete(PASSAGE_PROMPT, f"Question: {q}")).strip()
        lists = {"kq": await ranked(q, "keyword"), "kp": await ranked(p, "keyword"),
                 "vq": await ranked(q, "vector"), "vp": await ranked(p, "vector")}
        by_id = {h.chunk_id: h for lst in lists.values() for h in lst}
        for name, keys in combos.items():
            scores = rrf([[h.chunk_id for h in lists[k]] for k in keys])
            top = sorted(scores, key=scores.__getitem__, reverse=True)[: max(KS)]
            ranks[name].append(score_item([by_id[c] for c in top], it["doc"],
                                          set(it["gold_pages"])))
    n = len(items)
    print("| search | hit@1 | hit@3 | hit@6 | MRR |\n|---|---|---|---|---|")
    rr = {}
    for name, rk in ranks.items():
        rr[name] = [1 / r if r else 0.0 for r in rk]
        hit = {k: sum(1 for r in rk if r and r <= k) / n for k in KS}
        print(f"| {name} | {hit[1]:.2f} | {hit[3]:.2f} | {hit[6]:.2f} | {sum(rr[name]) / n:.3f} |")
    base = rr[next(iter(combos))]
    print()
    for name in list(combos)[1:]:
        d, lo, hi = paired_diff_ci(rr[name], base)
        print(f"- {name} minus deployed: MRR {d:+.3f} (95% CI {lo:+.3f} to {hi:+.3f})")
    await pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
