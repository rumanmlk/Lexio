"""The eval datasets must stay true to the PDFs: each gold page really contains its evidence."""

import functools
import json
import re

from app.ingest import extract_pages
from evals.common import DATASET, SAMPLES, sample_pdfs
from evals.common import FOLLOWUPS as FOLLOWUPS_FILE

ITEMS = json.loads(DATASET.read_text(encoding="utf-8"))
FOLLOWUPS = json.loads(FOLLOWUPS_FILE.read_text(encoding="utf-8"))


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


@functools.cache
def pages(doc: str) -> list[str]:
    return [_squash(t) for t in extract_pages((SAMPLES / doc).read_bytes())]


def _check_gold(items) -> None:
    for it in items:
        found = [n for n, text in enumerate(pages(it["doc"]), start=1) if it["evidence"] in text]
        assert found == it["gold_pages"], (it["id"], it["evidence"], found)


def test_gold_pages_match_evidence_exactly():
    _check_gold(i for i in ITEMS if i["answerable"])


def test_followup_gold_pages_match_evidence_exactly():
    _check_gold(FOLLOWUPS)
    assert all(it["history"] and it["history"][0]["role"] == "user" for it in FOLLOWUPS)


def test_near_miss_questions_really_are_absent_from_the_documents():
    """A near-miss asks for a figure the documents never give; guard the topic words so a
    future edit cannot turn one into an answerable question by accident."""
    text = " ".join(t for pdf in sample_pdfs() for t in pages(pdf.name))
    for phrase in ("minimumwage", "legalageofmarriage", "compensationmust", "daysofpaid"):
        assert phrase not in text


def test_every_sample_pdf_has_a_question_and_every_question_a_pdf():
    docs = {i["doc"] for i in ITEMS if i["answerable"]}
    assert docs == {p.name for p in sample_pdfs()}


def test_dataset_has_all_kinds_and_unique_ids():
    ids = [i["id"] for i in ITEMS] + [i["id"] for i in FOLLOWUPS]
    assert len(set(ids)) == len(ids)
    assert any(not i["answerable"] and "kind" not in i for i in ITEMS)  # out of scope
    assert any(i.get("kind") == "near_miss" for i in ITEMS)
    assert any(i["answerable"] for i in ITEMS)
