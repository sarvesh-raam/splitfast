"""Live balance updates over WebSockets.

Writes call db.notify() inside their transaction, so Postgres only delivers the
event after the commit. Every app instance LISTENs on the channel and pushes a
fresh snapshot to the sockets it holds for that group, which keeps updates
correct with several instances behind a load balancer and no Redis.
"""
import asyncio
import json
import logging
from collections import defaultdict
from uuid import UUID

import asyncpg
from fastapi import WebSocket

from . import db, ledger

log = logging.getLogger("splitfast.realtime")


class Hub:
    def __init__(self) -> None:
        self.rooms: dict[UUID, set[WebSocket]] = defaultdict(set)
        self._task: asyncio.Task | None = None

    def join(self, group_id: UUID, ws: WebSocket) -> None:
        self.rooms[group_id].add(ws)

    def leave(self, group_id: UUID, ws: WebSocket) -> None:
        room = self.rooms.get(group_id)
        if room is not None:
            room.discard(ws)
            if not room:
                del self.rooms[group_id]

    async def broadcast(self, group_id: UUID, message: dict) -> None:
        dead = []
        for ws in list(self.rooms.get(group_id, ())):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.leave(group_id, ws)

    async def _fanout(self, payload: str) -> None:
        event = json.loads(payload)
        group_id = UUID(event["group_id"])
        if group_id not in self.rooms:
            return
        async with db.pool.acquire() as conn:
            balances = await ledger.snapshot(conn, group_id)
        await self.broadcast(group_id, {"type": "group.updated", "kind": event["kind"], "balances": balances})

    def _on_notify(self, _conn, _pid, _channel, payload: str) -> None:
        asyncio.create_task(self._fanout(payload))

    async def _listen_forever(self, dsn: str) -> None:
        while True:
            conn = None
            try:
                conn = await asyncpg.connect(dsn)
                await conn.add_listener(db.EVENTS_CHANNEL, self._on_notify)
                log.info("listening on %s", db.EVENTS_CHANNEL)
                while True:
                    await asyncio.sleep(5)
                    await conn.execute("SELECT 1")  # surfaces a dropped connection
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.warning("listener connection lost (%s); reconnecting", exc)
                await asyncio.sleep(2)
            finally:
                if conn is not None and not conn.is_closed():
                    conn.terminate()

    def start(self, dsn: str) -> None:
        self._task = asyncio.create_task(self._listen_forever(dsn))

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass


hub = Hub()
