import secrets
from typing import Literal
from uuid import UUID

import asyncpg
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from .. import ledger
from ..db import get_conn, log_activity
from ..money import SplitError, compute_shares
from ..schemas import ExpenseIn, GroupIn, SettlementIn
from ..security import current_user, require_member

router = APIRouter(prefix="/api/groups", tags=["groups"])


def rupees(paise: int) -> str:
    return f"₹{paise // 100:,}" + (f".{paise % 100:02d}" if paise % 100 else "")


async def _members(conn: asyncpg.Connection, group_id: UUID) -> dict[UUID, str]:
    rows = await conn.fetch(
        "SELECT u.id, u.name FROM group_members m JOIN users u ON u.id = m.user_id"
        " WHERE m.group_id = $1 ORDER BY m.joined_at",
        group_id,
    )
    return {r["id"]: r["name"] for r in rows}


@router.get("")
async def list_groups(user=Depends(current_user), conn: asyncpg.Connection = Depends(get_conn)):
    return [
        {
            "id": str(r["id"]),
            "name": r["name"],
            "invite_code": r["invite_code"],
            "member_count": r["member_count"],
            "my_net_paise": r["my_net_paise"],
            "to_confirm": r["to_confirm"],
        }
        for r in await ledger.user_net_by_group(conn, user["id"])
    ]


@router.post("", status_code=201)
async def create_group(body: GroupIn, user=Depends(current_user), conn: asyncpg.Connection = Depends(get_conn)):
    async with conn.transaction():
        for _ in range(5):
            try:
                async with conn.transaction():
                    group = await conn.fetchrow(
                        "INSERT INTO groups (name, invite_code, created_by) VALUES ($1, $2, $3) RETURNING id, name, invite_code",
                        body.name.strip(), secrets.token_urlsafe(6), user["id"],
                    )
                break
            except asyncpg.UniqueViolationError:
                continue  # invite code collision; astronomically rare
        else:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Could not create group, try again")
        await conn.execute("INSERT INTO group_members (group_id, user_id) VALUES ($1, $2)", group["id"], user["id"])
        await log_activity(conn, group["id"], user["id"], "group.created", f"{user['name']} created the group")
    return {"id": str(group["id"]), "name": group["name"], "invite_code": group["invite_code"]}


class JoinIn(BaseModel):
    invite_code: str


@router.post("/join")
async def join_group(body: JoinIn, user=Depends(current_user), conn: asyncpg.Connection = Depends(get_conn)):
    group = await conn.fetchrow("SELECT id, name FROM groups WHERE invite_code = $1", body.invite_code.strip())
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "That invite link is not valid")
    async with conn.transaction():
        joined = await conn.fetchval(
            "INSERT INTO group_members (group_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING RETURNING 1",
            group["id"], user["id"],
        )
        if joined:
            await log_activity(conn, group["id"], user["id"], "member.joined", f"{user['name']} joined the group")
    return {"id": str(group["id"]), "name": group["name"]}


@router.get("/{group_id}")
async def get_group(group_id: UUID, user=Depends(current_user), conn: asyncpg.Connection = Depends(get_conn)):
    await require_member(conn, group_id, user["id"])
    group = await conn.fetchrow("SELECT id, name, invite_code FROM groups WHERE id = $1", group_id)
    # UPI IDs are shared only with fellow members, so they know where to pay.
    members = await conn.fetch(
        "SELECT u.id, u.name, u.upi_id FROM group_members m JOIN users u ON u.id = m.user_id"
        " WHERE m.group_id = $1 ORDER BY m.joined_at",
        group_id,
    )
    return {
        "id": str(group["id"]),
        "name": group["name"],
        "invite_code": group["invite_code"],
        "members": [{"id": str(m["id"]), "name": m["name"], "upi_id": m["upi_id"]} for m in members],
    }


@router.get("/{group_id}/balances")
async def balances(group_id: UUID, user=Depends(current_user), conn: asyncpg.Connection = Depends(get_conn)):
    await require_member(conn, group_id, user["id"])
    return await ledger.snapshot(conn, group_id)


@router.get("/{group_id}/activity")
async def activity(group_id: UUID, user=Depends(current_user), conn: asyncpg.Connection = Depends(get_conn)):
    await require_member(conn, group_id, user["id"])
    rows = await conn.fetch(
        "SELECT id, kind, summary, created_at FROM activity WHERE group_id = $1 ORDER BY id DESC LIMIT 50", group_id
    )
    return [{"id": r["id"], "kind": r["kind"], "summary": r["summary"], "created_at": r["created_at"].isoformat()} for r in rows]


_EXPENSE_SELECT = """
    SELECT e.id, e.description, e.amount_paise, e.split_type, e.paid_by, e.created_by, e.created_at,
           (SELECT jsonb_agg(jsonb_build_object('user_id', s.user_id, 'share_paise', s.share_paise))
              FROM expense_shares s WHERE s.expense_id = e.id) AS shares
      FROM expenses e
"""


def _expense_out(r) -> dict:
    return {
        "id": str(r["id"]),
        "description": r["description"],
        "amount_paise": r["amount_paise"],
        "split_type": r["split_type"],
        "paid_by": str(r["paid_by"]),
        "created_by": str(r["created_by"]),
        "created_at": r["created_at"].isoformat(),
        "shares": r["shares"] or [],
    }


@router.get("/{group_id}/expenses")
async def list_expenses(group_id: UUID, user=Depends(current_user), conn: asyncpg.Connection = Depends(get_conn)):
    await require_member(conn, group_id, user["id"])
    rows = await conn.fetch(
        _EXPENSE_SELECT + " WHERE e.group_id = $1 AND e.deleted_at IS NULL ORDER BY e.created_at DESC LIMIT 200",
        group_id,
    )
    return [_expense_out(r) for r in rows]


@router.post("/{group_id}/expenses", status_code=201)
async def create_expense(
    group_id: UUID,
    body: ExpenseIn,
    response: Response,
    user=Depends(current_user),
    conn: asyncpg.Connection = Depends(get_conn),
):
    await require_member(conn, group_id, user["id"])
    members = await _members(conn, group_id)
    if body.paid_by not in members or any(s.user_id not in members for s in body.splits):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Everyone in the split must be in the group")
    try:
        shares = compute_shares(body.amount_paise, body.split_type, [(s.user_id, s.value) for s in body.splits])
    except SplitError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))

    async with conn.transaction():
        inserted = await conn.fetchval(
            """INSERT INTO expenses (id, group_id, paid_by, description, amount_paise, split_type, created_by)
               VALUES ($1, $2, $3, $4, $5, $6, $7) ON CONFLICT (id) DO NOTHING RETURNING id""",
            body.id, group_id, body.paid_by, body.description.strip(), body.amount_paise, body.split_type.value, user["id"],
        )
        if inserted:
            await conn.executemany(
                "INSERT INTO expense_shares (expense_id, user_id, share_paise) VALUES ($1, $2, $3)",
                [(body.id, uid, paise) for uid, paise in shares.items() if paise > 0],
            )
            await log_activity(
                conn, group_id, user["id"], "expense.created",
                f"{user['name']} added “{body.description.strip()}” ({rupees(body.amount_paise)}, paid by {members[body.paid_by]})",
            )

    row = await conn.fetchrow(_EXPENSE_SELECT + " WHERE e.id = $1 AND e.group_id = $2", body.id, group_id)
    if row is None or (not inserted and row["created_by"] != user["id"]):
        raise HTTPException(status.HTTP_409_CONFLICT, "Expense id already used")
    if not inserted:
        response.status_code = status.HTTP_200_OK  # replay of a request we already applied
    return _expense_out(row)


@router.delete("/{group_id}/expenses/{expense_id}", status_code=204)
async def delete_expense(
    group_id: UUID, expense_id: UUID, user=Depends(current_user), conn: asyncpg.Connection = Depends(get_conn)
):
    await require_member(conn, group_id, user["id"])
    async with conn.transaction():
        row = await conn.fetchrow(
            """UPDATE expenses SET deleted_at = now()
                WHERE id = $1 AND group_id = $2 AND deleted_at IS NULL AND $3 IN (created_by, paid_by)
            RETURNING description, amount_paise""",
            expense_id, group_id, user["id"],
        )
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Expense not found, or only its creator or payer can delete it")
        await log_activity(
            conn, group_id, user["id"], "expense.deleted",
            f"{user['name']} deleted “{row['description']}” ({rupees(row['amount_paise'])})",
        )


@router.post("/{group_id}/settlements", status_code=201)
async def record_settlement(
    group_id: UUID,
    body: SettlementIn,
    response: Response,
    user=Depends(current_user),
    conn: asyncpg.Connection = Depends(get_conn),
):
    """Record a payment made outside the app (cash, or UPI straight to the friend).

    The app can't see either kind of payment, so only the receiver can vouch for
    it: if the receiver records it, it counts at once; if the payer records it,
    it stays pending until the receiver confirms the money arrived.
    """
    await require_member(conn, group_id, user["id"])
    members = await _members(conn, group_id)
    if body.from_user not in members or body.to_user not in members or body.from_user == body.to_user:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Pick two different group members")
    if user["id"] not in (body.from_user, body.to_user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the payer or the receiver can record a payment")

    state = "confirmed" if user["id"] == body.to_user else "pending"
    payer, payee, amount = members[body.from_user], members[body.to_user], rupees(body.amount_paise)
    via = "UPI" if body.method == "upi" else "cash"

    async with conn.transaction():
        inserted = await conn.fetchval(
            """INSERT INTO settlements (id, group_id, from_user, to_user, amount_paise, method, status, created_by, responded_at)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8, CASE WHEN $7 = 'confirmed' THEN now() END)
               ON CONFLICT (id) DO NOTHING RETURNING 1""",
            body.id, group_id, body.from_user, body.to_user, body.amount_paise, body.method, state, user["id"],
        )
        if inserted and state == "confirmed":
            await log_activity(conn, group_id, user["id"], "settlement.confirmed", f"{payee} received {amount} from {payer} ({via})")
        elif inserted:
            await log_activity(
                conn, group_id, user["id"], "settlement.pending",
                f"{payer} says they paid {payee} {amount} via {via}; waiting for {payee} to confirm",
            )

    if not inserted:
        response.status_code = status.HTTP_200_OK
        state = await conn.fetchval("SELECT status FROM settlements WHERE id = $1", body.id)
    return {"id": str(body.id), "status": state}


@router.post("/{group_id}/settlements/{settlement_id}/{action}")
async def respond_to_settlement(
    group_id: UUID,
    settlement_id: UUID,
    action: Literal["confirm", "reject"],
    user=Depends(current_user),
    conn: asyncpg.Connection = Depends(get_conn),
):
    await require_member(conn, group_id, user["id"])
    target = "confirmed" if action == "confirm" else "rejected"
    async with conn.transaction():
        # One conditional UPDATE is the whole state machine: it only matches a
        # pending row addressed to this user, so it can't run twice or out of turn.
        row = await conn.fetchrow(
            """UPDATE settlements SET status = $1, responded_at = now()
                WHERE id = $2 AND group_id = $3 AND to_user = $4 AND status = 'pending'
            RETURNING from_user, amount_paise, method""",
            target, settlement_id, group_id, user["id"],
        )
        if row is None:
            current = await conn.fetchrow(
                "SELECT status, to_user FROM settlements WHERE id = $1 AND group_id = $2", settlement_id, group_id
            )
            if current is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "Payment not found")
            if current["to_user"] != user["id"]:
                raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the person who received the money can confirm it")
            if current["status"] == target:
                return {"status": target}  # double tap or retry
            raise HTTPException(status.HTTP_409_CONFLICT, f"This payment was already {current['status']}")

        payer = await conn.fetchval("SELECT name FROM users WHERE id = $1", row["from_user"])
        amount = rupees(row["amount_paise"])
        if target == "confirmed":
            summary = f"{user['name']} confirmed receiving {amount} from {payer}"
        else:
            summary = f"{user['name']} says they didn't receive {amount} from {payer}"
        await log_activity(conn, group_id, user["id"], f"settlement.{target}", summary)
    return {"status": target}
