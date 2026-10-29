"""End-to-end through the real FastAPI app and a real Postgres+pgvector (docker compose up db).

Uses the hash embedder and a fake LLM, so it needs no API keys and runs offline."""

import asyncio
import io
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from pypdf import PdfWriter

os.environ.setdefault("DATABASE_URL", "postgresql://lexio:lexio@localhost:5433/lexio_test")
os.environ["EMBEDDING_PROVIDER"] = "hash"

from fastapi.testclient import TestClient  # noqa: E402

from app import budget, main, rag  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import open_pool  # noqa: E402
from app.errors import ProviderError  # noqa: E402

SAMPLE = (
    Path(__file__).resolve().parents[2]
    / "data" / "samples" / "universal_declaration_of_human_rights.pdf"
)

pytestmark = pytest.mark.db


class FakeLLM:
    async def stream(self, system, user):
        for piece in ["Everyone has the right ", "to education. [1]"]:
            yield piece

    async def complete(self, system, user):
        return "Everyone has the right to education. [1]"


@pytest.fixture(scope="module")
def client():
    url = get_settings().database_url
    admin = url.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS lexio_test WITH (FORCE)")
        conn.execute("CREATE DATABASE lexio_test")
    main.build_llm = lambda s: FakeLLM()
    with TestClient(main.app) as c:
        yield c


def parse_sse(text: str) -> list[tuple[str, dict]]:
    return [rag.parse_sse(block) for block in text.strip().split("\n\n")]


@pytest.fixture
def indexed(client):
    """The sample PDF uploaded for one test and removed afterwards, even if it fails."""
    client.post(
        "/api/documents", files={"file": (SAMPLE.name, SAMPLE.read_bytes(), "application/pdf")}
    )
    yield
    for d in client.get("/api/documents").json():
        client.delete(f"/api/documents/{d['id']}")


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_rejects_non_pdf(client):
    r = client.post("/api/documents", files={"file": ("a.txt", b"hello", "text/plain")})
    assert r.status_code == 415
    r = client.post("/api/documents", files={"file": ("a.pdf", b"not a pdf", "application/pdf")})
    assert r.status_code == 415


def test_upload_dedupes_chat_cites_and_delete(client):
    data = SAMPLE.read_bytes()
    first = client.post("/api/documents", files={"file": (SAMPLE.name, data, "application/pdf")})
    assert first.status_code == 201 and not first.json()["duplicate"]
    assert first.json()["chunks"] > 5
    doc_id = first.json()["id"]

    again = client.post("/api/documents", files={"file": (SAMPLE.name, data, "application/pdf")})
    assert again.json()["duplicate"] and again.json()["id"] == doc_id
    assert len(client.get("/api/documents").json()) == 1

    served = client.get(f"/api/documents/{doc_id}/file")
    assert served.status_code == 200 and served.content == data
    assert served.headers["content-type"] == "application/pdf"
    assert served.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/api/documents/{uuid4()}/file").status_code == 404

    # A document ingested before files were kept gets its file on the next upload of the same PDF.
    with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
        conn.execute("DELETE FROM document_files")
    assert client.get(f"/api/documents/{doc_id}/file").status_code == 404
    client.post("/api/documents", files={"file": (SAMPLE.name, data, "application/pdf")})
    assert client.get(f"/api/documents/{doc_id}/file").content == data

    r = client.post("/api/chat", json={"question": "Does everyone have the right to education?"})
    events = parse_sse(r.text)
    names = [n for n, _ in events]
    assert names[0] == "sources" and names[-1] == "done"
    sources = events[0][1]["sources"]
    assert sources and all(s["page"] >= 1 and s["document_id"] == doc_id for s in sources)
    assert "".join(d["text"] for n, d in events if n == "token").endswith("[1]")
    assert events[-1][1] == {"grounded": True, "cited": [1], "refused": False}

    assert client.delete(f"/api/documents/{doc_id}").status_code == 204
    assert client.delete(f"/api/documents/{doc_id}").status_code == 404
    assert client.get("/api/documents").json() == []
    assert client.get(f"/api/documents/{doc_id}/file").status_code == 404


def test_chat_refuses_when_nothing_indexed(client):
    r = client.post("/api/chat", json={"question": "What is the notice period?"})
    events = parse_sse(r.text)
    assert events[-1] == ("done", {"grounded": False, "cited": [], "refused": True})
    assert "can't find" in events[1][1]["text"]


def test_chat_validates_input(client):
    assert client.post("/api/chat", json={"question": ""}).status_code == 422


def test_follow_up_is_rewritten_before_searching_and_history_is_validated(
    client, indexed, swap_state
):
    class Rewriting(FakeLLM):
        calls = 0

        async def complete(self, system, user):
            Rewriting.calls += 1
            return "Does everyone have the right to education?"

    swap_state("llm", Rewriting())
    history = [
        {"role": "user", "content": "Does everyone have the right to education?"},
        {"role": "assistant", "content": "Yes. [1]"},
    ]
    r = client.post("/api/chat", json={"question": "And is it free?", "history": history})
    events = parse_sse(r.text)
    assert events[0][1]["query"] == "Does everyone have the right to education?"
    assert events[-1][0] == "done" and Rewriting.calls == 1

    alone = parse_sse(client.post("/api/chat", json={"question": "Is education free?"}).text)
    assert alone[0][1]["query"] == "Is education free?" and Rewriting.calls == 1  # no LLM call

    bad = client.post("/api/chat", json={"question": "hi there", "history": [{"role": "x"}]})
    assert bad.status_code == 422


def test_native_citation_format_is_normalized_in_the_stream(client, indexed, swap_state):
    class Native(FakeLLM):
        async def stream(self, system, user):
            for piece in ["Everyone has the right.【", "1†L1-L3】"]:
                yield piece

    swap_state("llm", Native())
    question = "Does everyone have the right to education?"
    events = parse_sse(client.post("/api/chat", json={"question": question}).text)
    assert "".join(d["text"] for n, d in events if n == "token") == "Everyone has the right.[1]"
    assert events[-1] == ("done", {"grounded": True, "cited": [1], "refused": False})


def _blank_pdf(password: str | None = None) -> bytes:
    w = PdfWriter()
    w.add_blank_page(200, 200)
    if password:
        w.encrypt(password)
    buf = io.BytesIO()
    w.write(buf)
    return buf.getvalue()


@pytest.mark.parametrize(
    ("data", "expect"),
    [
        (_blank_pdf(), "No text found"),  # what a scan looks like: pages, no text layer
        (_blank_pdf("secret"), "password-protected"),
        (b"%PDF-1.4 truncated garbage", "damaged"),
    ],
)
def test_unusable_pdfs_get_a_clear_422(client, data, expect):
    r = client.post("/api/documents", files={"file": ("x.pdf", data, "application/pdf")})
    assert r.status_code == 422 and expect in r.json()["detail"]
    assert client.get("/api/documents").json() == []


@pytest.fixture
def swap_state(client):
    """Replace app.state attributes for one test, then put the originals back."""
    saved = {}

    def swap(name, value):
        saved.setdefault(name, getattr(main.app.state, name))
        setattr(main.app.state, name, value)

    yield swap
    for name, value in saved.items():
        setattr(main.app.state, name, value)


class DownEmbedder:
    async def embed_documents(self, texts):
        raise ProviderError(502, "Gemini embeddings rejected the API key. Check it in .env.")

    async def embed_query(self, text):
        raise ProviderError(503, "Gemini embeddings rate limit reached. Try again shortly.")


def test_embedding_outage_is_a_clear_error_not_a_500(client, swap_state):
    swap_state("embedder", DownEmbedder())
    up = client.post(
        "/api/documents", files={"file": (SAMPLE.name, SAMPLE.read_bytes(), "application/pdf")}
    )
    assert up.status_code == 502 and "API key" in up.json()["detail"]
    assert client.get("/api/documents").json() == []  # nothing half-saved

    chat = client.post("/api/chat", json={"question": "What is the notice period?"})
    assert chat.status_code == 503 and "rate limit" in chat.json()["detail"]


def test_llm_failure_mid_answer_arrives_as_an_error_event(client, indexed, swap_state):
    class DownLLM:
        async def stream(self, system, user):
            yield "Everyone has "
            raise ProviderError(503, "Groq quota is used up; it resets in about 5 minutes.", True)

    swap_state("llm", DownLLM())
    r = client.post("/api/chat", json={"question": "Does everyone have the right to education?"})
    events = parse_sse(r.text)
    message = "Groq quota is used up; it resets in about 5 minutes."
    assert events[-1] == ("error", {"message": message, "quota": True})
    assert "done" not in [n for n, _ in events]


# ---- free-tier budgets (app/budget.py) -------------------------------------------------------

OTHER = SAMPLE.parent / "Mutual-NDA-public-2page.pdf"  # 9 chunks; the UDHR sample is 14


@pytest.fixture
def limits(client, monkeypatch):
    """Empty counters, and a helper that changes settings for one test only."""

    def reset():
        with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
            conn.execute("TRUNCATE daily_usage")
            conn.execute("TRUNCATE documents CASCADE")

    reset()

    def configure(**values):
        for name, value in values.items():
            monkeypatch.setattr(get_settings(), name, value)

    yield configure
    monkeypatch.undo()
    reset()


def ask(client, **headers):
    body = {"question": "What is the notice period?"}
    return client.post("/api/chat", json=body, headers=headers)


def upload(client, path=SAMPLE):
    return client.post(
        "/api/documents", files={"file": (path.name, path.read_bytes(), "application/pdf")}
    )


def used(client, field):
    return client.get("/api/limits").json()[field]["used"]


def test_visitor_question_limit_returns_429_with_a_reset_time(client, limits):
    limits(visitor_question_limit=2)
    assert ask(client).status_code == 200 and ask(client).status_code == 200
    r = ask(client)
    assert r.status_code == 429
    assert "2 questions" in r.json()["detail"] and "resets in about" in r.json()["detail"]
    assert 0 < int(r.headers["retry-after"]) <= 24 * 3600
    assert client.get("/api/limits").json()["questions"] == {"used": 2, "limit": 2}


def test_site_wide_limit_is_all_or_nothing_across_counters(client, limits):
    limits(question_daily_limit=1, trust_forwarded_for=True)
    assert ask(client, **{"x-forwarded-for": "10.0.0.1"}).status_code == 200
    assert ask(client, **{"x-forwarded-for": "10.0.0.2"}).status_code == 429
    # the refused request must not have been counted against its visitor either
    assert client.get("/api/limits", headers={"x-forwarded-for": "10.0.0.2"}).json()[
        "questions"
    ]["used"] == 0


def test_visitor_identity_ignores_forwarded_header_unless_trusted(client, limits):
    limits(visitor_question_limit=1)
    assert ask(client, **{"x-forwarded-for": "10.0.0.1"}).status_code == 200
    assert ask(client, **{"x-forwarded-for": "10.0.0.2"}).status_code == 429  # same real client
    limits(trust_forwarded_for=True)
    assert ask(client, **{"x-forwarded-for": "10.0.0.3"}).status_code == 200  # a different one
    assert ask(client, **{"x-forwarded-for": "10.0.0.3"}).status_code == 429
    # an appended spoof must not help: only the proxy's own (last) entry counts
    assert ask(client, **{"x-forwarded-for": "10.0.0.9, 10.0.0.3"}).status_code == 429


def test_demo_mode_makes_the_workspace_read_only(client, limits, indexed):
    limits(uploads_enabled=False)
    assert upload(client, OTHER).status_code == 403
    doc = client.get("/api/documents").json()[0]
    assert client.delete(f"/api/documents/{doc['id']}").status_code == 403
    assert len(client.get("/api/documents").json()) == 1
    assert client.get("/api/limits").json()["uploads_enabled"] is False


def test_upload_limits_count_new_documents_only(client, limits):
    limits(visitor_upload_limit=1)
    first = upload(client)
    assert first.status_code == 201
    assert upload(client).json()["duplicate"]  # a duplicate is free
    r = upload(client, OTHER)
    assert r.status_code == 429 and "upload limit" in r.json()["detail"]
    assert used(client, "uploads") == 1
    assert len(client.get("/api/documents").json()) == 1  # nothing half-saved


def test_embedding_budget_protects_the_question_reserve(client, limits):
    limits(embed_daily_limit=25, embed_query_reserve=5)  # uploads may use 20 requests
    assert upload(client).status_code == 201  # 14 chunks
    r = upload(client, OTHER)  # 9 more would make 23
    assert r.status_code == 429 and "document-processing budget" in r.json()["detail"]
    assert ask(client).status_code == 200  # questions still work
    too_big = SAMPLE.parent / "crc.pdf"
    assert upload(client, too_big).status_code == 413  # could never fit, so no "try later"


def test_max_upload_chunks(client, limits):
    limits(max_upload_chunks=10)
    r = upload(client)  # 14 chunks
    assert r.status_code == 413 and "limit is 10" in r.json()["detail"]


def test_failed_embedding_gives_the_reservation_back(client, limits, swap_state):
    limits(visitor_upload_limit=1, embed_daily_limit=100, embed_query_reserve=10,
           visitor_question_limit=1)
    swap_state("embedder", DownEmbedder())
    assert upload(client).status_code == 502
    assert ask(client).status_code == 503
    assert used(client, "uploads") == 0 and used(client, "questions") == 0


def test_provider_quota_error_shuts_the_upload_door_until_reset(client, limits, swap_state):
    limits(embed_daily_limit=1000, embed_query_reserve=200)

    msg = "Gemini embeddings quota is used up; it resets in about 3 hours."
    gone = ProviderError(503, msg, True)

    class OutOfQuota:
        async def embed_documents(self, texts):
            raise gone

        async def embed_query(self, text):
            raise gone

    healthy = main.app.state.embedder
    swap_state("embedder", OutOfQuota())
    assert upload(client).status_code == 503
    swap_state("embedder", healthy)
    r = upload(client)  # the provider is back in this test, but the day's budget is spent
    assert r.status_code == 429 and "budget" in r.json()["detail"]


def test_limits_endpoint_reports_the_configuration(client, limits):
    limits(demo_mode=True, visitor_question_limit=10, question_daily_limit=60,
           max_upload_chunks=150)
    body = client.get("/api/limits").json()
    assert body["demo_mode"] and body["max_upload_chunks"] == 150
    assert body["questions"] == {"used": 0, "limit": 10}
    assert body["site_questions"] == {"used": 0, "limit": 60}
    assert 0 < body["resets_in_seconds"] <= 24 * 3600


async def test_concurrent_claims_never_overshoot_a_limit(client, limits):
    """Many serverless instances claim at once; the database, not the app, enforces the cap."""
    pool = await open_pool(get_settings().database_url, max_size=10)
    try:
        claim = budget.Claim("race", 1, 10, "full")

        async def one():
            try:
                await budget.claim(pool, [claim])
                return True
            except budget.BudgetExceeded:
                return False

        results = await asyncio.gather(*(one() for _ in range(40)))
        assert sum(results) == 10
        assert (await budget.used_today(pool, ["race"]))[0]["race"] == 10
    finally:
        await pool.close()


def test_question_that_fails_before_any_text_is_given_back(client, limits, indexed, swap_state):
    limits(visitor_question_limit=5)

    class Failing(FakeLLM):
        def __init__(self, after):
            self.after = after

        async def stream(self, system, user):
            for piece in self.after:
                yield piece
            raise ProviderError(503, "Groq quota is used up; it resets in about 5 minutes.", True)

    question = {"question": "Does everyone have the right to education?"}
    swap_state("llm", Failing([]))
    events = parse_sse(client.post("/api/chat", json=question).text)
    assert events[-1][0] == "error" and used(client, "questions") == 0  # nothing was delivered

    swap_state("llm", Failing(["Everyone has "]))
    events = parse_sse(client.post("/api/chat", json=question).text)
    assert events[-1][0] == "error" and used(client, "questions") == 1  # part of an answer was


def test_done_event_says_whether_the_model_refused_or_just_gave_no_citation(
    client, indexed, swap_state
):
    def final(r):
        return parse_sse(r.text)[-1]

    class Says:
        def __init__(self, text):
            self.text = text

        async def stream(self, system, user):
            yield self.text

    ask = {"question": "Does everyone have the right to education?"}
    swap_state("llm", Says(rag.REFUSAL))
    assert final(client.post("/api/chat", json=ask)) == (
        "done", {"grounded": False, "cited": [], "refused": True}
    )
    swap_state("llm", Says("Probably, but I am not citing anything."))
    assert final(client.post("/api/chat", json=ask)) == (
        "done", {"grounded": False, "cited": [], "refused": False}
    )
