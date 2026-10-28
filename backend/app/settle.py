"""Debt minimisation: the fewest payments that settle a group.

Model the group as a graph where each person has a net balance (positive = is
owed money). Any set of payments that zeroes every balance is valid; we want the
smallest one.

Key fact: if the people can be partitioned into k disjoint groups that each sum
to zero, the whole group settles in n - k payments (each zero-sum group of size
m needs exactly m - 1). So minimising payments == maximising the number of
zero-sum groups. That is NP-hard in general (it contains subset-sum), so:

* n <= EXACT_LIMIT non-zero balances: exact bitmask DP over subsets, O(2^n * n).
* larger groups: greedy that always matches the largest debtor with the largest
  creditor. It is guaranteed to use at most n - 1 payments.

Either way, the payments inside a group are produced by the same greedy.
"""
import heapq
from dataclasses import dataclass
from typing import Hashable

EXACT_LIMIT = 14


@dataclass(frozen=True)
class Transfer:
    debtor: Hashable
    creditor: Hashable
    amount: int


def _greedy(balances: dict[Hashable, int]) -> list[Transfer]:
    # Max-heaps keyed by amount; str(id) makes ordering deterministic on ties.
    creditors = [(-b, str(u), u) for u, b in balances.items() if b > 0]
    debtors = [(b, str(u), u) for u, b in balances.items() if b < 0]
    heapq.heapify(creditors)
    heapq.heapify(debtors)
    out: list[Transfer] = []
    while creditors and debtors:
        c_neg, c_key, c = heapq.heappop(creditors)
        d_neg, d_key, d = heapq.heappop(debtors)
        amount = min(-c_neg, -d_neg)
        out.append(Transfer(d, c, amount))
        if -c_neg > amount:
            heapq.heappush(creditors, (c_neg + amount, c_key, c))
        if -d_neg > amount:
            heapq.heappush(debtors, (d_neg + amount, d_key, d))
    return out


def _zero_sum_groups(people: list[Hashable], amounts: list[int]) -> list[list[Hashable]]:
    """Partition people into the maximum number of zero-sum groups (bitmask DP)."""
    n = len(people)
    full = (1 << n) - 1
    subset_sum = [0] * (1 << n)
    for mask in range(1, 1 << n):
        low = mask & -mask
        subset_sum[mask] = subset_sum[mask ^ low] + amounts[low.bit_length() - 1]

    # best[mask] = most zero-sum groups that the people in `mask` can be cut into,
    # where we build `mask` one person at a time and close a group whenever the
    # running sum returns to zero.
    best = [0] * (1 << n)
    for mask in range(1, 1 << n):
        m, rest = 0, mask
        while rest:
            low = rest & -rest
            rest ^= low
            m = max(m, best[mask ^ low])
        best[mask] = m + (subset_sum[mask] == 0)

    # Walk back from the full set; every zero-sum prefix closes a group.
    groups: list[list[Hashable]] = []
    current: list[Hashable] = []
    mask = full
    while mask:
        gain = subset_sum[mask] == 0
        if gain and current:
            groups.append(current)
            current = []
        rest = mask
        while rest:
            low = rest & -rest
            rest ^= low
            if best[mask ^ low] + gain == best[mask]:
                current.append(people[low.bit_length() - 1])
                mask ^= low
                break
    groups.append(current)
    return groups


def minimize(balances: dict[Hashable, int]) -> list[Transfer]:
    if sum(balances.values()) != 0:
        raise ValueError("balances must sum to zero")
    nonzero = {u: b for u, b in balances.items() if b != 0}
    if len(nonzero) > EXACT_LIMIT:
        return _greedy(nonzero)

    people = sorted(nonzero, key=str)
    out: list[Transfer] = []
    for group in _zero_sum_groups(people, [nonzero[p] for p in people]):
        out.extend(_greedy({p: nonzero[p] for p in group}))
    return out


def naive_transfer_count(pair_debts: dict[tuple[Hashable, Hashable], int]) -> int:
    """Payments needed if everyone just repaid each person they owe directly.

    `pair_debts[(a, b)]` is what a owes b before netting a<->b against b<->a.
    """
    net: dict[tuple, int] = {}
    for (a, b), amount in pair_debts.items():
        key = (a, b) if str(a) < str(b) else (b, a)
        sign = 1 if key == (a, b) else -1
        net[key] = net.get(key, 0) + sign * amount
    return sum(1 for v in net.values() if v != 0)
