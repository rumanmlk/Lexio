from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector_async
from psycopg_pool import AsyncConnectionPool

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"


def apply_migrations(database_url: str) -> list[str]:
    """Run unapplied *.sql files in order. Idempotent; safe to call on every cold start."""
    applied: list[str] = []
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY)")
        done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
        for path in sorted(MIGRATIONS.glob("*.sql")):
            if path.name in done:
                continue
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute("INSERT INTO schema_migrations VALUES (%s)", (path.name,))
            applied.append(path.name)
    return applied


async def _configure(conn: psycopg.AsyncConnection) -> None:
    await register_vector_async(conn)


async def open_pool(database_url: str, max_size: int = 5) -> AsyncConnectionPool:
    pool = AsyncConnectionPool(
        database_url,
        min_size=0,  # Neon scales to zero; do not hold idle connections open.
        max_size=max_size,
        configure=_configure,
        open=False,
    )
    await pool.open()
    return pool
