"""The broker has been paid since 2026-11-09 and no screen said so.

`Account.apply_trade` started deducting brokerage, STT, GST, stamp duty and
the exchange/SEBI fees on 2026-11-09, so cash and equity became net that day.
Everything that displays a P&L kept reading `realized_pnl`, which is GROSS by
design - it is the price difference, kept unredefined so the pre- and
post-charge eras stay comparable on one figure. The result was a system whose
cash was net and whose every reported profit was gross.

THE SIZE OF IT. Across 125 real closed positions charges came to Rs 10,372
against Rs 3,262 of gross profit: 3.2x the entire gross profit, a profit
factor of 1.03 gross and 0.94 net. The lifetime record is negative once the
broker is paid. On a dashboard, "gross" is not a rounding difference - it is
the sign.

THE WAR CHEST WAS WORSE THAN A DISPLAY. `get_capital_report` computed
`available = starting + realized_pnl - deployed` from the gross total, and
`_strategy_available_capital` feeds that straight into order sizing. Every
chest believed it held more than the account did, and would have sized the
next order on the difference. There was no visible drift to catch it either:
the arena's reconciliation panel compared chest totals against
`initial_balance + realized_pnl`, gross on both sides, so the one number that
could have exposed this agreed with itself.

Nothing read `Position.net_pnl` or `Account.charges_paid` anywhere outside the
model that defined them. A grep for both returned the definitions and nothing
else.

NONE IS NOT ZERO, throughout. The 417 positions closed before charge
accounting carry `charges = None`, meaning "accounted gross" - a different
fact from "cost nothing". Every net figure here therefore travels with a
count of the rows that have no charge to subtract, and a part-closed position
reports None rather than a share of a cost that cannot be split.
"""
from __future__ import annotations

import io
from pathlib import Path

import pytest

from bots.execution.models import TradeDirection, TradeRecord, TradeStatus
from bots.portfolio.models import Account, Position, TradeApplication
from bots.portfolio.portfolio_bot import PortfolioBot
from bots.strategy.portfolio import StrategyPortfolioManager
from hokage.dashboard.models import PortfolioOverview, PositionSnapshot

ROOT = Path(__file__).resolve().parents[4]
GAS = "NATURALGAS26NOV285PE"
LOT = 1250.0


def _trade(direction: TradeDirection, price: float, quantity: float = LOT,
           market: str = GAS) -> TradeRecord:
    return TradeRecord(
        proposal_id=f"p-{market}-{price}-{direction}",
        market=market,
        direction=direction,
        quantity=quantity,
        entry_price=price,
        simulated_value=price * quantity,
        strategy_name="strat-trendrider-mcx-v1",
        sources_cited=[],
    )


def _round_trip(cash: float = 100_000.0) -> Account:
    """The real 2026-11-09 gas trade: 1250 @ 14.70 out at 13.90."""
    acct = Account(account_id="paper_mcx", initial_balance=cash, cash=cash)
    acct.apply_trade(_trade(TradeDirection.LONG, 14.70))
    acct.apply_trade(_trade(TradeDirection.SHORT, 13.90))
    return acct


# ===================================================== the account's own figures
def test_the_account_can_state_a_net_realized_figure():
    acct = _round_trip()
    assert acct.realized_pnl == pytest.approx(-1000.0)
    assert acct.charges_paid == pytest.approx(74.11, abs=0.05)
    assert acct.net_realized_pnl == pytest.approx(-1074.11, abs=0.05)


def test_the_gross_figure_is_left_alone():
    """Redefining it would silently change every caller that reads it, and
    would destroy the one number the two accounting eras share."""
    acct = _round_trip()
    assert acct.realized_pnl != acct.net_realized_pnl


def test_net_equals_gross_for_the_era_that_was_never_charged():
    """And the count says why, so the total cannot imply it covers history
    it does not."""
    acct = Account(account_id="paper", initial_balance=200_000.0, cash=193_988.5)
    acct.realized_pnl = -6_011.5
    acct.positions["old"] = Position(
        position_id="old", market="NIFTY2680424300CE",
        direction=TradeDirection.LONG, quantity=65.0, entry_price=91.85,
        current_price=90.0, status=TradeStatus.CLOSED,
    )
    assert acct.positions["old"].charges is None
    assert acct.charges_paid == 0.0
    assert acct.net_realized_pnl == acct.realized_pnl
    assert acct.gross_era_closed == 1


def test_an_open_position_is_not_counted_as_a_gross_era_row():
    acct = Account(account_id="paper", initial_balance=100_000.0, cash=100_000.0)
    acct.positions["live"] = Position(
        position_id="live", market=GAS, direction=TradeDirection.LONG,
        quantity=LOT, entry_price=14.70, current_price=14.70,
        status=TradeStatus.OPEN,
    )
    assert acct.gross_era_closed == 0


def test_cash_matches_the_net_figure_on_a_flat_book():
    """The property is only worth displaying if it describes the money."""
    acct = _round_trip()
    assert acct.cash == pytest.approx(
        acct.initial_balance + acct.net_realized_pnl, abs=0.01)


# ============================================ apply_trade reports what it did
def test_apply_trade_returns_the_round_trip_not_just_the_exit_leg():
    """The chest has to subtract BOTH legs. An exit-leg-only figure would
    leave the entry's brokerage in the chest forever."""
    acct = Account(account_id="paper_mcx", initial_balance=100_000.0,
                   cash=100_000.0)
    opened = acct.apply_trade(_trade(TradeDirection.LONG, 14.70))
    closed = acct.apply_trade(_trade(TradeDirection.SHORT, 13.90))

    assert isinstance(closed, TradeApplication)
    # Opening closed nothing, so there is no round trip to report.
    assert opened.closed_charges is None
    assert closed.order_charges == pytest.approx(40.87, abs=0.2)
    assert closed.closed_charges == pytest.approx(74.11, abs=0.05)
    assert closed.closed_charges > closed.order_charges


def test_the_reported_round_trip_equals_the_position_it_closed():
    acct = _round_trip()
    pos = next(iter(acct.positions.values()))
    again = Account(account_id="paper_mcx", initial_balance=100_000.0,
                    cash=100_000.0)
    again.apply_trade(_trade(TradeDirection.LONG, 14.70))
    result = again.apply_trade(_trade(TradeDirection.SHORT, 13.90))
    assert result.closed_charges == pytest.approx(pos.charges, abs=0.001)
    assert result.closed_gross_pnl == pytest.approx(pos.realized_pnl, abs=0.001)


def test_a_part_close_reports_no_round_trip_rather_than_half_a_cost():
    """The slice sold and the slice still held share one accruing charge,
    so neither can be priced on its own. None, not a fraction."""
    acct = Account(account_id="paper_mcx", initial_balance=100_000.0,
                   cash=100_000.0)
    acct.apply_trade(_trade(TradeDirection.LONG, 14.70))
    result = acct.apply_trade(_trade(TradeDirection.SHORT, 13.90, quantity=500.0))
    assert result.closed, "a part-close still realised P&L and must be reported"
    assert result.closed_charges is None


def test_a_gross_era_position_poisons_the_round_trip_to_none():
    """A sum over a mixed set would understate the cost and read complete."""
    legs = TradeApplication(order_charges=20.0, closed=())
    assert legs.closed_charges is None


def test_the_portfolio_bot_passes_the_result_through():
    """It swallowed the return for months, which is why callers recomputed
    P&L from their own prices and drifted from the account."""
    acct = Account(account_id="paper_mcx", initial_balance=100_000.0,
                   cash=100_000.0)
    bot = PortfolioBot(acct)
    assert isinstance(bot.apply_trade(_trade(TradeDirection.LONG, 14.70)),
                      TradeApplication)


# ================================================== the war chest spends net
def _chest_manager(tmp_path) -> StrategyPortfolioManager:
    class _Resolver:
        def __init__(self, root: Path) -> None:
            self._root = root

        def resolve_strategy_portfolio_path(self) -> Path:
            return self._root / "strategy_portfolio.json"

        def __getattr__(self, name):
            def _any(*_a, **_k):
                return self._root
            return _any

    return StrategyPortfolioManager(_Resolver(tmp_path))


def _one_strategy(mgr: StrategyPortfolioManager) -> str:
    return next(iter(mgr.portfolio["strategies"]))


def test_the_chest_keeps_the_gross_total_and_subtracts_charges_separately(tmp_path):
    """Reinterpreting a stored key is how a number comes to mean two things
    at once. Every chest on disk already holds a gross running total."""
    mgr = _chest_manager(tmp_path)
    sid = _one_strategy(mgr)
    mgr.record_trade_outcome(strategy_id=sid, asset="NATURALGAS", is_win=False,
                             pnl=-1000.0, charges=74.11)
    capital = mgr.portfolio["strategies"][sid]["capital"]
    assert capital["realized_pnl"] == pytest.approx(-1000.0)
    assert capital["charges_paid"] == pytest.approx(74.11)


def test_available_capital_is_net_of_the_broker(tmp_path):
    """This is the number `_strategy_available_capital` hands to sizing."""
    mgr = _chest_manager(tmp_path)
    sid = _one_strategy(mgr)
    before = {r["strategy_id"]: r for r in mgr.get_capital_report()}[sid]
    mgr.record_trade_outcome(strategy_id=sid, asset="NATURALGAS", is_win=False,
                             pnl=-1000.0, charges=74.11)
    after = {r["strategy_id"]: r for r in mgr.get_capital_report()}[sid]

    assert after["available"] == pytest.approx(
        before["available"] - 1074.11, abs=0.01)
    assert after["realized_pnl"] == pytest.approx(-1074.11, abs=0.01)
    assert after["gross_realized_pnl"] == pytest.approx(-1000.0)
    assert after["charges_paid"] == pytest.approx(74.11)


def test_the_stats_stay_gross_so_the_weeks_remain_comparable(tmp_path):
    """Expectancy has always been measured on the price difference. Netting
    it now, silently, would make this week incomparable with last week with
    nothing on screen saying so. The chest is money; the stats are edge."""
    mgr = _chest_manager(tmp_path)
    sid = _one_strategy(mgr)
    mgr.record_trade_outcome(strategy_id=sid, asset="NATURALGAS", is_win=False,
                             pnl=-1000.0, charges=74.11)
    strat = mgr.portfolio["strategies"][sid]
    assert strat["expectancy"]["NATURALGAS"] == pytest.approx(-1000.0)
    assert strat["pnl_history"]["NATURALGAS"][-1] == pytest.approx(-1000.0)


def test_an_uncharged_fill_is_counted_not_treated_as_free(tmp_path):
    """A venue with no charge accounting (live Kite) passes None. Booking it
    as zero would quietly claim the chest total was net."""
    mgr = _chest_manager(tmp_path)
    sid = _one_strategy(mgr)
    mgr.record_trade_outcome(strategy_id=sid, asset="NATURALGAS", is_win=True,
                             pnl=500.0, charges=None)
    capital = mgr.portfolio["strategies"][sid]["capital"]
    assert capital["trades_without_charges"] == 1
    assert "charges_paid" not in capital or capital["charges_paid"] == 0.0

    row = {r["strategy_id"]: r for r in mgr.get_capital_report()}[sid]
    assert row["trades_without_charges"] == 1
    assert row["realized_pnl"] == row["gross_realized_pnl"]


def test_a_chest_that_predates_the_charge_key_still_reports(tmp_path):
    """Both portfolio files on disk were written before `charges_paid`
    existed. A KeyError here would take the arena down."""
    mgr = _chest_manager(tmp_path)
    sid = _one_strategy(mgr)
    mgr.portfolio["strategies"][sid]["capital"] = {
        "starting": 100_000.0, "realized_pnl": 1_234.0}
    row = {r["strategy_id"]: r for r in mgr.get_capital_report()}[sid]
    assert row["charges_paid"] == 0.0
    assert row["realized_pnl"] == pytest.approx(1_234.0)
    assert row["available"] == pytest.approx(101_234.0)


# =================================================== what the dashboard sends
def test_the_overview_carries_net_charges_and_the_uncharged_count():
    acct = _round_trip()
    overview = PortfolioOverview.from_account(acct)
    assert overview.total_realized_pnl == pytest.approx(-1000.0)
    assert overview.net_realized_pnl == pytest.approx(-1074.11, abs=0.05)
    assert overview.charges_paid == pytest.approx(74.11, abs=0.05)
    assert overview.gross_era_positions == 0
    assert "net_realized_pnl" in overview.to_dict()


def test_a_position_row_carries_its_own_cost():
    acct = _round_trip()
    snap = PositionSnapshot.from_position(next(iter(acct.positions.values())))
    assert snap.realized_pnl == pytest.approx(-1000.0)
    assert snap.charges == pytest.approx(74.11, abs=0.05)
    assert snap.net_pnl == pytest.approx(-1074.11, abs=0.05)


def test_a_gross_era_row_sends_null_not_zero():
    """A zero in that column claims the trade was free. The table prints a
    dash for None, which is the truth: unmeasured."""
    pos = Position(
        position_id="old", market="NIFTY2680424300CE",
        direction=TradeDirection.LONG, quantity=65.0, entry_price=91.85,
        current_price=90.0, status=TradeStatus.CLOSED,
    )
    snap = PositionSnapshot.from_position(pos)
    assert snap.charges is None
    assert snap.net_pnl is None


# ======================================= the panels, as the browser gets them
def _page(name: str) -> str:
    path = ROOT / "src" / "hokage" / "dashboard" / "templates" / name
    return io.open(path, encoding="utf-8").read()


def _code_only(source: str) -> str:
    """Strips `//` comment lines. A text rail that reads its own explanation
    is how four false positives landed on 2026-11-09: the comment describing
    the trap matched the pattern guarding against it."""
    return "\n".join(line for line in source.splitlines()
                     if not line.lstrip().startswith("//"))


@pytest.mark.parametrize("page", ["arena.html", "arena_mcx.html"])
def test_both_arenas_name_the_charges_column(page):
    body = _code_only(_page(page))
    assert "<th>Charges</th>" in body
    assert "Realized P&L (net)" in body
    assert "c.charges_paid" in body


@pytest.mark.parametrize("page", ["arena.html", "arena_mcx.html"])
def test_both_arenas_show_the_gross_total_beside_the_net_one(page):
    """Hiding the gross figure would make the change unauditable from the
    screen that reports it."""
    body = _code_only(_page(page))
    assert "totalGross" in body
    assert "totalCharges" in body


@pytest.mark.parametrize("page", ["arena.html", "arena_mcx.html"])
def test_the_reconciliation_prints_the_figure_it_compared(page):
    """It said "chests = account <equity>" while comparing against settled
    cash, so with a position open the tick sat beside the wrong number."""
    body = _code_only(_page(page))
    assert "rec.account_settled" in body
    assert "rec.account_equity" not in body


@pytest.mark.parametrize("page", ["arena.html", "arena_mcx.html"])
def test_the_closed_trades_table_shows_a_dash_for_the_uncharged_era(page):
    body = _code_only(_page(page))
    assert "<th>Net P&L</th>" in body
    assert "t.net_pnl == null" in body


def test_the_portfolio_card_says_net_and_shows_what_was_taken():
    index = _page("index.html")
    assert 'Realized P&L (net)' in index
    assert 'id="port-charges-paid"' in index


# ================================== the venue tells the caller what it cost
def test_the_paper_venue_reports_the_round_trip_on_the_closing_fill(tmp_path):
    """The bot reads `closed_charges` off this response rather than
    recomputing the cost, for the same reason it reads `average_price`
    rather than the decision quote: two places computing one number is how
    the chest and the account came to disagree by 6.50 an exit."""
    from integrations.brokers.models import OrderRequest, OrderSide, OrderType
    from integrations.brokers.paper_venue import PaperVenue
    from integrations.data.models import AssetClass, Exchange, Instrument

    venue = PaperVenue(venue_id="paper_mcx", account_id="paper_mcx",
                       brain_root=tmp_path)
    venue.connect()
    inst = Instrument(symbol=GAS, asset_class=AssetClass.INDIAN_EQUITY,
                      exchange=Exchange.MCX)

    def _order(side: OrderSide) -> OrderRequest:
        return OrderRequest(instrument=inst, side=side, quantity=LOT,
                            order_type=OrderType.MARKET,
                            strategy_id="strat-trendrider-mcx-v1",
                            execution_reason="charge accounting test")

    opened = venue.place_order(_order(OrderSide.BUY))
    assert opened.metadata["order_charges"] > 0
    assert opened.metadata["closed_charges"] is None

    closed = venue.place_order(_order(OrderSide.SELL))
    # Same mock price both ways, so the price move is nil and the whole
    # result is what the broker took: a flat trade is not a free trade.
    assert closed.metadata["closed_gross_pnl"] == pytest.approx(0.0)
    assert closed.metadata["closed_charges"] == pytest.approx(
        opened.metadata["order_charges"] + closed.metadata["order_charges"],
        abs=0.01)


def test_a_non_option_fill_reports_no_charge_rather_than_zero(tmp_path):
    """The schedule modelled here is the options one. Guessing a rate for
    an equity would be inventing a cost."""
    from integrations.brokers.models import OrderRequest, OrderSide, OrderType
    from integrations.brokers.paper_venue import PaperVenue
    from integrations.data.models import AssetClass, Exchange, Instrument

    venue = PaperVenue(venue_id="paper_main", account_id="paper",
                       brain_root=tmp_path)
    venue.connect()
    inst = Instrument(symbol="TATA", asset_class=AssetClass.INDIAN_EQUITY,
                      exchange=Exchange.NSE)

    def _order(side: OrderSide) -> OrderRequest:
        return OrderRequest(instrument=inst, side=side, quantity=10.0,
                            order_type=OrderType.MARKET,
                            strategy_id="strat-123",
                            execution_reason="non-option")

    venue.place_order(_order(OrderSide.BUY))
    closed = venue.place_order(_order(OrderSide.SELL))
    assert closed.metadata["order_charges"] == 0.0
    assert closed.metadata["closed_charges"] is None


# ============================= the plain-English report he actually reads
def test_the_eod_report_tells_him_what_reached_the_account():
    from bots.autonomous.plain_report import build_plain_report

    report = build_plain_report(
        closed_trades=[{
            "symbol": GAS, "entry_price": 14.70, "exit_price": 13.90,
            "quantity": LOT, "pnl": -1000.0, "charges": 74.11,
            "net_pnl": -1074.11, "exit_reason": "STOP_LOSS",
        }],
        open_trades=[],
        date_label="Monday, 10 Nov 2026",
    )
    assert "1,074" in report, "the bottom line is not the net figure"
    assert "broker was paid" in report
    assert "74" in report


def test_the_report_says_nothing_about_costs_it_never_measured():
    """Silence, not a zero. A "the broker was paid Rs 0.00" line about the
    gross era would be a false statement in plain English."""
    from bots.autonomous.plain_report import build_plain_report

    report = build_plain_report(
        closed_trades=[{
            "symbol": "NIFTY2680424300CE", "entry_price": 91.85,
            "exit_price": 95.0, "quantity": 65.0, "pnl": 204.75,
            "charges": None, "net_pnl": None, "exit_reason": "TARGET_HIT",
        }],
        open_trades=[],
        date_label="Monday, 10 Nov 2026",
    )
    assert "broker was paid" not in report
    assert "before Hokage started" in report


# ================================ the answers the commander gets in chat
def test_the_chat_tool_no_longer_calls_a_gross_sum_net(tmp_path, monkeypatch):
    """`get_trades` returned `net_pnl` holding the gross total, and that key
    answers "how did we do today" in chat and in the state digest injected
    into every prompt. Charges are 3.2x the lifetime gross profit; the name
    was not a detail."""
    import sqlite3

    from bots.autonomous import hokage_tools

    db = tmp_path / "hokage.db"
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE positions (market TEXT, account_id TEXT, direction TEXT,"
        " entry_price REAL, current_price REAL, realized_pnl REAL,"
        " charges REAL, opened_at TEXT, closed_at TEXT, status TEXT)")
    today = hokage_tools._now()[:10]
    conn.executemany(
        "INSERT INTO positions VALUES (?,?,?,?,?,?,?,?,?,?)", [
            (GAS, "paper_mcx", "LONG", 14.70, 13.90, -1000.0, 74.11,
             f"{today} 09:30:00", f"{today} 11:00:00", "CLOSED"),
            ("NIFTY2680424300CE", "paper", "LONG", 91.85, 95.0, 204.75, None,
             f"{today} 10:00:00", f"{today} 12:00:00", "CLOSED"),
        ])
    conn.commit()
    conn.close()
    monkeypatch.setattr(hokage_tools, "DB_PATH", db)

    out = hokage_tools.get_trades(1)
    assert out["gross_pnl"] == pytest.approx(-795.25)
    assert out["charges"] == pytest.approx(74.11)
    assert out["net_pnl"] == pytest.approx(-869.36)
    # The uncharged row is named, not folded in as a free trade.
    assert out["uncharged_trades"] == 1
    assert out["trades"][0]["net_pnl"] == pytest.approx(-1074.11)
    assert out["trades"][1]["net_pnl"] is None


# ===================== the daily briefing netted against an invented cost
def _briefing_generator(tmp_path):
    """Only the cache is consulted on the path under test; the engines are
    reached through branches that swallow their own exceptions.

    THE RESOLVER ITSELF MUST BE REAL, not a mock whose resolve_* methods are
    stubbed: `generate_daily_briefing` hands `cache.resolver` straight to
    DecisionJournalSystem and PerformanceAnalyticsEngine, which build paths
    from the object. A MagicMock there stringifies into one, and the briefing
    wrote `Hokage/MagicMock/mock.resolver/<id>/journal` into the repository,
    a fresh directory per mock instance. tests/test_brain_hermeticity.py
    caught it, which is exactly what that rail is for."""
    from unittest.mock import MagicMock

    from bots.autonomous.briefings import BriefingGenerator
    from hokage.memory.resolver import PathResolver

    resolver = PathResolver(tmp_path)
    cache = MagicMock()
    cache.read_intelligence.return_value = {}
    cache.resolver = resolver
    cache._resolver = resolver
    return BriefingGenerator(MagicMock(), MagicMock(), MagicMock(),
                             MagicMock(), MagicMock(), cache)


def _daily_report(exits):
    from bots.autonomous.models import DailyReport

    return DailyReport(
        date="2026-11-10",
        trades_taken=(),
        exits_executed=tuple(exits),
        realized_pnl=round(sum(e["pnl"] for e in exits), 2),
        unrealized_pnl=0.0,
        win_rate=50.0,
        portfolio_allocation={},
        market_summary="test",
        lessons_learned="test",
    )


def test_the_briefing_nets_against_what_cash_actually_paid(tmp_path):
    """It summed the JSON tax ledger - a per-fill cost that
    integrations/tax/mock_provider invents and nothing deducts - and called
    the result "net realized P&L", printed beside the real gross figure
    with nothing saying which model each came from."""
    report = _daily_report([
        {"symbol": GAS, "pnl": -1000.0, "charges": 74.11,
         "net_pnl": -1074.11, "reason": "STOP_LOSS"},
    ])
    text = _briefing_generator(tmp_path).generate_daily_briefing(report)
    assert "costs/friction of **INR 74.11**" in text
    assert "net realized P&L of **INR -1,074.11**" in text


def test_the_briefing_names_the_exits_it_could_not_cost(tmp_path):
    """Folding them in at zero would make the net figure claim a
    completeness it does not have."""
    report = _daily_report([
        {"symbol": GAS, "pnl": -1000.0, "charges": 74.11,
         "net_pnl": -1074.11, "reason": "STOP_LOSS"},
        {"symbol": "NIFTY2680424300CE", "pnl": 500.0, "charges": None,
         "net_pnl": None, "reason": "TARGET_HIT"},
    ])
    text = _briefing_generator(tmp_path).generate_daily_briefing(report)
    assert "1 of today's exits carries no charge record" in text
    assert "NOT in the net figure" in text


def test_a_fully_charged_day_says_nothing_about_missing_records(tmp_path):
    report = _daily_report([
        {"symbol": GAS, "pnl": -1000.0, "charges": 74.11,
         "net_pnl": -1074.11, "reason": "STOP_LOSS"},
    ])
    text = _briefing_generator(tmp_path).generate_daily_briefing(report)
    assert "no charge record" not in text


# ========================== the command he types to see the paper account
def test_the_portfolio_command_prints_net_with_its_working():
    """`hokage portfolio` printed the gross total directly above the net
    cash it does not reconcile with."""
    from hokage.router.command_router import CommandRouter
    from unittest.mock import MagicMock

    acct = _round_trip()
    orchestrator = MagicMock()
    orchestrator.portfolio_store.load_account.return_value = acct
    router = CommandRouter.__new__(CommandRouter)
    router.orchestrator = orchestrator

    out = CommandRouter.handle_hokage_portfolio(router)
    assert "(net of charges)" in out
    assert "gross:" in out
    assert "charges paid:" in out
    # The net figure, not the price difference.
    plain = out.replace("₹", "")
    assert f"{abs(acct.net_realized_pnl):,.2f}" in plain
    assert f"{abs(acct.realized_pnl):,.2f}" in plain      # gross, under it
    assert abs(acct.net_realized_pnl) > abs(acct.realized_pnl)
