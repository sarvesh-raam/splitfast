import os
from uuid import uuid4

import asyncpg
import httpx
import pytest

from app import db
from app.config import settings

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")


@pytest.fixture
async def client():
    if not TEST_DB_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    from app.main import app

    settings.database_url = TEST_DB_URL
    settings.razorpay_key_id = "rzp_test_dummy"
    settings.razorpay_key_secret = "test_key_secret"
    settings.razorpay_webhook_secret = "test_webhook_secret"

    async with app.router.lifespan_context(app):
        async with db.pool.acquire() as conn:
            await conn.execute(
                "TRUNCATE users, groups, group_members, expenses, expense_shares, payments,"
                " settlements, webhook_events, activity CASCADE"
            )
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


async def make_user(client: httpx.AsyncClient, name: str) -> dict:
    r = await client.post(
        "/api/auth/register", json={"email": f"{name.lower()}-{uuid4().hex[:6]}@example.com", "name": name, "password": "password123"}
    )
    assert r.status_code == 201, r.text
    body = r.json()
    return {"id": body["user"]["id"], "name": name, "headers": {"Authorization": f"Bearer {body['token']}"}}
