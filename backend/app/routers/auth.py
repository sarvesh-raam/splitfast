import asyncpg
from fastapi import APIRouter, Depends, HTTPException, status

from ..db import get_conn
from ..schemas import LoginIn, ProfileIn, RegisterIn
from ..security import create_token, current_user, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _user_out(user) -> dict:
    return {"id": str(user["id"]), "name": user["name"], "email": user["email"], "upi_id": user["upi_id"]}


def _session(user) -> dict:
    return {"token": create_token(user["id"]), "user": _user_out(user)}


@router.post("/register", status_code=201)
async def register(body: RegisterIn, conn: asyncpg.Connection = Depends(get_conn)):
    try:
        user = await conn.fetchrow(
            "INSERT INTO users (email, name, password_hash) VALUES ($1, $2, $3) RETURNING id, email, name, upi_id",
            body.email, body.name, hash_password(body.password),
        )
    except asyncpg.UniqueViolationError:
        raise HTTPException(status.HTTP_409_CONFLICT, "An account with this email already exists")
    return _session(user)


@router.post("/login")
async def login(body: LoginIn, conn: asyncpg.Connection = Depends(get_conn)):
    user = await conn.fetchrow("SELECT id, email, name, upi_id, password_hash FROM users WHERE email = $1", body.email)
    if user is None or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password")
    return _session(user)


@router.get("/me")
async def me(user=Depends(current_user)):
    return _user_out(user)


@router.patch("/me")
async def update_me(body: ProfileIn, user=Depends(current_user), conn: asyncpg.Connection = Depends(get_conn)):
    updated = await conn.fetchrow(
        "UPDATE users SET upi_id = $2 WHERE id = $1 RETURNING id, email, name, upi_id", user["id"], body.upi_id
    )
    return _user_out(updated)
