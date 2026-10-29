import asyncio
import re
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

import numpy as np
from psycopg_pool import AsyncConnectionPool

from app.embeddings import Embedder

Mode = Literal["hybrid", "vector", "keyword"]
RRF_K = 60


@dataclass
class Hit:
    chunk_id: int
    document_id: UUID
    filename: str
    page: int
    content: str
    score: float
    similarity: float | None = None
    keyword_match: bool = False


@dataclass
class Retrieval:
    hits: list[Hit]
    top_similarity: float
    has_keyword_match: bool


def rrf(
    rankings: list[list[int]], k: int = RRF_K, weights: list[float] | None = None
) -> dict[int, float]:
    """Weighted Reciprocal Rank Fusion: score(d) = sum over lists of w / (k + rank)."""
    weights = weights or [1.0] * len(rankings)
    scores: dict[int, float] = {}
    for ranking, w in zip(rankings, weights, strict=True):
        for rank, key in enumerate(ranking, start=1):
            scores[key] = scores.get(key, 0.0) + w / (k + rank)
    return scores


def or_query(text: str) -> str:
    """OR the terms: natural-language questions rarely have every word in one chunk.
    Postgres drops English stopwords itself when it parses the query."""
    words = dict.fromkeys(re.findall(r"[A-Za-z0-9]+", text.lower()))
    return " | ".join(words)


_SCOPE = (
    "FROM chunks c JOIN documents d ON d.id = c.document_id "
    "WHERE d.owner_id = %(owner)s AND (%(docs)s::uuid[] IS NULL OR c.document_id = ANY(%(docs)s))"
)

_VECTOR_SQL = f"""
SELECT c.id, 1 - (c.embedding <=> %(vec)s) AS sim {_SCOPE}
ORDER BY c.embedding <=> %(vec)s LIMIT %(n)s
"""

# ts_rank (term frequency), not ts_rank_cd (cover density): with OR-ed terms, cover density
# rewards terms sitting close together and ranked worse than vectors on the 5-document eval
# (keyword-only MRR 0.54 vs 0.79).
_KEYWORD_SCOPE = _SCOPE.replace("WHERE", ", to_tsquery('english', %(q)s) q WHERE")
_KEYWORD_SQL = f"""
SELECT c.id, ts_rank(c.tsv, q) AS rank {_KEYWORD_SCOPE}
AND c.tsv @@ q ORDER BY rank DESC LIMIT %(n)s
"""

_FETCH_SQL = """
SELECT c.id, c.document_id, d.filename, c.page, c.content
FROM chunks c JOIN documents d ON d.id = c.document_id WHERE c.id = ANY(%s)
"""


async def retrieve(
    pool: AsyncConnectionPool,
    embedder: Embedder,
    query: str,
    *,
    owner_id: str,
    document_ids: list[UUID] | None = None,
    mode: Mode = "hybrid",
    candidates: int = 30,
    top_k: int = 6,
    keyword_weight: float = 1.0,
) -> Retrieval:
    params = {"owner": owner_id, "docs": document_ids, "n": candidates}

    async def vector() -> list[tuple[int, float]]:
        vec = np.asarray(await embedder.embed_query(query), dtype=np.float32)
        async with pool.connection() as conn:
            cur = await conn.execute(_VECTOR_SQL, {**params, "vec": vec})
            return await cur.fetchall()

    async def keyword() -> list[tuple[int, float]]:
        q = or_query(query)
        if not q:
            return []
        async with pool.connection() as conn:
            cur = await conn.execute(_KEYWORD_SQL, {**params, "q": q})
            return await cur.fetchall()

    vec_rows, kw_rows = await asyncio.gather(
        vector() if mode in ("hybrid", "vector") else _empty(),
        keyword() if mode in ("hybrid", "keyword") else _empty(),
    )
    sims = {cid: sim for cid, sim in vec_rows}
    kw_ids = [cid for cid, _ in kw_rows]

    fused = rrf([[cid for cid, _ in vec_rows], kw_ids], weights=[1.0, keyword_weight])
    ranked = sorted(fused, key=fused.__getitem__, reverse=True)[:top_k]
    if not ranked:
        return Retrieval([], 0.0, False)

    async with pool.connection() as conn:
        rows = await (await conn.execute(_FETCH_SQL, (ranked,))).fetchall()
    by_id = {r[0]: r for r in rows}
    kw_set = set(kw_ids)
    hits = [
        Hit(
            chunk_id=cid,
            document_id=by_id[cid][1],
            filename=by_id[cid][2],
            page=by_id[cid][3],
            content=by_id[cid][4],
            score=fused[cid],
            similarity=sims.get(cid),
            keyword_match=cid in kw_set,
        )
        for cid in ranked
    ]
    return Retrieval(
        hits=hits,
        top_similarity=max(sims.values(), default=0.0),
        has_keyword_match=bool(kw_ids),
    )


async def _empty() -> list:
    return []
