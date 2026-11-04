"""Langfuse tracing (app/tracing.py) on its own: no database, no keys, Langfuse mocked."""

import asyncio
import json
import logging

import anyio
import httpx
import pytest
import respx

from app import tracing
from app.config import Settings

URL = "https://langfuse.test/api/public/otel/v1/traces"


def settings(**over) -> Settings:
    return Settings(langfuse_public_key="pk", langfuse_secret_key="sk",
                    langfuse_host="https://langfuse.test", _env_file=None, **over)


def attrs_of(span: dict) -> dict:
    return {a["key"]: next(iter(a["value"].values())) for a in span["attributes"]}


def spans_of(trace: tracing.Trace) -> list[dict]:
    return trace.payload()["resourceSpans"][0]["scopeSpans"][0]["spans"]


def filled(content: bool) -> tracing.Trace:
    t = tracing.start(settings(langfuse_capture_content=content), "chat", "visitor", hits=3)
    t.input, t.output = "What is the notice period?", "Thirty days. [1]"
    t.timed("generation", "rewrite", 0.1, model="m", metadata={"rewritten": True},
            input="and the notice?", output="What is the notice period?")
    t.timed("span", "retrieval", 0.2, metadata={"hits": 3},
            input="What is the notice period?", output=["lease.pdf p.4"])
    return t


def test_steps_hang_under_the_root_and_carry_the_trace_fields():
    spans = spans_of(filled(content=False))
    root, steps = spans[0], spans[1:]
    assert root["name"] == "chat" and "parentSpanId" not in root
    assert [s["name"] for s in steps] == ["rewrite", "retrieval"]
    assert all(s["parentSpanId"] == root["spanId"] for s in steps)
    kinds = {s["name"]: attrs_of(s)["langfuse.observation.type"] for s in steps}
    assert kinds == {"rewrite": "generation", "retrieval": "span"}
    for s in spans:  # every span can be filtered by the trace fields
        a = attrs_of(s)
        assert a["langfuse.user.id"] == "visitor" and a["langfuse.trace.name"] == "chat"
        assert a["langfuse.trace.metadata.hits"] == "3"


def test_no_step_carries_text_unless_content_capture_is_on():
    off = json.dumps(spans_of(filled(content=False)))
    for secret in ("notice", "lease.pdf", "Thirty days"):
        assert secret not in off
    on = spans_of(filled(content=True))
    assert json.loads(attrs_of(on[0])["langfuse.observation.input"]) == "What is the notice period?"
    assert json.loads(attrs_of(on[1])["langfuse.observation.input"]) == "and the notice?"
    assert json.loads(attrs_of(on[2])["langfuse.observation.output"]) == ["lease.pdf p.4"]


def test_a_clock_that_jumps_back_cannot_make_a_step_end_after_its_trace(monkeypatch):
    t = tracing.start(settings(), "chat", "visitor")
    monkeypatch.setattr(tracing.time, "time", lambda: 0.0)  # the wall clock is reset mid-request
    t.timed("span", "retrieval", 0.0)  # no duration, so it cannot begin before the trace did
    root, step = spans_of(t)
    assert int(step["startTimeUnixNano"]) <= int(step["endTimeUnixNano"])
    assert int(root["startTimeUnixNano"]) <= int(step["startTimeUnixNano"])
    assert int(step["endTimeUnixNano"]) <= int(root["endTimeUnixNano"])
    assert int(attrs_of(root)["langfuse.trace.metadata.total_ms"]) >= 0


@pytest.mark.parametrize(
    ("reply", "expect"),
    [
        (httpx.Response(200, json={}), None),
        (httpx.Response(200, json={"partialSuccess": {"rejectedSpans": "0"}}), None),
        (httpx.Response(200, text="<html>ok</html>"), None),  # delivered; not a failure
        (httpx.Response(200, json={"partialSuccess": {"rejectedSpans": "2",
                                                      "errorMessage": "bad span"}}),
         "langfuse rejected 2 span(s): bad span"),
        (httpx.Response(401, text="Invalid credentials"), "langfuse answered 401: Invalid"),
    ],
)
async def test_send_reports_only_real_problems(reply, expect, caplog):
    caplog.set_level(logging.WARNING, logger="app.tracing")
    with respx.mock() as mock:
        mock.post(URL).mock(return_value=reply)
        await filled(content=False).send()
    messages = [r.getMessage() for r in caplog.records]
    if expect is None:
        assert messages == []
    else:
        assert len(messages) == 1 and messages[0].startswith(expect)


async def test_an_abandoned_chat_still_reaches_langfuse(monkeypatch):
    """The visitor closes the tab mid-answer: the request is cancelled, the trace still goes."""
    delivered: list[str] = []

    async def send(self):
        await asyncio.sleep(0.1)  # a network round trip, which a cancelled request would cut off
        delivered.append(self.metadata["outcome"])

    monkeypatch.setattr(tracing.Trace, "send", send)
    s = settings()

    async def stream():
        for i in range(100):
            yield f'event: token\ndata: {{"text":"w{i} "}}\n\n'
            await asyncio.sleep(0.01)

    # Starlette cancels a request with an anyio cancel scope, which, unlike Task.cancel(), keeps
    # cancelling every await inside it, including the ones in a finally block.
    scope = anyio.CancelScope()

    async def consume():
        with scope:
            async for _ in tracing.traced(stream(), tracing.start(s, "chat", "visitor"), s):
                pass

    task = asyncio.create_task(consume())
    await asyncio.sleep(0.05)
    scope.cancel()
    await task
    assert scope.cancelled_caught
    await asyncio.gather(*tracing._sending)
    assert delivered == ["interrupted"]
