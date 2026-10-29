import asyncio
import json
from collections.abc import AsyncIterator
from typing import Protocol

import httpx

from app.errors import ProviderError, RetryPolicy, from_exception, retry_delay

NAME = "Groq"


class LLM(Protocol):
    def stream(self, system: str, user: str) -> AsyncIterator[str]: ...
    async def complete(self, system: str, user: str) -> str: ...


class GroqLLM:
    """Groq's OpenAI-compatible chat endpoint. gpt-oss reasons in a separate field, so
    delta.content is already the clean answer (no <think> stripping needed)."""

    def __init__(self, api_key: str, model: str, policy: RetryPolicy | None = None):
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is not set")
        self.model = model
        self.policy = policy or RetryPolicy()
        self.client = httpx.AsyncClient(
            base_url="https://api.groq.com/openai/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(60, connect=10),
        )

    def _body(self, system: str, user: str, stream: bool) -> dict:
        return {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0.1,
            "max_completion_tokens": 1500,
            "reasoning_effort": "low",
            "stream": stream,
        }

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        body = self._body(system, user, True)
        started = False  # once tokens went out, a retry would repeat them
        for attempt in range(self.policy.attempts):
            try:
                async with self.client.stream("POST", "/chat/completions", json=body) as resp:
                    if resp.status_code >= 400:
                        await resp.aread()
                        resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data: "):
                            continue
                        payload = line[6:]
                        if payload == "[DONE]":
                            return
                        delta = json.loads(payload)["choices"][0]["delta"].get("content")
                        if delta:
                            started = True
                            yield delta
                    return
            except (KeyError, IndexError, ValueError) as exc:  # malformed stream chunk
                raise ProviderError(502, f"{NAME} returned an unexpected response.") from exc
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                delay = None if started else retry_delay(exc, attempt, self.policy)
                if delay is None or attempt == self.policy.attempts - 1:
                    raise from_exception(NAME, exc) from exc
                await asyncio.sleep(delay)

    async def complete(self, system: str, user: str) -> str:
        body = self._body(system, user, False)
        for attempt in range(self.policy.attempts):
            try:
                resp = await self.client.post("/chat/completions", json=body)
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"] or ""
            except (KeyError, IndexError, ValueError) as exc:
                raise ProviderError(502, f"{NAME} returned an unexpected response.") from exc
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                delay = retry_delay(exc, attempt, self.policy)
                if delay is None or attempt == self.policy.attempts - 1:
                    raise from_exception(NAME, exc) from exc
                await asyncio.sleep(delay)
