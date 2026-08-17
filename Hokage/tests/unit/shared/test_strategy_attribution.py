"""Which strategy opened a position must survive into the ledger.

Found 2026-08-17 while trying to verify a claim that SessionShift was at "50%
win rate" on gold after two losing gold trades. It could not be verified,
because attribution was persisted NOWHERE:

  * trades.strategy_name was the literal "AutonomousExit" for all 101 rows —
    it records the exit MECHANISM, not the strategy
  * trade_attributions existed and had ZERO rows, ever
  * decision_journal / decision_outcomes carried conviction, P&L and exit
    reason but no strategy
  * positions.playbook_id held a playbook NAME for one of the day's trades and
    None for the other

So attribution lived only in the bot's in-memory tracking dict and in aggregate
form in the portfolio JSON — where it is polluted across the pre/post-scoping
eras (RangeFade still shows GOLDM at 100% win rate off ONE pre-scoping trade).

This blocks tiered autonomy directly: a loop that archives a strategy for
measuring badly must be able to prove which trades were its.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bots.execution.models import TradeDirection, TradeRecord
from bots.portfolio.models import Account, Position


def _pos(strategy_id=None, pid="p1"):
    return Position(
        position_id=pid, market="GOLDM26AUG153500PE",
        direction=TradeDirection.LONG, quantity=10.0,
        entry_price=2240.0, current_price=2240.0,
        strategy_id=strategy_id,
    )


def test_a_position_carries_the_strategy_that_opened_it():
    assert _pos("strat-sessionshift-mcx-v1").strategy_id == "strat-sessionshift-mcx-v1"


def test_it_defaults_to_None_not_a_guess():
    """None means "we do not know". A default strategy id would attribute a
    real outcome to a strategy that did not make the trade."""
    assert _pos().strategy_id is None


def test_it_survives_a_serialise_round_trip():
    original = _pos("strat-rangefade-mcx-v1")
    assert Position.from_dict(original.to_dict()).strategy_id == "strat-rangefade-mcx-v1"


def test_older_serialised_positions_load_without_it():
    """Rows written before schema v8 have no strategy_id. Loading them must
    yield None rather than raising — attribution for them was genuinely lost
    and inventing it would be fabrication."""
    data = _pos("x").to_dict()
    del data["strategy_id"]
    assert Position.from_dict(data).strategy_id is None


def test_a_partial_close_keeps_the_attribution():
    """Halving a position must not orphan the remainder."""
    acct = Account(account_id="paper_mcx", initial_balance=200000.0, cash=200000.0)
    opened = _pos("strat-sessionshift-mcx-v1", pid="t1")
    acct.positions["t1"] = opened

    closing = TradeRecord(
        trade_id="t2", proposal_id="pr", market="GOLDM26AUG153500PE",
        direction=TradeDirection.SHORT, quantity=4.0, entry_price=2300.0,
        simulated_value=0.0, mode="PAPER", status="FILLED",
        strategy_name="AutonomousExit", sources_cited=(),
        executed_at=datetime.now(timezone.utc),
    )
    acct.apply_trade(closing)
    remaining = acct.positions["t1"]
    assert remaining.quantity == pytest.approx(6.0)
    assert remaining.strategy_id == "strat-sessionshift-mcx-v1", (
        "the surviving half lost its owner"
    )


def test_the_schema_migration_is_idempotent_and_versioned():
    import inspect

    from shared.persistence.sqlite_engine import SqliteStorageEngine

    src = inspect.getsource(SqliteStorageEngine.run_migrations)
    assert "current_version < 8" in src
    assert "ADD COLUMN strategy_id" in src
    assert "OperationalError" in src, "re-running the migration must not raise"


def test_the_write_path_persists_it():
    import inspect

    from shared.persistence.sqlite_stores import SqlitePortfolioStore

    src = inspect.getsource(SqlitePortfolioStore.save_account)
    assert "strategy_id" in src
    # 16 bound parameters now, not 15.
    assert src.count("?") >= 16


def test_the_phantom_default_is_gone_from_the_exit_path():
    """The outcome recorder used to fall back to "strat-autotrend-equities-v1",
    an id in NEITHER portfolio — the same dead id that silently disabled the
    ImprovementBot's evolution path. Attributing a real loss to a strategy that
    does not exist writes stats for a ghost AND hides that attribution failed.
    """
    from pathlib import Path

    import bots.autonomous.autonomous_bot as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    assert 'entry_meta.get("strategy_id", "strat-autotrend-equities-v1")' not in src
    assert "recording the" in src, "the no-attribution case must warn, not guess"


def test_the_exit_loop_restamps_attribution_every_pass():
    """Self-healing on purpose: a position that predates this change, or whose
    attribution was lost, gets it back on the next iteration instead of staying
    anonymous forever. And a known id is never overwritten with None."""
    from pathlib import Path

    import bots.autonomous.autonomous_bot as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    start = src.index("def _monitor_and_exit_positions")
    body = src[start:start + 6000]
    assert "pos.strategy_id = _owner" in body
    assert "if _owner and" in body, "must not clobber a known id with None"
