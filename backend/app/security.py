from datetime import datetime, timedelta, timezone
from uuid import UUID

import asyncpg
import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import settings
from .db import get_conn

_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode(), hashed.encode())


def create_token(user_id: UUID) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(user_id), "iat": now, "exp": now + timedelta(hours=settings.jwt_ttl_hours)}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_token(token: str) -> UUID:
    try:
        return UUID(jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token")


async def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    conn: asyncpg.Connection = Depends(get_conn),
) -> asyncpg.Record:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")
    user = await conn.fetchrow("SELECT id, email, name, upi_id FROM users WHERE id = $1", decode_token(creds.credentials))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Account no longer exists")
    return user


async def require_member(conn: asyncpg.Connection, group_id: UUID, user_id: UUID) -> None:
    # 404 rather than 403 so group ids can't be probed for existence.
    ok = await conn.fetchval(
        "SELECT 1 FROM group_members WHERE group_id = $1 AND user_id = $2", group_id, user_id
    )
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
