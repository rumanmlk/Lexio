"""PDFs in Vercel Blob (private store), for deployments where uploads bypass the API.

The browser uploads with a token the Next.js app mints after checking the Auth.js session, into
`u/<hash of user id>/`. That prefix is what ties an object to its uploader: the API only registers
an object whose pathname starts with the caller's own prefix. The SDK reads BLOB_READ_WRITE_TOKEN
from the environment."""

import hashlib
import logging
import os
import re
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack
from datetime import UTC, datetime, timedelta

import httpx
from psycopg_pool import AsyncConnectionPool

from app.config import Settings
from app.ranges import parse_range

log = logging.getLogger(__name__)

ROOT = "u/"
# An object the browser uploaded but nobody registered is junk; the free store is only 1 GB.
ORPHAN_AFTER = timedelta(hours=2)
_NAME = re.compile(r"^[^/\\\x00-\x1f]{1,300}$")


class BlobMissing(Exception):
    pass


def user_prefix(user_id: str) -> str:
    """Must match userPrefix() in frontend/lib/blob.ts."""
    return f"{ROOT}{hashlib.sha256(user_id.encode()).hexdigest()[:24]}/"


def owns(user_id: str, pathname: str) -> bool:
    prefix = user_prefix(user_id)
    return (
        pathname.startswith(prefix)
        and bool(_NAME.match(pathname[len(prefix):]))
        and ".." not in pathname
    )


def _blob(s: Settings):
    os.environ.setdefault("BLOB_READ_WRITE_TOKEN", s.blob_read_write_token)
    from vercel import blob  # imported late: only deployments that use Blob need the SDK

    return blob


async def read(s: Settings, pathname: str) -> bytes:
    blob = _blob(s)
    try:
        return (await blob.get_blob(pathname, access="private")).body
    except blob.BlobNotFoundError as exc:
        raise BlobMissing(pathname) from exc


async def open_stream(
    s: Settings, pathname: str
) -> tuple[AsyncIterator[bytes], AsyncExitStack, int | None]:
    """The object's bytes as a stream, opened now so a missing object is an error here rather
    than after the response has started, and its size if storage said. Close the returned stack
    when the response is done."""
    blob = _blob(s)
    stack = AsyncExitStack()
    try:
        stream = await stack.enter_async_context(blob.stream_blob(pathname, access="private"))
    except blob.BlobNotFoundError as exc:
        await stack.aclose()
        raise BlobMissing(pathname) from exc
    return stream, stack, stream.metadata.size


# Set once storage has plainly ignored a Range request. From then on this process goes straight to
# the ordinary read, instead of paying a head call and a failed ranged request for every piece. A
# new process (every cold start on Vercel) tries again, so a later change in storage is picked up.
_ignores_ranges = False


async def open_range(
    s: Settings, pathname: str, wanted: str
) -> tuple[AsyncIterator[bytes], AsyncExitStack, tuple[int, int], int] | None:
    """Only the bytes of a `Range` header, asked of storage itself, so nothing before them is read.

    Returns (stream, stack, (first, last), total), or None when the whole object should be served
    the ordinary way: the header asks for everything or is ignorable, or storage did not honour
    the range. The SDK has no ranged read, so this talks to storage directly, and any surprise
    falls back rather than failing a request the ordinary path can answer. Raises BlobMissing for
    a missing object and RangeNotSatisfiable for a range outside it."""
    global _ignores_ranges
    if _ignores_ranges:
        return None
    blob = _blob(s)
    try:
        head = await blob.head_blob(pathname)
    except blob.BlobNotFoundError as exc:
        raise BlobMissing(pathname) from exc
    except Exception:  # noqa: BLE001 - the ordinary path will report a real problem
        log.warning("blob head failed; reading the whole object", exc_info=True)
        return None
    piece = parse_range(wanted, head.size)
    if piece is None:
        return None
    stack = AsyncExitStack()
    try:
        client = await stack.enter_async_context(httpx.AsyncClient(timeout=30))
        resp = await stack.enter_async_context(
            client.stream(
                "GET",
                head.url,
                headers={
                    "authorization": f"Bearer {s.blob_read_write_token}",
                    "x-api-version": "12",
                    "range": f"bytes={piece[0]}-{piece[1]}",
                },
            )
        )
        want = f"bytes {piece[0]}-{piece[1]}/{head.size}"
        if resp.status_code != 206 or resp.headers.get("content-range") != want:
            if resp.status_code in (200, 206):  # storage answered, but not with the part asked for
                _ignores_ranges = True
                log.warning(
                    "Blob ignores byte ranges (HTTP %s, Content-Range %r): uploaded PDFs are read "
                    "whole in this process from now on",
                    resp.status_code,
                    resp.headers.get("content-range"),
                )
            else:  # an error or a refusal says nothing about ranges; try again next time
                log.warning("Blob refused the ranged read (HTTP %s)", resp.status_code)
            await stack.aclose()
            return None
        return resp.aiter_bytes(), stack, piece, head.size
    except Exception:  # noqa: BLE001
        log.warning("ranged blob read failed; reading the whole object", exc_info=True)
        await stack.aclose()
        return None


async def delete(s: Settings, pathnames: list[str]) -> None:
    """Best effort: a failure leaves an unreferenced object, which sweep_orphans removes."""
    if not pathnames:
        return
    try:
        await _blob(s).delete_blob(pathnames)
    except Exception:  # noqa: BLE001 - never fail a user's request over cleanup
        log.warning("could not delete %d blob(s)", len(pathnames), exc_info=True)


async def sweep_orphans(pool: AsyncConnectionPool, s: Settings) -> int:
    """Delete uploaded objects no document refers to (an upload that was never registered or was
    rejected, and a delete that failed halfway). Only objects older than ORPHAN_AFTER, so an upload
    that is still being registered is never touched."""
    blob = _blob(s)
    cutoff = datetime.now(UTC) - ORPHAN_AFTER
    old = [b.pathname async for b in blob.query_blobs(prefix=ROOT) if b.uploaded_at < cutoff]
    if not old:
        return 0
    async with pool.connection() as conn:
        rows = await (
            await conn.execute("SELECT blob_path FROM documents WHERE blob_path = ANY(%s)", (old,))
        ).fetchall()
    kept = {r[0] for r in rows}
    orphans = [p for p in old if p not in kept]
    for i in range(0, len(orphans), 1000):
        await delete(s, orphans[i : i + 1000])
    return len(orphans)
