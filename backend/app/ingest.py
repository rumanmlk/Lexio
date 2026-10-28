import hashlib
import io
import re
from dataclasses import dataclass
from uuid import UUID

import numpy as np
from psycopg_pool import AsyncConnectionPool
from pypdf import PdfReader

from app.embeddings import Embedder


@dataclass(frozen=True)
class PageChunk:
    page: int
    content: str


def extract_pages(data: bytes) -> list[str]:
    reader = PdfReader(io.BytesIO(data))
    return [(p.extract_text() or "") for p in reader.pages]


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


async def ingest_pdf(
    pool: AsyncConnectionPool,
    embedder: Embedder,
    *,
    owner_id: str,
    filename: str,
    data: bytes,
    chunk_chars: int,
    overlap: int,
) -> IngestResult:
    sha = hashlib.sha256(data).hexdigest()
    async with pool.connection() as conn:
        row = await (
            await conn.execute(
                "SELECT id, filename, page_count, chunk_count FROM documents "
                "WHERE owner_id = %s AND sha256 = %s",
                (owner_id, sha),
            )
        ).fetchone()
    if row:
        return IngestResult(row[0], row[1], row[2], row[3], duplicate=True)

    pages = extract_pages(data)
    chunks = chunk_pages(pages, chunk_chars, overlap)
    if not chunks:
        raise ValueError("No extractable text. Scanned PDFs need OCR, which is not supported yet.")

    vectors = await embedder.embed_documents([c.content for c in chunks])

    async with pool.connection() as conn, conn.transaction():
        doc_id = (
            await (
                await conn.execute(
                    "INSERT INTO documents (owner_id, filename, sha256, page_count, chunk_count) "
                    "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                    (owner_id, filename, sha, len(pages), len(chunks)),
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
    return IngestResult(doc_id, filename, len(pages), len(chunks), duplicate=False)
