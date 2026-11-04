"""Optional Langfuse tracing of /api/chat. Off unless LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY
are set.

Langfuse no longer takes trace writes on its old /api/public/ingestion endpoint; traces arrive as
OpenTelemetry spans. This builds those spans by hand (OTLP over HTTP with a JSON body) and sends
one request after the answer has finished, from inside the request, so it needs no OpenTelemetry
package. The OTel SDK batches in a background thread, which a serverless instance can freeze
before it flushes. A failing or slow Langfuse never affects the chat: the send has a short
timeout and every error is swallowed.

By default a trace holds only numbers and flags (timings, counts, similarity, whether the answer was
grounded or refused) and a salted visitor hash. The question, the retrieved passages and the answer
come from users' private documents, so they are included only with LANGFUSE_CAPTURE_CONTENT=true."""

import asyncio
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator

import httpx

from app import rag
from app.config import Settings

log = logging.getLogger(__name__)

SEND_TIMEOUT = 3.0
_client: httpx.AsyncClient | None = None
_sending: set[asyncio.Task] = set()  # keeps an in-flight send alive; the loop holds tasks weakly


def _http() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=SEND_TIMEOUT)
    return _client


def _value(v) -> dict:
    """One OTLP attribute value."""
    if isinstance(v, bool):  # before int: bool is an int
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, str):
        return {"stringValue": v}
    if isinstance(v, list) and all(isinstance(i, str) for i in v):
        return {"arrayValue": {"values": [{"stringValue": i} for i in v]}}
    return {"stringValue": json.dumps(v, default=str)}


def _attributes(d: dict) -> list[dict]:
    return [{"key": k, "value": _value(v)} for k, v in d.items() if v is not None]


def _nanos(unix_seconds: float) -> str:
    return str(int(unix_seconds * 1_000_000_000))


def _observation(kind: str, step: dict) -> dict:
    """The attributes that belong to one span or generation, as opposed to the whole trace."""
    attrs = {"langfuse.observation.type": kind,
             "langfuse.observation.model.name": step.get("model")}
    attrs.update({f"langfuse.observation.metadata.{k}": v
                  for k, v in step.get("metadata", {}).items()})
    for key in ("input", "output"):  # only present when content capture is on
        if step.get(key) is not None:
            attrs[f"langfuse.observation.{key}"] = json.dumps(step[key])
    return attrs


class Trace:
    def __init__(self, s: Settings, name: str, user_key: str, metadata: dict):
        self.s = s
        self.id = uuid.uuid4().hex  # 32 hex characters: an OTel trace id
        self.name = name
        self.user_key = user_key
        self.metadata = dict(metadata)
        self.started_at = time.time()
        self._mono0 = time.monotonic()
        self.steps: list[dict] = []
        self.content = s.langfuse_capture_content
        self.input: str | None = None
        self.output: str | None = None

    def _now(self) -> float:
        """Unix time that cannot jump: the wall clock read once at the start plus monotonic
        elapsed time. A clock adjustment mid-request then cannot give a negative duration or a
        step that ends after the trace does."""
        return self.started_at + (time.monotonic() - self._mono0)

    def timed(self, kind: str, name: str, seconds: float, *, model: str | None = None,
              metadata: dict | None = None, input=None, output=None) -> None:
        """Record a step that just finished and took `seconds`. kind: "span" or "generation".
        `input` and `output` are kept only when content capture is on."""
        end = self._now()
        self.steps.append({"kind": kind, "name": name, "start": end - seconds, "end": end,
                           "model": model, "metadata": metadata or {},
                           **({"input": input, "output": output} if self.content else {})})

    def payload(self) -> dict:
        end = self._now()
        # Trace-level fields go on every span so each one can be filtered by them. They are
        # encoded once here and shared.
        shared = _attributes({
            "langfuse.trace.name": self.name,
            "langfuse.user.id": self.user_key,
            "langfuse.trace.tags": ["lexio"],
            **{f"langfuse.trace.metadata.{k}": v for k, v in {
                **self.metadata, "total_ms": round((end - self.started_at) * 1000)}.items()},
        })

        def span(name: str, start: float, stop: float, parent: str | None, own: dict) -> dict:
            out = {"traceId": self.id, "spanId": uuid.uuid4().hex[:16], "name": name, "kind": 1,
                   "startTimeUnixNano": _nanos(start), "endTimeUnixNano": _nanos(stop),
                   "attributes": shared + _attributes(own)}
            if parent:
                out["parentSpanId"] = parent
            return out

        root = span(self.name, self.started_at, end, None, _observation(
            "span", {"input": self.input, "output": self.output} if self.content else {}))
        spans = [root] + [
            span(st["name"], st["start"], st["end"], root["spanId"], _observation(st["kind"], st))
            for st in self.steps
        ]
        return {"resourceSpans": [{
            "resource": {"attributes": _attributes({"service.name": "lexio"})},
            "scopeSpans": [{"scope": {"name": "lexio"}, "spans": spans}],
        }]}

    async def send(self) -> None:
        try:
            resp = await _http().post(
                f"{self.s.langfuse_host.rstrip('/')}/api/public/otel/v1/traces",
                json=self.payload(),
                auth=(self.s.langfuse_public_key, self.s.langfuse_secret_key),
                headers={"x-langfuse-ingestion-version": "4"},  # show up now, not in 10 minutes
            )
            if resp.status_code >= 300:
                log.warning("langfuse answered %s: %s", resp.status_code, resp.text[:600])
                return
            try:  # a 2xx can still say some spans were refused
                partial = resp.json().get("partialSuccess") or {}
                rejected = int(partial.get("rejectedSpans") or 0)  # OTLP/JSON may give "0"
            except (ValueError, TypeError, AttributeError):  # not JSON: delivered, nothing to say
                return
            if rejected:
                log.warning("langfuse rejected %d span(s): %s", rejected,
                            str(partial.get("errorMessage"))[:600])
        except Exception:  # noqa: BLE001 - tracing must never break a chat
            log.warning("could not send trace to langfuse", exc_info=True)


def enabled(s: Settings) -> bool:
    return bool(s.langfuse_public_key and s.langfuse_secret_key)


def start(s: Settings, name: str, user_key: str, **metadata) -> Trace | None:
    return Trace(s, name, user_key, metadata) if enabled(s) else None


async def _send_quietly(trace: Trace) -> None:
    try:
        await asyncio.wait_for(trace.send(), SEND_TIMEOUT + 1)
    except Exception:  # noqa: BLE001 - a slow or broken Langfuse must not touch the chat
        log.warning("trace not sent", exc_info=True)


async def _deliver(trace: Trace) -> None:
    """Send the trace as a task of its own and wait for it behind a shield. When the visitor
    closes the tab the request is cancelled and this wait is cut short, but the send carries on
    alone (still bounded by the timeout). Sent inline it would be cancelled with the request, and
    an abandoned chat, the one most worth looking at, would never reach Langfuse."""
    task = asyncio.ensure_future(_send_quietly(trace))
    _sending.add(task)
    task.add_done_callback(_sending.discard)
    await asyncio.shield(task)


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
        await _deliver(trace)
