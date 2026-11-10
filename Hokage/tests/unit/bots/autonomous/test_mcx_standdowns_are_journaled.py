"""The whole commodity arena could stand down all day and say nothing.

2026-11-10. The question was why `no_trade_decisions` stops at 22:15 IST every
day while MCX trades to 23:30. The answer was benign — `_MCX_LAST_ENTRY` is
(22, 30), commander-approved 2026-07-18, and 22:15 is the last 15-minute tick
inside the window. Nothing wrong with it.

What WAS wrong is how the scan left. Five bare `return`s, and four of them
deny every commodity in the league:

    * the ordinary 09:30-22:30 entry window is shut
    * a special session's published hours are shut
    * no MCX venue is attached to the orchestrator
    * the account is at or below the Rs 1,000 cash floor

The index league journals its own equivalent with a reason the gate tally can
rank ("Late-session cutoff (15:00 IST): no new entries into the close."). The
MCX ones ranked nowhere, so an empty chest standing the entire arena down for
a whole session was indistinguishable, in the record, from a quiet market.
That exact failure — a strategy with no chest that still wins its auction and
then cannot fill — has already cost both leagues a day.

THE RATE LIMIT IS PART OF THE FIX, NOT A CONCESSION. A 15-minute scan would
write ~38 window-shut rows a day. `tools/ops/session_coverage.py` counts rows
in this table and calls any day with 20 of them a session ATTENDED, so a row
per cycle would manufacture coverage out of a shut market and bend the uptime
number in the flattering direction. Once a day, per reason.
"""
from __future__ import annotations

import ast
import datetime as dt
import inspect
import textwrap

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot
from bots.strategy.mcx_portfolio import MCX_UNIVERSE


class _Journal:
    def __init__(self):
        self.records = []

    def record_no_trade_decision(self, decision):
        self.records.append(decision)


def _bot(*, parked=("CRUDEOIL", "SILVERM"), now=None):
    bot = object.__new__(Bot)
    bot.journal = _Journal()
    bot.is_parked = lambda s: str(s).upper() in {p.upper() for p in parked}
    bot._now_ist = lambda: (now or dt.datetime(2026, 11, 10, 22, 30))
    return bot


def _assets(bot):
    return [r.asset for r in bot.journal.records]


def _reasons(bot):
    return [r.reasons[0] for r in bot.journal.records]


# ----------------------------------------------------- the stand-down is recorded
def test_a_league_wide_standdown_names_every_unparked_asset():
    bot = _bot()
    Bot._journal_league_standdown(bot, "mcx-chest-empty", "cash is Rs 0")
    assert sorted(_assets(bot)) == ["GOLDM", "NATURALGAS"]
    assert all(r.supporting_evidence.get("league") == "MCX"
               for r in bot.journal.records)


def test_a_parked_asset_is_not_named_again():
    """A park is announced at boot. Restating it every day is the 2026-10-13
    noise, and it would bury the entries that carry information."""
    bot = _bot(parked=MCX_UNIVERSE)
    Bot._journal_league_standdown(bot, "mcx-chest-empty", "cash is Rs 0")
    assert _assets(bot) == []


def test_the_reason_reaches_the_record_verbatim():
    bot = _bot()
    Bot._journal_league_standdown(bot, "mcx-venue-missing", "no MCX venue")
    assert all(r == "no MCX venue" for r in _reasons(bot))


# ------------------------------------------------------------- once a day, not once a cycle
def test_the_same_reason_is_recorded_once_a_day():
    bot = _bot()
    for _ in range(38):
        Bot._journal_league_standdown(bot, "mcx-window-shut-for-the-day", "shut")
    assert len(bot.journal.records) == 2      # one per unparked asset, once


def test_two_different_reasons_both_get_recorded():
    bot = _bot()
    Bot._journal_league_standdown(bot, "mcx-window-shut-for-the-day", "shut")
    Bot._journal_league_standdown(bot, "mcx-chest-empty", "broke")
    assert sorted(set(_reasons(bot))) == ["broke", "shut"]


def test_a_new_day_reopens_every_reason():
    bot = _bot(now=dt.datetime(2026, 11, 10, 22, 30))
    Bot._journal_league_standdown(bot, "mcx-window-shut-for-the-day", "shut")
    bot._now_ist = lambda: dt.datetime(2026, 11, 11, 22, 30)
    Bot._journal_league_standdown(bot, "mcx-window-shut-for-the-day", "shut")
    assert len(bot.journal.records) == 4

def test_a_row_per_cycle_would_forge_session_coverage():
    """The rate limit exists because `session_coverage` counts these rows.

    MIN_DECISIONS_FOR_A_FULL_SESSION is 20. Thirty-eight window-shut rows
    would make a day the market was closed read as a session ATTENDED, which
    is worse than noise: it moves the uptime number in the direction that
    flatters the system.
    """
    import sys
    from pathlib import Path

    ops = str(Path(__file__).resolve().parents[4] / "tools" / "ops")
    if ops not in sys.path:
        sys.path.insert(0, ops)
    import session_coverage

    bot = _bot()
    for _ in range(38):
        Bot._journal_league_standdown(bot, "mcx-window-shut-for-the-day", "shut")
    assert len(bot.journal.records) < session_coverage.MIN_DECISIONS_FOR_A_FULL_SESSION


# --------------------------------------------------- the two halves of the window
def test_before_the_open_and_after_the_close_are_different_keys():
    """One key would let the morning claim the day and lose the 22:30 row.

    Before 09:30 and after 22:30 are the same `elif`. Under a single key the
    08:45 tick — which happens first, every day, because that is when he
    starts — would consume the day's one slot and the stand-down worth having
    would never be written.
    """
    src = textwrap.dedent(inspect.getsource(
        Bot._scan_and_enter_mcx_opportunities))
    tree = ast.parse(src)
    keys = {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value.startswith("mcx-window-")}
    assert len(keys) == 2, f"both halves of the window need their own key: {keys}"


def test_every_standdown_key_is_distinct():
    src = textwrap.dedent(inspect.getsource(
        Bot._scan_and_enter_mcx_opportunities))
    tree = ast.parse(src)
    keys = [n.args[0].value for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(getattr(n.func, "attr", None), str)
            and n.func.attr == "_journal_league_standdown"
            and n.args and isinstance(n.args[0], ast.Constant)]
    assert len(keys) == 4, f"expected four journaled stand-downs, got {keys}"
    assert len(set(keys)) == len(keys), f"duplicate key collapses two causes: {keys}"


# ------------------------------------------------------------------ the weekend
def test_the_weekend_return_is_deliberately_not_journaled():
    """A weekend is the absence of a session, not a stand-down.

    Which days traded is already defined by the candle archive. Rows every
    Saturday would answer a question nobody asked — and, per the coverage
    test above, pad a non-session.
    """
    src = textwrap.dedent(inspect.getsource(
        Bot._scan_and_enter_mcx_opportunities))
    tree = ast.parse(src)
    weekend = [n for n in ast.walk(tree)
               if isinstance(n, ast.If)
               and "weekday" in ast.dump(n.test)]
    assert weekend, "the weekday guard moved; this test must be re-aimed"
    body = ast.dump(ast.Module(body=weekend[0].body, type_ignores=[]))
    assert "_journal_league_standdown" not in body


# ------------------------------------------------------------- never fatal
@pytest.mark.parametrize("broken", ["journal", "is_parked", "_now_ist"])
def test_a_journal_fault_cannot_stop_a_scan(broken):
    """A record of a refusal must never be able to become the refusal."""
    bot = _bot()
    if broken == "journal":
        class _Boom:
            def record_no_trade_decision(self, d):
                raise RuntimeError("disk full")
        bot.journal = _Boom()
    else:
        def _raise(*a, **k):
            raise RuntimeError("boom")
        setattr(bot, broken, _raise)
    Bot._journal_league_standdown(bot, "mcx-chest-empty", "broke")   # must not raise


def test_a_missing_journal_is_survived():
    bot = _bot()
    bot.journal = None
    Bot._journal_league_standdown(bot, "mcx-chest-empty", "broke")


# -------------------------------------------------- the cutoff itself is unchanged
def test_the_entry_window_constants_are_untouched():
    """22:15 was never the defect. These are commander-approved (2026-07-18)
    and this change must not have moved them."""
    assert Bot._MCX_FIRST_ENTRY == (9, 30)
    assert Bot._MCX_LAST_ENTRY == (22, 30)
