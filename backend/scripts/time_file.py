"""Times what the document viewer asks of the API, against a running server.

    uv run python scripts/time_file.py https://lexio-api-five.vercel.app buyer
    uv run python scripts/time_file.py http://localhost:8000 buyer --full

The second argument picks a shared sample by part of its filename. It prints the latency of a
trivial call (the floor for every request), then the requests the viewer makes: the first 512 KB,
the end of the file (where pdf.js finds the page index) and a few 256 KB pieces from the middle.
`--full` also downloads the whole file, which on a slow deployment can take minutes."""

import sys
import time

import httpx

FIRST, CHUNK = 512 * 1024, 256 * 1024  # keep in step with frontend/lib/ranges.ts


def timed(client: httpx.Client, url: str, rng: str | None = None) -> tuple[float, float, int, int]:
    """(seconds to first byte, seconds in all, bytes, status)."""
    start = time.perf_counter()
    first = 0.0
    size = 0
    with client.stream("GET", url, headers={"Range": rng} if rng else {}) as r:
        for chunk in r.iter_bytes():
            first = first or time.perf_counter() - start
            size += len(chunk)
        return first, time.perf_counter() - start, size, r.status_code


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 2:
        sys.exit(__doc__)
    base, name = args[0].rstrip("/"), args[1].lower()
    with httpx.Client(timeout=900) as client:
        docs = client.get(f"{base}/api/documents").json()
        doc = next((d for d in docs if name in d["filename"].lower()), None)
        if not doc:
            sys.exit(f"no document matching {name!r}: {[d['filename'] for d in docs]}")
        url = f"{base}/api/documents/{doc['id']}/file"
        print(doc["filename"], f"({doc['pages']} pages)")
        lat = sorted(timed(client, f"{base}/api/limits")[1] for _ in range(5))
        print(f"trivial call (floor per request): median {lat[2]:.2f}s, worst {lat[-1]:.2f}s")

        probe = client.get(url, headers={"Range": "bytes=-1"})
        if probe.status_code != 206:
            print(f"Range ignored (HTTP {probe.status_code}): this server cannot serve pieces yet")
            if "--full" not in sys.argv:
                return
        else:
            total = int(probe.headers["content-range"].split("/")[1])
            asks = [("first 512 KB", f"bytes=0-{FIRST - 1}"), ("end of file", f"bytes=-{CHUNK}")]
            for p in (25, 50, 75):
                at = total * p // 100
                asks.append((f"piece at {p}%", f"bytes={at}-{at + CHUNK - 1}"))
            spent = 0.0
            for label, rng in asks:
                ttfb, secs, size, status = timed(client, url, rng)
                spent += secs
                print(f"{label:>14}: HTTP {status}, {size / 1024:.0f} KB, "
                      f"first byte {ttfb:.2f}s, total {secs:.2f}s")
            print(f"{len(asks)} requests in a row: {spent:.1f}s (a page needs about this many)")
        if "--full" in sys.argv:
            _, secs, size, _ = timed(client, url)
            print(f"whole file: {size / 1e6:.1f} MB in {secs:.1f}s")


if __name__ == "__main__":
    main()
