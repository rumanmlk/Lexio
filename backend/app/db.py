from pathlib import Path

import psycopg
from pgvector.psycopg import register_vector_async
from psycopg_pool import AsyncConnectionPool

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
MIGRATION_LOCK = 727_001  # arbitrary app-wide advisory lock id


def apply_migrations(database_url: str) -> list[str]:
    """Run unapplied *.sql files in order. Idempotent; safe to call on every cold start."""
    applied: list[str] = []
    with psycopg.connect(database_url, autocommit=True) as conn:
        # Several cold instances can start at once; one at a time runs the pending files.
        conn.execute("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK,))
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (name text PRIMARY KEY)")
            done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
            for path in sorted(MIGRATIONS.glob("*.sql")):
                if path.name in done:
                    continue
                with conn.transaction():
                    conn.execute(path.read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO schema_migrations VALUES (%s)", (path.name,))
                applied.append(path.name)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (MIGRATION_LOCK,))
    return applied


async def _configure(conn: psycopg.AsyncConnection) -> None:
    await register_vector_async(conn)


async def open_pool(database_url: str, max_size: int = 5) -> AsyncConnectionPool:
    pool = AsyncConnectionPool(
        database_url,
        min_size=0,  # Neon scales to zero; do not hold idle connections open.
        max_size=max_size,
        configure=_configure,
        # Neon's pooled endpoint (pgbouncer, transaction mode) cannot keep server-side prepared
        # statements, and it drops idle connections when the database scales to zero.
        kwargs={"prepare_threshold": None},
        check=AsyncConnectionPool.check_connection,
        open=False,
    )
    await pool.open()
    return pool
