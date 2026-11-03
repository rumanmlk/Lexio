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


def _results(**over):
    base = {
        "answerable": [{"grounded": True}] * 9 + [{"grounded": False}],
        "out_of_scope": [{"ok": True}],
        "injection": [{"obeyed": False}],
    }
    return {**base, **over}


def test_answer_eval_verdict_fails_ci_only_when_asked_and_only_for_real_problems():
    from evals.answers import verdict

    assert verdict(_results(), None, strict=False, min_grounded=None) == 0
    assert verdict(_results(), None, strict=True, min_grounded=0.9) == 0
    assert verdict(_results(), None, strict=False, min_grounded=0.95) == 1  # 90% < 95%
    answered = _results(out_of_scope=[{"ok": False}])
    assert verdict(answered, None, strict=False, min_grounded=None) == 0  # not asked to check
    assert verdict(answered, None, strict=True, min_grounded=None) == 1
    obeyed = _results(injection=[{"obeyed": True}])
    assert verdict(obeyed, None, strict=True, min_grounded=None) == 1
    # Groq stopped it half way: a strict run proves nothing, a plain run is just a partial report
    assert verdict(_results(), "quota", strict=True, min_grounded=None) == 1
    assert verdict(_results(), "quota", strict=False, min_grounded=None) == 0


def test_wilson_interval_matches_known_values_and_stays_inside_0_to_1():
    from evals.common import wilson

    lo, hi = wilson(68, 73)  # the answer eval's grounded rate: 93%
    assert (round(lo, 3), round(hi, 3)) == (0.849, 0.970)
    assert wilson(0, 10)[0] == 0.0 and round(wilson(0, 10)[1], 3) == 0.278
    assert wilson(10, 10)[1] == 1.0 and round(wilson(10, 10)[0], 3) == 0.722
    assert wilson(0, 0) == (0.0, 1.0)


def test_share_formats_a_rate_with_its_interval():
    from evals.common import share

    assert share(68, 73) == "93% (68/73, 95% CI 85%-97%)"
    assert share(0, 0) == "not run yet"


def test_bootstrap_intervals_cover_the_mean_and_shrink_with_more_questions():
    from evals.common import bootstrap_ci, paired_diff_ci

    few = [1.0, 0.0] * 10
    many = [1.0, 0.0] * 200
    (lo1, hi1), (lo2, hi2) = bootstrap_ci(few), bootstrap_ci(many)
    assert lo1 < 0.5 < hi1 and lo2 < 0.5 < hi2
    assert (hi2 - lo2) < (hi1 - lo1)
    assert bootstrap_ci(few) == bootstrap_ci(few)  # seeded: the same report every time
    d, lo, hi = paired_diff_ci([1.0, 1.0, 1.0, 1.0], [0.0, 1.0, 1.0, 1.0])
    assert d == 0.25 and lo <= d <= hi
    same, lo, hi = paired_diff_ci([0.5, 1.0, 0.0], [0.5, 1.0, 0.0])
    assert same == 0.0 and lo == 0.0 == hi  # identical modes: no difference at all
