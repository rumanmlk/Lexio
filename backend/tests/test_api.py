"""End-to-end through the real FastAPI app and a real Postgres+pgvector (docker compose up db).

Uses the hash embedder and a fake LLM, so it needs no API keys and runs offline."""

import asyncio
import io
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from uuid import uuid4

import jwt
import psycopg
import pytest
from pypdf import PdfWriter

os.environ.setdefault("DATABASE_URL", "postgresql://lexio:lexio@localhost:5433/lexio_test")
os.environ["EMBEDDING_PROVIDER"] = "hash"
os.environ["API_TOKEN_SECRET"] = "test-secret-test-secret-test-secret-0123"
os.environ["ALLOW_DEV_USERS"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app import auth, budget, main, rag, storage  # noqa: E402
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


def token(sub="dev:alice", **claims):
    """A token as the Next.js app mints it, with any claim overridden (None removes it)."""
    key = claims.pop("_key", None) or get_settings().api_token_secret
    now = int(time.time())
    body = {"sub": sub, "iss": "lexio-web", "aud": "lexio-api", "iat": now, "exp": now + 300}
    body.update(claims)
    body = {k: v for k, v in body.items() if v is not None}
    return jwt.encode(body, key, algorithm="HS256")


def bearer(sub="dev:alice", **claims):
    return {"Authorization": f"Bearer {token(sub, **claims)}"}


@pytest.fixture(scope="module")
def client():
    url = get_settings().database_url
    admin = url.rsplit("/", 1)[0] + "/postgres"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS lexio_test WITH (FORCE)")
        conn.execute("CREATE DATABASE lexio_test")
    main.build_llm = lambda s: FakeLLM()
    with TestClient(main.app, headers=bearer("dev:alice")) as c:  # alice unless a test says so
        yield c


@pytest.fixture
def anon(client):
    """The same app with no sign-in at all (the app is already running; no new lifespan)."""
    return TestClient(main.app)


@pytest.fixture
def bob(client):
    return TestClient(main.app, headers=bearer("dev:bob"))


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
    return client.post("/api/chat", json=body, headers=headers or None)


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


def test_site_wide_limit_is_all_or_nothing_across_counters(anon, limits):
    limits(question_daily_limit=1, trust_forwarded_for=True)
    assert ask(anon, **{"x-forwarded-for": "10.0.0.1"}).status_code == 200
    assert ask(anon, **{"x-forwarded-for": "10.0.0.2"}).status_code == 429
    # the refused request must not have been counted against its visitor either
    assert anon.get("/api/limits", headers={"x-forwarded-for": "10.0.0.2"}).json()[
        "questions"
    ]["used"] == 0


def test_anonymous_identity_ignores_forwarded_header_unless_trusted(anon, limits):
    limits(visitor_question_limit=1)
    assert ask(anon, **{"x-forwarded-for": "10.0.0.1"}).status_code == 200
    assert ask(anon, **{"x-forwarded-for": "10.0.0.2"}).status_code == 429  # same real client
    limits(trust_forwarded_for=True)
    assert ask(anon, **{"x-forwarded-for": "10.0.0.3"}).status_code == 200  # a different one
    assert ask(anon, **{"x-forwarded-for": "10.0.0.3"}).status_code == 429
    # an appended spoof must not help: only the proxy's own (last) entry counts
    assert ask(anon, **{"x-forwarded-for": "10.0.0.9, 10.0.0.3"}).status_code == 429


def test_uploads_switch_turns_off_upload_and_delete_for_everyone(client, limits, indexed):
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


def test_migration_004_renames_public_to_samples_and_records_sizes(client):
    """Starts from a database as phase 2 left it, then applies the real migrations."""
    from app.db import MIGRATIONS, apply_migrations

    url = get_settings().database_url
    admin = url.rsplit("/", 1)[0] + "/postgres"
    target = url.rsplit("/", 1)[0] + "/lexio_migration"
    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute("DROP DATABASE IF EXISTS lexio_migration WITH (FORCE)")
        conn.execute("CREATE DATABASE lexio_migration")
    with psycopg.connect(target, autocommit=True) as conn:
        conn.execute("CREATE TABLE schema_migrations (name text PRIMARY KEY)")
        for path in sorted(MIGRATIONS.glob("00[1-3]_*.sql")):
            conn.execute(path.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations VALUES (%s)", (path.name,))
        vec = "[" + ",".join(["0"] * 768) + "]"
        for sha, owner, data in (("a", "public", b"%PDF-12345"), ("b", "public", None)):
            doc = conn.execute(
                "INSERT INTO documents (owner_id, filename, sha256, page_count) "
                "VALUES (%s, %s, %s, 1) RETURNING id", (owner, sha + ".pdf", sha),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO chunks (document_id, chunk_index, page, content, embedding) "
                "VALUES (%s, 0, 1, 'x', %s)", (doc, vec),
            )
            if data:
                conn.execute("INSERT INTO document_files VALUES (%s, %s)", (doc, data))

    assert apply_migrations(target) == ["004_owners.sql", "005_blob_path.sql"]
    with psycopg.connect(target) as conn:
        rows = conn.execute("SELECT owner_id, size_bytes FROM documents ORDER BY sha256").fetchall()
        assert rows == [("samples", 10), ("samples", 0)]  # no data moved; size only where known
        assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 2
        with pytest.raises(psycopg.errors.NotNullViolation):  # no silent default owner any more
            conn.execute(
                "INSERT INTO documents (filename, sha256, page_count) VALUES ('c', 'c', 1)"
            )


def test_private_pdfs_are_never_cached_but_samples_are(client, clean):
    sample = _seed_sample()
    mine = upload(client, OTHER).json()["id"]
    assert "max-age" in client.get(f"/api/documents/{sample.document_id}/file").headers[
        "cache-control"
    ]
    assert client.get(f"/api/documents/{mine}/file").headers["cache-control"] == (
        "private, no-store"
    )


def test_reuploading_a_pdf_stored_before_files_were_kept_fixes_its_size(client, clean):
    doc = upload(client).json()["id"]
    with psycopg.connect(get_settings().database_url, autocommit=True) as conn:
        conn.execute("DELETE FROM document_files")
        conn.execute("UPDATE documents SET size_bytes = 0")
    assert upload(client).json()["id"] == doc
    with psycopg.connect(get_settings().database_url) as conn:
        size = conn.execute("SELECT size_bytes FROM documents WHERE id = %s", (doc,)).fetchone()
    assert size == (SAMPLE.stat().st_size,)


# ---- sign-in and per-user documents (app/auth.py) -----------------------------------------


@pytest.fixture
def clean(client, limits):
    limits()  # empty documents and counters, restored afterwards
    return client


def test_anonymous_cannot_upload_or_delete_and_sees_only_samples(anon, clean):
    assert upload(anon).status_code == 401
    assert anon.delete(f"/api/documents/{uuid4()}").status_code == 401
    assert anon.delete("/api/me").status_code == 401
    assert anon.get("/api/documents").json() == []
    body = anon.get("/api/limits").json()
    assert body["signed_in"] is False and body["uploads_enabled"] is False
    assert ask(anon).status_code == 200  # may still ask questions


def test_user_cannot_list_read_chat_over_or_delete_another_users_documents(client, bob, clean):
    mine = upload(client).json()["id"]
    assert [d["id"] for d in client.get("/api/documents").json()] == [mine]
    assert bob.get("/api/documents").json() == []
    assert bob.get(f"/api/documents/{mine}/file").status_code == 404
    assert bob.delete(f"/api/documents/{mine}").status_code == 404  # 404, not 403: not revealed
    question = "Does everyone have the right to education?"
    scoped = bob.post("/api/chat", json={"question": question, "document_ids": [mine]})
    assert scoped.status_code == 404
    events = parse_sse(bob.post("/api/chat", json={"question": question}).text)
    assert events[-1][1]["refused"] is True  # unscoped: bob's search never touches alice's chunks
    assert client.get(f"/api/documents/{mine}/file").status_code == 200  # still there


def test_same_pdf_uploaded_by_two_users_is_two_private_documents(client, bob, clean):
    a, b = upload(client).json(), upload(bob).json()
    assert a["id"] != b["id"] and not a["duplicate"] and not b["duplicate"]


def _seed_sample(path=SAMPLE):
    """What `python -m evals.seed` does for the shared sample set, without the embedding API."""
    async def run():
        pool = await open_pool(get_settings().database_url)
        try:
            from app.ingest import ingest_pdf
            return await ingest_pdf(
                pool, main.app.state.embedder, owner_id=auth.SAMPLES, filename=path.name,
                data=path.read_bytes(), chunk_chars=1200, overlap=150,
            )
        finally:
            await pool.close()

    return asyncio.run(run())


def test_samples_are_visible_to_all_searchable_and_undeletable(client, anon, clean):
    sample = _seed_sample()
    listed = anon.get("/api/documents").json()
    assert [d["id"] for d in listed] == [str(sample.document_id)] and listed[0]["sample"] is True
    assert anon.get(f"/api/documents/{sample.document_id}/file").status_code == 200
    events = parse_sse(
        anon.post("/api/chat", json={"question": "Does everyone have the right to education?"}).text
    )
    assert events[-1][1]["grounded"] is True, events
    assert client.delete(f"/api/documents/{sample.document_id}").status_code == 403
    assert len(anon.get("/api/documents").json()) == 1


def test_uploading_a_sample_reuses_it_and_costs_nothing(client, limits, swap_state):
    limits(visitor_upload_limit=1, embed_daily_limit=100, embed_query_reserve=10)
    sample = _seed_sample()
    swap_state("embedder", DownEmbedder())  # any attempt to embed would fail
    r = upload(client)
    assert r.status_code == 201
    assert r.json() == {
        "id": str(sample.document_id), "filename": SAMPLE.name, "pages": sample.page_count,
        "chunks": sample.chunk_count, "duplicate": True, "sample": True,
    }
    assert used(client, "uploads") == 0
    assert client.get("/api/limits").json()["documents"]["used"] == 0  # nothing stored for them


def test_per_user_document_and_storage_caps(client, bob, limits):
    limits(user_max_documents=1)
    assert upload(client).status_code == 201
    r = upload(client, OTHER)
    assert r.status_code == 403 and "1 documents" in r.json()["detail"]
    assert upload(bob, OTHER).status_code == 201  # caps are per user
    assert client.delete(f"/api/documents/{upload(client).json()['id']}").status_code == 204
    assert upload(client, OTHER).status_code == 201

    limits(user_max_documents=10, user_max_mb=0)
    assert upload(client, SAMPLE.parent / "crc.pdf").status_code == 403
    body = client.get("/api/limits").json()
    assert body["documents"] == {"used": 1, "limit": 10} and body["storage_mb"]["limit"] == 0


def test_per_user_limits_follow_the_user_not_the_ip(client, bob, limits):
    limits(visitor_question_limit=1)
    assert ask(client).status_code == 200 and ask(client).status_code == 429
    assert ask(bob).status_code == 200  # same IP, different user


def test_delete_me_removes_everything_and_leaves_others_alone(client, bob, clean):
    mine, theirs = upload(client).json()["id"], upload(bob, OTHER).json()["id"]
    assert client.delete("/api/me").status_code == 204
    assert client.get("/api/documents").json() == []
    assert client.get(f"/api/documents/{mine}/file").status_code == 404
    with psycopg.connect(get_settings().database_url) as conn:
        left = conn.execute(
            "SELECT (SELECT count(*) FROM documents WHERE owner_id = 'dev:alice'),"
            " (SELECT count(*) FROM chunks c JOIN documents d ON d.id = c.document_id"
            "  WHERE d.owner_id = 'dev:alice'),"
            " (SELECT count(*) FROM document_files WHERE document_id = %s)",
            (mine,),
        ).fetchone()
        total = conn.execute("SELECT count(*) FROM document_files").fetchone()[0]
    assert left == (0, 0, 0) and total == 1
    assert [d["id"] for d in bob.get("/api/documents").json()] == [theirs]


@pytest.mark.parametrize(
    "headers",
    [
        {"Authorization": "Bearer not.a.token"},
        {"Authorization": "Basic abc"},
        {"Authorization": "Bearer"},
        bearer(exp=int(time.time()) - 60),  # expired
        bearer(aud="somebody-else"),
        bearer(iss="somebody-else"),
        bearer(sub=None),
        bearer(exp=None),
        bearer("google:123", _key="x" * 40),  # signed with another key
        bearer("someone"),  # not a user id we issue
        bearer("dev:../etc"),
    ],
    ids=["garbage", "scheme", "empty", "expired", "audience", "issuer", "no-sub", "no-exp",
         "forged", "bad-sub", "bad-chars"],
)
def test_bad_tokens_get_401_not_anonymous_access(anon, headers):
    assert anon.get("/api/documents", headers=headers).status_code == 401
    assert anon.post("/api/chat", json={"question": "hello?"}, headers=headers).status_code == 401


def test_unsigned_and_wrong_algorithm_tokens_are_refused(anon):
    claims = {"sub": "google:1", "iss": "lexio-web", "aud": "lexio-api", "exp": time.time() + 99}
    unsigned = jwt.encode(claims, None, algorithm="none")
    hs512 = jwt.encode(claims, get_settings().api_token_secret + "x" * 40, algorithm="HS512")
    for t in (unsigned, hs512):
        headers = {"Authorization": f"Bearer {t}"}
        assert anon.get("/api/documents", headers=headers).status_code == 401


def test_google_users_work_and_dev_users_need_the_switch(anon, limits):
    assert anon.get("/api/documents", headers=bearer("google:1234567890")).status_code == 200
    limits(allow_dev_users=False)
    assert anon.get("/api/documents", headers=bearer("dev:alice")).status_code == 401
    assert anon.get("/api/documents", headers=bearer("google:1234567890")).status_code == 200


def test_signing_in_is_off_without_a_secret(anon, limits):
    limits(api_token_secret="")
    assert anon.get("/api/documents", headers=bearer("google:1", _key="x" * 40)).status_code == 401
    assert anon.get("/api/documents").status_code == 200  # anonymous still works


FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
MINT = (
    'import { mintApiToken } from "./lib/apitoken.ts";'
    "const e = process.env;"
    "console.log(JSON.stringify(await mintApiToken(e.UID, "
    "{ secret: e.SECRET, issuer: e.ISS, audience: e.AUD })));"
)


def mint_in_frontend(uid="google:104857293746501928374", **override):
    """A token made by the frontend's own minting code (lib/apitoken.ts), run with Node."""
    env = {**os.environ, "UID": uid, "SECRET": get_settings().api_token_secret,
           "ISS": "lexio-web", "AUD": "lexio-api", **override}
    out = subprocess.run(
        [shutil.which("node"), "--experimental-strip-types", "--input-type=module", "-e", MINT],
        cwd=FRONTEND, env=env, capture_output=True, text=True, timeout=60, check=True,
    )
    return json.loads(out.stdout)["token"]


@pytest.mark.skipif(
    not shutil.which("node") or not (FRONTEND / "node_modules" / "jose").exists(),
    reason="needs Node and `npm install` in frontend/",
)
def test_a_token_minted_by_the_frontend_is_what_the_backend_accepts(anon):
    good = {"Authorization": f"Bearer {mint_in_frontend()}"}
    assert anon.get("/api/limits", headers=good).json()["signed_in"] is True
    assert anon.get("/api/documents", headers=good).status_code == 200

    for wrong in ({"AUD": "somebody-else"}, {"ISS": "somebody-else"}, {"SECRET": "x" * 40}):
        bad = {"Authorization": f"Bearer {mint_in_frontend(**wrong)}"}
        assert anon.get("/api/documents", headers=bad).status_code == 401


def test_cors_allows_the_authorization_header(anon):
    r = anon.options(
        "/api/documents",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert r.status_code == 200
    assert "authorization" in r.headers["access-control-allow-headers"].lower()


# ---- direct-to-storage uploads (app/storage.py, Vercel Blob) ------------------------------


class FakeBlob:
    """Stands in for Vercel Blob: what the browser uploaded, and what the API deleted."""

    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.deleted: list[str] = []

    def put(self, user_id: str, name: str, data: bytes) -> str:
        path = storage.user_prefix(user_id) + name
        self.files[path] = data
        return path


@pytest.fixture
def blob(clean, monkeypatch):
    fake = FakeBlob()

    async def read(s, pathname):
        if pathname not in fake.files:
            raise storage.BlobMissing(pathname)
        return fake.files[pathname]

    async def open_stream(s, pathname):
        from contextlib import AsyncExitStack

        if pathname not in fake.files:
            raise storage.BlobMissing(pathname)

        async def chunks():
            data = fake.files[pathname]
            for i in range(0, len(data), 100_000):
                yield data[i : i + 100_000]

        return chunks(), AsyncExitStack()

    async def delete(s, pathnames):
        for p in pathnames:
            fake.files.pop(p, None)
            fake.deleted.append(p)

    monkeypatch.setattr(storage, "read", read)
    monkeypatch.setattr(storage, "open_stream", open_stream)
    monkeypatch.setattr(storage, "delete", delete)
    monkeypatch.setattr(get_settings(), "blob_read_write_token", "test-token")
    return fake


def register(client, path, filename="udhr.pdf"):
    return client.post("/api/documents/register", json={"pathname": path, "filename": filename})


def test_direct_upload_is_registered_streamed_back_and_deleted_with_its_blob(client, blob):
    assert client.get("/api/limits").json()["direct_upload"] is True
    assert upload(client).status_code == 400  # the multipart route is closed in this mode

    path = blob.put("dev:alice", "udhr.pdf", SAMPLE.read_bytes())
    r = register(client, path)
    assert r.status_code == 201 and r.json()["duplicate"] is False
    doc = r.json()["id"]
    with psycopg.connect(get_settings().database_url) as conn:
        assert conn.execute("SELECT blob_path FROM documents WHERE id = %s", (doc,)).fetchone() == (
            path,
        )
        assert conn.execute("SELECT count(*) FROM document_files").fetchone() == (0,)

    got = client.get(f"/api/documents/{doc}/file")
    assert got.status_code == 200 and got.content == SAMPLE.read_bytes()
    assert got.headers["cache-control"] == "private, no-store"
    assert ask(client).status_code == 200  # the chunks are searchable like any other

    assert client.delete(f"/api/documents/{doc}").status_code == 204
    assert blob.deleted == [path]
    assert client.get(f"/api/documents/{doc}/file").status_code == 404


def test_register_refuses_someone_elses_or_malformed_pathnames(client, blob):
    theirs = blob.put("dev:bob", "udhr.pdf", SAMPLE.read_bytes())
    assert register(client, theirs).status_code == 403
    mine = storage.user_prefix("dev:alice")
    for bad in ("udhr.pdf", "u/x.pdf", mine + "a/b.pdf", mine + "../x.pdf", mine, mine + "x\\y"):
        assert register(client, bad).status_code == 403, bad
    assert register(client, mine + "missing.pdf").status_code == 404
    assert blob.deleted == []  # nothing that was not the caller's was ever touched


def test_register_is_anonymous_proof_and_needs_the_switch(anon, client, blob, monkeypatch):
    assert register(anon, "u/x/y.pdf").status_code == 401
    monkeypatch.setattr(get_settings(), "blob_read_write_token", "")
    assert register(client, "u/x/y.pdf").status_code == 404


def test_registering_twice_keeps_the_file_the_document_uses(client, blob):
    path = blob.put("dev:alice", "udhr.pdf", SAMPLE.read_bytes())
    first = register(client, path).json()
    again = register(client, path)
    assert again.status_code == 201 and again.json()["id"] == first["id"]
    assert path in blob.files and blob.deleted == []


def test_a_second_copy_of_the_same_pdf_is_dropped_and_the_first_kept(client, blob):
    one = blob.put("dev:alice", "one.pdf", SAMPLE.read_bytes())
    two = blob.put("dev:alice", "two.pdf", SAMPLE.read_bytes())
    a = register(client, one).json()
    b = register(client, two).json()
    assert b["duplicate"] is True and b["id"] == a["id"]
    assert blob.deleted == [two] and one in blob.files
    assert client.get(f"/api/documents/{a['id']}/file").content == SAMPLE.read_bytes()


@pytest.mark.parametrize(
    ("data", "name", "status"),
    [(b"not a pdf", "x.pdf", 415), (SAMPLE.read_bytes(), "x.txt", 415)],
)
def test_a_rejected_upload_is_deleted_from_storage(client, blob, data, name, status):
    path = blob.put("dev:alice", "x.pdf", data)
    assert register(client, path, filename=name).status_code == status
    assert blob.deleted == [path]


def test_a_big_pdf_is_streamed_whole_from_postgres(client, clean):
    """The 6 MB sample is over Vercel's 4.5 MB response limit, so it must arrive in pieces."""
    big = SAMPLE.parent / "Buyer_Guidance_-_MSC_v2.2A_2025.pdf"
    doc = _seed_sample(big).document_id
    r = client.get(f"/api/documents/{doc}/file")
    assert r.content == big.read_bytes()
    assert int(r.headers["content-length"]) == big.stat().st_size


def test_delete_me_deletes_the_users_blobs(client, blob):
    path = blob.put("dev:alice", "udhr.pdf", SAMPLE.read_bytes())
    register(client, path)
    assert client.delete("/api/me").status_code == 204
    assert blob.deleted == [path]


async def test_sweep_removes_old_unregistered_uploads_only(client, blob, monkeypatch):
    from datetime import UTC, datetime, timedelta

    old, fresh = datetime.now(UTC) - timedelta(hours=5), datetime.now(UTC)
    kept = blob.put("dev:alice", "kept.pdf", SAMPLE.read_bytes())
    register(client, kept)
    stray = storage.user_prefix("dev:alice") + "stray.pdf"
    young = storage.user_prefix("dev:alice") + "young.pdf"

    class Entry:
        def __init__(self, pathname, uploaded_at):
            self.pathname, self.uploaded_at = pathname, uploaded_at

    class Sdk:
        async def _gen(self):
            for e in (Entry(kept, old), Entry(stray, old), Entry(young, fresh)):
                yield e

        def query_blobs(self, prefix=None):
            return self._gen()

    monkeypatch.setattr(storage, "_blob", lambda s: Sdk())
    pool = await open_pool(get_settings().database_url)
    try:
        assert await storage.sweep_orphans(pool, get_settings()) == 1
    finally:
        await pool.close()
    assert blob.deleted == [stray]


def test_upload_ticket_names_the_users_prefix_and_checks_before_any_token_exists(
    client, anon, blob, limits
):
    me = storage.user_prefix("dev:alice")
    assert client.get("/api/limits").json()["upload_prefix"] == me
    assert anon.get("/api/limits").json()["upload_prefix"] is None
    r = client.post("/api/upload-ticket")
    assert r.status_code == 200
    assert r.json() == {"prefix": me, "max_bytes": get_settings().max_upload_mb * 1024 * 1024}
    assert anon.post("/api/upload-ticket").status_code == 401

    limits(upload_ticket_limit=2, user_max_documents=1)
    assert client.post("/api/upload-ticket").status_code == 200  # second of two today
    assert client.post("/api/upload-ticket").status_code == 429  # third is refused with a wait
    assert "Retry-After" in client.post("/api/upload-ticket").headers

    limits(uploads_enabled=False)
    assert client.post("/api/upload-ticket").status_code == 403


def test_upload_ticket_refuses_a_full_account_and_a_server_without_blob(client, blob, limits):
    limits(user_max_documents=1)
    register(client, blob.put("dev:alice", "udhr.pdf", SAMPLE.read_bytes()))
    assert client.post("/api/upload-ticket").status_code == 403  # already at the document cap
    limits(blob_read_write_token="")
    assert client.post("/api/upload-ticket").status_code == 404


# ---- Langfuse tracing (app/tracing.py) ----------------------------------------------------


INGEST = "https://langfuse.test/api/public/ingestion"


@pytest.fixture
def langfuse(limits, indexed):
    """Tracing switched on and pointed at a mocked Langfuse. (The test client is httpx2, which
    respx does not touch; only the app's own Langfuse calls are intercepted.)"""
    import respx

    limits(langfuse_public_key="pk-test", langfuse_secret_key="sk-test",
           langfuse_host="https://langfuse.test")
    with respx.mock(assert_all_called=False) as mock:
        mock.post(INGEST).respond(207, json={"successes": [], "errors": []})
        yield mock


def sent_batch(mock):
    assert mock.calls.call_count == 1
    call = mock.calls.last
    return json.loads(call.request.content)["batch"], call.request


def test_a_chat_is_traced_with_numbers_and_flags_but_no_content_by_default(client, langfuse):
    r = ask(client)
    assert r.status_code == 200
    batch, request = sent_batch(langfuse)
    assert request.headers["authorization"].startswith("Basic ")
    kinds = [e["type"] for e in batch]
    assert kinds[0] == "trace-create" and "span-create" in kinds and "generation-create" in kinds
    trace = batch[0]["body"]
    assert trace["name"] == "chat" and "input" not in trace and "output" not in trace
    meta = trace["metadata"]
    assert meta["outcome"] in ("answered", "refused") and meta["total_ms"] >= 0
    assert "userId" in trace and "alice" not in json.dumps(batch)  # a salted hash, not the id
    everything = json.dumps(batch)
    assert "notice period" not in everything and "find this" not in everything  # no content


def test_content_is_included_only_when_asked_for(client, langfuse, limits):
    limits(langfuse_capture_content=True)
    ask(client)
    batch, _ = sent_batch(langfuse)
    trace = batch[0]["body"]
    assert trace["input"] == "What is the notice period?" and trace["output"]


def test_tracing_is_off_without_keys_and_a_broken_langfuse_never_breaks_a_chat(
    client, indexed, limits
):
    import httpx
    import respx

    with respx.mock(assert_all_called=False) as mock:
        route = mock.post(INGEST).respond(207)
        assert ask(client).status_code == 200
        assert route.call_count == 0  # no keys: nothing is sent
        limits(langfuse_public_key="pk", langfuse_secret_key="sk",
               langfuse_host="https://langfuse.test")
        route.respond(500)
        assert ask(client).status_code == 200
        route.mock(side_effect=httpx.ConnectTimeout("slow"))
        r = ask(client)
        assert r.status_code == 200 and "event: done" in r.text
