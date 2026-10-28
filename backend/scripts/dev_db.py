"""Local Postgres without Docker: `pip install pgserver`, then run this once.

Starts a real PostgreSQL 16 whose data lives in <repo>/.pgdata, creates the
`splitfast` and `splitfast_test` databases and prints the URLs to use. The
server keeps running in the background after this script exits.
"""
import asyncio
from pathlib import Path

import asyncpg
import pgserver

DATA = Path(__file__).resolve().parents[2] / ".pgdata"


async def ensure_databases(uri: str) -> None:
    conn = await asyncpg.connect(uri)
    for name in ("splitfast", "splitfast_test"):
        if not await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", name):
            await conn.execute(f'CREATE DATABASE "{name}"')
    await conn.close()


if __name__ == "__main__":
    server = pgserver.get_server(DATA, cleanup_mode=None)
    uri = server.get_uri()
    asyncio.run(ensure_databases(uri))
    base = uri.rsplit("/", 1)[0]
    print(f"DATABASE_URL={base}/splitfast")
    print(f"TEST_DATABASE_URL={base}/splitfast_test")
