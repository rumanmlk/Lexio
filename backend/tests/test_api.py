"""End-to-end through the real FastAPI app and a real Postgres+pgvector (docker compose up db).

Uses the hash embedder and a fake LLM, so it needs no API keys and runs offline."""

import json
import os
from pathlib import Path

import psycopg
import pytest

os.environ.setdefault("DATABASE_URL", "postgresql://lexio:lexio@localhost:5433/lexio_test")
os.environ["EMBEDDING_PROVIDER"] = "hash"

from fastapi.testclient import TestClient  # noqa: E402

from app import main  # noqa: E402
from app.config import get_settings  # noqa: E402

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
    events = []
    for block in text.strip().split("\n\n"):
        lines = block.split("\n")
        name = lines[0].removeprefix("event: ")
        events.append((name, json.loads(lines[1].removeprefix("data: "))))
    return events


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
