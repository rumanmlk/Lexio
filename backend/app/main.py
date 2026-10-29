import asyncio
import logging
from contextlib import asynccontextmanager
from uuid import UUID

import psycopg
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from app import budget, ingest, rag, retrieval
from app.auth import SAMPLES, User, Who
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
    allow_methods=["GET", "POST", "DELETE"],
    # "*" does not cover Authorization in browsers, so it is named.
    allow_headers=["Authorization", "Content-Type"],
)


@app.exception_handler(ProviderError)
async def provider_error_handler(_: Request, exc: ProviderError):
    return JSONResponse({"detail": exc.message}, status_code=exc.status)


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
    """Switched off with UPLOADS_ENABLED=false; sign-in is checked separately (401)."""
    if not s.uploads_enabled:
        raise HTTPException(403, "Uploads are turned off on this server.")


async def storage_used(pool, user_id: str | None) -> tuple[int, int]:
    """(documents, bytes) a user has stored; (0, 0) for an anonymous visitor."""
    if user_id is None:
        return 0, 0
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT count(*), coalesce(sum(size_bytes), 0)::bigint FROM documents "
                "WHERE owner_id = %s",
                (user_id,),
            )
        ).fetchone()
    return row[0], row[1]


async def require_room(pool, s: Settings, user_id: str, nbytes: int) -> None:
    """403 when one more document of `nbytes` would break the user's storage caps."""
    try:
        count, size = await storage_used(pool, user_id)
    except psycopg.Error as exc:
        raise HTTPException(503, "Database unavailable") from exc
    if count >= s.user_max_documents:
        raise HTTPException(
            403, f"You can keep {s.user_max_documents} documents. Delete one to upload another."
        )
    if size + nbytes > s.user_max_mb * 1024 * 1024:
        raise HTTPException(
            403, f"Your documents would use more than {s.user_max_mb} MB. Delete one to make room."
        )


async def require_visible(pool, owners: list[str], ids: set[UUID]) -> None:
    """404 for a document the caller may not see, exactly as if it did not exist."""
    try:
        async with pool.connection() as conn:
            rows = await (
                await conn.execute(
                    "SELECT id FROM documents WHERE id = ANY(%s) AND owner_id = ANY(%s)",
                    (list(ids), owners),
                )
            ).fetchall()
    except psycopg.Error as exc:
        raise HTTPException(503, "Database unavailable") from exc
    if len(rows) != len(ids):
        raise HTTPException(404, "Document not found")


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
async def upload_document(request: Request, who: User, file: UploadFile):
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
        """Runs once the PDF is new and readable, so duplicates, samples and bad files cost
        nothing."""
        nonlocal receipt
        await require_room(pool, s, who.user_id, len(data))
        room = s.embed_daily_limit - s.embed_query_reserve if s.embed_daily_limit else None
        cap = min((c for c in (s.max_upload_chunks, room) if c), default=None)
        if cap and chunks > cap:
            raise HTTPException(
                413,
                f"This PDF is too long for the free tier ({chunks} sections; "
                f"the limit is {cap}).",
            )
        receipt = await claim_budget(pool, [
            budget.Claim(budget.visitor_uploads(who.counter_key), 1, s.visitor_upload_limit,
                         "You have reached today's upload limit."),
            budget.Claim(budget.EMBEDDINGS, chunks, room,
                         "Today's document-processing budget is used up."),
        ])

    try:
        result = await ingest.ingest_pdf(
            pool,
            request.app.state.embedder,
            owner_id=who.user_id,
            reuse_from=[SAMPLES],
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
        "sample": result.owner_id == SAMPLES,
    }


@app.get("/api/documents")
async def list_documents(request: Request, who: Who):
    async with request.app.state.pool.connection() as conn:
        cur = await conn.execute(
            "SELECT id, filename, page_count, chunk_count, created_at, owner_id = %s AS sample "
            "FROM documents WHERE owner_id = ANY(%s) ORDER BY sample DESC, created_at DESC",
            (SAMPLES, who.owners),
        )
        rows = await cur.fetchall()
    return [
        {"id": str(r[0]), "filename": r[1], "pages": r[2], "chunks": r[3], "created_at": r[4],
         "sample": r[5]}
        for r in rows
    ]


@app.get("/api/documents/{document_id}/file")
async def document_file(document_id: UUID, request: Request, who: Who):
    async with request.app.state.pool.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT f.data, d.owner_id FROM documents d "
                "JOIN document_files f ON f.document_id = d.id "
                "WHERE d.id = %s AND d.owner_id = ANY(%s)",
                (document_id, who.owners),
            )
        ).fetchone()
    if not row:
        raise HTTPException(404, "Document file not found")
    # A browser cache is keyed by URL, not by who is signed in, so only the samples (readable by
    # everyone) may be cached; a user's own PDF must be checked again on every request.
    cache = "private, max-age=3600" if row[1] == SAMPLES else "private, no-store"
    return Response(
        row[0],
        media_type="application/pdf",
        headers={
            "Content-Disposition": "inline",
            "Cache-Control": cache,
            # Uploaded bytes: never let a browser reinterpret them as another type.
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.delete("/api/documents/{document_id}", status_code=204)
async def delete_document(document_id: UUID, request: Request, who: User):
    require_writable(get_settings())
    async with request.app.state.pool.connection() as conn:
        cur = await conn.execute(
            "DELETE FROM documents WHERE id = %s AND owner_id = %s", (document_id, who.user_id)
        )
        if cur.rowcount:
            return
        shared = await (
            await conn.execute(
                "SELECT 1 FROM documents WHERE id = %s AND owner_id = %s", (document_id, SAMPLES)
            )
        ).fetchone()
    if shared:
        raise HTTPException(403, "The sample documents can't be deleted.")
    raise HTTPException(404, "Document not found")  # also what someone else's document gets


@app.delete("/api/me", status_code=204)
async def delete_me(request: Request, who: User):
    """Erase everything stored for this user: documents, their chunks and PDF files (both cascade).
    Nothing else identifies them: the daily counters are keyed by a salted hash and expire on
    their own, which also stops a delete-and-sign-up-again from resetting today's limits."""
    async with request.app.state.pool.connection() as conn:
        await conn.execute("DELETE FROM documents WHERE owner_id = %s", (who.user_id,))


@app.get("/api/limits")
async def limits(request: Request, who: Who):
    """What this visitor may still do today, so a client can disable controls instead of failing."""
    s = get_settings()
    pool = request.app.state.pool
    keys = [budget.QUESTIONS, budget.visitor_questions(who.counter_key),
            budget.visitor_uploads(who.counter_key)]
    try:
        (used, resets_in), (docs_used, bytes_used) = await asyncio.gather(
            budget.used_today(pool, keys), storage_used(pool, who.user_id)
        )
    except psycopg.Error as exc:
        raise HTTPException(503, "Database unavailable") from exc

    def entry(key: str, limit: int | None) -> dict:
        return {"used": used[key], "limit": limit}

    return {
        "demo_mode": s.demo_mode,
        "signed_in": who.signed_in,
        # can this caller upload and delete right now (anonymous visitors never can)
        "uploads_enabled": s.uploads_enabled and who.signed_in,
        "documents": {"used": docs_used, "limit": s.user_max_documents},
        "storage_mb": {"used": round(bytes_used / 1024 / 1024, 1), "limit": s.user_max_mb},
        "max_upload_mb": s.max_upload_mb,
        "max_upload_chunks": s.max_upload_chunks,
        "questions": entry(keys[1], s.visitor_question_limit),
        "site_questions": entry(keys[0], s.question_daily_limit),
        "uploads": entry(keys[2], s.visitor_upload_limit),
        "resets_in_seconds": resets_in,
    }


@app.post("/api/chat")
async def chat(body: ChatRequest, request: Request, who: Who):
    s = get_settings()
    pool = request.app.state.pool
    # Reserved before any provider is called, so a refused request costs nothing. Only limits
    # that are switched on are tracked, so an unlimited deployment pays no database round trips.
    # The query embedding is counted, never refused: it spends the reserve uploads leave alone.
    if body.document_ids:
        await require_visible(pool, who.owners, set(body.document_ids))
    claims = []
    if s.visitor_question_limit:
        claims.append(budget.Claim(
            budget.visitor_questions(who.counter_key), 1, s.visitor_question_limit,
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
            owners=who.owners,
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
