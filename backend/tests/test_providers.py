"""Provider failures: retries, and the clear errors a client gets when Gemini or Groq misbehave.
No network: respx intercepts httpx."""

import httpx
import pytest
import respx

from app.embeddings import GeminiEmbedder
from app.errors import ProviderError, RetryPolicy
from app.llm import GroqLLM

GEMINI = "https://generativelanguage.googleapis.com/v1beta/models/m:batchEmbedContents"
GROQ = "https://api.groq.com/openai/v1/chat/completions"
OK = httpx.Response(200, json={"embeddings": [{"values": [0.1, 0.2]}]})


EMBED_POLICY = RetryPolicy(attempts=5, backoff=0)
LLM_POLICY = RetryPolicy(attempts=4, backoff=0)


def embedder() -> GeminiEmbedder:
    return GeminiEmbedder("key", "m", 2, EMBED_POLICY)


def llm() -> GroqLLM:
    return GroqLLM("key", "m", LLM_POLICY)


def sse(*pieces: str) -> httpx.Response:
    body = "".join(f'data: {{"choices":[{{"delta":{{"content":"{p}"}}}}]}}\n\n' for p in pieces)
    return httpx.Response(200, text=body + "data: [DONE]\n\n")


async def collect(gen) -> str:
    return "".join([p async for p in gen])


@respx.mock
async def test_gemini_retries_429_then_succeeds():
    route = respx.post(GEMINI).mock(side_effect=[httpx.Response(429), httpx.Response(503), OK])
    assert await embedder().embed_query("q") == [0.1, 0.2]
    assert route.call_count == 3


@respx.mock
async def test_gemini_gives_up_on_persistent_rate_limit_with_503():
    route = respx.post(GEMINI).mock(return_value=httpx.Response(429))
    with pytest.raises(ProviderError) as e:
        await embedder().embed_query("q")
    assert e.value.status == 503 and "rate limit" in e.value.message
    assert route.call_count == EMBED_POLICY.attempts


@respx.mock
async def test_gemini_bad_key_is_502_and_not_retried():
    route = respx.post(GEMINI).mock(return_value=httpx.Response(403, json={"error": "nope"}))
    with pytest.raises(ProviderError) as e:
        await embedder().embed_query("q")
    assert e.value.status == 502 and "API key" in e.value.message
    assert route.call_count == 1


@respx.mock
async def test_gemini_timeout_is_retried_then_503():
    route = respx.post(GEMINI).mock(side_effect=httpx.ReadTimeout("slow"))
    with pytest.raises(ProviderError) as e:
        await embedder().embed_query("q")
    assert e.value.status == 503 and "timed out" in e.value.message
    assert route.call_count == EMBED_POLICY.attempts


@respx.mock
async def test_gemini_malformed_200_is_502():
    respx.post(GEMINI).mock(return_value=httpx.Response(200, json={"unexpected": 1}))
    with pytest.raises(ProviderError) as e:
        await embedder().embed_query("q")
    assert e.value.status == 502


@respx.mock
async def test_error_message_never_contains_the_response_body_or_key():
    respx.post(GEMINI).mock(return_value=httpx.Response(400, text="secret-body key=abc"))
    with pytest.raises(ProviderError) as e:
        await embedder().embed_query("q")
    assert "secret-body" not in e.value.message and "abc" not in e.value.message


@respx.mock
async def test_groq_streams_tokens():
    respx.post(GROQ).mock(return_value=sse("Hel", "lo"))
    assert await collect(llm().stream("s", "u")) == "Hello"


@respx.mock
async def test_groq_retries_429_using_retry_after_before_any_token():
    route = respx.post(GROQ).mock(
        side_effect=[httpx.Response(429, headers={"retry-after": "0"}), sse("ok")]
    )
    assert await collect(llm().stream("s", "u")) == "ok"
    assert route.call_count == 2


@respx.mock
async def test_groq_bad_key_raises_502():
    respx.post(GROQ).mock(return_value=httpx.Response(401))
    with pytest.raises(ProviderError) as e:
        await collect(llm().stream("s", "u"))
    assert e.value.status == 502


@respx.mock
async def test_groq_does_not_retry_after_tokens_were_sent():
    class Half(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'data: {"choices":[{"delta":{"content":"par"}}]}\n\n'
            raise httpx.ReadError("connection dropped")

    route = respx.post(GROQ).mock(return_value=httpx.Response(200, stream=Half()))
    got = []
    with pytest.raises(ProviderError):
        async for piece in llm().stream("s", "u"):
            got.append(piece)
    assert got == ["par"] and route.call_count == 1


@respx.mock
async def test_groq_complete_retries_and_fails_clearly():
    route = respx.post(GROQ).mock(return_value=httpx.Response(500))
    with pytest.raises(ProviderError) as e:
        await llm().complete("s", "u")
    assert e.value.status == 502 and route.call_count == LLM_POLICY.attempts


QUOTA_BODY = {
    "error": {
        "code": 429,
        "details": [{"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "68681s"}],
    }
}


@respx.mock
async def test_gemini_daily_quota_fails_fast_with_the_reset_time():
    route = respx.post(GEMINI).mock(return_value=httpx.Response(429, json=QUOTA_BODY))
    with pytest.raises(ProviderError) as e:
        await embedder().embed_query("q")
    assert e.value.status == 503 and "quota is used up" in e.value.message
    assert "19 hours" in e.value.message and e.value.quota
    assert route.call_count == 1  # no point retrying a daily limit


@respx.mock
async def test_gemini_short_retry_delay_is_honoured_then_succeeds():
    short = {"error": {"details": [{"@type": "x.RetryInfo", "retryDelay": "0s"}]}}
    route = respx.post(GEMINI).mock(side_effect=[httpx.Response(429, json=short), OK])
    assert await embedder().embed_query("q") == [0.1, 0.2]
    assert route.call_count == 2


@respx.mock
async def test_groq_daily_limit_fails_fast():
    route = respx.post(GROQ).mock(
        return_value=httpx.Response(429, headers={"retry-after": "3600"})
    )
    with pytest.raises(ProviderError) as e:
        await collect(llm().stream("s", "u"))
    assert "quota is used up" in e.value.message and "60 minutes" in e.value.message
    assert e.value.quota
    assert route.call_count == 1
