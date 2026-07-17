"""Portfolio-level entry gates born from the 2026-07-17 session:
three simultaneous same-direction index CE entries (-6.3k as one macro bet
tripled) and a post-win dip re-entry (-1,774)."""
from __future__ import annotations

from bots.autonomous.autonomous_bot import AutonomousTradingBot


def _bot():
    b = AutonomousTradingBot.__new__(AutonomousTradingBot)
    b._active_positions_tracking = {}
    b._target_exit_watermarks = {}
    return b


def _ce(underlying):
    return {"underlying": underlying, "side": "BUY", "option_type": "CE"}


def _pe(underlying):
    return {"underlying": underlying, "side": "BUY", "option_type": "PE"}


def test_position_direction_reads_option_type_not_side():
    # Bought options are always side=BUY; the bet lives in CE/PE.
    assert AutonomousTradingBot._position_direction(_ce("NIFTY")) == "long"
    assert AutonomousTradingBot._position_direction(_pe("NIFTY")) == "short"
    assert AutonomousTradingBot._position_direction({"side": "SELL"}) == "short"


def test_third_same_direction_index_entry_is_blocked():
    bot = _bot()
    bot._active_positions_tracking = {
        "NIFTY2672124250CE": _ce("NIFTY"),
        "BANKNIFTY26JUL58100CE": _ce("BANKNIFTY"),
    }
    ok, reason = bot._entry_cluster_gate("SENSEX", "long", 78000.0)
    assert not ok and "CorrelationCap" in reason


def test_opposite_direction_and_second_entry_still_allowed():
    bot = _bot()
    bot._active_positions_tracking = {
        "NIFTY2672124250CE": _ce("NIFTY"),
        "BANKNIFTY26JUL58100CE": _ce("BANKNIFTY"),
    }
    # A PUT (short bet) is a hedge, not more of the same bet.
    ok, _ = bot._entry_cluster_gate("SENSEX", "short", 78000.0)
    assert ok
    # With only ONE long open, a second long is fine (cap is 2).
    bot._active_positions_tracking = {"NIFTY2672124250CE": _ce("NIFTY")}
    ok, _ = bot._entry_cluster_gate("SENSEX", "long", 78000.0)
    assert ok


def test_non_family_symbol_ignores_the_cap():
    bot = _bot()
    bot._active_positions_tracking = {
        "NIFTY2672124250CE": _ce("NIFTY"),
        "BANKNIFTY26JUL58100CE": _ce("BANKNIFTY"),
    }
    ok, _ = bot._entry_cluster_gate("CRUDEOIL", "long", 6800.0)
    assert ok


def test_watermark_blocks_buying_the_dip_of_our_own_winner():
    bot = _bot()
    bot._target_exit_watermarks["NIFTY"] = {"direction": "long", "level": 24260.0}
    # Index BELOW the level where profit was taken: blocked.
    ok, reason = bot._entry_cluster_gate("NIFTY", "long", 24240.0)
    assert not ok and "ReentryWatermark" in reason
    # Index pushed PAST the exit level: fresh trend leg, allowed.
    ok, _ = bot._entry_cluster_gate("NIFTY", "long", 24275.0)
    assert ok
    # Opposite direction is a different thesis: allowed.
    ok, _ = bot._entry_cluster_gate("NIFTY", "short", 24240.0)
    assert ok
