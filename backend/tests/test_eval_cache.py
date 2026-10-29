"""The eval caches spend a free-tier quota exactly once per piece of work."""

import pytest

from app.errors import ProviderError
from evals.common import CachedEmbedder, CachedLLM, JsonlCache


def test_jsonl_cache_persists_across_instances(tmp_path):
    path = tmp_path / "c.jsonl"
    first = JsonlCache(path)
    first.put("a", [1.0, 2.0])
    first.put("b", "text")
    again = JsonlCache(path)
    assert again.get("a") == [1.0, 2.0] and again.get("b") == "text" and again.get("c") is None
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2  # appended, never rewritten


class CountingEmbedder:
    def __init__(self):
        self.docs, self.queries = [], []

    async def embed_documents(self, texts):
        self.docs += texts
        return [[float(len(t))] for t in texts]

    async def embed_query(self, text):
        self.queries.append(text)
        return [1.0]


async def test_embeddings_are_bought_once_even_across_runs(tmp_path):
    inner = CountingEmbedder()
    path = tmp_path / "e.jsonl"
    e = CachedEmbedder(inner, JsonlCache(path))
    assert await e.embed_documents(["aa", "bbb", "aa"]) == [[2.0], [3.0], [2.0]]
    await e.embed_query("q")
    await e.embed_query("q")
    later = CachedEmbedder(inner, JsonlCache(path))  # a new process, same files
    await later.embed_documents(["bbb", "aa"])
    await later.embed_query("q")
    assert inner.docs == ["aa", "bbb"] and inner.queries == ["q"]


class FlakyLLM:
    def __init__(self, fail_after: int | None = None):
        self.fail_after, self.calls = fail_after, 0

    async def complete(self, system, user):
        self.calls += 1
        return f"{system}|{user}"

    async def stream(self, system, user):
        self.calls += 1
        for i, piece in enumerate(["a", "b", "c"]):
            if self.fail_after is not None and i == self.fail_after:
                raise ProviderError(503, "quota", True)
            yield piece


async def test_llm_answers_are_cached_by_exact_prompt(tmp_path):
    inner = FlakyLLM()
    llm = CachedLLM(inner, JsonlCache(tmp_path / "l.jsonl"))
    assert [p async for p in llm.stream("s", "u")] == ["a", "b", "c"]
    assert [p async for p in llm.stream("s", "u")] == ["abc"]  # replayed whole, no new call
    assert await llm.complete("s", "u") == "s|u" and await llm.complete("s", "u") == "s|u"
    assert [p async for p in llm.stream("s", "other")] == ["a", "b", "c"]
    assert inner.calls == 3


async def test_a_stream_cut_short_by_the_quota_is_not_cached(tmp_path):
    llm = CachedLLM(FlakyLLM(fail_after=2), JsonlCache(tmp_path / "l.jsonl"))
    with pytest.raises(ProviderError):
        _ = [p async for p in llm.stream("s", "u")]
    assert llm.cache.get(next(iter(llm.cache.data), "")) is None  # nothing was stored
    assert not llm.cache.data
