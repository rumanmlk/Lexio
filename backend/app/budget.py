"""Daily budgets that keep a public deployment inside the free tiers.

Counters live in Postgres, so every serverless instance shares them and a cold start forgets
nothing. Days are Pacific-time calendar days, the moment Gemini's daily quota resets. The
counters only see traffic that goes through this API; the providers' own errors stay the
backstop (a used-up Gemini quota is recorded with `exhaust`, so the next request is refused
here instead of failing slowly there).
"""

from dataclasses import dataclass
from datetime import date

from psycopg_pool import AsyncConnectionPool

TZ = "America/Los_Angeles"
_DAY = "SELECT (now() AT TIME ZONE %(tz)s)::date"
_RESET = (
    "SELECT extract(epoch FROM date_trunc('day', now() AT TIME ZONE %(tz)s) + interval '1 day'"
    " - (now() AT TIME ZONE %(tz)s))::int"
)

EMBEDDINGS = "embeddings"  # one per text sent to the embedding API
QUESTIONS = "questions"  # one per answered question (each costs about 3k Groq tokens)
RETENTION_DAYS = 7


def visitor_questions(visitor: str) -> str:
    return f"questions:{visitor}"


def visitor_uploads(visitor: str) -> str:
    return f"uploads:{visitor}"


@dataclass(frozen=True)
class Claim:
    counter: str
    amount: int
    limit: int | None  # None: count it, never refuse (e.g. query embeddings spend the reserve)
    message: str  # shown to the client when this claim is the one that does not fit


@dataclass(frozen=True)
class Receipt:
    day: date
    claims: tuple[Claim, ...]

    def excluding(self, counter: str) -> "Receipt":
        return Receipt(self.day, tuple(c for c in self.claims if c.counter != counter))


NO_LIMIT = 2**62  # "count it, never refuse" as a number the upsert's comparison always passes


async def _scalar(conn, sql: str, params):
    return (await (await conn.execute(sql, params)).fetchone())[0]


class BudgetExceeded(Exception):
    def __init__(self, message: str, retry_after: int):
        super().__init__(message)
        self.message, self.retry_after = message, retry_after


async def claim(pool: AsyncConnectionPool, claims: list[Claim]) -> Receipt:
    """Reserve every claim or none: the first one that does not fit raises BudgetExceeded and the
    others are rolled back. Atomic across instances (one upsert per counter, row-locked)."""
    async with pool.connection() as conn, conn.transaction():
        day = await _scalar(conn, _DAY, {"tz": TZ})
        for c in claims:
            row = await (
                await conn.execute(
                    "INSERT INTO daily_usage (day, counter, used) "
                    "SELECT %(day)s, %(counter)s, %(n)s::bigint WHERE %(n)s::bigint <= %(lim)s "
                    "ON CONFLICT (day, counter) DO UPDATE "
                    "SET used = daily_usage.used + EXCLUDED.used "
                    "WHERE daily_usage.used + EXCLUDED.used <= %(lim)s RETURNING used",
                    {"day": day, "counter": c.counter, "n": c.amount,
                     "lim": NO_LIMIT if c.limit is None else c.limit},
                )
            ).fetchone()
            if row is None:  # leaving the block rolls every earlier claim back
                raise BudgetExceeded(c.message, await _scalar(conn, _RESET, {"tz": TZ}))
    return Receipt(day, tuple(claims))


async def refund(pool: AsyncConnectionPool, receipt: Receipt) -> None:
    """Give a reservation back when the work it paid for never happened."""
    async with pool.connection() as conn, conn.transaction():
        for c in receipt.claims:
            await conn.execute(
                "UPDATE daily_usage SET used = greatest(used - %s, 0) "
                "WHERE day = %s AND counter = %s",
                (c.amount, receipt.day, c.counter),
            )


async def exhaust(pool: AsyncConnectionPool, counter: str, limit: int) -> None:
    """The provider says its quota is gone: make the counter agree, whatever it had counted."""
    async with pool.connection() as conn, conn.transaction():
        day = await _scalar(conn, _DAY, {"tz": TZ})
        await conn.execute(
            "INSERT INTO daily_usage (day, counter, used) VALUES (%s, %s, %s) "
            "ON CONFLICT (day, counter) DO UPDATE SET used = greatest(daily_usage.used, %s)",
            (day, counter, limit, limit),
        )


async def used_today(
    pool: AsyncConnectionPool, counters: list[str]
) -> tuple[dict[str, int], int]:
    """Today's count for each counter (0 if untouched) and the seconds until the day resets."""
    async with pool.connection() as conn:
        day = await _scalar(conn, _DAY, {"tz": TZ})
        rows = await (
            await conn.execute(
                "SELECT counter, used FROM daily_usage WHERE day = %s AND counter = ANY(%s)",
                (day, counters),
            )
        ).fetchall()
        reset = await _scalar(conn, _RESET, {"tz": TZ})
    found = dict(rows)
    return {c: found.get(c, 0) for c in counters}, reset


async def prune(pool: AsyncConnectionPool) -> None:
    async with pool.connection() as conn:
        await conn.execute(
            "DELETE FROM daily_usage WHERE day < (now() AT TIME ZONE %s)::date - %s",
            (TZ, RETENTION_DAYS),
        )
