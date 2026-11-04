"""Do out-of-scope questions still get refused when search has no similarity gate?

Visitors from regions without Gemini access are served by keyword search plus an LLM-written
passage (see chat() in app/main.py), so the usual embedding-similarity refusal gate cannot apply.
This runs the out-of-scope questions through that pipeline with the real LLM.

    uv run python -m evals.blocked_refusal       # needs GROQ_API_KEY; about 17k tokens
"""

import asyncio
import json
import sys

from evals import answers
from evals.common import DATASET, eval_llm, prepare


async def main() -> int:
    sys.stdout.reconfigure(errors="replace")
    answers.NO_GEMINI = True
    s, pool, embedder = await prepare("gemini", reuse=True)
    llm = eval_llm(s)
    items = [i for i in json.loads(DATASET.read_text(encoding="utf-8"))
             if not i["answerable"] and i.get("kind") != "near_miss"]
    refused = 0
    for it in items:
        r = await answers.ask(pool, embedder, llm, s, it["question"])
        if r["error"]:
            print(f"  {it['id']}: LLM error: {r['error']}")
            return 1
        ok = not r["done"]["grounded"]
        refused += ok
        print(f"  {it['id']}: {'refused' if ok else 'ANSWERED'}: {r['text'].strip()[:160]!r}")
    print(f"\nrefused {refused} of {len(items)} out-of-scope questions without the similarity gate")
    await pool.close()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
