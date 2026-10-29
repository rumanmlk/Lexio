"""End-to-end through the real FastAPI app and a real Postgres+pgvector (docker compose up db).

Uses the hash embedder and a fake LLM, so it needs no API keys and runs offline."""

import io
import os
from pathlib import Path

import psycopg
import pytest
from pypdf import PdfWriter

os.environ.setdefault("DATABASE_URL", "postgresql://lexio:lexio@localhost:5433/lexio_test")
os.environ["EMBEDDING_PROVIDER"] = "hash"

from fastapi.testclient import TestClient  # noqa: E402

from app import main, rag  # noqa: E402
from app.config import get_settings  # noqa: E402
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

    r = client.post("/api/chat", json={"question": "Does everyone have the right to education?"})
    events = parse_sse(r.text)
    names = [n for n, _ in events]
    assert names[0] == "sources" and names[-1] == "done"
    sources = events[0][1]["sources"]
    assert sources and all(s["page"] >= 1 and s["document_id"] == doc_id for s in sources)
    assert "".join(d["text"] for n, d in events if n == "token").endswith("[1]")
    assert events[-1][1] == {"grounded": True, "cited": [1]}

    assert client.delete(f"/api/documents/{doc_id}").status_code == 204
    assert client.delete(f"/api/documents/{doc_id}").status_code == 404
    assert client.get("/api/documents").json() == []


def test_chat_refuses_when_nothing_indexed(client):
    r = client.post("/api/chat", json={"question": "What is the notice period?"})
    events = parse_sse(r.text)
    assert events[-1] == ("done", {"grounded": False, "cited": []})
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
    assert events[-1] == ("done", {"grounded": True, "cited": [1]})


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
