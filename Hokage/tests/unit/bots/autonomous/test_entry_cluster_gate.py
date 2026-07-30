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


def test_opposite_direction_is_no_longer_treated_as_a_hedge():
    """REVERSED 2026-07-30 by commander instruction.

    This test used to assert that a PUT against open CALLs was allowed, on the
    reasoning that "a PUT is a hedge, not more of the same bet". Live evidence
    retired that premise: Hokage held NIFTY calls, SENSEX calls and BANKNIFTY
    puts simultaneously. It only ever BUYS premium, so opposing legs on indices
    that move ~90% together are not a hedge — the directional edge cancels while
    both legs keep paying theta and a spread. The right answer to a flipped
    thesis is for the open position to exit, not to be offset.
    """
    bot = _bot()
    bot._active_positions_tracking = {
        "NIFTY2672124250CE": _ce("NIFTY"),
        "BANKNIFTY26JUL58100CE": _ce("BANKNIFTY"),
    }
    ok, reason = bot._entry_cluster_gate("SENSEX", "short", 78000.0)
    assert not ok and "OpposingFamilyBet" in reason


def test_second_agreeing_entry_is_still_allowed():
    # With only ONE long open, a second long is fine (cap is 2).
    bot = _bot()
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


# --- opposing-direction block (added 2026-07-30) ---------------------------
# The cap stopped one bet being taken three times, but the family could still be
# bet BOTH ways at once: Hokage held NIFTY calls, SENSEX calls and BANKNIFTY puts
# together. It buys premium only, so opposing legs on ~90%-correlated indices
# cancel the edge and keep paying two spreads and two theta bills.


def test_opposing_index_bet_is_blocked():
    bot = _bot()
    bot._active_positions_tracking = {"NIFTY2680424300CE": _ce("NIFTY")}
    ok, reason = bot._entry_cluster_gate("BANKNIFTY", "short", 57000.0)
    assert not ok
    assert "OpposingFamilyBet" in reason
    assert "NIFTY" in reason


def test_opposing_block_works_in_both_directions():
    bot = _bot()
    bot._active_positions_tracking = {"BANKNIFTY26AUG57000PE": _pe("BANKNIFTY")}
    ok, reason = bot._entry_cluster_gate("NIFTY", "long", 24300.0)
    assert not ok and "OpposingFamilyBet" in reason


def test_second_same_direction_entry_is_still_allowed():
    """The cap is 2; tightening opposing bets must not tighten agreement."""
    bot = _bot()
    bot._active_positions_tracking = {"NIFTY2680424300CE": _ce("NIFTY")}
    ok, _ = bot._entry_cluster_gate("SENSEX", "long", 78000.0)
    assert ok


def test_opposing_position_outside_the_family_is_ignored():
    bot = _bot()
    bot._active_positions_tracking = {"CRUDEOIL26AUG7700PE": _pe("CRUDEOIL")}
    ok, _ = bot._entry_cluster_gate("NIFTY", "long", 24300.0)
    assert ok


def test_mcx_families_get_the_same_opposing_discipline():
    from bots.strategy.mcx_portfolio import MCX_FAMILY_ENERGY

    bot = _bot()
    bot._active_positions_tracking = {"CRUDEOIL26AUG7700CE": _ce("CRUDEOIL")}
    ok, reason = bot._entry_cluster_gate(
        "NATURALGAS", "short", 250.0,
        family=MCX_FAMILY_ENERGY, max_same_direction=2, family_label="MCX-energy",
    )
    assert not ok and "OpposingFamilyBet" in reason


def test_precious_and_energy_stay_independent():
    from bots.strategy.mcx_portfolio import MCX_FAMILY_PRECIOUS

    bot = _bot()
    bot._active_positions_tracking = {"CRUDEOIL26AUG7700CE": _ce("CRUDEOIL")}
    ok, _ = bot._entry_cluster_gate(
        "GOLDM", "short", 71000.0,
        family=MCX_FAMILY_PRECIOUS, max_same_direction=2, family_label="MCX-precious",
    )
    assert ok
