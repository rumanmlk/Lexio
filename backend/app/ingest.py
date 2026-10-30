import asyncio
import hashlib
import io
import re
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from uuid import UUID

import numpy as np
from psycopg_pool import AsyncConnectionPool
from pypdf import PdfReader
from pypdf.errors import PyPdfError

from app.embeddings import Embedder


@dataclass(frozen=True)
class PageChunk:
    page: int
    content: str


def extract_pages(data: bytes) -> list[str]:
    """Raises ValueError with a user-facing message for unreadable or locked PDFs."""
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted and not reader.decrypt(""):
            raise ValueError("This PDF is password-protected. Remove the password and retry.")
        return [(p.extract_text() or "") for p in reader.pages]
    except PyPdfError as exc:
        raise ValueError("This PDF is damaged or unreadable.") from exc


def normalize(text: str) -> str:
    text = text.replace("\r", "")
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)  # re-join words hyphenated at a line break
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)  # single newline = soft wrap
    text = re.sub(r"\n{2,}", "\n\n", text)
    return text.strip()


_SEPARATORS = ["\n\n", ". ", "; ", ", ", " "]


def _split(text: str, size: int, seps: list[str]) -> list[str]:
    if len(text) <= size:
        return [text]
    if not seps:
        return [text[i : i + size] for i in range(0, len(text), size)]
    sep, rest = seps[0], seps[1:]
    parts = text.split(sep)
    out: list[str] = []
    cur = ""
    for i, part in enumerate(parts):
        piece = part + (sep if i < len(parts) - 1 else "")
        if len(piece) > size:
            if cur:
                out.append(cur)
                cur = ""
            out += _split(piece, size, rest)
        elif len(cur) + len(piece) <= size:
            cur += piece
        else:
            out.append(cur)
            cur = piece
    if cur:
        out.append(cur)
    return out


def chunk_pages(pages: list[str], size: int, overlap: int) -> list[PageChunk]:
    """Chunks never cross a page boundary, so every citation points at exactly one page."""
    chunks: list[PageChunk] = []
    for page_no, raw in enumerate(pages, start=1):
        text = normalize(raw)
        if not text:
            continue
        pieces = [p.strip() for p in _split(text, size, _SEPARATORS) if p.strip()]
        for i, piece in enumerate(pieces):
            if i > 0 and overlap:
                tail = pieces[i - 1][-overlap:]
                tail = tail[tail.find(" ") + 1 :] if " " in tail else tail
                piece = f"{tail} {piece}"
            chunks.append(PageChunk(page=page_no, content=piece))
    return chunks


@dataclass(frozen=True)
class IngestResult:
    document_id: UUID
    filename: str
    page_count: int
    chunk_count: int
    duplicate: bool
    owner_id: str


async def _store_file(conn, doc_id, data: bytes) -> None:
    await conn.execute(
        "INSERT INTO document_files (document_id, data) VALUES (%s, %s) ON CONFLICT DO NOTHING",
        (doc_id, data),
    )
    # Rows from before files were kept have size 0; the storage cap counts this column.
    await conn.execute("UPDATE documents SET size_bytes = %s WHERE id = %s", (len(data), doc_id))


async def ingest_pdf(
    pool: AsyncConnectionPool,
    embedder: Embedder,
    *,
    owner_id: str,
    reuse_from: Sequence[str] = (),
    filename: str,
    data: bytes,
    chunk_chars: int,
    overlap: int,
    before_embed: Callable[[int], Awaitable[None]] | None = None,
    blob_path: str | None = None,
) -> IngestResult:
    """`before_embed(n)` runs once the PDF is known to be new and readable, with the number of
    chunks about to be embedded (one API request each). Raising there aborts the ingest, which is
    where a deployment enforces its free-tier budget without charging duplicates or bad files.
    A PDF already stored under `owner_id` or any owner in `reuse_from` (the shared samples, first)
    is returned as it is, so nobody spends embedding quota or storage on a copy.
    `blob_path`: the PDF already sits in object storage under that pathname; the document records
    it instead of keeping the bytes in Postgres. A duplicate keeps the existing document and its
    file, so the caller deletes its own copy."""
    sha = hashlib.sha256(data).hexdigest()
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT d.id, d.filename, d.page_count, d.chunk_count, "
                "(f.document_id IS NOT NULL OR d.blob_path IS NOT NULL), "
                "d.owner_id "
                "FROM documents d LEFT JOIN document_files f ON f.document_id = d.id "
                "WHERE d.owner_id = ANY(%s) AND d.sha256 = %s "
                "ORDER BY d.owner_id = %s LIMIT 1",
                ([owner_id, *reuse_from], sha, owner_id),
            )
        ).fetchone()
    if row:
        if not row[4]:  # ingested before files were kept: fill it in once
            async with pool.connection() as conn:
                await _store_file(conn, row[0], data)
        return IngestResult(row[0], row[1], row[2], row[3], duplicate=True, owner_id=row[5])

    pages = await asyncio.to_thread(extract_pages, data)  # CPU-bound; keep the event loop free
    chunks = chunk_pages(pages, chunk_chars, overlap)
    if not chunks:
        raise ValueError(
            "No text found in this PDF. It is probably a scan; OCR is not supported yet."
        )

    if before_embed:
        await before_embed(len(chunks))
    vectors = await embedder.embed_documents([c.content for c in chunks])

    async with pool.connection() as conn, conn.transaction():
        doc_id = (
            await (
                await conn.execute(
                    "INSERT INTO documents (owner_id, filename, sha256, page_count, chunk_count, "
                    "size_bytes, blob_path) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                    (owner_id, filename, sha, len(pages), len(chunks), len(data), blob_path),
                )
            ).fetchone()
        )[0]
        async with conn.cursor() as cur:
            await cur.executemany(
                "INSERT INTO chunks (document_id, chunk_index, page, content, embedding) "
                "VALUES (%s, %s, %s, %s, %s)",
                [
                    (doc_id, i, c.page, c.content, np.asarray(v, dtype=np.float32))
                    for i, (c, v) in enumerate(zip(chunks, vectors, strict=True))
                ],
            )
        if not blob_path:
            await _store_file(conn, doc_id, data)
    return IngestResult(doc_id, filename, len(pages), len(chunks), False, owner_id)
