"""The eval dataset must stay true to the PDFs: each gold page really contains its evidence."""

import json
import re
from pathlib import Path

from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[2]
ITEMS = json.loads((ROOT / "backend" / "evals" / "dataset.json").read_text(encoding="utf-8"))


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def test_gold_pages_match_evidence_exactly():
    cache: dict[str, list[str]] = {}
    for it in (i for i in ITEMS if i["answerable"]):
        if it["doc"] not in cache:
            reader = PdfReader(ROOT / "data" / "samples" / it["doc"])
            cache[it["doc"]] = [_squash(p.extract_text() or "") for p in reader.pages]
        pages = cache[it["doc"]]
        found = [n for n, text in enumerate(pages, start=1) if it["evidence"] in text]
        assert found == it["gold_pages"], (it["id"], it["evidence"], found)


def test_dataset_has_both_kinds_and_unique_ids():
    assert len({i["id"] for i in ITEMS}) == len(ITEMS)
    assert any(not i["answerable"] for i in ITEMS) and any(i["answerable"] for i in ITEMS)
