"""Integration tests against a real PostgreSQL (set TEST_DATABASE_URL)."""
import asyncio
import hashlib
import hmac
import json
from uuid import uuid4

import asyncpg
import pytest

from app import db, razorpay
from app.config import settings

from .conftest import make_user


async def setup_group(client, *names):
    users = [await make_user(client, n) for n in names]
    owner = users[0]
    r = await client.post("/api/groups", json={"name": "Goa trip"}, headers=owner["headers"])
    assert r.status_code == 201
    group = r.json()
    for u in users[1:]:
        r = await client.post("/api/groups/join", json={"invite_code": group["invite_code"]}, headers=u["headers"])
        assert r.status_code == 200
    return group["id"], users


async def add_expense(client, gid, payer, amount, members, split_type="equal", values=None, expense_id=None):
    body = {
        "id": expense_id or str(uuid4()),
        "description": "Dinner",
        "amount_paise": amount,
        "paid_by": payer["id"],
        "split_type": split_type,
        "splits": [{"user_id": m["id"], "value": (values or {}).get(m["id"], 0)} for m in members],
    }
    return await client.post(f"/api/groups/{gid}/expenses", json=body, headers=payer["headers"])


def nets(snapshot):
    return {m["name"]: m["net_paise"] for m in snapshot["members"]}


async def test_balances_and_simplification(client):
    gid, (a, b, c) = await setup_group(client, "Asha", "Bala", "Chitra")
    assert (await add_expense(client, gid, a, 300_00, [a, b, c])).status_code == 201
    assert (await add_expense(client, gid, b, 300_00, [b, c])).status_code == 201

    snap = (await client.get(f"/api/groups/{gid}/balances", headers=c["headers"])).json()
    assert nets(snap) == {"Asha": 200_00, "Bala": 50_00, "Chitra": -250_00}
    # Chitra owes both; Bala owes Asha 100 but is owed 150 by Chitra -> Bala's debt nets away.
    assert snap["naive_transfer_count"] == 3
    assert len(snap["transfers"]) == 2
    assert sum(t["amount_paise"] for t in snap["transfers"]) == 250_00


async def test_expense_create_is_idempotent(client):
    gid, (a, b) = await setup_group(client, "Asha", "Bala")
    eid = str(uuid4())
    first = await add_expense(client, gid, a, 100_00, [a, b], expense_id=eid)
    retry = await add_expense(client, gid, a, 100_00, [a, b], expense_id=eid)
    assert (first.status_code, retry.status_code) == (201, 200)
    expenses = (await client.get(f"/api/groups/{gid}/expenses", headers=a["headers"])).json()
    assert len(expenses) == 1


async def test_split_validation(client):
    gid, (a, b) = await setup_group(client, "Asha", "Bala")
    r = await add_expense(client, gid, a, 100_00, [a, b], "percent", {a["id"]: 6000, b["id"]: 3000})
    assert r.status_code == 422
    r = await add_expense(client, gid, a, 100_00, [a, b], "exact", {a["id"]: 30_00, b["id"]: 70_00})
    assert r.status_code == 201
    shares = {s["user_id"]: s["share_paise"] for s in r.json()["shares"]}
    assert shares == {a["id"]: 30_00, b["id"]: 70_00}


async def test_database_rejects_unbalanced_expense(client):
    gid, (a,) = await setup_group(client, "Asha")
    async with db.pool.acquire() as conn:
        with pytest.raises(asyncpg.CheckViolationError):
            async with conn.transaction():
                eid = uuid4()
                await conn.execute(
                    "INSERT INTO expenses (id, group_id, paid_by, description, amount_paise, split_type, created_by)"
                    " VALUES ($1, $2, $3, 'x', 1000, 'exact', $3)",
                    eid, gid, a["id"],
                )
                await conn.execute(
                    "INSERT INTO expense_shares (expense_id, user_id, share_paise) VALUES ($1, $2, 999)", eid, a["id"]
                )


async def test_outsiders_cannot_see_group(client):
    gid, _ = await setup_group(client, "Asha")
    stranger = await make_user(client, "Mallory")
    assert (await client.get(f"/api/groups/{gid}/balances", headers=stranger["headers"])).status_code == 404
    assert (await client.get(f"/api/groups/{gid}/balances")).status_code == 401


async def test_payer_claim_is_pending_until_receiver_confirms(client):
    gid, (a, b) = await setup_group(client, "Asha", "Bala")
    await add_expense(client, gid, a, 100_00, [a, b])
    body = {"id": str(uuid4()), "from_user": b["id"], "to_user": a["id"], "amount_paise": 50_00, "method": "upi"}
    r = await client.post(f"/api/groups/{gid}/settlements", json=body, headers=b["headers"])
    assert (r.status_code, r.json()["status"]) == (201, "pending")
    retry = await client.post(f"/api/groups/{gid}/settlements", json=body, headers=b["headers"])
    assert (retry.status_code, retry.json()["status"]) == (200, "pending")

    # Saying "I paid" changes nothing until Asha confirms.
    snap = (await client.get(f"/api/groups/{gid}/balances", headers=a["headers"])).json()
    assert nets(snap) == {"Asha": 50_00, "Bala": -50_00}
    assert [p["id"] for p in snap["pending"]] == [body["id"]]

    url = f"/api/groups/{gid}/settlements/{body['id']}"
    assert (await client.post(f"{url}/confirm", headers=b["headers"])).status_code == 403  # payer can't self-confirm
    assert (await client.post(f"{url}/confirm", headers=a["headers"])).json() == {"status": "confirmed"}
    assert (await client.post(f"{url}/confirm", headers=a["headers"])).json() == {"status": "confirmed"}  # double tap
    assert (await client.post(f"{url}/reject", headers=a["headers"])).status_code == 409

    snap = (await client.get(f"/api/groups/{gid}/balances", headers=a["headers"])).json()
    assert nets(snap) == {"Asha": 0, "Bala": 0}
    assert snap["pending"] == []


async def test_rejected_claim_never_counts(client):
    gid, (a, b) = await setup_group(client, "Asha", "Bala")
    await add_expense(client, gid, a, 100_00, [a, b])
    sid = str(uuid4())
    body = {"id": sid, "from_user": b["id"], "to_user": a["id"], "amount_paise": 50_00, "method": "upi"}
    await client.post(f"/api/groups/{gid}/settlements", json=body, headers=b["headers"])
    groups = (await client.get("/api/groups", headers=a["headers"])).json()
    assert groups[0]["to_confirm"] == 1

    assert (await client.post(f"/api/groups/{gid}/settlements/{sid}/reject", headers=a["headers"])).json() == {"status": "rejected"}
    assert (await client.post(f"/api/groups/{gid}/settlements/{sid}/confirm", headers=a["headers"])).status_code == 409
    snap = (await client.get(f"/api/groups/{gid}/balances", headers=a["headers"])).json()
    assert nets(snap) == {"Asha": 50_00, "Bala": -50_00}


async def test_receiver_recording_counts_immediately(client):
    gid, (a, b) = await setup_group(client, "Asha", "Bala")
    await add_expense(client, gid, a, 100_00, [a, b])
    body = {"id": str(uuid4()), "from_user": b["id"], "to_user": a["id"], "amount_paise": 50_00}
    r = await client.post(f"/api/groups/{gid}/settlements", json=body, headers=a["headers"])
    assert r.json()["status"] == "confirmed"
    snap = (await client.get(f"/api/groups/{gid}/balances", headers=a["headers"])).json()
    assert nets(snap) == {"Asha": 0, "Bala": 0}
    assert snap["transfers"] == []


# --- Razorpay ---------------------------------------------------------------

def signed(payload: dict) -> tuple[bytes, str]:
    raw = json.dumps(payload).encode()
    return raw, hmac.new(settings.razorpay_webhook_secret.encode(), raw, hashlib.sha256).hexdigest()


def captured_event(order_id: str, payment_id: str, amount: int, event="payment.captured") -> dict:
    return {
        "event": event,
        "payload": {"payment": {"entity": {"id": payment_id, "order_id": order_id, "amount": amount, "status": "captured"}}},
    }


async def post_webhook(client, payload, event_id):
    raw, sig = signed(payload)
    return await client.post(
        "/api/webhooks/razorpay",
        content=raw,
        headers={"x-razorpay-signature": sig, "x-razorpay-event-id": event_id, "content-type": "application/json"},
    )


async def open_order(client, monkeypatch, gid, payer, payee, amount):
    async def fake_create_order(amount_paise, receipt, notes):
        return {"id": f"order_{uuid4().hex[:14]}", "amount": amount_paise}

    monkeypatch.setattr(razorpay, "create_order", fake_create_order)
    r = await client.post(
        f"/api/groups/{gid}/payments", json={"to_user": payee["id"], "amount_paise": amount}, headers=payer["headers"]
    )
    assert r.status_code == 201, r.text
    return r.json()["order_id"]


async def settlement_count(gid):
    async with db.pool.acquire() as conn:
        return await conn.fetchval("SELECT count(*) FROM settlements WHERE group_id = $1", gid)


async def test_webhook_redelivery_settles_once(client, monkeypatch):
    gid, (a, b) = await setup_group(client, "Asha", "Bala")
    await add_expense(client, gid, a, 100_00, [a, b])
    order_id = await open_order(client, monkeypatch, gid, b, a, 50_00)

    event = captured_event(order_id, "pay_123", 50_00)
    assert (await post_webhook(client, event, "evt_1")).json() == {"status": "settled"}
    assert (await post_webhook(client, event, "evt_1")).json() == {"status": "duplicate"}
    # A different event about the same payment (Razorpay sends both) is also a no-op.
    other = captured_event(order_id, "pay_123", 50_00, event="order.paid")
    assert (await post_webhook(client, other, "evt_2")).json() == {"status": "already_settled"}

    assert await settlement_count(gid) == 1
    snap = (await client.get(f"/api/groups/{gid}/balances", headers=a["headers"])).json()
    assert nets(snap) == {"Asha": 0, "Bala": 0}


async def test_concurrent_confirmations_cannot_double_settle(client, monkeypatch):
    """Deterministic interleaving: the first confirmation holds its transaction
    open while a second one arrives. Without the row lock, the second would read
    the stale 'created' status and settle the payment again."""
    from app.routers.payments import mark_paid

    gid, (a, b) = await setup_group(client, "Asha", "Bala")
    order_id = await open_order(client, monkeypatch, gid, b, a, 50_00)

    async with db.pool.acquire() as first, db.pool.acquire() as second:
        tx = first.transaction()
        await tx.start()
        assert await mark_paid(first, order_id, "pay_1", 50_00) == "settled"

        late = asyncio.create_task(mark_paid(second, order_id, "pay_1", 50_00))
        await asyncio.sleep(0.3)
        assert not late.done(), "second confirmation must wait for the first to finish"

        await tx.commit()
        assert await late == "already_settled"

    assert await settlement_count(gid) == 1


async def test_webhook_and_client_callback_burst(client, monkeypatch):
    gid, (a, b) = await setup_group(client, "Asha", "Bala")
    await add_expense(client, gid, a, 100_00, [a, b])
    order_id = await open_order(client, monkeypatch, gid, b, a, 50_00)
    signature = hmac.new(
        settings.razorpay_key_secret.encode(), f"{order_id}|pay_race".encode(), hashlib.sha256
    ).hexdigest()

    verify = client.post(
        "/api/payments/verify",
        json={"razorpay_order_id": order_id, "razorpay_payment_id": "pay_race", "razorpay_signature": signature},
        headers=b["headers"],
    )
    hooks = [post_webhook(client, captured_event(order_id, "pay_race", 50_00), f"evt_{i}") for i in range(30)]
    results = await asyncio.gather(verify, *hooks)

    statuses = sorted(r.json()["status"] for r in results)
    assert statuses.count("settled") == 1
    assert await settlement_count(gid) == 1


async def test_webhook_rejects_bad_signature_and_wrong_amount(client, monkeypatch):
    gid, (a, b) = await setup_group(client, "Asha", "Bala")
    order_id = await open_order(client, monkeypatch, gid, b, a, 50_00)

    raw, _ = signed(captured_event(order_id, "pay_x", 50_00))
    r = await client.post("/api/webhooks/razorpay", content=raw, headers={"x-razorpay-signature": "forged"})
    assert r.status_code == 400

    r = await post_webhook(client, captured_event(order_id, "pay_x", 1_00), "evt_tampered")
    assert r.json() == {"status": "amount_mismatch"}
    assert await settlement_count(gid) == 0


async def test_verify_rejects_forged_signature(client, monkeypatch):
    gid, (a, b) = await setup_group(client, "Asha", "Bala")
    order_id = await open_order(client, monkeypatch, gid, b, a, 50_00)
    r = await client.post(
        "/api/payments/verify",
        json={"razorpay_order_id": order_id, "razorpay_payment_id": "pay_1", "razorpay_signature": "0" * 64},
        headers=b["headers"],
    )
    assert r.status_code == 400
    assert await settlement_count(gid) == 0


async def test_upi_id_profile_and_visibility(client):
    gid, (a, b) = await setup_group(client, "Asha", "Bala")
    bad = await client.patch("/api/auth/me", json={"upi_id": "not a upi id"}, headers=a["headers"])
    assert bad.status_code == 422
    ok = await client.patch("/api/auth/me", json={"upi_id": " asha.k@okaxis "}, headers=a["headers"])
    assert ok.json()["upi_id"] == "asha.k@okaxis"
    group = (await client.get(f"/api/groups/{gid}", headers=b["headers"])).json()
    assert {m["name"]: m["upi_id"] for m in group["members"]} == {"Asha": "asha.k@okaxis", "Bala": None}
    cleared = await client.patch("/api/auth/me", json={"upi_id": ""}, headers=a["headers"])
    assert cleared.json()["upi_id"] is None
