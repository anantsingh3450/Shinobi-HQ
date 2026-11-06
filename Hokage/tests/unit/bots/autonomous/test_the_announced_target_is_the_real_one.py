"""There were two targets and the commander was shown the dead one.

2026-11-06 10:30:37, NATURALGAS 280 CE bought at a premium of 14.55. The
entry alert said:

    • *Target*: ₹16.01

which is entry x 1.10 -- `tracked_entry_price * (1.0 + self.tp_percent)`,
written by all three entry paths and quoted straight into the alert. Sixty-six
seconds later the first exit-ladder tick overwrote `target_price` with its own
adaptive figure:

    10:31:43  Exit ladder NATURALGAS26NOV280CE: ... target 16.73
    11:56:44  Triggering Exit (TARGET_HIT: premium 16.65 reached adaptive
              target 16.61 (entry 14.55))

and the revised number was never announced: zero Telegram messages mentioned
a target after entry. The premium crossed 16.01 at 11:28:01 and stayed above
it for nine of the seventy-seven archived marks, so for twenty-eight minutes
the commander watched a position sit past its stated target without selling,
and asked whether that was a way of earning more or a bug.

Neither. He had been given a number nothing in the system acts on -- the same
defect as the `floor` printed on every poll that could not stop anything
(fixed two days earlier, after it cost a real 7% on GOLDM). The trade closed
+2,625 on the real target, so this one cost nothing, by the luck that the
dead number happened to be LOWER than the live one.

The fix is one formula in one place: `_adaptive_premium_target`. The exit
ladder calls it, and the entry paths seed `target_price` by calling it too, so
the figure in the alert is the figure the engine will use. It does still
MOVE -- it is sized from the underlying's ATR times the square root of the
bars left in the session, so it decays as the day runs out of time to deliver
the move. That is the design, so the alert says so rather than printing
something that looks fixed.
"""
from __future__ import annotations

import inspect
from datetime import datetime, timedelta, timezone

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot
from integrations.notifications.telegram_bot import TelegramBotUplink

IST = timezone(timedelta(hours=5, minutes=30))

# The real fill, from active_positions.json and the 2026-11-06 log.
ENTRY_PREMIUM = 14.55
UND_PRICE = 279.40
UND_ATR = 1.307142857142862
STRATEGY = "strat-rangefade-mcx-v1"
UNDERLYING = "NATURALGAS"
FILLED_AT = datetime(2026, 11, 6, 10, 30, 37, tzinfo=IST)

#: What the ladder printed on its first tick, 66 seconds after the fill.
LADDER_FIRST_TICK = 16.73
#: What the alert said instead.
DEAD_NUMBER = 16.01


#: Read off the constructor rather than hardcoded, so this file measures the
#: production take-profit and not a copy of it that can drift.
TP_PERCENT = inspect.signature(Bot.__init__).parameters["tp_percent"].default


@pytest.fixture
def bot() -> Bot:
    """A bare bot. _adaptive_premium_target reads only class constants and
    _risk_pct_for, so none of the engine has to be started to measure it.
    tp_percent is an __init__ argument, so the no-ATR fallback needs it set."""
    b = Bot.__new__(Bot)
    b.tp_percent = TP_PERCENT
    return b


def _target(bot, at=FILLED_AT, is_mcx=True, atr=UND_ATR):
    return bot._adaptive_premium_target(
        ENTRY_PREMIUM, UND_PRICE, atr, STRATEGY, UNDERLYING, is_mcx, at)


# ===================================================== the incident, replayed
def test_the_entry_seed_is_what_the_ladder_will_use(bot):
    """THE RAIL. Seed and first tick must be the same number, or the alert is
    quoting something the engine has already discarded."""
    assert round(_target(bot), 2) == LADDER_FIRST_TICK


def test_the_alert_no_longer_quotes_the_ten_percent_number(bot):
    """What the entry path now stamps, at the real fill instant."""
    seeded, adaptive = bot._seed_target_price(
        ENTRY_PREMIUM, UNDERLYING, UND_PRICE, UND_ATR, STRATEGY, FILLED_AT)
    assert adaptive is True
    assert seeded == LADDER_FIRST_TICK
    assert seeded != round(ENTRY_PREMIUM * (1.0 + TP_PERCENT), 2), \
        "the dead number is back in the alert"
    assert DEAD_NUMBER == round(ENTRY_PREMIUM * (1.0 + TP_PERCENT), 2), \
        "the observed value: entry x 1.10 is what the alert used to say"


def test_the_dead_number_was_reachable_and_the_real_one_was_not(bot):
    """Why the commander saw what he saw: the premium spent 28 minutes between
    the two figures. 16.05 is a real archived mark from 11:28:01."""
    observed = 16.05
    assert observed > DEAD_NUMBER, "the alert's target had been passed"
    assert observed < _target(bot, at=datetime(2026, 11, 6, 11, 28, tzinfo=IST)), \
        "the engine's target had NOT been reached, which is why it held"


def test_the_real_exit_price_did_clear_the_real_target(bot):
    """It sold at 16.65 against 16.61. The engine was never wrong."""
    at_exit = datetime(2026, 11, 6, 11, 56, 44, tzinfo=IST)
    assert 16.65 >= round(_target(bot, at=at_exit), 2) == 16.61


# ===================================================== the target does move
def test_the_target_decays_through_the_session(bot):
    """It is sized from bars LEFT, so it falls as the day runs out of time to
    deliver the move. An alert printing one figure as fixed is lying by
    omission, which is why the wording says it drifts."""
    morning = _target(bot, at=datetime(2026, 11, 6, 10, 30, tzinfo=IST))
    midday = _target(bot, at=datetime(2026, 11, 6, 14, 0, tzinfo=IST))
    evening = _target(bot, at=datetime(2026, 11, 6, 22, 0, tzinfo=IST))
    assert morning > midday > evening


def test_the_decay_is_floored_by_reward_to_risk(bot):
    """It decays towards the minimum reward:risk the position is taking, never
    to zero, or a late-session trade would target its own entry price."""
    at_close = datetime(2026, 11, 6, 23, 14, tzinfo=IST)
    assert _target(bot, at=at_close) > ENTRY_PREMIUM


def test_the_session_clock_is_the_instruments_own(bot):
    """MCX runs to 23:15 on 5-minute bars, NSE to 15:20 on 15-minute bars. Two
    different clocks for the same fill must give two different targets, or the
    entry path and the exit path would disagree again."""
    assert _target(bot, is_mcx=True) != _target(bot, is_mcx=False)


@pytest.mark.parametrize("symbol,expected", [
    ("NATURALGAS", True), ("GOLDM26NOVFUT", True), ("CRUDEOIL", True),
    ("SILVERM", True), ("NIFTY", False), ("BANKNIFTY", False), ("SENSEX", False),
])
def test_the_mcx_clock_is_chosen_by_symbol(bot, symbol, expected):
    """Recognised by symbol so a paper-venue commodity option still squares
    off at the MCX close. The entry path has no venue to ask."""
    assert bot._is_mcx_symbol(symbol) is expected


# =============================================== no ATR means no target rung
def test_without_an_entry_atr_there_is_no_target_at_all(bot):
    """The ladder has always SKIPPED the rung rather than fabricate a level.
    So the honest answer is None, not 10%."""
    assert _target(bot, atr=None) is None
    assert _target(bot, atr=0) is None


def test_the_seed_flags_that_no_target_rung_is_live(bot):
    """The tp_percent figure is still stored, because the dashboard, the mark
    archive and the review all expect a float. The flag is how the alert knows
    not to call it a target."""
    seeded, adaptive = bot._seed_target_price(
        ENTRY_PREMIUM, UNDERLYING, UND_PRICE, None, STRATEGY, FILLED_AT)
    assert adaptive is False
    assert seeded == pytest.approx(ENTRY_PREMIUM * (1.0 + TP_PERCENT), abs=0.01)


# ===================================================== what the alert says
@pytest.fixture
def uplink(monkeypatch, tmp_path) -> TelegramBotUplink:
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path))
    b = TelegramBotUplink(bot_token="111:fake-not-a-real-token", chat_id="999")
    b.enabled = True
    sent: list[str] = []
    monkeypatch.setattr(b, "send_message", lambda text: sent.append(text) or True)
    b._sent = sent
    return b


def test_an_adaptive_target_is_announced_as_adaptive(uplink):
    uplink.notify_entry(
        symbol="NATURALGAS26NOV280CE", cmp=ENTRY_PREMIUM,
        target=LADDER_FIRST_TICK, edge=69.0, strategy="RangeFade",
        target_adaptive=True)
    msg = uplink._sent[0]
    assert "₹16.73" in msg
    assert "adaptive" in msg
    assert "runs out of time" in msg, (
        "a figure presented as fixed is the defect in a different font")


def test_no_target_rung_is_announced_as_no_target(uplink):
    """Naming a level nothing acts on is exactly what went wrong. Say there
    isn't one."""
    uplink.notify_entry(
        symbol="NIFTY26NOV24000CE", cmp=ENTRY_PREMIUM,
        target=DEAD_NUMBER, edge=55.0, target_adaptive=False)
    msg = uplink._sent[0]
    assert "none" in msg
    assert "trail or the stop" in msg
    assert "16.01" not in msg, "it printed the figure it was told not to trust"


def test_a_caller_that_says_nothing_still_gets_a_plain_line(uplink):
    """Back-compat: the manual and legacy call sites, and any test that
    predates the flag."""
    uplink.notify_entry(symbol="X26NOV100CE", cmp=10.0, target=11.0, edge=50.0)
    msg = uplink._sent[0]
    assert "• *Target*: ₹11.00" in msg
    assert "adaptive" not in msg


# ===================================================== the source-level rail
def test_the_formula_lives_in_exactly_one_place():
    """The whole defect was two copies of 'the target'. If the expression
    reappears outside _adaptive_premium_target, they can diverge again."""
    module_src = inspect.getsource(inspect.getmodule(Bot))
    owner = inspect.getsource(Bot._adaptive_premium_target)
    marker = "_OPTION_TARGET_MOVE_FRACTION * self._OPTION_TARGET_ATM_DELTA"
    assert module_src.count(marker) == 1, (
        "the adaptive target formula is written more than once")
    assert marker in owner, "the one copy is not the one the ladder calls"


def test_the_ladder_takes_its_target_from_that_function():
    src = inspect.getsource(Bot._evaluate_option_exit_ladder)
    assert "self._adaptive_premium_target(" in src
    assert "TARGET_HIT" in src


def test_every_entry_path_stamps_whether_the_target_is_live():
    """A fourth entry path added later must not quietly reintroduce the
    divergence: if it seeds target_price it has to seed the flag beside it."""
    module_src = inspect.getsource(inspect.getmodule(Bot))
    seeds = [ln.strip() for ln in module_src.splitlines()
             if '"target_price":' in ln]
    assert len(seeds) >= 3, f"expected the three entry paths, found {len(seeds)}"
    for line in seeds:
        assert "self.tp_percent" not in line, (
            f"an entry path still seeds the dead 10% target: {line}")
    assert module_src.count('"target_is_adaptive":') == len(seeds), (
        "an entry path seeds a target without saying whether it is live")


def test_no_entry_path_quotes_tp_percent_to_the_alert():
    """The bug in one expression."""
    module_src = inspect.getsource(inspect.getmodule(Bot))
    for ln in module_src.splitlines():
        if "notify_entry" in ln or "target=" in ln:
            assert "tp_percent" not in ln, ln
