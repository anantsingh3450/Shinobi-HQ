"""The weekly audit scored a system nobody runs.

It applied the production STOP and then exited at the horizon. Production also
exits at a TARGET, and a target truncates exactly the winners a horizon exit
counts in full. It also hardcoded 1.25 ATR while SessionShift/GOLDM has run
3.0 since 2026-08-13.

Both omissions flatter, and not cosmetically. Re-measured 2026-10-14 across
every live cell on the full archive:

    SessionShift / SILVERM   stop only +0.283 t+3.15   full +0.096 t+1.54
    TrendRider   / CRUDEOIL  stop only +0.109 t+2.30   full +0.079 t+1.93
    SessionShift / CRUDEOIL  stop only +0.153 t+2.21   full +0.113 t+2.12

SILVERM was the ONE cell the audit called confirmed, and it does not survive.
The bot's own stop table had said so in a comment since 2026-08-13 - "+0.007
under full geometry, indistinguishable from zero at ANY stop width" - and the
audit disagreed only because of what it left out. Every promotion and
retirement decision in Hokage's history rested on that basis.

Five labs share realised(), so the fix lands in one place and these tests pin
the three things that make it trustworthy: the target is really applied, the
stop is really per-cell, and the pessimistic tie-breaks are still pessimistic.
"""
from __future__ import annotations

import importlib.util
import math
import pathlib
import sys
from datetime import datetime

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

import signal_lab  # noqa: E402

signal_lab._fetch_from_kite = lambda *a, **k: []

import sweep_lab as sl  # noqa: E402
import weekly_audit as wa  # noqa: E402

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot  # noqa: E402


def _bars(rows, start=datetime(2026, 6, 1, 10, 0)):
    """rows: (close, high, low) per 15-minute bar."""
    from datetime import timedelta

    return [
        {"date": start + timedelta(minutes=15 * i), "open": c,
         "close": c, "high": h, "low": lo, "volume": 100}
        for i, (c, h, lo) in enumerate(rows)
    ]


# --------------------------------------------------- the target is applied
#: Late in the MCX session, so sqrt(bars_left) has collapsed and the
#: reward:risk FLOOR is what sets the target - the deterministic case. Early in
#: the day the adaptive leg is far away by design, which is production
#: behaviour and not what these two tests are about.
LATE = datetime(2026, 6, 1, 22, 30)


def test_a_long_that_reaches_the_target_exits_there():
    """THE OMISSION. Without a target this trade would be scored at its
    horizon close, counting a run the system would have cashed out of."""
    # entry 100, atr 10, stop 1.25 -> 87.5; target floor 1.5*1.25*10 = +18.75
    bars = _bars([(100, 100, 100), (110, 125, 105), (104, 104, 104),
                  (103, 103, 103), (102, 102, 102)], start=LATE)
    edge = sl.realised(bars, 0, 1, 10.0, "entry-sessionshift-mcx-v1", "SILVERM")
    assert edge == pytest.approx(1.875), "the target leg was not applied"


def test_a_short_targets_downward():
    bars = _bars([(100, 100, 100), (90, 95, 75), (96, 96, 96),
                  (97, 97, 97), (98, 98, 98)], start=LATE)
    edge = sl.realised(bars, 0, -1, 10.0, "entry-sessionshift-mcx-v1", "SILVERM")
    assert edge == pytest.approx(1.875)


def test_early_in_the_session_the_adaptive_target_is_further_than_the_floor():
    """The whole point of the adaptive leg: more time left, more room to run."""
    early = sl.target_move(10.0, 1.25, sl._bars_left(
        datetime(2026, 6, 1, 10, 0), "SILVERM"))
    late = sl.target_move(10.0, 1.25, sl._bars_left(LATE, "SILVERM"))
    assert early > late
    assert late == pytest.approx(1.5 * 1.25 * 10.0), "the floor should bind late"


def test_a_trade_that_reaches_neither_still_exits_at_the_horizon():
    bars = _bars([(100, 100, 100), (101, 101, 100), (102, 102, 101),
                  (103, 103, 102), (104, 104, 103)])
    edge = sl.realised(bars, 0, 1, 10.0, "entry-sessionshift-mcx-v1", "SILVERM")
    assert edge == pytest.approx(0.4)


def test_the_stop_still_fires():
    bars = _bars([(100, 100, 100), (90, 100, 80), (95, 95, 95),
                  (96, 96, 96), (97, 97, 97)])
    edge = sl.realised(bars, 0, 1, 10.0, "entry-sessionshift-mcx-v1", "SILVERM")
    assert edge == pytest.approx(-1.25)


def test_a_bar_touching_both_resolves_to_the_stop():
    """OHLC cannot say which came first. Resolving the tie to the target would
    flatter every number this produces."""
    # range spans both 87.5 (stop) and 118.75 (target)
    bars = _bars([(100, 100, 100), (100, 130, 80), (100, 100, 100),
                  (100, 100, 100), (100, 100, 100)])
    edge = sl.realised(bars, 0, 1, 10.0, "entry-sessionshift-mcx-v1", "SILVERM")
    assert edge == pytest.approx(-1.25), "an intrabar tie was given to the target"


# ------------------------------------------------- the stop is per cell
def test_the_stop_is_resolved_per_cell_not_assumed():
    assert sl.production_stop_atr("entry-sessionshift-mcx-v1", "GOLDM") == 3.0
    assert sl.production_stop_atr("entry-sessionshift-mcx-v1", "SILVERM") == 1.25


def test_the_resolver_agrees_with_the_bot_everywhere():
    import stop_lab

    for module_id, assets in stop_lab.LIVE_SCOPE.items():
        for asset in assets:
            strategy_id = module_id.replace("entry-", "strat-", 1)
            assert sl.production_stop_atr(module_id, asset) == (
                Bot._thesis_atr_mult_for(Bot, strategy_id, asset)
            ), f"{module_id}/{asset}"


def test_an_unnamed_cell_still_measures_inside_some_stop():
    """A sweep over a hypothetical module must not silently become unstopped -
    an unstopped number is the one that misled for two months."""
    assert sl.production_stop_atr(None, None) == sl.PROD_STOP_ATR
    bars = _bars([(100, 100, 100), (90, 100, 80), (95, 95, 95),
                  (96, 96, 96), (97, 97, 97)])
    assert sl.realised(bars, 0, 1, 10.0) == pytest.approx(-1.25)


def test_the_per_asset_stop_actually_changes_the_result():
    """GOLDM at 3.0 must not stop where SILVERM at 1.25 does, or the per-cell
    resolution is decorative."""
    bars = _bars([(100, 100, 100), (85, 100, 85), (95, 95, 95),
                  (96, 96, 96), (97, 97, 97)])
    silver = sl.realised(bars, 0, 1, 10.0, "entry-sessionshift-mcx-v1", "SILVERM")
    gold = sl.realised(bars, 0, 1, 10.0, "entry-sessionshift-mcx-v1", "GOLDM")
    assert silver == pytest.approx(-1.25), "SILVERM should stop at 1.25"
    assert gold != pytest.approx(-1.25), "GOLDM runs 3.0 and should not stop here"


# --------------------------------------- the target rule is production's
def test_the_target_rule_reads_the_bot_not_a_literal():
    atr, stop_atr, bars_left = 10.0, 1.25, 100.0
    expected = max(
        Bot._OPTION_TARGET_MOVE_FRACTION * atr * math.sqrt(bars_left),
        Bot._OPTION_MIN_REWARD_RISK * stop_atr * atr,
    )
    assert sl.target_move(atr, stop_atr, bars_left) == pytest.approx(expected)


def test_the_target_never_falls_below_the_reward_risk_floor():
    """Late in the session sqrt(bars_left) collapses. The floor is what keeps
    reward:risk honest, and it is the whole reason _risk_pct_for exists."""
    floor = Bot._OPTION_MIN_REWARD_RISK * 1.25 * 10.0
    assert sl.target_move(10.0, 1.25, 0.0) == pytest.approx(floor)


def test_the_target_widens_with_the_stop():
    """A strategy running a wide stop must not be handed a target priced off
    the narrow default - that is the unreachable-target geometry in reverse."""
    assert sl.target_move(10.0, 3.0, 0.0) > sl.target_move(10.0, 1.25, 0.0)


def test_bars_left_shrinks_through_the_session():
    mcx_open = datetime(2026, 6, 1, 10, 0)
    mcx_late = datetime(2026, 6, 1, 22, 0)
    assert sl._bars_left(mcx_open, "SILVERM") > sl._bars_left(mcx_late, "SILVERM")
    assert sl._bars_left(datetime(2026, 6, 1, 23, 30), "SILVERM") == 0.0


def test_mcx_and_index_sessions_close_at_different_times():
    noon = datetime(2026, 6, 1, 16, 0)
    assert sl._bars_left(noon, "SILVERM") > 0, "MCX runs to 23:15"
    assert sl._bars_left(noon, "NIFTY") == 0.0, "the index session closed at 15:20"


# ------------------------------------------------------ the basis is stamped
def test_the_geometry_string_names_what_changed():
    """A silent basis change is worse than the original fault: the policy
    would read last week's number against this week's and call the difference
    a decline in edge."""
    assert "target" in wa.GEOMETRY
    assert "stop-per-cell" in wa.GEOMETRY
    assert wa.GEOMETRY != "holdout-split+stop1.25+tradedbars"


def test_the_basis_change_resets_the_retirement_clock():
    from bots.autonomous import evolution as ev

    old = {"geometry": "holdout-split+stop1.25+tradedbars", "date": "2026-10-12"}
    new = {"geometry": wa.GEOMETRY, "date": "2026-10-19"}
    assert ev._same_geometry(new, old) is False
    assert [d for d in ev.plan([new, old]) if d.action == "archive"] == []


def test_no_lab_holds_its_own_copy_of_the_target_rule():
    """One rule, read from the bot. Two copies drift, and the half that drifts
    is whichever one nobody ran that week."""
    for name in ("weekly_audit", "iv_lab", "event_lab", "stop_lab"):
        src = (ROOT / "tools" / "research" / f"{name}.py").read_text(encoding="utf-8")
        assert "_OPTION_MIN_REWARD_RISK * " not in src, f"{name} re-implements the floor"
