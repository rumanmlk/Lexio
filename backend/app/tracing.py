"""Optional Langfuse tracing of /api/chat. Off unless LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY
are set.

It talks to Langfuse's HTTP ingestion endpoint directly and sends one batch after the answer has
finished, from inside the request. The Langfuse SDK batches in a background thread, which a
serverless instance can freeze before it flushes. A failing or slow Langfuse never affects the chat:
the send has a short timeout and every error is swallowed.

By default a trace holds only numbers and flags (timings, counts, similarity, whether the answer was
grounded or refused) and a salted visitor hash. The question, the retrieved passages and the answer
come from users' private documents, so they are included only with LANGFUSE_CAPTURE_CONTENT=true."""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import httpx

from app import rag
from app.config import Settings

log = logging.getLogger(__name__)

SEND_TIMEOUT = 3.0
_client: httpx.AsyncClient | None = None


def _iso(unix_seconds: float) -> str:
    return datetime.fromtimestamp(unix_seconds, UTC).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=SEND_TIMEOUT)
    return _client


class Trace:
    def __init__(self, s: Settings, name: str, user_key: str, metadata: dict):
        self.s = s
        self.id = uuid.uuid4().hex
        self.name = name
        self.user_key = user_key
        self.metadata = dict(metadata)
        self.started = time.monotonic()
        self.started_at = _iso(time.time())
        self.events: list[dict] = []
        self.content = s.langfuse_capture_content
        self.input: str | None = None
        self.output: str | None = None

    def observe(self, kind: str, name: str, started_at: str, ended_at: str, **fields) -> None:
        """kind: "span" or "generation"."""
        self.events.append({
            "id": uuid.uuid4().hex,
            "type": f"{kind}-create",
            "timestamp": ended_at,
            "body": {"id": uuid.uuid4().hex, "traceId": self.id, "name": name,
                     "startTime": started_at, "endTime": ended_at, **fields},
        })

    def timed(self, kind: str, name: str, seconds: float, **fields) -> None:
        """Record something that just finished and took `seconds`."""
        end = time.time()
        self.observe(kind, name, _iso(end - seconds), _iso(end), **fields)

    async def send(self) -> None:
        body = {
            "id": self.id,
            "name": self.name,
            "timestamp": self.started_at,
            "userId": self.user_key,
            "metadata": {
                **self.metadata,
                "total_ms": round((time.monotonic() - self.started) * 1000),
            },
            "tags": ["lexio"],
        }
        if self.content:
            body["input"], body["output"] = self.input, self.output
        batch = [{"id": uuid.uuid4().hex, "type": "trace-create", "timestamp": self.started_at,
                  "body": body}, *self.events]
        try:
            resp = await _http().post(
                f"{self.s.langfuse_host.rstrip('/')}/api/public/ingestion",
                json={"batch": batch},
                auth=(self.s.langfuse_public_key, self.s.langfuse_secret_key),
            )
            if resp.status_code >= 300:  # 207 carries per-item errors in its body
                log.warning("langfuse answered %s", resp.status_code)
            elif resp.status_code == 207 and (errors := resp.json().get("errors")):
                log.warning("langfuse rejected %d event(s)", len(errors))
        except Exception:  # noqa: BLE001 - tracing must never break a chat
            log.warning("could not send trace to langfuse", exc_info=True)


def enabled(s: Settings) -> bool:
    return bool(s.langfuse_public_key and s.langfuse_secret_key)


def start(s: Settings, name: str, user_key: str, **metadata) -> Trace | None:
    return Trace(s, name, user_key, metadata) if enabled(s) else None


async def traced(
    stream: AsyncIterator[str], trace: Trace | None, s: Settings
) -> AsyncIterator[str]:
    """Pass the SSE stream through, noting when the first text arrived and how it ended, then
    send the trace. With tracing off this is the stream itself."""
    if trace is None:
        async for chunk in stream:
            yield chunk
        return
    began = time.monotonic()
    first: float | None = None
    outcome: dict = {"outcome": "interrupted"}
    text = ""
    try:
        async for chunk in stream:
            if chunk.startswith("event: token"):
                if first is None:
                    first = time.monotonic() - began
                if trace.content:
                    text += rag.parse_sse(chunk)[1].get("text", "")
            elif chunk.startswith("event: done"):
                done = rag.parse_sse(chunk)[1]
                outcome = {"outcome": "refused" if done.get("refused") else "answered",
                           "grounded": done.get("grounded"), "cited": len(done.get("cited", []))}
            elif chunk.startswith("event: error"):
                outcome = {"outcome": "error", "quota": rag.parse_sse(chunk)[1].get("quota")}
            yield chunk
    finally:
        first_ms = None if first is None else round(first * 1000)
        trace.timed("generation", "answer", time.monotonic() - began, model=s.groq_model,
                    metadata={**outcome, "first_token_ms": first_ms})
        trace.metadata.update(outcome)
        trace.output = text or None
        try:
            await asyncio.wait_for(trace.send(), SEND_TIMEOUT + 1)
        except Exception:  # noqa: BLE001 - a slow or broken Langfuse must not touch the chat
            log.warning("trace not sent", exc_info=True)
