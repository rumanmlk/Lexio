import asyncio
import hashlib
import hmac
import logging
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

import psycopg
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app import budget, ingest, rag, retrieval
from app.config import Settings, get_settings
from app.db import apply_migrations, open_pool
from app.embeddings import build_embedder
from app.errors import ProviderError, duration
from app.llm import GroqLLM

log = logging.getLogger(__name__)


def build_llm(s: Settings):
    return GroqLLM(s.groq_api_key, s.groq_model)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    apply_migrations(s.database_url)
    app.state.pool = await open_pool(s.database_url)
    # Housekeeping must not delay the first request of a cold serverless instance.
    pruning = asyncio.create_task(budget.prune(app.state.pool))
    app.state.embedder = build_embedder(s)
    app.state.llm = build_llm(s)
    yield
    pruning.cancel()
    await app.state.pool.close()


app = FastAPI(title="Lexio API", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ProviderError)
async def provider_error_handler(_: Request, exc: ProviderError):
    return JSONResponse({"detail": exc.message}, status_code=exc.status)


def owner_id() -> str:
    """Single shared workspace for now. Auth (phase 3) replaces this one dependency."""
    return "public"


Owner = Annotated[str, Depends(owner_id)]


def visitor_id(request: Request) -> str:
    """Who the per-visitor limits count: a salted hash of the client IP (never stored raw).
    Behind a proxy that sets X-Forwarded-For itself, its last entry is the real client; trusting
    the header anywhere else would let a visitor pick their own identity. Auth (phase 3)
    replaces this with the user id."""
    s = get_settings()
    ip = request.client.host if request.client else "unknown"
    if s.trust_forwarded_for and (fwd := request.headers.get("x-forwarded-for", "").strip()):
        ip = fwd.split(",")[-1].strip()
    return hmac.new(s.visitor_salt.encode(), ip.encode(), hashlib.sha256).hexdigest()[:16]


Visitor = Annotated[str, Depends(visitor_id)]


async def claim_budget(pool, claims: list[budget.Claim]) -> budget.Receipt:
    try:
        return await budget.claim(pool, claims)
    except budget.BudgetExceeded as exc:
        raise HTTPException(
            429,
            f"{exc.message} It resets in about {duration(exc.retry_after)}.",
            headers={"Retry-After": str(exc.retry_after)},
        ) from exc
    except psycopg.Error as exc:
        raise HTTPException(503, "Database unavailable") from exc


async def provider_failed(pool, s: Settings, receipt: budget.Receipt | None, exc: ProviderError):
    """The work a reservation paid for did not happen: give it back, and if the provider says
    its daily quota is gone, make the embeddings counter agree so later requests stop early."""
    if receipt:
        await budget.refund(pool, receipt)
    if exc.quota and s.embed_daily_limit:
        await budget.exhaust(pool, budget.EMBEDDINGS, s.embed_daily_limit)


async def refund_if_unanswered(stream, pool, receipt: budget.Receipt | None):
    """A question whose answer failed at the provider before any text was sent was not
    answered, so it should not cost the visitor one of their daily questions. The embedding
    request was really spent, so that count stays."""
    answered = False
    async for chunk in stream:
        if chunk.startswith("event: token"):
            answered = True
        elif chunk.startswith("event: error") and receipt and not answered:
            try:
                await budget.refund(pool, receipt.excluding(budget.EMBEDDINGS))
            except psycopg.Error:
                log.warning("could not refund an unanswered question")
        yield chunk


def require_writable(s: Settings) -> None:
    """In demo mode the workspace is shared, so visitors may neither upload nor delete."""
    if not s.uploads_enabled:
        raise HTTPException(403, "This demo is read-only: the sample documents are already loaded.")


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    document_ids: list[UUID] | None = None
    # Earlier turns, oldest first, so a follow-up like "and what about torture?" can be resolved.
    history: list[rag.Turn] = Field(default_factory=list, max_length=20)


@app.get("/api/health")
async def health(request: Request):
    async with request.app.state.pool.connection() as conn:
        await conn.execute("SELECT 1")
    return {"status": "ok"}


@app.post("/api/documents", status_code=201)
async def upload_document(request: Request, owner: Owner, visitor: Visitor, file: UploadFile):
    s = get_settings()
    require_writable(s)
    if not (file.filename or "").lower().endswith(".pdf"):
        raise HTTPException(415, "Only PDF files are supported")
    data = await file.read()
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"File exceeds {s.max_upload_mb} MB")
    if not data.startswith(b"%PDF"):
        raise HTTPException(415, "File is not a valid PDF")
    pool = request.app.state.pool
    receipt: budget.Receipt | None = None

    async def reserve(chunks: int) -> None:
        """Runs once the PDF is new and readable, so duplicates and bad files cost nothing."""
        nonlocal receipt
        room = s.embed_daily_limit - s.embed_query_reserve if s.embed_daily_limit else None
        cap = min((c for c in (s.max_upload_chunks, room) if c), default=None)
        if cap and chunks > cap:
            raise HTTPException(
                413,
                f"This PDF is too long for the free tier ({chunks} sections; "
                f"the limit is {cap}).",
            )
        receipt = await claim_budget(pool, [
            budget.Claim(budget.visitor_uploads(visitor), 1, s.visitor_upload_limit,
                         "You have reached today's upload limit."),
            budget.Claim(budget.EMBEDDINGS, chunks, room,
                         "Today's document-processing budget is used up."),
        ])

    try:
        result = await ingest.ingest_pdf(
            pool,
            request.app.state.embedder,
            owner_id=owner,
            filename=file.filename,
            data=data,
            chunk_chars=s.chunk_chars,
            overlap=s.chunk_overlap_chars,
            before_embed=reserve,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except ProviderError as exc:
        await provider_failed(pool, s, receipt, exc)
        raise
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
    require_writable(get_settings())
    async with request.app.state.pool.connection() as conn:
        cur = await conn.execute(
            "DELETE FROM documents WHERE id = %s AND owner_id = %s", (document_id, owner)
        )
        if cur.rowcount == 0:
            raise HTTPException(404, "Document not found")


@app.get("/api/limits")
async def limits(request: Request, visitor: Visitor):
    """What this visitor may still do today, so a client can disable controls instead of failing."""
    s = get_settings()
    pool = request.app.state.pool
    keys = [budget.QUESTIONS, budget.visitor_questions(visitor), budget.visitor_uploads(visitor)]
    try:
        used, resets_in = await budget.used_today(pool, keys)
    except psycopg.Error as exc:
        raise HTTPException(503, "Database unavailable") from exc

    def entry(key: str, limit: int | None) -> dict:
        return {"used": used[key], "limit": limit}

    return {
        "demo_mode": s.demo_mode,
        "uploads_enabled": s.uploads_enabled,
        "max_upload_mb": s.max_upload_mb,
        "max_upload_chunks": s.max_upload_chunks,
        "questions": entry(keys[1], s.visitor_question_limit),
        "site_questions": entry(keys[0], s.question_daily_limit),
        "uploads": entry(keys[2], s.visitor_upload_limit),
        "resets_in_seconds": resets_in,
    }


@app.post("/api/chat")
async def chat(body: ChatRequest, request: Request, owner: Owner, visitor: Visitor):
    s = get_settings()
    pool = request.app.state.pool
    # Reserved before any provider is called, so a refused request costs nothing. Only limits
    # that are switched on are tracked, so an unlimited deployment pays no database round trips.
    # The query embedding is counted, never refused: it spends the reserve uploads leave alone.
    claims = []
    if s.visitor_question_limit:
        claims.append(budget.Claim(
            budget.visitor_questions(visitor), 1, s.visitor_question_limit,
            f"You have used your {s.visitor_question_limit} questions for today."))
    if s.question_daily_limit:
        claims.append(budget.Claim(
            budget.QUESTIONS, 1, s.question_daily_limit,
            "The demo has answered all the questions the free tier allows today."))
    if s.embed_daily_limit:
        claims.append(budget.Claim(budget.EMBEDDINGS, 1, None, ""))
    receipt = await claim_budget(pool, claims) if claims else None
    try:
        query = await rag.standalone_question(request.app.state.llm, body.history, body.question)
        result = await retrieval.retrieve(
            pool,
            request.app.state.embedder,
            query,
            owner_id=owner,
            document_ids=body.document_ids,
            candidates=s.retrieve_candidates,
            top_k=s.retrieve_top_k,
            keyword_weight=s.keyword_weight,
        )
    except ProviderError as exc:
        await provider_failed(pool, s, receipt, exc)
        raise
    except psycopg.Error as exc:
        if receipt:
            await budget.refund(pool, receipt)
        raise HTTPException(503, "Database unavailable") from exc
    stream = rag.answer_stream(
        request.app.state.llm, query, result, min_similarity=s.min_similarity
    )
    return StreamingResponse(
        refund_if_unanswered(stream, pool, receipt),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
