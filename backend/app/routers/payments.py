"""Settling up through Razorpay.

A payment can be confirmed two ways, and both can arrive, in either order, any
number of times:

1. the browser posts the Checkout callback to /api/payments/verify, and
2. Razorpay posts payment.captured / order.paid to the webhook (at least once).

Both paths go through mark_paid(), which locks the payment row, moves it from
'created' to 'paid' exactly once, and inserts the settlement. The UNIQUE
constraint on settlements.payment_id backs this up at the database level, and
webhook_events dedupes redelivered events by id.
"""
import hashlib
import json
import logging
from uuid import UUID, uuid4

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Request, status

from .. import razorpay
from ..config import settings
from ..db import get_conn, log_activity
from ..schemas import PaymentOrderIn, PaymentVerifyIn
from ..security import current_user, require_member
from .groups import rupees

log = logging.getLogger("splitfast.payments")
router = APIRouter(tags=["payments"])


@router.get("/api/config")
async def public_config():
    return {"razorpay_key_id": settings.razorpay_key_id if settings.razorpay_enabled else None}


@router.post("/api/groups/{group_id}/payments", status_code=201)
async def create_order(
    group_id: UUID, body: PaymentOrderIn, user=Depends(current_user), conn: asyncpg.Connection = Depends(get_conn)
):
    if not settings.razorpay_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Online payments are not configured")
    await require_member(conn, group_id, user["id"])
    payee = await conn.fetchrow(
        "SELECT u.id, u.name FROM group_members m JOIN users u ON u.id = m.user_id WHERE m.group_id = $1 AND m.user_id = $2",
        group_id, body.to_user,
    )
    if payee is None or payee["id"] == user["id"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Pick another member of this group to pay")

    payment_id = uuid4()
    try:
        order = await razorpay.create_order(
            body.amount_paise,
            receipt=str(payment_id),
            notes={"group_id": str(group_id), "payer_id": str(user["id"]), "payee_id": str(payee["id"])},
        )
    except razorpay.RazorpayError as exc:
        log.error("%s", exc)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not reach the payment provider")

    await conn.execute(
        """INSERT INTO payments (id, group_id, payer_id, payee_id, amount_paise, razorpay_order_id)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        payment_id, group_id, user["id"], payee["id"], body.amount_paise, order["id"],
    )
    return {
        "payment_id": str(payment_id),
        "order_id": order["id"],
        "amount_paise": body.amount_paise,
        "currency": "INR",
        "key_id": settings.razorpay_key_id,
        "payee_name": payee["name"],
    }


async def mark_paid(conn: asyncpg.Connection, order_id: str, razorpay_payment_id: str, amount_paise: int | None) -> str:
    async with conn.transaction():
        p = await conn.fetchrow(
            """SELECT p.id, p.group_id, p.payer_id, p.payee_id, p.amount_paise, p.status,
                      payer.name AS payer_name, payee.name AS payee_name
                 FROM payments p
                 JOIN users payer ON payer.id = p.payer_id
                 JOIN users payee ON payee.id = p.payee_id
                WHERE p.razorpay_order_id = $1
                  FOR UPDATE OF p""",
            order_id,
        )
        if p is None:
            return "unknown_order"
        if p["status"] == "paid":
            return "already_settled"
        if amount_paise is not None and amount_paise != p["amount_paise"]:
            log.error("order %s: captured %s paise but expected %s", order_id, amount_paise, p["amount_paise"])
            return "amount_mismatch"

        await conn.execute(
            "UPDATE payments SET status = 'paid', razorpay_payment_id = $2, updated_at = now() WHERE id = $1",
            p["id"], razorpay_payment_id,
        )
        await conn.execute(
            """INSERT INTO settlements (id, group_id, from_user, to_user, amount_paise, method, payment_id, created_by)
               VALUES (gen_random_uuid(), $1, $2, $3, $4, 'razorpay', $5, $2)
               ON CONFLICT (payment_id) DO NOTHING""",
            p["group_id"], p["payer_id"], p["payee_id"], p["amount_paise"], p["id"],
        )
        await log_activity(
            conn, p["group_id"], p["payer_id"], "settlement.razorpay",
            f"{p['payer_name']} paid {p['payee_name']} {rupees(p['amount_paise'])} via Razorpay",
        )
        return "settled"


async def mark_failed(conn: asyncpg.Connection, order_id: str) -> str:
    # Only a still-open order can fail; a later successful retry can still settle it.
    done = await conn.fetchval(
        "UPDATE payments SET status = 'failed', updated_at = now()"
        " WHERE razorpay_order_id = $1 AND status = 'created' RETURNING 1",
        order_id,
    )
    return "marked_failed" if done else "ignored"


@router.post("/api/payments/verify")
async def verify_checkout(body: PaymentVerifyIn, user=Depends(current_user), conn: asyncpg.Connection = Depends(get_conn)):
    if not settings.razorpay_enabled:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Online payments are not configured")
    if not razorpay.verify_checkout_signature(body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Payment signature is invalid")
    owner = await conn.fetchval(
        "SELECT payer_id FROM payments WHERE razorpay_order_id = $1", body.razorpay_order_id
    )
    if owner != user["id"]:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
    return {"status": await mark_paid(conn, body.razorpay_order_id, body.razorpay_payment_id, None)}


@router.post("/api/webhooks/razorpay")
async def razorpay_webhook(request: Request, conn: asyncpg.Connection = Depends(get_conn)):
    raw = await request.body()
    if not razorpay.verify_webhook_signature(raw, request.headers.get("x-razorpay-signature", "")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bad signature")
    event = json.loads(raw)
    event_type = event.get("event", "")
    event_id = request.headers.get("x-razorpay-event-id") or hashlib.sha256(raw).hexdigest()

    # The dedupe insert and the processing share one transaction: if processing
    # fails, the event row rolls back too and Razorpay's retry gets a fresh try.
    async with conn.transaction():
        fresh = await conn.fetchval(
            "INSERT INTO webhook_events (event_id, event_type, payload) VALUES ($1, $2, $3)"
            " ON CONFLICT (event_id) DO NOTHING RETURNING 1",
            event_id, event_type, event,
        )
        if not fresh:
            return {"status": "duplicate"}

        payment = (event.get("payload", {}).get("payment") or {}).get("entity") or {}
        if event_type in ("payment.captured", "order.paid") and payment.get("order_id"):
            result = await mark_paid(conn, payment["order_id"], payment["id"], payment.get("amount"))
        elif event_type == "payment.failed" and payment.get("order_id"):
            result = await mark_failed(conn, payment["order_id"])
        else:
            result = "ignored"
    log.info("webhook %s %s -> %s", event_id, event_type, result)
    return {"status": result}
