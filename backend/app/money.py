"""Turning an expense into per-person shares.

All money is integer paise. Floats never touch an amount, so shares always sum
to the expense total exactly; the leftover paise from division are handed out
by the largest-remainder method with a deterministic tie-break.
"""
from enum import StrEnum
from uuid import UUID


class SplitType(StrEnum):
    EQUAL = "equal"      # value ignored; everyone listed pays the same
    EXACT = "exact"      # value = paise owed by that person
    PERCENT = "percent"  # value = basis points (2500 = 25.00%), must total 10000
    SHARES = "shares"    # value = integer weight (2 shares vs 1 share)


class SplitError(ValueError):
    pass


def _apportion(amount: int, weights: dict[UUID, int]) -> dict[UUID, int]:
    """Split `amount` in proportion to `weights` with no rounding drift."""
    total = sum(weights.values())
    floors = {u: amount * w // total for u, w in weights.items()}
    leftover = amount - sum(floors.values())
    # Biggest fractional part first; user id breaks ties so results are stable.
    order = sorted(weights, key=lambda u: (-(amount * weights[u] % total), str(u)))
    for u in order[:leftover]:
        floors[u] += 1
    return floors


def compute_shares(amount: int, split_type: SplitType, entries: list[tuple[UUID, int]]) -> dict[UUID, int]:
    if amount <= 0:
        raise SplitError("amount must be positive")
    if not entries:
        raise SplitError("at least one person must share the expense")
    users = [u for u, _ in entries]
    if len(set(users)) != len(users):
        raise SplitError("a person appears twice in the split")
    values = dict(entries)

    if split_type == SplitType.EQUAL:
        return _apportion(amount, {u: 1 for u in users})

    if any(v < 0 for v in values.values()):
        raise SplitError("split values cannot be negative")

    if split_type == SplitType.EXACT:
        if sum(values.values()) != amount:
            raise SplitError(f"exact amounts add up to {sum(values.values())} paise, expected {amount}")
        return values

    if split_type == SplitType.PERCENT:
        if sum(values.values()) != 10_000:
            raise SplitError("percentages must add up to 100%")
        return _apportion(amount, values)

    if split_type == SplitType.SHARES:
        if sum(values.values()) == 0:
            raise SplitError("at least one person needs a share")
        return _apportion(amount, values)

    raise SplitError(f"unknown split type {split_type}")
