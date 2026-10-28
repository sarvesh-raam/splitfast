"""Group balances, derived on demand from expenses and confirmed settlements.

Balances are never stored; storing them would mean keeping a second copy of
the truth in sync. Net balance > 0 means the group owes you.
"""
from uuid import UUID

import asyncpg

from . import settle

_FLOWS = """
    SELECT e.paid_by AS user_id, e.amount_paise AS delta
      FROM expenses e WHERE e.group_id = $1 AND e.deleted_at IS NULL
    UNION ALL
    SELECT s.user_id, -s.share_paise
      FROM expense_shares s JOIN expenses e ON e.id = s.expense_id
     WHERE e.group_id = $1 AND e.deleted_at IS NULL
    UNION ALL
    SELECT from_user, amount_paise FROM settlements WHERE group_id = $1 AND status = 'confirmed'
    UNION ALL
    SELECT to_user, -amount_paise FROM settlements WHERE group_id = $1 AND status = 'confirmed'
"""

_PAIR_DEBTS = """
    SELECT s.user_id AS debtor, e.paid_by AS creditor, sum(s.share_paise)::bigint AS amount
      FROM expense_shares s JOIN expenses e ON e.id = s.expense_id
     WHERE e.group_id = $1 AND e.deleted_at IS NULL AND s.user_id <> e.paid_by AND s.share_paise > 0
     GROUP BY 1, 2
    UNION ALL
    -- Paying someone back reduces what you owe them.
    SELECT from_user, to_user, -sum(amount_paise)::bigint
      FROM settlements WHERE group_id = $1 AND status = 'confirmed' GROUP BY 1, 2
"""


async def snapshot(conn: asyncpg.Connection, group_id: UUID) -> dict:
    rows = await conn.fetch(
        f"""
        WITH flows AS ({_FLOWS})
        SELECT m.user_id, u.name, COALESCE(sum(f.delta), 0)::bigint AS net
          FROM group_members m
          JOIN users u ON u.id = m.user_id
          LEFT JOIN flows f ON f.user_id = m.user_id
         WHERE m.group_id = $1
         GROUP BY m.user_id, u.name
         ORDER BY u.name
        """,
        group_id,
    )
    balances = {r["user_id"]: r["net"] for r in rows}
    transfers = settle.minimize(balances)

    pair_debts: dict[tuple[UUID, UUID], int] = {}
    for r in await conn.fetch(_PAIR_DEBTS, group_id):
        key = (r["debtor"], r["creditor"])
        pair_debts[key] = pair_debts.get(key, 0) + r["amount"]

    pending = await conn.fetch(
        """SELECT id, from_user, to_user, amount_paise, method, created_at FROM settlements
            WHERE group_id = $1 AND status = 'pending' ORDER BY created_at""",
        group_id,
    )

    return {
        "members": [{"user_id": str(r["user_id"]), "name": r["name"], "net_paise": r["net"]} for r in rows],
        "transfers": [
            {"from_user": str(t.debtor), "to_user": str(t.creditor), "amount_paise": t.amount} for t in transfers
        ],
        "naive_transfer_count": settle.naive_transfer_count(pair_debts),
        # Marked as paid by the payer, waiting for the receiver; not in balances yet.
        "pending": [
            {
                "id": str(r["id"]),
                "from_user": str(r["from_user"]),
                "to_user": str(r["to_user"]),
                "amount_paise": r["amount_paise"],
                "method": r["method"],
                "created_at": r["created_at"].isoformat(),
            }
            for r in pending
        ],
    }


async def user_net_by_group(conn: asyncpg.Connection, user_id: UUID) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        WITH flows AS (
            SELECT group_id, amount_paise AS delta FROM expenses WHERE paid_by = $1 AND deleted_at IS NULL
            UNION ALL
            SELECT e.group_id, -s.share_paise FROM expense_shares s JOIN expenses e ON e.id = s.expense_id
             WHERE s.user_id = $1 AND e.deleted_at IS NULL
            UNION ALL
            SELECT group_id, amount_paise FROM settlements WHERE from_user = $1 AND status = 'confirmed'
            UNION ALL
            SELECT group_id, -amount_paise FROM settlements WHERE to_user = $1 AND status = 'confirmed'
        )
        SELECT g.id, g.name, g.invite_code,
               (SELECT count(*) FROM group_members gm WHERE gm.group_id = g.id) AS member_count,
               COALESCE((SELECT sum(delta) FROM flows f WHERE f.group_id = g.id), 0)::bigint AS my_net_paise,
               (SELECT count(*) FROM settlements s
                 WHERE s.group_id = g.id AND s.to_user = $1 AND s.status = 'pending') AS to_confirm
          FROM groups g JOIN group_members m ON m.group_id = g.id AND m.user_id = $1
         ORDER BY g.created_at DESC
        """,
        user_id,
    )
