from app.embeddings import HashEmbedder
from app.ingest import chunk_pages, normalize
from app.rag import REFUSAL, build_user_prompt, cited_numbers, should_refuse
from app.retrieval import Hit, Retrieval, or_query, rrf


def test_normalize_joins_soft_wraps_and_hyphenation():
    raw = "The par-\nties agree\nto the terms.\n\nSecond   paragraph."
    assert normalize(raw) == "The parties agree to the terms.\n\nSecond paragraph."


def test_chunks_never_cross_pages_and_respect_size():
    pages = ["Alpha. " * 200, "", "Beta. " * 50]
    chunks = chunk_pages(pages, size=300, overlap=40)
    assert {c.page for c in chunks} == {1, 3}  # blank page 2 is skipped
    assert all(len(c.content) <= 300 + 40 + 1 for c in chunks)
    assert all("Beta" not in c.content for c in chunks if c.page == 1)


def test_short_page_is_a_single_chunk_without_overlap_tail():
    chunks = chunk_pages(["One short page."], size=1200, overlap=150)
    assert [c.content for c in chunks] == ["One short page."]


def test_rrf_rewards_agreement_between_rankings():
    scores = rrf([[1, 2, 3], [4, 2, 5]])
    assert max(scores, key=scores.__getitem__) == 2  # rank 2 in both beats rank 1 in only one
    assert scores[5] < scores[2] and scores[3] < scores[2]


def test_or_query_dedupes_and_strips_punctuation():
    assert or_query("What is a child? A child, a child!") == "what | is | a | child"
    assert or_query("???") == ""


def test_cited_numbers_ignores_out_of_range_and_duplicates():
    assert cited_numbers("See [1], [3][1] and [9].", n_sources=3) == [1, 3]
    assert cited_numbers("no citations", n_sources=3) == []


def _hit() -> Hit:
    return Hit(1, "00000000-0000-0000-0000-000000000000", "a.pdf", 4, "text", 0.03)


def test_should_refuse_only_when_no_keyword_and_weak_similarity():
    assert should_refuse(Retrieval([], 0.0, False), 0.5)
    assert should_refuse(Retrieval([_hit()], 0.3, False), 0.5)
    assert not should_refuse(Retrieval([_hit()], 0.3, True), 0.5)
    assert not should_refuse(Retrieval([_hit()], 0.8, False), 0.5)


def test_prompt_numbers_sources_from_one():
    prompt = build_user_prompt("Why?", [_hit(), _hit()])
    assert "[1] (a.pdf, page 4)" in prompt and "[2] (a.pdf, page 4)" in prompt
    assert prompt.endswith("Question: Why?")
    assert "can't find" in REFUSAL


async def test_hash_embedder_is_deterministic_and_normalized():
    e = HashEmbedder(768)
    a, b = await e.embed_query("freedom of speech"), await e.embed_query("freedom of speech")
    assert a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-4
