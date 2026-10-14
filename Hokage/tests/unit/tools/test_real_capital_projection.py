"""Hokage learns on 250,000 of paper against a real seed of 30,000.

Paper chests are 50,000 (Index Dojo) and 200,000 (MCX Arena). Every position
size he has chosen, every drawdown percentage he has reported and every
affordability call he has made was taken at a scale the commander will not
have for years.

THE OBVIOUS FIX IS A TRAP, and it is worth stating because someone will try
it: setting the paper chests to 30,000 makes him honest and useless in one
stroke. The cheapest option lot in his universe costs 10,748 and production
caps premium at 33% of the account, so a 30,000 account cannot place a SINGLE
order. He would take zero paper trades, learn nothing, and produce no record.

So he keeps learning at a scale that generates trades, and this reports
separately what the real plan would have done over the same tape. Replayed
against the record Hokage actually produced:

    trades in record  90
      affordable      10
      SKIPPED         80   could not afford one lot
    paid in       50,000   (30,000 seed + 20,000 contributed)
    ended with    44,024
    trading P&L   -5,976

89% of his trades were out of reach, and the ten that were not lost a fifth of
the original seed. That is the honest state of the plan, and it is the number
that should drive decisions rather than a paper equity curve run on money that
does not exist.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
from datetime import date

import pytest

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents
            if (p / "pyproject.toml").is_file())
sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location(
    "real_capital_projection",
    ROOT / "tools" / "research" / "real_capital_projection.py",
)
rcp = importlib.util.module_from_spec(_spec)
sys.modules["real_capital_projection"] = rcp
_spec.loader.exec_module(rcp)


def _pos(day, qty, price, pnl):
    return {"opened_at": f"{day}T10:00:00+00:00", "quantity": qty,
            "entry_price": price, "realized_pnl": pnl}


# ------------------------------------------------- the plan is the commander's
def test_the_plan_matches_what_was_stated():
    """30,000 initial and 10,000 a month, stated 2026-10-14."""
    assert rcp.DEFAULT_SEED == 30_000.0
    assert rcp.DEFAULT_MONTHLY == 10_000.0


def test_the_premium_cap_is_read_from_production_not_assumed():
    """The whole point is to apply the REAL constraint. A local 0.33 would
    drift the moment production changed its cap."""
    src = (ROOT / "tools" / "research" / "real_capital_projection.py").read_text(
        encoding="utf-8"
    )
    assert "MAX_PREMIUM_CHEST_FRACTION" in src
    cap = rcp._premium_cap()
    assert 0 < cap <= 1


# ----------------------------------------------- affordability actually bites
def test_a_trade_beyond_the_cap_is_skipped_not_taken():
    """THE BINDING CONSTRAINT. 80 of 90 real trades were out of reach, and a
    projection that quietly took them would be the paper fiction again."""
    out = rcp.project([_pos("2026-07-16", 1, 20_000, 5_000)],
                      seed=30_000, monthly=0, cap=0.33)
    assert out["taken"] == 0
    assert out["skipped"] == 1
    assert out["equity"] == 30_000, "a skipped trade must not move the account"


def test_a_trade_inside_the_cap_is_taken_with_its_real_pnl():
    """Paper positions are one lot, so the rupee outcome transfers directly -
    nothing is scaled or modelled."""
    out = rcp.project([_pos("2026-07-16", 1, 9_000, 1_500)],
                      seed=30_000, monthly=0, cap=0.33)
    assert out["taken"] == 1
    assert out["equity"] == pytest.approx(31_500)


def test_the_account_growing_makes_later_trades_affordable():
    """The contribution is the engine. A trade out of reach in month one must
    become reachable once enough has been paid in."""
    trades = [_pos("2026-07-16", 1, 20_000, 0), _pos("2027-07-16", 1, 20_000, 0)]
    out = rcp.project(trades, seed=30_000, monthly=10_000, cap=0.33)
    assert out["skipped"] == 1, "the first was unaffordable"
    assert out["taken"] == 1, "the second became affordable through contributions"


def test_never_affordable_is_reported_as_NEVER():
    out = rcp.project([_pos("2026-07-16", 1, 99_000, 0)],
                      seed=30_000, monthly=0, cap=0.33)
    assert out["first_affordable"] is None


# -------------------------------------------------- the contribution schedule
def test_contributions_credit_monthly_from_the_first_trade():
    assert rcp._months_between(date(2026, 7, 16), date(2026, 7, 16)) == 0
    assert rcp._months_between(date(2026, 7, 16), date(2026, 8, 15)) == 0
    assert rcp._months_between(date(2026, 8, 16), date(2026, 8, 16)) == 0
    assert rcp._months_between(date(2026, 7, 16), date(2026, 8, 16)) == 1
    assert rcp._months_between(date(2026, 7, 16), date(2027, 7, 16)) == 12


def test_a_contribution_is_never_counted_twice():
    """Credited by TOTAL OWED at the trade's date, not per trade, so several
    trades in one month cannot each add 10,000.

    The schedule starts at the first trade, so month zero contributes nothing -
    the seed is the month-zero payment.
    """
    trades = [
        _pos("2026-07-16", 1, 1_000, 0),   # month 0, nothing owed yet
        _pos("2026-08-20", 1, 1_000, 0),   # month 1
        _pos("2026-08-21", 1, 1_000, 0),   # still month 1
        _pos("2026-08-28", 1, 1_000, 0),   # still month 1
    ]
    out = rcp.project(trades, seed=30_000, monthly=10_000, cap=0.99)
    assert out["taken"] == 4
    assert out["contributed"] == 10_000, (
        "three trades in month 1 must credit one contribution, not three"
    )


def test_month_zero_contributes_nothing_because_the_seed_is_that_payment():
    out = rcp.project([_pos("2026-07-16", 1, 1_000, 0)],
                      seed=30_000, monthly=10_000, cap=0.99)
    assert out["contributed"] == 0.0
    assert out["invested"] == 30_000


def test_invested_separates_contributions_from_trading():
    """"Up 14,000" means nothing if 20,000 of it was paid in. The two must
    never be added together and called performance."""
    out = rcp.project([_pos("2026-07-16", 1, 5_000, 2_000)],
                      seed=30_000, monthly=10_000, cap=0.99)
    assert out["invested"] == 30_000 + out["contributed"]
    assert out["pnl"] == pytest.approx(out["equity"] - out["invested"])


# ------------------------------------------------------- it is not a forecast
def test_the_cascade_day_is_excluded():
    """208 positions on one CRUDEOIL strike inside two minutes at zero P&L.
    Including them is how +19,737 was believed for three months."""
    assert rcp.CASCADE_DAY == "2026-07-15"
    src = (ROOT / "tools" / "research" / "real_capital_projection.py").read_text(
        encoding="utf-8"
    )
    assert "substr(opened_at,1,10) != ?" in src


def test_it_says_it_is_not_a_forecast():
    doc = rcp.__doc__ or ""
    assert "not a forecast" in doc.lower()
    assert "0.92" in doc, "it must name the profit factor it is replaying"


def test_a_zero_outlay_row_is_skipped_rather_than_counted_free():
    """A position with no premium recorded is missing data. Treating it as a
    free trade would hand the projection trades the real account never paid
    for."""
    out = rcp.project([_pos("2026-07-16", 0, 0, 5_000)],
                      seed=30_000, monthly=0, cap=0.33)
    assert out["taken"] == 0 and out["skipped"] == 0


def test_an_empty_record_does_not_invent_a_curve():
    assert rcp.project([], 30_000, 10_000, 0.33) == {"trades": 0}
