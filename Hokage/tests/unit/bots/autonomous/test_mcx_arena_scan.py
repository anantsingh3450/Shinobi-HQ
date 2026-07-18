"""End-to-end drive of _scan_and_enter_mcx_opportunities: proves the wiring
(not just syntax) — a CRUDEOIL long lands on the MCX venue/ledger, never the
index one, tracked with the right strategy_id and venue_id."""
from __future__ import annotations

from contextlib import ExitStack
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot
from bots.strategy.components.models import MarketContext
from integrations.brokers.models import AccountBalance, ExecutionContext, ExecutionMode, OrderStatus, OrderResponse
from hokage.memory.resolver import PathResolver


@pytest.fixture
def mock_orchestrator_with_mcx():
    orch = MagicMock()
    orch.get_execution_context.return_value = ExecutionContext(
        execution_mode=ExecutionMode.PAPER, active_venue_id="paper_main",
        brain_id="primary_brain", authority_level="elder",
    )

    index_venue = MagicMock()
    index_venue.venue_id = "paper_main"
    index_venue.get_account_balance.return_value = AccountBalance(
        venue_id="paper_main", total_equity=200000.0, cash=200000.0, margin_available=200000.0, margin_used=0.0,
    )
    index_venue.get_positions.return_value = []
    index_venue.place_order = MagicMock(side_effect=AssertionError("index venue must NEVER receive an MCX order"))

    mcx_venue = MagicMock()
    mcx_venue.venue_id = "paper_mcx"
    mcx_venue.get_account_balance.return_value = AccountBalance(
        venue_id="paper_mcx", total_equity=400000.0, cash=400000.0, margin_available=400000.0, margin_used=0.0,
    )
    mcx_venue.get_positions.return_value = []
    order_resp = MagicMock()
    order_resp.status = OrderStatus.FILLED
    order_resp.filled_quantity = 100.0
    order_resp.error_message = None
    mcx_venue.place_order.return_value = order_resp

    orch.paper_venue = index_venue
    orch.mcx_venue = mcx_venue
    orch.registry.get_venue.return_value = index_venue
    orch.registry.list_venues.return_value = ["paper_main", "paper_mcx"]

    def _quote_for(symbol):
        q = MagicMock()
        # The underlying's live tick is ~7952; the OPTION CONTRACT's premium
        # is a different, much smaller number (~Rs 250/barrel here) — using
        # one shared price for both would make the router "buy" a lot priced
        # at the underlying's spot, blowing through every chest.
        q.price = 250.0 if str(symbol).upper().endswith(("CE", "PE")) else 7952.0
        q.bid, q.ask = q.price - 0.5, q.price + 0.5
        q.volume = 5000.0
        q.provider = "test-live-feed"
        q.quoted_at = datetime.now(timezone.utc)
        return q
    orch.price_source.get_quote.side_effect = _quote_for
    orch.price_source.get_price.return_value = 7952.0

    # Real ATM contract dict — proves the router's lot-size math runs for real.
    orch.price_source.resolve_option_contract.return_value = {
        "tradingsymbol": "CRUDEOIL26AUG7950CE",
        "exchange": "MCX",
        "strike": 7950.0,
        "expiry": "2026-08-19",
        "lot_size": 100.0,  # the hand-verified multiplier, not Kite's raw 1
    }

    from integrations.brokers.session_manager import TradingSessionManager
    real_session_mgr = TradingSessionManager()
    orch.session_manager = MagicMock(wraps=real_session_mgr)
    # is_tradable's default current_time reads the REAL wall clock, not the
    # bot's mocked _now_ist — irrelevant to what this test exercises (the
    # scan/entry wiring), so it's pinned open regardless of when tests run.
    orch.session_manager.is_tradable.return_value = True
    orch.session_manager.resolve_exchange = real_session_mgr.resolve_exchange
    orch.session_manager.resolve_asset_class = real_session_mgr.resolve_asset_class
    return orch


@pytest.fixture(autouse=True)
def isolate_resolver(tmp_path):
    def mock_init(self, brain_root=None):
        self._brain_root = tmp_path
    with patch.object(PathResolver, "__init__", mock_init):
        yield


def test_crudeoil_long_lands_on_mcx_venue_never_index(mock_orchestrator_with_mcx, tmp_path):
    orch = mock_orchestrator_with_mcx
    with ExitStack() as stack:
        stack.enter_context(patch.object(PathResolver, "__init__", lambda self, brain_root=None: setattr(self, "_brain_root", tmp_path)))
        bot = AutonomousTradingBot(orch, watchlist=["CRUDEOIL"], scan_interval_seconds=1)

        # Mid-evening, well inside the MCX entry window (09:30-22:30), a
        # Tuesday so the weekday guard passes. (2026-07-21 is a Tuesday.)
        bot._now_ist = lambda: datetime(2026, 7, 21, 18, 0, tzinfo=timezone.utc)

        # The MCX scan always walks the full MCX_UNIVERSE (CRUDEOIL,
        # NATURALGAS, GOLDM, SILVERM) regardless of `watchlist` — this test
        # wants exactly ONE entry, so only CRUDEOIL gets a real uptrend
        # context; the other three get a flat, signal-free tape.
        _uptrend = tuple(7900.0 + i * 3.0 for i in range(30))
        _flat = tuple([100.0] * 30)

        def _ctx_for(symbol, cache=None):
            if symbol == "CRUDEOIL":
                c = _uptrend
                return MarketContext(
                    symbol=symbol, price=c[-1], ema9=c[-1] - 5, ema21=c[-1] - 40, vwap=c[-1] - 20,
                    closes=c, highs=tuple(x * 1.001 for x in c), lows=tuple(x * 0.999 for x in c),
                    minutes_into_session=600,  # 19:00 for a 09:00 MCX open — TrendRider's window
                )
            c = _flat
            return MarketContext(
                symbol=symbol, price=c[-1], ema9=c[-1], ema21=c[-1], vwap=c[-1],
                closes=c, highs=c, lows=c, minutes_into_session=600,
            )
        bot._build_market_context = _ctx_for
        bot._compute_underlying_bias = lambda symbol: None
        bot._india_vix_percentile = lambda: None
        bot._get_atr_for_symbol = lambda symbol: 40.0

        bot._scan_and_enter_mcx_opportunities()

        # The order went to the MCX venue (the index venue's mock raises if touched).
        orch.mcx_venue.place_order.assert_called_once()
        placed_req = orch.mcx_venue.place_order.call_args[0][0]
        assert placed_req.instrument.symbol == "CRUDEOIL26AUG7950CE"

        # Tracked correctly: right venue, right underlying, an MCX strategy_id.
        tracked = bot._active_positions_tracking.get("CRUDEOIL26AUG7950CE")
        assert tracked is not None
        assert tracked["venue_id"] == "paper_mcx"
        assert tracked["underlying"] == "CRUDEOIL"
        assert tracked["strategy_id"] in bot.mcx_strategy_portfolio.portfolio["strategies"]


def test_weekend_and_outside_window_are_silent_no_ops(mock_orchestrator_with_mcx, tmp_path):
    orch = mock_orchestrator_with_mcx
    with ExitStack() as stack:
        stack.enter_context(patch.object(PathResolver, "__init__", lambda self, brain_root=None: setattr(self, "_brain_root", tmp_path)))
        bot = AutonomousTradingBot(orch, watchlist=["CRUDEOIL"], scan_interval_seconds=1)

        # Saturday.
        bot._now_ist = lambda: datetime(2026, 7, 18, 12, 0, tzinfo=timezone.utc)
        bot._scan_and_enter_mcx_opportunities()
        orch.mcx_venue.place_order.assert_not_called()

        # Weekday but before the 09:30 open.
        bot._now_ist = lambda: datetime(2026, 7, 21, 9, 0, tzinfo=timezone.utc)
        bot._scan_and_enter_mcx_opportunities()
        orch.mcx_venue.place_order.assert_not_called()

        # Weekday but after the 22:30 cutoff.
        bot._now_ist = lambda: datetime(2026, 7, 21, 22, 45, tzinfo=timezone.utc)
        bot._scan_and_enter_mcx_opportunities()
        orch.mcx_venue.place_order.assert_not_called()
