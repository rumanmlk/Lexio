from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app import ingest, rag, retrieval
from app.config import Settings, get_settings
from app.db import apply_migrations, open_pool
from app.embeddings import build_embedder
from app.llm import GroqLLM


def build_llm(s: Settings):
    return GroqLLM(s.groq_api_key, s.groq_model)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    apply_migrations(s.database_url)
    app.state.pool = await open_pool(s.database_url)
    app.state.embedder = build_embedder(s)
    app.state.llm = build_llm(s)
    yield
    await app.state.pool.close()


app = FastAPI(title="Lexio API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


def owner_id() -> str:
    """Single shared workspace for now. Auth (phase 3) replaces this one dependency."""
    return "public"


Owner = Annotated[str, Depends(owner_id)]


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    document_ids: list[UUID] | None = None


@app.get("/api/health")
async def health(request: Request):
    async with request.app.state.pool.connection() as conn:
        await conn.execute("SELECT 1")
    return {"status": "ok"}


@app.post("/api/documents", status_code=201)
async def upload_document(request: Request, owner: Owner, file: UploadFile):
    s = get_settings()
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(415, "Only PDF files are supported")
    data = await file.read()
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {s.max_upload_mb} MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(415, "File is not a valid PDF")
    try:
        result = await ingest.ingest_pdf(
            request.app.state.pool,
            request.app.state.embedder,
            owner_id=owner,
            filename=file.filename,
            data=data,
            chunk_chars=s.chunk_chars,
            overlap=s.chunk_overlap_chars,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        "id": str(result.document_id),
        "filename": result.filename,
        "pages": result.page_count,
        "chunks": result.chunk_count,
        "duplicate": result.duplicate,
    }


@app.get("/api/documents")
async def list_documents(request: Request, owner: Owner):
    async with request.app.state.pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, filename, page_count, chunk_count, created_at FROM documents "
            "WHERE owner_id = %s ORDER BY created_at DESC",
            (owner,),
        )
        rows = await cur.fetchall()
    return [
        {"id": str(r[0]), "filename": r[1], "pages": r[2], "chunks": r[3], "created_at": r[4]}
        for r in rows
    ]


@app.delete("/api/documents/{document_id}", status_code=204)
async def delete_document(document_id: UUID, request: Request, owner: Owner):
    async with request.app.state.pool.connection() as conn:
        cur = await conn.execute(
            "DELETE FROM documents WHERE id = %s AND owner_id = %s", (document_id, owner)
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Document not found")


@app.post("/api/chat")
async def chat(body: ChatRequest, request: Request, owner: Owner):
    s = get_settings()
    try:
        result = await retrieval.retrieve(
            request.app.state.pool,
            request.app.state.embedder,
            body.question,
            owner_id=owner,
            document_ids=body.document_ids,
            candidates=s.retrieve_candidates,
            top_k=s.retrieve_top_k,
            keyword_weight=s.keyword_weight,
        )
    except psycopg.Error as exc:
        raise HTTPException(503, "Database unavailable") from exc
    stream = rag.answer_stream(
        request.app.state.llm, body.question, result, min_similarity=s.min_similarity
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
