import json
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import asyncpg

MIGRATIONS = Path(__file__).resolve().parent.parent / "migrations"
EVENTS_CHANNEL = "splitfast_events"

pool: asyncpg.Pool | None = None


async def _init_conn(conn: asyncpg.Connection) -> None:
    await conn.set_type_codec("jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


def _clean_dsn(dsn: str) -> str:
    # asyncpg forwards unknown query params as server settings, so libpq-only
    # options like Neon's channel_binding=require would make Postgres reject the login.
    parts = urlsplit(dsn)
    query = [(k, v) for k, v in parse_qsl(parts.query) if k != "channel_binding"]
    return urlunsplit(parts._replace(query=urlencode(query)))


async def connect(dsn: str) -> asyncpg.Pool:
    global pool
    pool = await asyncpg.create_pool(_clean_dsn(dsn), min_size=1, max_size=10, init=_init_conn)
    await migrate(pool)
    return pool


async def disconnect() -> None:
    global pool
    if pool is not None:
        await pool.close()
        pool = None


async def migrate(p: asyncpg.Pool) -> None:
    async with p.acquire() as conn, conn.transaction():
        # Several app instances may boot at once; only one applies migrations.
        await conn.execute("SELECT pg_advisory_xact_lock(hashtext('splitfast.migrate'))")
        await conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            " name text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
        )
        applied = {r["name"] for r in await conn.fetch("SELECT name FROM schema_migrations")}
        for f in sorted(MIGRATIONS.glob("*.sql")):
            if f.name not in applied:
                await conn.execute(f.read_text(encoding="utf-8"))
                await conn.execute("INSERT INTO schema_migrations (name) VALUES ($1)", f.name)


async def get_conn():
    async with pool.acquire() as conn:
        yield conn


async def notify(conn: asyncpg.Connection, group_id, kind: str) -> None:
    """Queue a realtime event. Postgres only delivers it if the transaction commits."""
    await conn.execute(
        "SELECT pg_notify($1, $2)", EVENTS_CHANNEL, json.dumps({"group_id": str(group_id), "kind": kind})
    )


async def log_activity(conn: asyncpg.Connection, group_id, actor_id, kind: str, summary: str) -> None:
    await conn.execute(
        "INSERT INTO activity (group_id, actor_id, kind, summary) VALUES ($1, $2, $3, $4)",
        group_id, actor_id, kind, summary,
    )
    await notify(conn, group_id, kind)
