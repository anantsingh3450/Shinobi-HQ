"""The gate that decides real money had two holes in it.

`live_readiness` measures the commander's own agreed bar - Sharpe >= 1.20,
profit factor >= 1.30, drawdown <= 8%, one confirmed cell - and it is the last
thing between a paper record and his seed capital. Two things were wrong with
it on 2026-11-10.

ONE: IT READ GROSS. Every ratio came from `realized_pnl`, the price
difference. Brokerage is FLAT at 40 rupees a round trip, so it does not cancel
out of a ratio and it falls hardest on the smallest positions - the only ones
this account can afford. Across the ledger charges came to 3.2x the entire
gross profit and moved the profit factor from 1.03 to 0.94. The gate was the
last screen in the system still reading the wrong number, and it is the one
that matters most.

TWO: ONE DAY COULD CARRY IT. The attributed record was +23,458 over 68 trades
at PF 1.40 net, which CLEARS the 1.30 bar. 2026-08-19 alone was +22,416 of it:
five long calls riding one gold trend inside three hours. The other 67 trades,
over twenty-three days, were worth +1,042. Those five positions are one
observation, not five.

The gate already refused to be judged on the 2026-07-15 cascade, on the stated
ground that "a system is not judged on its best day's accounting artifact" -
and then said nothing at all about a best day that was real. A real day is
still n=1.

THE BAR ITSELF IS UNCHANGED. 1.30 is the commander's number and nothing here
moves it. What changed is which arithmetic it is asked of.
"""
from __future__ import annotations

import sys
from pathlib import Path


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "src").is_dir() and (parent / "tests").is_dir():
            return parent
    raise AssertionError("could not find the repository root")


ROOT = _repo_root()
for _p in (ROOT / "src", ROOT / "tools" / "research"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import live_readiness as lr          # noqa: E402
import net_record as nr              # noqa: E402


def _row(pnl: float, *, day: str, entry: float = 100.0, exit_: float = 100.0,
         qty: float = 10.0, charges: float | None = None,
         market: str = "GOLDM26AUG154500CE") -> dict:
    return {
        "market": market,
        "quantity": qty,
        "entry_price": entry,
        "current_price": exit_,
        "realized_pnl": pnl,
        "charges": charges,
        "status": "CLOSED",
        "opened_at": f"{day}T10:00:00",
        "closed_at": f"{day}T11:00:00",
        "account_id": "paper_mcx",
    }


# ------------------------------------------------------- it read gross
def test_the_gate_now_measures_net():
    rows = [_row(1000.0, day="2026-09-01"), _row(-500.0, day="2026-09-02")]
    gross = lr.measure(rows, 200_000.0, pnl_key="realized_pnl")
    net = lr.measure(rows, 200_000.0)
    assert gross["total_pnl"] == 500.0
    assert net["total_pnl"] < gross["total_pnl"], "charges were not deducted"
    assert net["cost_total"] > 0
    assert net["profit_factor"] < gross["profit_factor"]


def test_the_default_is_net_not_gross():
    """A caller that passes no key must get the figure that matches the cash.
    The whole defect was a default nobody stated."""
    rows = [_row(1000.0, day="2026-09-01")]
    assert lr.measure(rows, 200_000.0)["pnl_key"] == "net_pnl"


def test_a_recorded_charge_beats_an_estimate():
    priced = lr.with_net([_row(1000.0, day="2026-09-01", charges=77.0)])[0]
    assert priced["cost"] == 77.0
    assert priced["charges_measured"] is True
    assert priced["net_pnl"] == 923.0


def test_an_absent_charge_is_priced_not_counted_free():
    """Absent is not zero. Every row before 2026-11-09 has NULL here, and
    treating that as free is how the gross era passed for a net record."""
    priced = lr.with_net([_row(1000.0, day="2026-09-01", charges=None)])[0]
    assert priced["cost"] > 0
    assert priced["charges_measured"] is False
    assert priced["net_pnl"] < 1000.0


def test_a_row_with_no_entry_value_is_carried_not_dropped():
    """Nothing to price a percentage against, so it is flagged rather than
    silently costed at zero or thrown away."""
    priced = lr.with_net([_row(50.0, day="2026-09-01", entry=0.0)])[0]
    assert priced["cost_unknown"] is True
    assert priced["net_pnl"] == 50.0


def test_a_flat_row_is_decided_on_gross_and_stays_excluded():
    """The 2026-07-15 cascade opened and closed 208 positions at one price.
    Charges make their net negative; letting that promote them to "losers"
    would be the same artifact flattering the ratios from the other side."""
    rows = [_row(0.0, day="2026-07-15"), _row(0.0, day="2026-07-15"),
            _row(600.0, day="2026-09-01")]
    m = lr.measure(rows, 200_000.0)
    assert m["n"] == 1
    assert m["flats"] == 2
    assert m["win_rate"] == 100.0


def test_the_costing_has_one_definition():
    """The gate and the record must not be able to disagree about the same
    ledger, so the gate imports the pricing rather than restating it."""
    assert lr.cost_for is nr.cost_for
    src = (ROOT / "tools" / "research" / "live_readiness.py").read_text(
        encoding="utf-8")
    code = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    assert "option_round_trip" not in code, "a second copy of the cost rule"


# -------------------------------------------------- one day could carry it
def test_day_concentration_names_the_day_and_what_is_left():
    best, pnl, share, rest = nr.day_concentration(
        {"2026-08-19": 22_416.0, "2026-10-30": 800.0, "2026-11-02": -300.0})
    assert best == "2026-08-19"
    assert pnl == 22_416.0
    assert round(share) == 98
    assert rest == 500.0


def test_concentration_of_nothing_is_not_a_crash():
    assert nr.day_concentration({}) == (None, 0.0, 0.0, 0.0)


def test_a_losing_record_reports_no_share_rather_than_nonsense():
    """"This day is 400% of the total" is arithmetic, not information."""
    best, pnl, share, rest = nr.day_concentration(
        {"2026-11-02": 400.0, "2026-11-03": -900.0})
    assert best == "2026-11-02"
    assert share == 0.0
    assert rest == -900.0


def test_the_best_day_goes_and_the_worst_day_stays():
    """The question is whether the edge survives losing its luck, not whether
    the losses can be tidied away."""
    rows = [_row(9000.0, day="2026-08-19"), _row(-4000.0, day="2026-08-20"),
            _row(300.0, day="2026-09-01")]
    best, kept = lr.without_the_best_day(lr.with_net(rows))
    assert best == "2026-08-19"
    days = {lr._day_of(r) for r in kept}
    assert days == {"2026-08-20", "2026-09-01"}


def test_the_best_day_is_the_day_it_closed():
    """P&L belongs to the session it was booked in, not the one it opened in."""
    row = _row(500.0, day="2026-09-01")
    row["opened_at"] = "2026-08-31T23:00:00"
    assert lr._day_of(row) == "2026-09-01"


def test_a_profit_factor_one_day_carries_now_fails_the_gate():
    """THE REGRESSION TEST FOR THE REAL DEFECT. A record that clears 1.30 on
    the strength of a single session must not read as a system."""
    rows = [_row(22_416.0, day="2026-08-19")]
    rows += [_row(-400.0, day=f"2026-09-{d:02d}") for d in range(1, 21)]
    rows += [_row(500.0, day=f"2026-10-{d:02d}") for d in range(1, 16)]

    whole = lr.measure(rows, 200_000.0)
    assert whole["profit_factor"] >= lr.MIN_PROFIT_FACTOR, (
        "this fixture is meant to PASS the headline bar")

    best, kept = lr.without_the_best_day(lr.with_net(rows))
    assert best == "2026-08-19"
    assert lr.measure(kept, 200_000.0)["profit_factor"] < lr.MIN_PROFIT_FACTOR


def test_the_agreed_bar_was_not_moved():
    """The thresholds are the commander's, from 2026-07-15. This work changed
    what they are measured against, never where they sit."""
    assert lr.MIN_SHARPE == 1.20
    assert lr.MIN_PROFIT_FACTOR == 1.30
    assert lr.MAX_DRAWDOWN_PCT == 8.0
    assert lr.MIN_CONFIRMED_CELLS == 1
    assert lr.MIN_TRADES_FOR_A_VERDICT == 30


def test_the_gate_asks_for_the_bar_without_the_best_day():
    src = (ROOT / "tools" / "research" / "live_readiness.py").read_text(
        encoding="utf-8")
    code = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    assert "without its best day" in code
    assert "without_the_best_day(" in code
    assert code.count("MIN_PROFIT_FACTOR") >= 3, (
        "the bar must be asked of both populations")


def test_the_record_reports_its_own_concentration():
    src = (ROOT / "tools" / "research" / "net_record.py").read_text(
        encoding="utf-8")
    code = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    assert "day_concentration(" in code
    assert "CONCENTRATION" in code
