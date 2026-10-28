from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.money import SplitError, SplitType, compute_shares

A, B, C = (UUID(int=i) for i in (1, 2, 3))


def test_equal_split_hands_out_leftover_paise():
    shares = compute_shares(100_00 + 1, SplitType.EQUAL, [(A, 0), (B, 0), (C, 0)])
    assert sorted(shares.values()) == [33_33, 33_34, 33_34]
    assert sum(shares.values()) == 100_01


def test_percent_split():
    shares = compute_shares(1000_00, SplitType.PERCENT, [(A, 5000), (B, 3000), (C, 2000)])
    assert shares == {A: 500_00, B: 300_00, C: 200_00}


def test_percent_must_total_100():
    with pytest.raises(SplitError):
        compute_shares(100, SplitType.PERCENT, [(A, 5000), (B, 4000)])


def test_exact_must_match_amount():
    with pytest.raises(SplitError):
        compute_shares(1000, SplitType.EXACT, [(A, 400), (B, 500)])
    assert compute_shares(1000, SplitType.EXACT, [(A, 400), (B, 600)]) == {A: 400, B: 600}


def test_shares_split_by_weight():
    assert compute_shares(900, SplitType.SHARES, [(A, 2), (B, 1)]) == {A: 600, B: 300}


def test_duplicate_person_rejected():
    with pytest.raises(SplitError):
        compute_shares(100, SplitType.EQUAL, [(A, 0), (A, 0)])


@given(
    amount=st.integers(min_value=1, max_value=10**10),
    weights=st.lists(st.integers(min_value=0, max_value=1000), min_size=1, max_size=20),
    split=st.sampled_from([SplitType.EQUAL, SplitType.SHARES]),
)
def test_shares_always_sum_to_amount(amount, weights, split):
    if split == SplitType.SHARES and sum(weights) == 0:
        weights[0] = 1
    entries = [(uuid4(), w) for w in weights]
    shares = compute_shares(amount, split, entries)
    assert sum(shares.values()) == amount
    assert all(v >= 0 for v in shares.values())
    if split == SplitType.EQUAL:
        assert max(shares.values()) - min(shares.values()) <= 1
