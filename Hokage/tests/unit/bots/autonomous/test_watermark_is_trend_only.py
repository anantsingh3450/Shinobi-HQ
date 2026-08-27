"""The re-entry watermark is a momentum rule. Do not point it at a fade module.

2026-08-27, on the one asset with a confirmed edge:

    RangeFade won the NATURALGAS auction   17 times
    blocked by ReentryWatermark            16
    actually traded                         1     (+2,000, TARGET_HIT)

The rule reads "took long profit at 281.40; now 279.20 — not buying the dip of
our own winner". That is sound for a module whose thesis is that a move
CONTINUES. RangeFade declares `COUNTER_TREND = True`: its entire thesis is that
price stretched BELOW VWAP snaps back, so a lower price is a BETTER entry, not a
stale one. The gate was keyed on the symbol and could not see which module had
won the auction, so it applied a trend rule to a fade.

MEASURED BEFORE CHANGING — is the Nth signal of a day worse than the first?
Train vs hold-out, full geometry, RangeFade/NATURALGAS long:

    1st of the day   TRAIN n=5  +1.907 t=+1.10 | HOLD n=20 -0.059 t=-0.21
    2nd onward       TRAIN n=11 +1.946 t=+2.15 | HOLD n=71 +0.225 t=+1.28
    3rd onward       TRAIN n=7  +2.148 t=+2.93 | HOLD n=51 +0.267 t=+1.38

The repeats measure BETTER on both halves, and the hold-out puts the FIRST
signal of the day slightly negative. The watermark was keeping the worst signal
and discarding the best.

WHAT THIS IS NOT. Nothing above clears t>=2 on both halves, and the ordinal
split is a proxy — the watermark only triggers after a PROFITABLE exit, while
"2nd onward" counts every repeat. So this is the removal of a rule the evidence
does not support from the one module whose thesis it contradicts, not a
confirmed improvement. Commander-approved 2026-08-27.

TREND MODULES KEEP IT IN FULL FORCE, and the tests below spend as much effort on
that as on the change itself: a fix that quietly disabled the watermark for
SessionShift would be a much larger mistake than the one it repairs.
"""
from __future__ import annotations

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

GAS = "NATURALGAS"


def _bot(watermark_level: float = 281.40, direction: str = "long"):
    bot = object.__new__(Bot)
    bot._active_positions_tracking = {}
    bot._target_exit_watermarks = {
        GAS: {"direction": direction, "level": watermark_level}
    }
    return bot


def _gate(bot, *, counter_trend, price=279.20, direction="long"):
    return Bot._entry_cluster_gate(
        bot, GAS, direction, price,
        family={GAS, "CRUDEOIL"}, max_same_direction=2, family_label="ENERGY",
        counter_trend=counter_trend,
    )


# ------------------------------------------------------ the fade module passes
def test_a_counter_trend_module_may_buy_below_its_own_winner():
    """The exact 2026-08-27 block: profit taken at 281.40, signal at 279.20."""
    ok, reason = _gate(_bot(), counter_trend=True)
    assert ok, reason
    assert "counter-trend" in reason


def test_a_trend_module_is_still_refused_at_the_same_price():
    ok, reason = _gate(_bot(), counter_trend=False)
    assert not ok
    assert "ReentryWatermark" in reason
    assert "281.40" in reason


@pytest.mark.parametrize("price", [279.20, 279.30, 278.60, 281.39])
def test_every_price_blocked_that_day_now_passes_for_the_fade(price):
    """The four underlying levels the log actually recorded being refused."""
    assert _gate(_bot(), counter_trend=True, price=price)[0]


def test_the_watermark_still_releases_a_trend_module_past_its_level():
    """The rule's own escape hatch must survive: re-entry unlocks past 281.40."""
    assert _gate(_bot(), counter_trend=False, price=281.41)[0]


# ------------------------------------- the other gates must not be weakened
def test_the_correlation_cap_still_applies_to_a_counter_trend_module():
    """Only the watermark is scoped away. A fade module must not become exempt
    from the portfolio caps — those stop one bet being taken three times, which
    has nothing to do with trend or fade."""
    bot = _bot()
    bot._active_positions_tracking = {
        "a": {"underlying": GAS, "option_type": "CE"},
        "b": {"underlying": "CRUDEOIL", "option_type": "CE"},
    }
    ok, reason = _gate(bot, counter_trend=True)
    assert not ok
    assert "CorrelationCap" in reason


def test_the_opposing_family_bet_still_applies_to_a_counter_trend_module():
    bot = _bot()
    bot._active_positions_tracking = {
        "a": {"underlying": "CRUDEOIL", "option_type": "PE"},
    }
    ok, reason = _gate(bot, counter_trend=True)
    assert not ok
    assert "OpposingFamilyBet" in reason


def test_the_caps_are_checked_before_the_watermark_exemption():
    """Ordering matters: if the counter-trend return sat above the cap checks it
    would silently exempt a fade module from every portfolio gate at once."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(Bot._entry_cluster_gate)))
    cap_line = watermark_line = None
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "CorrelationCap" in node.value and cap_line is None:
                cap_line = node.lineno
            if "counter-trend module" in node.value and watermark_line is None:
                watermark_line = node.lineno
    assert cap_line and watermark_line
    assert cap_line < watermark_line, (
        "the counter-trend exemption must come AFTER the correlation cap"
    )


# --------------------------------------------------- both call sites wired
@pytest.mark.parametrize("method", [
    "_scan_and_enter_mcx_opportunities",
])
def test_the_entry_paths_tell_the_gate_which_kind_of_module_won(method):
    """A parameter defaulting to False is only a fix if the callers set it."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(getattr(Bot, method))))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "attr", None) == "_entry_cluster_gate"):
            assert any(kw.arg == "counter_trend" for kw in node.keywords), (
                f"{method} calls the cluster gate without saying whether the "
                f"winning module is counter-trend"
            )
            return
    pytest.fail(f"{method} does not call _entry_cluster_gate")


def test_rangefade_is_the_module_this_protects():
    from bots.strategy.components.mcx_entries import RangeFadeEntry

    assert RangeFadeEntry.COUNTER_TREND is True


def test_sessionshift_is_not_counter_trend_and_keeps_the_watermark():
    from bots.strategy.components.mcx_entries import SessionShiftEntry

    assert getattr(SessionShiftEntry, "COUNTER_TREND", False) is False
