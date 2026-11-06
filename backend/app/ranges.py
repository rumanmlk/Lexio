"""HTTP byte ranges (RFC 9110 section 14) for serving a PDF in pieces.

The viewer needs one page, not the whole file: pdf.js asks for the end of the file (where the page
index is) and then only the bytes of the page it draws. A server that cannot answer "bytes=a-b" has
to send everything, which for a 6 MB PDF through a serverless function takes far longer than a page
needs."""

import re
from collections.abc import AsyncIterator

_SPEC = re.compile(r"^bytes=(\d*)-(\d*)$")


class RangeNotSatisfiable(Exception):
    def __init__(self, size: int):
        self.size = size


def parse_range(header: str | None, size: int) -> tuple[int, int] | None:
    """The inclusive (first, last) byte to send, or None to send the whole file.

    Only a single range is served; a header this does not understand (another unit, several ranges,
    nonsense) is ignored, which the RFC allows, rather than failing a request that would work whole.
    A well-formed range that lies outside the file raises RangeNotSatisfiable (416)."""
    if not header:
        return None
    m = _SPEC.match(header.strip().lower())
    if not m or (m[1] == "" and m[2] == ""):
        return None
    if m[1] == "":  # "-n": the last n bytes
        n = int(m[2])
        if n == 0 or size == 0:
            raise RangeNotSatisfiable(size)
        return max(size - n, 0), size - 1
    first = int(m[1])
    last = min(int(m[2]), size - 1) if m[2] else size - 1
    if first >= size:
        raise RangeNotSatisfiable(size)
    if last < first:
        return None  # "bytes=5-2" is invalid, so it is ignored like any other malformed header
    return first, last


def part_headers(first: int, last: int, total: int) -> dict[str, str]:
    """The headers of a 206 response carrying bytes first..last of `total`."""
    return {
        "Content-Length": str(last - first + 1),
        "Content-Range": f"bytes {first}-{last}/{total}",
    }


async def slice_stream(chunks: AsyncIterator[bytes], first: int, last: int) -> AsyncIterator[bytes]:
    """Bytes first..last (inclusive) of a stream, read from its start; stops reading at `last`."""
    pos = 0
    async for chunk in chunks:
        end = pos + len(chunk)
        if end > first:
            yield chunk[max(first - pos, 0) : last + 1 - pos]
        pos = end
        if pos > last:
            return
