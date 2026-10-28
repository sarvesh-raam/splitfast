import logging
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from . import db, ledger
from .config import settings
from .realtime import hub
from .routers import auth, groups, payments
from .security import decode_token

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.check()
    await db.connect(settings.database_url)
    hub.start(settings.database_url)
    yield
    await hub.stop()
    await db.disconnect()


app = FastAPI(title="SplitFast", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(groups.router)
app.include_router(payments.router)


@app.get("/health")
async def health():
    async with db.pool.acquire() as conn:
        await conn.fetchval("SELECT 1")
    return {"ok": True}


@app.websocket("/ws/groups/{group_id}")
async def group_socket(ws: WebSocket, group_id: UUID, token: str = ""):
    # Browsers can't set headers on a WebSocket, so the JWT comes as a query param.
    try:
        user_id = decode_token(token)
    except HTTPException:
        await ws.close(code=4401)
        return
    async with db.pool.acquire() as conn:
        is_member = await conn.fetchval(
            "SELECT 1 FROM group_members WHERE group_id = $1 AND user_id = $2", group_id, user_id
        )
        if not is_member:
            await ws.close(code=4404)
            return
        initial = await ledger.snapshot(conn, group_id)

    await ws.accept()
    hub.join(group_id, ws)
    try:
        await ws.send_json({"type": "group.updated", "kind": "connected", "balances": initial})
        while True:
            await ws.receive_text()  # we only push; reading detects disconnects
    except WebSocketDisconnect:
        pass
    finally:
        hub.leave(group_id, ws)


# Serve the built PWA from the same origin, with SPA fallback to index.html.
if settings.static_dir and Path(settings.static_dir).is_dir():
    static_root = Path(settings.static_dir).resolve()

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str):
        candidate = (static_root / path).resolve()
        if path and candidate.is_file() and static_root in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(static_root / "index.html")
