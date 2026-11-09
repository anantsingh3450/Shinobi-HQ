"""The cost model, and the two ways it could quietly be wrong.

2026-11-09, Phase 1. Every P&L figure Hokage reports is gross, so the question
"does the edge beat the cost" had never been asked with real numbers. Two
traps, both hit on the way to answering it:

1. REMEMBERED RATES. Third-party brokerage calculators disagreed by a factor
   of 2.4 on the largest line - options STT read as 0.0625% on several pages
   and 0.15% on the broker's own. A go-live decision cannot rest on whichever
   page ranked first, so every rate here is quoted from zerodha.com/charges
   with the date it was read.

2. A WRONG LOT SIZE. Brokerage is FLAT, so cost as a percentage is entirely a
   function of turnover. Kite's instrument dump reports `lot_size=1` for MCX
   contracts - the known defect that parked the commodity league - and reading
   it straight priced a NATURALGAS round trip at 320% of premium and CRUDEOIL
   at 15%. Both were pure fabrication: 40 rupees divided by fifteen instead of
   by eighteen thousand. A missing number must read as missing.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from bots.execution import charges as ch  # noqa: E402


# ======================================================= the published rates
def test_the_rates_carry_their_source_and_date():
    """A rate that has moved is a wrong answer, not a stale one - so the
    reader has to be able to see how old it is."""
    assert ch.RATES_SOURCE == "zerodha.com/charges"
    assert ch.RATES_READ_ON == "2026-11-09"


def test_options_stt_is_the_brokers_number_not_the_calculators():
    """0.15% of premium on the sell side. Several calculator sites say
    0.0625%, which is 2.4x lighter and would make a losing cell look
    profitable."""
    assert ch.RATES["NSE"].stt == 0.0015
    assert ch.RATES["MCX"].stt == 0.0005


def test_brokerage_is_flat_per_order():
    assert ch.BROKERAGE_PER_ORDER == 20.0
    rt = ch.option_round_trip(100_000, "NIFTY")
    assert rt.brokerage == 40.0          # two executed orders


# ============================================== which side each charge falls on
def test_stt_falls_on_the_sell_side_only():
    """Charged on the EXIT turnover. An exit at half the entry pays half the
    STT, which a single-sided model would get wrong in the direction that
    flatters a loss."""
    small_exit = ch.option_round_trip(20_000, "NIFTY", exit_value=10_000)
    flat = ch.option_round_trip(20_000, "NIFTY")
    assert small_exit.stt == pytest.approx(flat.stt / 2)


def test_stamp_duty_falls_on_the_buy_side_only():
    a = ch.option_round_trip(20_000, "NIFTY", exit_value=10_000)
    b = ch.option_round_trip(20_000, "NIFTY", exit_value=40_000)
    assert a.stamp == b.stamp == pytest.approx(0.00003 * 20_000)


def test_transaction_charges_fall_on_both_sides():
    rt = ch.option_round_trip(20_000, "NIFTY")
    assert rt.transaction == pytest.approx(0.0003553 * 40_000)


def test_gst_excludes_stt_and_stamp_duty():
    """18% on brokerage + transaction + SEBI. Charging it on STT would
    overstate cost, and this model exists to be trusted in both directions."""
    rt = ch.option_round_trip(20_000, "NIFTY")
    expected = 0.18 * (rt.brokerage + rt.transaction + rt.sebi)
    assert rt.gst == pytest.approx(expected)
    assert rt.gst < 0.18 * rt.total      # sanity: it is not on everything


# ====================================== the flat-fee effect, stated as a test
def test_a_smaller_position_costs_a_larger_percentage():
    """THE FINDING THAT MATTERS AT THIS ACCOUNT SIZE. Flat brokerage means
    trading smaller is dearer, not cheaper - the opposite of the intuition a
    small account brings."""
    small = ch.option_round_trip(14_000, "SENSEX").pct_of_premium
    large = ch.option_round_trip(140_000, "SENSEX").pct_of_premium
    assert small > large
    assert small > 2 * large


def test_brokerage_is_the_biggest_line_at_this_size():
    """On a one-lot index trade, 40 rupees of brokerage outweighs STT. That
    is why the answer changes with position size and not only with rates."""
    lines = ch.option_round_trip(17_810, "NIFTY").breakdown()
    assert lines[0][0] == "brokerage"


def test_the_breakdown_is_ordered_and_adds_up():
    rt = ch.option_round_trip(25_000, "GOLDM")
    lines = rt.breakdown()
    assert [v for _, v, _ in lines] == sorted((v for _, v, _ in lines),
                                              reverse=True)
    assert sum(v for _, v, _ in lines) == pytest.approx(rt.total)


# ========================================================== segment routing
@pytest.mark.parametrize("underlying,segment", [
    ("NIFTY", "NSE"), ("BANKNIFTY", "NSE"), ("SENSEX", "NSE"),
    ("CRUDEOIL", "MCX"), ("NATURALGAS", "MCX"), ("GOLDM", "MCX"),
    ("SILVERM", "MCX"), ("nifty", "NSE"), ("goldm", "MCX"),
])
def test_every_underlying_routes_to_its_own_schedule(underlying, segment):
    assert ch.segment_for(underlying) == segment


def test_an_unknown_underlying_is_treated_as_equity():
    """The archive's universe is equity-segment by default, same convention
    as option_archive's CALENDAR_SEGMENT."""
    assert ch.segment_for("SOMETHINGNEW") == "NSE"


def test_mcx_is_cheaper_on_stt_and_dearer_on_transaction():
    """Not symmetry for its own sake - the two segments genuinely differ, and
    a single blended rate would be wrong for both."""
    assert ch.RATES["MCX"].stt < ch.RATES["NSE"].stt
    assert ch.RATES["MCX"].transaction > ch.RATES["NSE"].transaction


# ================================================================ edge cases
def test_zero_turnover_does_not_divide_by_zero():
    rt = ch.option_round_trip(0, "NIFTY")
    assert rt.pct_of_premium == 0.0
    assert rt.total > 0                  # brokerage is still charged


def test_a_negative_premium_is_floored_not_trusted():
    assert ch.option_round_trip(-500, "NIFTY").turnover == 0.0


def test_breakeven_is_the_round_trip_cost():
    assert ch.breakeven_move_pct(20_000, "NIFTY") == pytest.approx(
        ch.option_round_trip(20_000, "NIFTY").pct_of_premium)


# ===================================== it does not touch the ledger, yet
def test_nothing_in_the_trading_path_subtracts_this_yet():
    """Subtracting these from historical P&L would rewrite every number the
    commander has ever been shown. That is his call to make knowingly, not
    mine to slip in - so the model measures and nothing imports it into a
    fill path until that is announced."""
    import ast

    hits = []
    for path in (ROOT / "src").rglob("*.py"):
        if path.name == "charges.py":
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and "charges" in (node.module or ""):
                hits.append(path.name)
    assert not hits, f"charges is now wired into: {hits} - was that announced?"


def test_the_lab_refuses_an_unusable_lot_size():
    """The fabrication guard. A lot size of 1 on an option is the MCX dump
    defect, and dividing flat brokerage by one lot-unit invented a cost of
    320% of premium."""
    src = (ROOT / "tools" / "research" / "spread_lab.py").read_text(
        encoding="utf-8")
    assert "if lot <= 1:" in src
    assert "LOT SIZE UNUSABLE" in src
    assert "resolve_option_contract" in src
