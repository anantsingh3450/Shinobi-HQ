"""A parked asset is a decision already made. Stop re-making it every cycle.

On 2026-10-12, 108 of Hokage's 294 journal entries were

    EntrySignal: SessionShift: not scoped to CRUDEOIL.
    EntrySignal: SessionShift: not scoped to NATURALGAS.

37% of the day's record spent restating a choice taken weeks earlier. It
buried the entries that carried information: 16 IV-guard refusals and 7
volume refusals, the only two gates that actually turned a tradeable signal
away that day.

THE DANGER IN FIXING THIS is making the assets invisible instead of quiet.
"Ceasing to trade an asset silently is a worse failure than trading it badly"
is the rail that blocks the pending MacroBreakout retirements, and it applies
here too. So these tests pin the three things that must keep working:

  1. audit_asset_coverage still names every parked asset at EVERY boot, with
     the reason.
  2. candle_archive still syncs them, so the tape keeps accumulating.
  3. weekly_audit still has them in UNIVERSE, so parked_watch keeps scoring
     them from that tape.

Measurement is the only route back to trading a parked asset. That route is
untouched; only the per-cycle repetition is gone.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot

SRC = pathlib.Path("src/bots/autonomous/autonomous_bot.py")


# ------------------------------------------------------------- the predicate
@pytest.mark.parametrize("asset", sorted(AutonomousTradingBot.PARKED_ASSETS))
def test_a_parked_asset_reports_itself_parked(asset):
    bot = AutonomousTradingBot.__new__(AutonomousTradingBot)
    assert bot.is_parked(asset) is True
    assert bot.is_parked(asset.lower()) is True


@pytest.mark.parametrize("asset", ["GOLDM", "NIFTY", "SENSEX"])
def test_a_live_asset_is_not_parked(asset):
    """The funded lineup must still be scanned. Over-matching here would
    switch the system off.

    SILVERM and BANKNIFTY left this list on 2026-11-09: both were parked on
    COST, measured live against their real books - BANKNIFTY's edge is 0.65%
    of premium against a 0.69-0.75% round trip, SILVERM's 0.24% against
    0.69-0.70%. See hokage.research.funded_cells.
    """
    bot = AutonomousTradingBot.__new__(AutonomousTradingBot)
    assert bot.is_parked(asset) is False


def test_the_parked_set_is_exactly_what_was_decided():
    """A silent addition here stops an asset being scanned. That must be a
    deliberate, reviewed act, not a drive-by edit."""
    # CRUDEOIL has been parked throughout - 7 sweeps, all failing out of
    # sample.
    #
    # NATURALGAS was removed from this set on 2026-10-21 by commander
    # directive, to accumulate a record on an archive that now survives the
    # futures roll, and RE-PARKED on 2026-11-09 on cost. That is not a
    # reversal of the 10-21 reasoning but its satisfaction: parked assets stay
    # in candle_archive.ASSETS, so the tape keeps accumulating and only the
    # money stops.
    #
    # BANKNIFTY and SILVERM joined on 2026-11-09, on the same measurement:
    # these are the four underlyings whose round trip costs more than their
    # measured edge pays. The three that survive - NIFTY, SENSEX, GOLDM - are
    # the funded family. See hokage.research.funded_cells for the arithmetic.
    assert set(AutonomousTradingBot.PARKED_ASSETS) == {
        "CRUDEOIL", "NATURALGAS", "BANKNIFTY", "SILVERM"}

    # And the two lists cannot drift: what is not parked IS what is funded.
    from hokage.research import funded_cells

    universe = {"NIFTY", "BANKNIFTY", "SENSEX", "CRUDEOIL", "NATURALGAS",
                "GOLDM", "SILVERM"}
    assert universe - set(AutonomousTradingBot.PARKED_ASSETS) ==         funded_cells.funded_assets()


def test_every_parked_asset_carries_its_reason():
    for asset, reason in AutonomousTradingBot.PARKED_ASSETS.items():
        assert len(reason) > 40, f"{asset} is parked without a stated reason"


# -------------------------------------------------- both leagues use the rule
def test_both_scan_loops_consult_the_same_predicate():
    """One rule. Parking an index asset later must need no second change."""
    src = SRC.read_text(encoding="utf-8")
    assert src.count("self.is_parked(") >= 2, (
        "both the MCX and index scan loops must skip parked assets"
    )


def test_the_skip_happens_before_any_entry_evaluation():
    """Skipping after the modules have run would save nothing — the journal
    entry is written by the module, which is the noise being removed."""
    src = SRC.read_text(encoding="utf-8")
    mcx = src.index("for symbol in MCX_UNIVERSE:")
    block = src[mcx:mcx + 900]
    assert "self.is_parked(symbol)" in block
    assert block.index("self.is_parked(symbol)") < block.index("is_tradable")


# ---------------------------------------- quiet, but never invisible
def test_the_boot_audit_still_names_parked_assets():
    """The loud, once-per-boot statement is what makes the quiet loop safe."""
    src = SRC.read_text(encoding="utf-8")
    assert "is PARKED" in src
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "audit_asset_coverage")
    assert "PARKED_ASSETS" in ast.dump(fn), (
        "audit_asset_coverage must still consult PARKED_ASSETS"
    )


def test_the_candle_archive_still_syncs_parked_assets():
    """The tape is the evidence that could un-park them. If the archive stops
    collecting it, parking becomes permanent by accident."""
    src = pathlib.Path("tools/research/candle_archive.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    assets = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", None) == "ASSETS" for t in node.targets)):
            assets = {e.value for e in node.value.elts
                      if isinstance(e, ast.Constant)}
    assert assets, "could not read candle_archive.ASSETS"
    for parked in AutonomousTradingBot.PARKED_ASSETS:
        assert parked in assets, f"{parked} would stop being archived"


def test_the_weekly_audit_still_measures_parked_assets():
    """parked_watch scores them from the archive every week — the only route
    back to trading one."""
    src = pathlib.Path("tools/research/weekly_audit.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    universe = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", None) == "UNIVERSE" for t in node.targets)):
            universe = {e.value for e in node.value.elts
                        if isinstance(e, ast.Constant)}
    assert universe, "could not read weekly_audit.UNIVERSE"
    for parked in AutonomousTradingBot.PARKED_ASSETS:
        assert parked in universe, f"{parked} would stop being measured"


def test_the_skip_is_logged_not_swallowed():
    """Debug, not nothing. A loop that drops an asset with no trace at all is
    how a scanning gap becomes undiagnosable."""
    src = SRC.read_text(encoding="utf-8")
    for league in ("MCX Arena", "Index Dojo"):
        assert f'{league}: {{symbol' in src or f'{league}: {{symbol_upper' in src, (
            f"{league} must log the skip"
        )
