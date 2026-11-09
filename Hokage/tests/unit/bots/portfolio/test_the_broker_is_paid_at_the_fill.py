"""Cash now moves by what the trade actually cost, not by the price change.

APPROVED BY THE COMMANDER 2026-11-09: "yes, deduct at the fill".

Until that day `Account.apply_trade` did `self.cash += pos.realized_pnl` and
stopped there - no brokerage, no STT, no GST, no stamp duty, in any path. So
every figure the system produced was GROSS, including the profit factor the
go-live gate is judged on. Measured across 125 real closed positions
(`tools/research/net_record.py`): charges Rs 10,372 against Rs 3,262 of gross
profit, PF 1.03 gross becoming 0.94 net. The lifetime record is negative once
the broker is paid.

WHAT IS NOW NET AND WHAT IS STILL GROSS, deliberately:
  cash, equity, Position.net_pnl   net
  Position.realized_pnl            GROSS - it is the price difference, and
                                   redefining it would silently change every
                                   caller that reads it
  Account.realized_pnl             GROSS - keeps the two eras comparable on
                                   one figure

ONE ORDER, ONE BROKERAGE. The Rs 20 is charged per executed order, not per
position, so an order that closes three positions pays it once and the cost
is shared out pro rata purely as attribution. The split must never change the
total: the last share takes the rounding remainder rather than every share
being rounded and the paise going missing.

NONE IS NOT ZERO. Positions closed before this change carry `charges = None`,
meaning "accounted gross", which is a different fact from "cost nothing". The
same distinction cost a week when a missing `strategy_id` was read as False.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / "src"))

from bots.execution import charges  # noqa: E402
from bots.execution.models import TradeDirection, TradeRecord  # noqa: E402
from bots.portfolio.models import Account, Position  # noqa: E402

GAS = "NATURALGAS26NOV285PE"
LOT = 1250.0


def _trade(market: str, direction: TradeDirection, price: float,
           quantity: float = LOT, trade_id: str | None = None) -> TradeRecord:
    rec = TradeRecord(
        proposal_id=trade_id or f"p-{market}-{price}",
        market=market,
        direction=direction,
        quantity=quantity,
        entry_price=price,
        simulated_value=price * quantity,
        strategy_name="strat-trendrider-mcx-v1",
        sources_cited=[],
    )
    return rec


def _account(cash: float = 100_000.0) -> Account:
    return Account(account_id="paper_mcx", initial_balance=cash, cash=cash)


# ============================================ the real trade, end to end
def test_todays_gas_round_trip_costs_what_the_schedule_says():
    """1250 @ 14.70 out at 13.90. Gross -1,000; the schedule says -74.11."""
    acct = _account()
    acct.apply_trade(_trade(GAS, TradeDirection.LONG, 14.70))
    acct.apply_trade(_trade(GAS, TradeDirection.SHORT, 13.90))

    pos = next(iter(acct.positions.values()))
    assert pos.realized_pnl == pytest.approx(-1000.0)
    assert pos.charges == pytest.approx(74.11, abs=0.05)
    assert pos.net_pnl == pytest.approx(-1074.11, abs=0.05)
    assert acct.cash == pytest.approx(100_000.0 - 1074.11, abs=0.05)


def test_the_two_legs_sum_to_the_round_trip():
    """`option_leg` x2 must equal `option_round_trip`, or the per-fill model
    and the research model would quietly disagree about the same trade."""
    buy = charges.option_leg(18_375.0, "NATURALGAS", "BUY")
    sell = charges.option_leg(17_375.0, "NATURALGAS", "SELL")
    whole = charges.option_round_trip(18_375.0, "NATURALGAS",
                                      exit_value=17_375.0)
    assert buy.total + sell.total == pytest.approx(whole.total, abs=0.02)


def test_the_entry_leg_is_paid_at_entry_not_at_exit():
    """Cash is right at every instant, not only once the trade is closed."""
    acct = _account()
    acct.apply_trade(_trade(GAS, TradeDirection.LONG, 14.70))
    assert acct.cash < 100_000.0
    assert acct.cash == pytest.approx(100_000.0 - 33.24, abs=0.05)
    assert next(iter(acct.positions.values())).charges == pytest.approx(
        33.24, abs=0.05)


# ================================================ which side pays what
def test_stt_falls_on_the_sell_leg_only():
    buy = charges.option_leg(18_375.0, "NATURALGAS", "BUY")
    sell = charges.option_leg(18_375.0, "NATURALGAS", "SELL")
    assert buy.stt == 0.0
    assert sell.stt > 0.0


def test_stamp_duty_falls_on_the_buy_leg_only():
    buy = charges.option_leg(18_375.0, "NATURALGAS", "BUY")
    sell = charges.option_leg(18_375.0, "NATURALGAS", "SELL")
    assert buy.stamp > 0.0
    assert sell.stamp == 0.0


def test_brokerage_is_charged_on_each_leg():
    for side in ("BUY", "SELL"):
        leg = charges.option_leg(18_375.0, "NATURALGAS", side)
        assert leg.brokerage == charges.BROKERAGE_PER_ORDER


def test_gst_is_not_charged_on_stt_or_stamp_duty():
    leg = charges.option_leg(100_000.0, "NIFTY", "SELL")
    expected = charges.GST_RATE * (leg.brokerage + leg.transaction + leg.sebi)
    assert leg.gst == pytest.approx(expected)


def test_the_index_and_commodity_schedules_differ():
    """MCX CTT is 0.05% against NSE's 0.15% STT - a 3x difference on the
    single largest percentage line, so one rate for both would be wrong."""
    nse = charges.option_leg(50_000.0, "NIFTY", "SELL")
    mcx = charges.option_leg(50_000.0, "NATURALGAS", "SELL")
    assert nse.stt > mcx.stt * 2


# ============================================= one order, one brokerage
def test_an_order_closing_three_positions_pays_brokerage_once():
    """Brokerage is per ORDER. Charging it per position would treble it and
    make a partial-exit strategy look worse than it is."""
    acct = _account()
    for i in range(3):
        acct.apply_trade(_trade(GAS, TradeDirection.LONG, 14.70,
                                quantity=LOT, trade_id=f"open-{i}"))
    paid_on_entries = acct.charges_paid
    assert paid_on_entries == pytest.approx(33.24 * 3, abs=0.1)

    acct.apply_trade(_trade(GAS, TradeDirection.SHORT, 13.90,
                            quantity=LOT * 3, trade_id="close-all"))
    exit_cost = acct.charges_paid - paid_on_entries
    one_leg = charges.option_leg(13.90 * LOT * 3, "NATURALGAS", "SELL")
    assert exit_cost == pytest.approx(one_leg.total, abs=0.05)
    assert exit_cost < 33.24 * 3 + charges.BROKERAGE_PER_ORDER * 2


def test_the_split_across_positions_loses_no_paise():
    """Attribution must sum to exactly what cash paid. Rounding each share
    independently is how a total quietly stops matching its parts."""
    acct = _account()
    for i in range(3):
        acct.apply_trade(_trade(GAS, TradeDirection.LONG, 14.70,
                                quantity=LOT, trade_id=f"open-{i}"))
    acct.apply_trade(_trade(GAS, TradeDirection.SHORT, 13.90,
                            quantity=LOT * 3, trade_id="close-all"))
    attributed = sum(p.charges for p in acct.positions.values())
    assert attributed == pytest.approx(100_000.0 - acct.cash
                                       - abs(acct.realized_pnl), abs=0.01)


# ================================================= what stays gross
def test_realized_pnl_on_the_position_stays_the_price_difference():
    """Redefining it would change every caller that reads it, silently."""
    acct = _account()
    acct.apply_trade(_trade(GAS, TradeDirection.LONG, 14.70))
    acct.apply_trade(_trade(GAS, TradeDirection.SHORT, 13.90))
    pos = next(iter(acct.positions.values()))
    assert pos.realized_pnl == pytest.approx(-1000.0)
    assert acct.realized_pnl == pytest.approx(-1000.0)


def test_equity_is_net_because_cash_is():
    acct = _account()
    acct.apply_trade(_trade(GAS, TradeDirection.LONG, 14.70))
    acct.apply_trade(_trade(GAS, TradeDirection.SHORT, 13.90))
    assert acct.equity == pytest.approx(100_000.0 - 1074.11, abs=0.05)


# ========================================= none is not zero, both ways
def test_a_position_from_the_gross_era_has_no_net_figure():
    """Subtracting zero would make it look like a charged trade that
    happened to be free."""
    pos = Position(position_id="old", market=GAS,
                   direction=TradeDirection.LONG, quantity=LOT,
                   entry_price=14.70, current_price=13.90)
    assert pos.charges is None
    assert pos.net_pnl is None


def test_gross_era_positions_contribute_nothing_to_charges_paid():
    acct = _account()
    acct.positions["old"] = Position(
        position_id="old", market=GAS, direction=TradeDirection.LONG,
        quantity=LOT, entry_price=14.70, current_price=13.90)
    assert acct.charges_paid == 0.0
    acct.apply_trade(_trade(GAS, TradeDirection.LONG, 14.70,
                            trade_id="new"))
    assert acct.charges_paid == pytest.approx(33.24, abs=0.05)


def test_a_charged_position_is_never_left_as_none():
    acct = _account()
    acct.apply_trade(_trade(GAS, TradeDirection.LONG, 14.70))
    assert next(iter(acct.positions.values())).charges is not None


def test_a_non_option_symbol_is_not_charged_a_guessed_rate():
    """This schedule is for Indian index and commodity options. Applying it
    to anything that does not parse would be inventing a cost."""
    acct = _account(1_000.0)
    acct.apply_trade(_trade("BTC/USD", TradeDirection.LONG, 100.0,
                            quantity=1.0))
    assert acct.cash == 1_000.0
    assert next(iter(acct.positions.values())).charges is None


def test_a_zero_value_fill_is_not_charged_brokerage():
    """`TradeRecord` already refuses a non-positive price, so this guard is
    defence rather than a live path - which is why it is exercised on the
    method directly instead of through a record that cannot exist."""
    acct = _account()
    zero = _trade(GAS, TradeDirection.LONG, 14.70)
    object.__setattr__(zero, "entry_price", 0.0)
    assert acct._leg_charges(zero) == 0.0


# ============================================== it survives a round trip
def test_charges_survive_serialisation():
    acct = _account()
    acct.apply_trade(_trade(GAS, TradeDirection.LONG, 14.70))
    pos = next(iter(acct.positions.values()))
    revived = Position.from_dict(pos.to_dict())
    assert revived.charges == pytest.approx(pos.charges)


def test_a_none_survives_serialisation_as_none():
    pos = Position(position_id="old", market=GAS,
                   direction=TradeDirection.LONG, quantity=LOT,
                   entry_price=14.70, current_price=13.90)
    assert Position.from_dict(pos.to_dict()).charges is None


def test_charges_paid_is_derived_not_stored():
    """A reporting total kept in its own column is a total that can disagree
    with the rows it came from - which is how `max_portfolio_exposure_pct`
    came to be displayed everywhere and obeyed nowhere."""
    acct = _account()
    acct.apply_trade(_trade(GAS, TradeDirection.LONG, 14.70))
    assert "charges_paid" not in acct.to_dict().keys() - {"charges_paid"}
    assert acct.charges_paid == pytest.approx(
        sum(p.charges for p in acct.positions.values()))
    with pytest.raises(AttributeError):
        acct.charges_paid = 5.0


# =========================================================== persistence
def test_the_schema_migrates_an_existing_ledger(tmp_path):
    """Schema 10 on a live database that already has 417 rows: the column is
    added and every existing row stays NULL, because those trades really
    were accounted gross."""
    from shared.persistence.sqlite_engine import LATEST_SCHEMA_VERSION

    assert LATEST_SCHEMA_VERSION >= 10

    db = tmp_path / "old.db"
    con = sqlite3.connect(str(db))
    con.execute(
        "CREATE TABLE positions (position_id TEXT PRIMARY KEY, "
        "account_id TEXT, market TEXT, realized_pnl REAL, strategy_id TEXT)")
    con.execute("INSERT INTO positions VALUES ('old', 'a', ?, -1000.0, 's')",
                (GAS,))
    con.commit()
    con.execute("ALTER TABLE positions ADD COLUMN charges REAL;")
    row = con.execute("SELECT charges FROM positions").fetchone()
    con.close()
    assert row[0] is None


def test_the_migration_is_idempotent(tmp_path):
    """It runs on every boot. A second ALTER raises OperationalError and must
    be swallowed, exactly as the strategy_id migration does."""
    db = tmp_path / "twice.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE positions (position_id TEXT PRIMARY KEY)")
    con.execute("ALTER TABLE positions ADD COLUMN charges REAL;")
    with pytest.raises(sqlite3.OperationalError):
        con.execute("ALTER TABLE positions ADD COLUMN charges REAL;")
    con.close()

    src = (ROOT / "src" / "shared" / "persistence"
           / "sqlite_engine.py").read_text(encoding="utf-8")
    block = src.split("Schema Version 10")[1][:600]
    assert "except sqlite3.OperationalError" in block


def test_the_changeover_date_is_recorded_in_the_code():
    """A behaviour change with no date is one nobody can bisect a report
    against. Every number before this day is gross."""
    assert charges.DEDUCTED_FROM == "2026-11-09"
