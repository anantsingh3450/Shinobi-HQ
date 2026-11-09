"""The paper books carry seven times the real account.

2026-11-09. Every live strategy holds a full 1,00,000 chest, and after
NATURALGAS was unparked there are seven of them - one on the index book, six
on MCX. So the books allocate 7,00,000 against a real seed of 1,00,000.

The percentage measurements are untouched by this, which is exactly why it
went unnoticed: an edge of 1.64% of premium is 1.64% at any account size. What
is wrong is every RUPEE figure and every risk check built on one - the
"every competing strategy can afford to trade" audit passes against chests
that do not exist, and a drawdown limit of 8% is measured against seven times
the money.

TWO SIZING RULES, AND THEY DISAGREE BY A FACTOR OF THREE. Splitting the
account evenly means every chest must survive the dearest lot any strategy
might take, so a GOLDM lot at 27,515 forces an 83,379 chest on all of them.
Sizing each chest to its own asset's lot funds the same arena for 229,591
instead of 333,515 - and on a 1,00,000 account it is the difference between
one concurrent asset and two.

LOTS ARE INDIVISIBLE, which is what makes this arithmetic awkward rather than
a division. A chest only functions if the premium cap still buys one whole
lot, so shrinking a chest does not shrink a position - it removes it. That is
the same wall the 20,000 seed hit.

These tests pin the arithmetic, not the prices. Premiums move every day; the
rules by which capital is committed must not move with them.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

import capital_lab  # noqa: E402

from bots.execution.options_router import MAX_PREMIUM_CHEST_FRACTION  # noqa: E402
from hokage.research import funded_cells  # noqa: E402


# ============================================= a chest must buy a WHOLE lot
def test_the_chest_a_lot_needs_is_the_lot_over_the_cap():
    """A 27,515 GOLDM lot inside a 33% cap needs 83,379, not 27,515."""
    assert capital_lab.chest_needed_for(27_515.0) == pytest.approx(
        27_515.0 / MAX_PREMIUM_CHEST_FRACTION)
    assert capital_lab.chest_needed_for(27_515.0) > 80_000


def test_a_chest_too_small_for_one_lot_funds_nothing():
    """Not a smaller position - no position. The premium cap cannot buy a
    fraction of a lot, so a 25,000 chest is not 'GOLDM at reduced size'."""
    assert capital_lab.max_concurrent(25_000.0, [27_515.0]) == 0
    assert capital_lab.max_concurrent_per_asset(
        25_000.0, {"GOLDM": 27_515.0}) == []


def test_an_even_split_is_bound_by_the_dearest_lot():
    """THE TRAP IN DIVIDING BY N. Three cheap assets and one dear one do not
    average out: every chest has to survive the dear one."""
    lots = {"SENSEX": 12_039.0, "NIFTY": 17_024.0,
            "NATURALGAS": 19_188.0, "GOLDM": 27_515.0}
    # 4 chests of 25,000 give a 8,250 cap - under even the cheapest lot.
    assert capital_lab.max_concurrent(100_000.0, list(lots.values())) == 1


def test_sizing_per_asset_beats_an_even_split():
    """Same arena, same cap, far less capital - because a cheap asset stops
    being provisioned for an expensive one's lot."""
    lots = {"SENSEX": 12_039.0, "NIFTY": 17_024.0,
            "NATURALGAS": 19_188.0, "GOLDM": 27_515.0}
    even = capital_lab.max_concurrent(100_000.0, list(lots.values()))
    per = capital_lab.max_concurrent_per_asset(100_000.0, lots)
    assert len(per) > even
    assert per == ["SENSEX", "NIFTY"]


def test_the_cheapest_assets_are_taken_first():
    """Cheapest-first is what maximises the count. Any other order funds
    fewer assets with the same money."""
    lots = {"DEAR": 90_000.0, "CHEAP": 3_300.0, "MID": 16_500.0}
    assert capital_lab.max_concurrent_per_asset(60_000.0, lots) == [
        "CHEAP", "MID"]


def test_nothing_priced_means_no_arithmetic():
    """Absent is not zero. An unpriced lot must not read as a free one."""
    assert capital_lab.max_concurrent(100_000.0, []) == 0
    assert capital_lab.max_concurrent_per_asset(100_000.0, {}) == []


# ===================================== what the concurrency bound is built on
def test_concurrency_is_bounded_by_assets_not_strategies():
    """Winner-take-asset. Six gas strategies cannot hold six gas positions,
    so the exposure denominator is the scannable ASSET count - which is why
    unparking gas added one unit of concurrent risk and not five."""
    assets = capital_lab.scannable_assets()
    assert set(assets) == (funded_cells.funded_assets()
                           | set(funded_cells.TRADED_FOR_THE_RECORD))
    assert "NATURALGAS" in assets
    for parked in funded_cells.PARKED_FOR_COST:
        assert parked not in assets, (
            "a chest held for an asset the scan loop never reaches is capital "
            "committed against nothing")


def test_the_real_seed_is_stated_not_read_from_the_books():
    """Reading the seed from the portfolio would make the tool agree with the
    thing it exists to check."""
    assert capital_lab.DEFAULT_CAPITAL == 100_000.0
    src = (ROOT / "tools" / "research" / "capital_lab.py").read_text(
        encoding="utf-8")
    flat = " ".join(src.split())
    assert "the books are what this tool exists to check" in flat


# ================================================ flat brokerage, small sizes
def test_shrinking_a_position_raises_its_percentage_cost():
    """40 rupees is fixed. This is the reason 'just trade smaller' is not an
    answer to a capital shortfall: the measured edges are 1.06-1.64% of
    premium, and a 5,000 position pays 1.10% in charges alone."""
    from bots.execution import charges

    small = charges.option_round_trip(5_000.0, "GOLDM").pct_of_premium
    large = charges.option_round_trip(50_000.0, "GOLDM").pct_of_premium
    assert small > large * 3
    assert small > 1.0, "a 5,000 lot pays more than a full percent in charges"


def test_a_one_lot_size_is_refused_rather_than_priced():
    """Kite reports lot_size=1 for MCX contracts, and reading it straight once
    priced a gas round trip at 320% of premium. A lot size of 1 on an options
    contract is a missing number, not a cheap lot."""
    src = (ROOT / "tools" / "research" / "capital_lab.py").read_text(
        encoding="utf-8")
    assert "lot <= 1" in src
    assert "unusable" in src
    flat = " ".join(src.split())
    assert "not a cheap lot, it is a missing one" in flat


def test_the_lab_changes_no_risk_constant():
    """It reports. Chest sizes and the premium cap move on his word alone."""
    src = (ROOT / "tools" / "research" / "capital_lab.py").read_text(
        encoding="utf-8")
    assert "MAX_PREMIUM_CHEST_FRACTION =" not in src, (
        "the lab must import the cap, never define its own")
    flat = " ".join(src.split())
    assert "This tool reports; it changes nothing" in flat


# ============================ ONE LAKH IS THE ACCOUNT, NOT A CHEST (corrected)
# The first version of the lab carved the seed into per-strategy chests and
# applied the 33% cap INSIDE each one. On one pooled account that compounds to
# cap = 33%/N: 8.25% at four assets, which no lot in the universe fits under.
# It made a 27,440 GOLDM lot look like it needed 83,152 of capital, and put
# the four-asset arena at 3,33,515 when the honest figure is a fraction of it.
#
# Read correctly, every lot fits inside a single 33% cap of the pool, so the
# cap does not bind at all. What binds is how much can be LOST at once.

def test_every_lot_fits_inside_the_cap_on_a_pooled_account():
    """The correction, stated as arithmetic. GOLDM is the dearest lot in the
    universe at 27,440 and the cap on a 1,00,000 pool is 33,000."""
    cap = 100_000.0 * MAX_PREMIUM_CHEST_FRACTION
    for lot in (12_039.0, 17_024.0, 19_375.0, 27_440.0):
        assert lot <= cap


def test_the_chest_model_is_three_times_dearer_than_the_pool():
    """Same arena, same cap, same lots - and a 3x difference in the capital it
    appears to need, purely from where the fraction is applied."""
    lots = [12_039.0, 17_024.0, 19_375.0, 27_440.0]
    split = len(lots) * capital_lab.chest_needed_for(max(lots))
    pooled = sum(lots)
    assert split > pooled * 3


def test_the_budget_comes_from_the_loss_not_the_cap():
    """8% of 1,00,000 is 8,000. If a stop costs 28.36% of premium, 8,000 of
    loss is 28,204 of premium - and that, not 33,000, is the real limit."""
    budget = capital_lab.premium_budget(100_000.0, 8.0, 28.36)
    assert budget == pytest.approx(28_204.0, abs=5.0)
    assert budget < 100_000.0 * MAX_PREMIUM_CHEST_FRACTION


def test_a_gentler_loss_assumption_buys_more_concurrency():
    """Not a different calculation - a different question about risk."""
    harsh = capital_lab.premium_budget(100_000.0, 8.0, 28.36)
    p90 = capital_lab.premium_budget(100_000.0, 8.0, 16.80)
    median = capital_lab.premium_budget(100_000.0, 8.0, 7.76)
    assert harsh < p90 < median
    lots = {"SENSEX": 12_039.0, "NIFTY": 17_024.0,
            "NATURALGAS": 19_375.0, "GOLDM": 27_440.0}
    assert capital_lab.fit_within(harsh, lots) == ["SENSEX"]
    assert capital_lab.fit_within(p90, lots) == ["SENSEX", "NIFTY"]
    assert len(capital_lab.fit_within(median, lots)) == 4


def test_a_zero_loss_assumption_buys_nothing_rather_than_everything():
    """Dividing by a zero loss would report an infinite budget. A loss nobody
    has measured is not a loss of zero."""
    assert capital_lab.premium_budget(100_000.0, 8.0, 0.0) == 0.0


def test_the_losses_are_measured_and_phantoms_are_excluded():
    """292 phantom rows closed at entry. Counting them would pull every
    percentile toward zero and make the account look safer than it is."""
    src = (ROOT / "tools" / "research" / "capital_lab.py").read_text(
        encoding="utf-8")
    body = src.split("def measured_losses")[1].split("def loss_at")[0]
    assert "PHANTOM" in body
    assert "upper(status) = 'CLOSED'" in body
    assert "FROM positions" in body and "FROM trades" not in body


def test_the_worst_quantile_is_the_worst_loss():
    losses = [-1.0, -5.0, -9.0, -28.36]
    assert capital_lab.loss_at(losses, 1.0) == pytest.approx(28.36)
    assert capital_lab.loss_at(losses, 0.0) == pytest.approx(1.0)
    assert capital_lab.loss_at([], 1.0) is None


def test_the_drawdown_mandate_is_the_gate_s_own_constant():
    """8% must not be retyped here. A second copy would let the lab and the
    go-live gate disagree about the same limit."""
    from live_readiness import MAX_DRAWDOWN_PCT as gate

    assert capital_lab.MAX_DRAWDOWN_PCT == gate
    src = (ROOT / "tools" / "research" / "capital_lab.py").read_text(
        encoding="utf-8")
    assert "MAX_DRAWDOWN_PCT = " not in src


def test_the_pooled_reading_is_stated_in_the_docstring():
    src = (ROOT / "tools" / "research" / "capital_lab.py").read_text(
        encoding="utf-8")
    flat = " ".join(src.split())
    assert "ONE LAKH IS THE WHOLE ACCOUNT, NOT A CHEST" in flat
    assert "the cap does not bind" in flat or "not what binds" in flat
