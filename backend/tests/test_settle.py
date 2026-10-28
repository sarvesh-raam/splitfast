from hypothesis import given, settings
from hypothesis import strategies as st

from app.settle import EXACT_LIMIT, _greedy, minimize, naive_transfer_count


def apply(balances, transfers):
    left = dict(balances)
    for t in transfers:
        assert t.amount > 0
        assert left[t.debtor] < 0 < left[t.creditor], "payments only flow from debtors to creditors"
        left[t.debtor] += t.amount
        left[t.creditor] -= t.amount
    return left


def test_chain_collapses_to_one_payment():
    # A owes B 100, B owes C 100  =>  A pays C directly.
    balances = {"A": -100, "B": 0, "C": 100}
    assert [(t.debtor, t.creditor, t.amount) for t in minimize(balances)] == [("A", "C", 100)]


def test_exact_beats_greedy_on_splittable_groups():
    # Two independent pairs hidden inside one group: {a:-5, b:+5} and {c:-3, d:-4, e:+7}.
    # Greedy pairs the largest amounts first and needs 4 payments; the optimum is 3.
    balances = {"a": -5, "b": 5, "c": -3, "d": -4, "e": 7}
    assert len(_greedy(balances)) >= len(minimize(balances))
    assert len(minimize(balances)) == 3


def test_unsplittable_group_needs_n_minus_one():
    balances = {"p1": 6, "p2": 4, "q1": -5, "q2": -5}
    # p1+p2 = q1+q2 = 10, no smaller zero-sum subset, so 3 payments is optimal.
    assert len(minimize(balances)) == 3


def test_naive_count_nets_opposite_debts():
    assert naive_transfer_count({("A", "B"): 50, ("B", "A"): 50}) == 0
    assert naive_transfer_count({("A", "B"): 50, ("B", "A"): 20, ("C", "A"): 5}) == 2


balance_lists = st.lists(st.integers(min_value=-50_000, max_value=50_000), min_size=1, max_size=EXACT_LIMIT - 1)


@settings(max_examples=300, deadline=None)
@given(balance_lists)
def test_minimize_settles_everyone(values):
    values = values + [-sum(values)]  # make it zero-sum
    balances = {f"u{i}": v for i, v in enumerate(values)}
    transfers = minimize(balances)
    assert all(v == 0 for v in apply(balances, transfers).values())
    nonzero = sum(1 for v in values if v)
    assert len(transfers) <= max(nonzero - 1, 0)
    assert len(transfers) <= len(_greedy(balances))


@settings(max_examples=200, deadline=None)
@given(st.lists(st.integers(min_value=-1000, max_value=1000), min_size=EXACT_LIMIT + 1, max_size=40))
def test_large_groups_fall_back_to_greedy(values):
    values = values + [-sum(values)]
    balances = {f"u{i}": v for i, v in enumerate(values)}
    transfers = minimize(balances)
    assert all(v == 0 for v in apply(balances, transfers).values())
    assert len(transfers) <= max(sum(1 for v in values if v) - 1, 0)
