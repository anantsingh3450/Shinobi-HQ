"""Every display called a number "floor" that could not stop anything.

2026-11-02. GOLDM26NOV138500PE was entered at 3566.50 and the first thing the
ladder printed was `floor RATCHETED 0.00 -> 3388.17`, which reads as
protection arriving. Nothing arrived. 3388.17 is `tracking["stop_price"]`
being SEEDED at entry x (1 - tsl_percent), and on a bought option that field
is rung 4's PROFIT floor: it arms only once the peak clears
`_OPTION_TRAIL_ARM_PCT` above entry, and its enforcement sits inside
`if floor_candidates:`, which stays empty until then.

That position peaked at +4.53%. Arming needed 3744.83. It missed by 16.83
points, so nothing ever compared the premium to 3388.17 — and the archive
holds SEVEN consecutive one-minute marks, 19:01:20 to 19:07:23, with the
premium between 3229 and 3375 while every one of them printed floor 3388.17.
It exited on the -12% hard backstop at 2934, a loss of Rs 6,325 against the
Rs 1,910 the displayed floor implied.

THE EXIT WAS CORRECT. The grades were already fixed (02dc802, 2026-11-01) and
read `risk_pct_at_entry` instead. What was never fixed is what a human SEES:
the log line, the Telegram status and the premium archive all printed
stop_price and called it the floor. It misled the commander, and it misled me
for an hour while I diagnosed the loss as an enforcement bug.

So the displays now show the level that would ACTUALLY fire. The enforcement
path is untouched, deliberately: this describes the ladder, it does not change
it, and no risk constant moves.
"""
from __future__ import annotations

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot


class _Probe(Bot):
    """The real methods and the real constants, no broker and no boot."""

    def __init__(self):
        pass


#: The real trade, from `positions` and the 17:02 ladder trace.
GOLD_ENTRY = 3566.50
GOLD_SEED = GOLD_ENTRY * 0.95          # 3388.175, the number that was printed
GOLD_PEAK = 3728.00                    # +4.53%, from the premium archive
GOLD_BACKSTOP = GOLD_ENTRY * 0.88      # premium >= 500 -> the 12% tier


@pytest.fixture
def bot():
    return _Probe()


# ===================================================== the GOLDM replay
def test_an_unarmed_position_reports_the_backstop_not_the_seed(bot):
    """THE BUG. 3388.17 was never live; 3138.52 always was."""
    level, rung = bot._effective_premium_floor(
        GOLD_ENTRY, GOLD_PEAK, {"stop_price": GOLD_SEED})
    assert rung == "backstop"
    assert level == pytest.approx(GOLD_BACKSTOP, abs=0.01)
    assert level < GOLD_SEED, "the real floor was BELOW the one on screen"


def test_the_displayed_risk_was_understated_by_more_than_four_thousand_rupees(bot):
    """What the number cost in plain terms, on 10 lots."""
    level, _ = bot._effective_premium_floor(
        GOLD_ENTRY, GOLD_PEAK, {"stop_price": GOLD_SEED})
    implied = (GOLD_ENTRY - GOLD_SEED) * 10
    real = (GOLD_ENTRY - level) * 10
    assert implied == pytest.approx(1783.25, abs=1)     # 5% of entry, 10 lots
    assert real == pytest.approx(4279.80, abs=1)        # 12% of entry, 10 lots
    assert real - implied > 2_400


def test_missing_the_arm_by_a_fraction_still_means_unarmed(bot):
    """3728.00 against a 3744.83 threshold. There is no partial arming."""
    threshold = GOLD_ENTRY * (1.0 + Bot._OPTION_TRAIL_ARM_PCT)
    assert GOLD_PEAK < threshold
    _level, rung = bot._effective_premium_floor(
        GOLD_ENTRY, threshold - 0.01, {"stop_price": GOLD_SEED})
    assert rung == "backstop"


# ===================================================== once the trail arms
def test_an_armed_trail_is_reported_as_the_trail(bot):
    peak = GOLD_ENTRY * 1.06                      # clears +5%
    tracking = {"stop_price": GOLD_ENTRY}         # rung 4 holds it at breakeven
    level, rung = bot._effective_premium_floor(GOLD_ENTRY, peak, tracking)
    assert rung == "trail"
    assert level == pytest.approx(GOLD_ENTRY)


def test_the_backstop_wins_while_it_sits_higher(bot):
    """Armed is not the same as protected. If rung 4's stored floor is still
    below the backstop, the backstop is what a falling premium meets first."""
    peak = GOLD_ENTRY * 1.06
    level, rung = bot._effective_premium_floor(
        GOLD_ENTRY, peak, {"stop_price": GOLD_ENTRY * 0.80})
    assert rung == "backstop"
    assert level == pytest.approx(GOLD_BACKSTOP, abs=0.01)


def test_a_far_runner_reports_a_floor_above_entry(bot):
    """Past +11.1% the trail finally clears entry and means something."""
    peak = GOLD_ENTRY * 1.30
    stored = peak * (1.0 - Bot._OPTION_TRAIL_LOCK_FRACTION)
    level, rung = bot._effective_premium_floor(
        GOLD_ENTRY, peak, {"stop_price": stored})
    assert rung == "trail"
    assert level > GOLD_ENTRY


# ===================================================== the cheap-premium tiers
@pytest.mark.parametrize("entry,pct", [
    (3566.50, 0.12),   # >= 500
    (300.00, 0.20),    # >= 200
    (150.00, 0.28),    # >= 100
    (18.40, 0.40),     # the gas calls
])
def test_each_backstop_tier_is_reported(bot, entry, pct):
    level, rung = bot._effective_premium_floor(entry, entry, {"stop_price": entry * 0.95})
    assert rung == "backstop"
    assert level == pytest.approx(entry * (1.0 - pct), abs=0.01)


def test_the_gas_call_of_2026_11_03(bot):
    """Entry 17.25, peak 17.80 (+3.2%) — short of +5%, so its real floor was
    the 40% tier at 10.35, not the 16.39 every ladder line printed."""
    level, rung = bot._effective_premium_floor(17.25, 17.80, {"stop_price": 16.39})
    assert rung == "backstop"
    assert level == pytest.approx(10.35, abs=0.01)


# ===================================================== it must not misreport
def test_a_zero_entry_says_unknown_rather_than_zero(bot):
    """A floor of 0.00 reads as "no stop at all", which is a claim. Unknown is
    the truth when there is nothing to compute from."""
    assert bot._effective_premium_floor(0.0, 0.0, {}) == (0.0, "unknown")
    assert bot._effective_premium_floor(None, None, {}) == (0.0, "unknown")


def test_a_missing_stop_price_is_not_an_error(bot):
    level, rung = bot._effective_premium_floor(GOLD_ENTRY, GOLD_ENTRY, {})
    assert rung == "backstop"
    assert level == pytest.approx(GOLD_BACKSTOP, abs=0.01)


def test_rubbish_in_tracking_never_raises(bot):
    level, rung = bot._effective_premium_floor(
        GOLD_ENTRY, GOLD_ENTRY * 1.06, {"stop_price": "not a number"})
    assert rung in ("backstop", "unknown")


def test_it_never_writes_to_tracking(bot):
    """It describes the ladder. The ladder's enforcement reads stop_price
    directly, so this method touching it would be a risk change."""
    tracking = {"stop_price": GOLD_SEED, "peak_price": GOLD_PEAK}
    before = dict(tracking)
    bot._effective_premium_floor(GOLD_ENTRY, GOLD_PEAK, tracking)
    assert tracking == before


# ===================================================== the enforcement is untouched
def test_the_ladder_still_holds_through_the_seeded_floor(bot):
    """The DISPLAY changed; the behaviour did not. This is the same replay
    that proved the original diagnosis, and it must still come out the same —
    otherwise a telemetry fix has quietly moved a stop."""
    from datetime import datetime

    class _Replay(Bot):
        def __init__(self):
            pass

        def _get_validated_live_price(self, symbol):
            return 138500.0, "probe"

        def _archive_mark(self, *a, **k):
            pass

        def _trace_ladder(self, *a, **k):
            pass

    replay = _Replay()
    for premium in (3388.17, 3375.5, 3327.0, 3229.0):
        tracking = {
            "peak_price": GOLD_PEAK, "stop_price": GOLD_SEED,
            "underlying": "GOLDM26NOVFUT",
            "entry_underlying_price": 138500.0,
            "entry_underlying_atr": 900.0,
            "strategy_id": "strat-sessionshift-mcx-v1",
        }
        should, reason, _ = replay._evaluate_option_exit_ladder(
            "GOLDM26NOV138500PE", 10.0, GOLD_ENTRY, premium, tracking,
            datetime(2026, 11, 2, 19, 0), True)
        assert not should, f"premium {premium} now exits: {reason}"

    tracking = {
        "peak_price": GOLD_PEAK, "stop_price": GOLD_SEED,
        "strategy_id": "strat-sessionshift-mcx-v1",
    }
    should, reason, _ = replay._evaluate_option_exit_ladder(
        "GOLDM26NOV138500PE", 10.0, GOLD_ENTRY, 3138.52, tracking,
        datetime(2026, 11, 2, 19, 0), True)
    assert should and "Backstop" in reason
