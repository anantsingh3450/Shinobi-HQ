"""Every Monday, Hokage could not size a trade until lunchtime.

ATR asked the venue for 2 CALENDAR days of 15-minute candles and required 14
of them. The bias engine and MarketContext asked for 3 and required 21.

Calendar days are not trading days. On a Monday, "now - 2 days" reaches back
to Saturday; the market was shut Saturday and Sunday, so the window holds only
Monday's own bars. The 14th fifteen-minute bar does not exist until three and
a half hours after the open.

Measured on 2026-10-12, a Monday:

    ATR unavailable for all seven assets, 10:00 -> 12:15
    "Cannot size NIFTY: ATR unavailable" at 10:31, 10:45 and 11:00

Three NIFTY entries had passed every gate -- the entry module, the bias
engine, volume, liquidity, the IV premium guard -- and then died on a
lookback. Not a refusal. A defect that looked exactly like restraint, which is
why it survived: the log said "standing aside", and standing aside is what
Hokage is supposed to do most of the time.

The 3-day sites are the same bug with a longer fuse: they survive an ordinary
Monday (Friday is within reach) and break after any holiday, which is when
nobody is watching closely.

THE RULE: a lookback measured in calendar days must be wide enough that the
longest market closure still leaves a full prior session inside it.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot

SRC = pathlib.Path("src/bots/autonomous/autonomous_bot.py")

#: Bars a 15-minute series yields per session. One prior session is enough for
#: every consumer below; the window only has to REACH one.
BARS_PER_SESSION_NSE = 25      # 09:15-15:30
BARS_PER_SESSION_MCX = 58      # 09:00-23:30

#: The most candles any consumer of this window demands.
MAX_BARS_REQUIRED = 21         # bias engine and MarketContext


def test_the_window_survives_a_normal_weekend():
    """Saturday and Sunday. The old 2-day ATR window did not."""
    assert AutonomousTradingBot._INTRADAY_LOOKBACK_DAYS > 2 + 1


def test_the_window_survives_a_long_weekend_with_a_holiday():
    """Friday holiday plus the weekend is three closed days; a Monday holiday
    plus the weekend is another three. A 3-day window dies on both."""
    assert AutonomousTradingBot._INTRADAY_LOOKBACK_DAYS > 3 + 1


def test_the_window_survives_a_diwali_length_cluster():
    """India's exchange holidays cluster. Five consecutive closed days has
    happened; the window must still reach a prior session."""
    longest_closure_days = 5
    assert AutonomousTradingBot._INTRADAY_LOOKBACK_DAYS >= longest_closure_days + 2


def test_one_reachable_session_supplies_every_consumer():
    """The window does not need many sessions -- it needs to REACH one."""
    assert BARS_PER_SESSION_NSE >= MAX_BARS_REQUIRED
    assert BARS_PER_SESSION_MCX >= MAX_BARS_REQUIRED


# ----------------------------------------- no site may hardcode its own window
def test_no_intraday_request_hardcodes_a_short_calendar_window():
    """Three sites each carried their own number: days=2 for ATR, days=3 twice.
    A new one added later is the regression this guards."""
    tree = ast.parse(SRC.read_text(encoding="utf-8"))

    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "timedelta"):
            continue
        for kw in node.keywords:
            if kw.arg != "days" or not isinstance(kw.value, ast.Constant):
                continue
            if kw.value.value <= 7:
                offenders.append(f"line {node.lineno}: timedelta(days={kw.value.value})")
    assert not offenders, (
        "a short calendar lookback is back; use _INTRADAY_LOOKBACK_DAYS: "
        f"{offenders}"
    )


def test_every_intraday_request_uses_the_shared_constant():
    src = SRC.read_text(encoding="utf-8")
    uses = src.count("timedelta(days=self._INTRADAY_LOOKBACK_DAYS)")
    assert uses >= 3, (
        f"expected the ATR, bias-engine and MarketContext windows to share the "
        f"constant, found {uses}"
    )


def test_the_constant_is_documented_with_the_incident():
    """A bare number invites someone shrinking it back to save a few candles."""
    src = SRC.read_text(encoding="utf-8")
    block = src.split("_INTRADAY_LOOKBACK_DAYS = ")[0][-2200:]
    assert "CALENDAR DAYS ARE NOT TRADING DAYS" in block
    assert "Cannot size NIFTY" in block


# ------------------------------------------------ absence is still not faked
def test_atr_still_returns_none_rather_than_a_fabricated_value():
    """Widening the window must not turn 'unknown' into a guess. A fabricated
    ATR sizes a real position."""
    src = SRC.read_text(encoding="utf-8")
    assert "rather than a\n            f\"fabricated value" in src or \
           "fabricated value" in src
    assert "return None" in src.split("ATR unavailable for")[1][:400]
