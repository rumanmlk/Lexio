"""Writes app/sample_queries.json: the Gemini query vectors of the suggested sample questions.

Visitors from regions where Google's terms do not allow the Gemini free tier (see
Settings.blocked_countries) may still ask exactly these questions; their vectors come from this
file, so nothing the visitor sends reaches Gemini. Run it after changing SAMPLE_QUESTIONS in the
frontend (lib/samples.ts), with a warm evals cache:  uv run python -m evals.export_sample_queries
"""

import json
import re
from pathlib import Path

from app.config import get_settings
from evals.common import _digest, embedding_cache

ROOT = Path(__file__).resolve().parents[2]
SAMPLES_TS = ROOT / "frontend" / "lib" / "samples.ts"
OUT = Path(__file__).resolve().parents[1] / "app" / "sample_queries.json"


def sample_questions() -> list[str]:
    text = SAMPLES_TS.read_text(encoding="utf-8")
    block = re.search(r"SAMPLE_QUESTIONS = \[(.*?)\];", text, re.S)
    return json.loads("[" + block.group(1).rstrip().rstrip(",") + "]")


def main() -> None:
    s = get_settings()
    cache = embedding_cache(s, "gemini")
    out = {}
    for q in sample_questions():
        vec = cache.get("Q" + _digest(q))
        if vec is None:
            raise SystemExit(f"No cached vector for: {q!r}. Run the evals (or ask it once) first.")
        out[q] = [round(x, 6) for x in vec]
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(out)} vectors to {OUT}")


if __name__ == "__main__":
    main()
