"""The premium path exists only if we record it, starting now.

2026-11-12. `exit_lab` made the premium backstop the worst mechanism in the
book per trade: 16 exits, -44,724, average -2,795, and 11 of the 16 are
GOLDM - the funded cell. `entry_lab` then showed those trades enter
indistinguishably from winners (+3.66 ATR of prior move against the winners'
+3.70), so whatever kills them is on the premium side: IV, theta, spread.

NOT ONE of those questions is answerable. `archive_options.py` runs once a
day at 23:40 from Sync-Candles.ps1, and these positions are held 11 to 77
minutes. Option premium history dies with the contract, so this is not a gap
that can be back-filled - the corpus either starts now or the question stays
unanswerable for ever. Same argument that built the candle archive after a
futures roll ate three months of training tape.

WHAT THIS CHANGE IS NOT. No new archiver, no new schema, no new scheduled
task. `archive_options.capture` already stamps `captured_at` and
`option_archive.closing_snapshots` already excludes rows taken before the
close, so intraday marks cannot contaminate the close-based spread corpus.
Hokage's own loop simply calls the existing capture more often.

These tests pin the three ways it could do harm: blocking the trading loop,
spending broker calls on a shut market, and letting a capture failure stop a
scan.
"""
from __future__ import annotations

import ast
import datetime as dt
import inspect
import textwrap
from types import SimpleNamespace

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
NOW = dt.datetime(2026, 11, 12, 11, 0, tzinfo=IST)


def _bot(*, feed_ok=True, shut=False, running=False, last=None):
    bot = object.__new__(Bot)
    bot._now_ist = lambda: NOW
    bot._feed_probe_ok = feed_ok
    bot._nothing_trades_today = lambda: shut
    bot._chain_capture_running = running
    if last is not None:
        bot._chain_capture_at = last
    bot._started = []
    return bot


def _spy(bot, monkeypatch):
    """Capture the thread that would have been started, without running it."""
    import bots.autonomous.autonomous_bot as mod

    class _Thread:
        def __init__(self, target=None, name=None, daemon=None):
            self.target, self.name, self.daemon = target, name, daemon

        def start(self):
            bot._started.append(self)

    monkeypatch.setattr(mod.threading, "Thread", _Thread)


# ============================================ when it runs, and when not
def test_a_capture_is_started_inside_a_live_session(monkeypatch):
    bot = _bot()
    _spy(bot, monkeypatch)
    bot._capture_option_chain_intraday()
    assert len(bot._started) == 1
    assert bot._started[0].name == "HokageChainCapture"


def test_it_never_blocks_the_trading_loop(monkeypatch):
    """A chain fetch is six quote calls and can hang on a slow broker. The
    loop manages exits; a blocked iteration is a position nobody is
    watching."""
    bot = _bot()
    _spy(bot, monkeypatch)
    bot._capture_option_chain_intraday()
    thread = bot._started[0]
    assert thread.daemon is True, "it must not hold the process open either"
    assert thread.target == bot._run_option_chain_capture


def test_a_shut_market_is_not_captured(monkeypatch):
    """The broker still answers on a holiday - with the PREVIOUS session's
    prints, which would be indistinguishable from today's."""
    bot = _bot(shut=True)
    _spy(bot, monkeypatch)
    bot._capture_option_chain_intraday()
    assert bot._started == []


def test_a_down_nse_feed_probe_does_NOT_stop_the_capture(monkeypatch):
    """THIS TEST USED TO ASSERT THE BUG.

    It read "Same guard as the candle catch-up: no token, no point" and
    required NO capture when `_feed_probe_ok` was false. That guard is what
    made the recorder capture nothing: the probe reads `get_price("NIFTY 50")`
    and NSE shuts at 15:30, so during the MCX evening - the window the
    recorder exists for - it is reliably false. It also flaps on real DNS
    failures.

    Inverted rather than deleted, because the old assertion is exactly the
    mistake and the inversion is the fix.
    """
    bot = _bot(feed_ok=False)
    _spy(bot, monkeypatch)
    bot._capture_option_chain_intraday()
    assert len(bot._started) == 1, (
        "the broker handle is the real precondition, and the thread checks it")


def test_a_capture_already_running_is_not_started_again(monkeypatch):
    bot = _bot(running=True)
    _spy(bot, monkeypatch)
    bot._capture_option_chain_intraday()
    assert bot._started == []


def test_it_is_rate_limited_to_one_per_tick(monkeypatch):
    """Finer than the loop's own cadence costs broker calls for resolution
    the exit ladder does not use."""
    bot = _bot(last=NOW - dt.timedelta(minutes=5))
    _spy(bot, monkeypatch)
    bot._capture_option_chain_intraday()
    assert bot._started == [], "5 minutes after the last one is too soon"

    bot = _bot(last=NOW - dt.timedelta(minutes=16))
    _spy(bot, monkeypatch)
    bot._capture_option_chain_intraday()
    assert len(bot._started) == 1


def test_the_cadence_matches_the_loop():
    assert Bot._CHAIN_CAPTURE_MINUTES == 15


# ===================================== the fetch itself cannot do harm
def _runner(monkeypatch, *, kite=object(), capture=None, remember=None,
            market_open=True):
    import sys
    import types

    bot = object.__new__(Bot)
    bot._now_ist = lambda: NOW
    bot._chain_capture_running = True
    bot.orchestrator = SimpleNamespace(
        kite_connection=SimpleNamespace(get_kite_client=lambda: kite))

    fake_ao = types.ModuleType("archive_options")
    fake_ao.UNDERLYINGS = {"NIFTY": ("NFO", "NSE:NIFTY 50"),
                           "GOLDM": ("MCX", None)}
    fake_ao.capture = capture or (lambda *a, **k: [{"symbol": "NIFTY"}])
    monkeypatch.setitem(sys.modules, "archive_options", fake_ao)

    import hokage.memory.option_archive as oa
    monkeypatch.setattr(oa, "now_ist", lambda: NOW)
    monkeypatch.setattr(oa, "market_was_open",
                        lambda s, d: market_open)
    monkeypatch.setattr(oa, "remember", remember or (lambda rows, when: len(rows)))
    return bot


def test_a_broken_capture_does_not_raise(monkeypatch):
    """A measurement failure must never reach the trading loop."""
    def boom(*a, **k):
        raise RuntimeError("broker timed out")

    bot = _runner(monkeypatch, capture=boom)
    bot._run_option_chain_capture()          # must not raise
    assert bot._chain_capture_running is False, "the flag must always clear"


def test_a_broken_write_does_not_raise(monkeypatch):
    def boom(rows, when):
        raise RuntimeError("database is locked")

    bot = _runner(monkeypatch, remember=boom)
    bot._run_option_chain_capture()
    assert bot._chain_capture_running is False


def test_no_broker_session_is_a_quiet_skip(monkeypatch):
    bot = _runner(monkeypatch, kite=None)
    written = []
    bot._run_option_chain_capture()
    assert written == []
    assert bot._chain_capture_running is False


def test_a_shut_symbol_is_skipped_but_the_others_are_not(monkeypatch):
    """MCX trades while NSE is closed, and the reverse on a holiday evening.
    One shut segment must not cost the whole sweep."""
    seen = []

    def capture(kite, symbol, segment, spot_key, when):
        seen.append(symbol)
        return [{"symbol": symbol}]

    import hokage.memory.option_archive as oa
    bot = _runner(monkeypatch, capture=capture)
    monkeypatch.setattr(oa, "market_was_open",
                        lambda s, d: False if s == "NIFTY" else True)
    bot._run_option_chain_capture()
    assert seen == ["GOLDM"]


def test_one_timestamp_for_the_whole_sweep(monkeypatch):
    """Per-symbol clocks would spread one snapshot over several minutes and
    make the rows look like different captures."""
    stamps = []

    def capture(kite, symbol, segment, spot_key, when):
        stamps.append(when)
        return [{"symbol": symbol}]

    bot = _runner(monkeypatch, capture=capture)
    bot._run_option_chain_capture()
    assert len(stamps) == 2
    assert stamps[0] is stamps[1]


# ============================= the close corpus must stay uncontaminated
def test_it_reuses_the_existing_archiver_and_writer():
    """One archiver, and the writer for the grain being written.

    THIS RAIL USED TO ASSERT `option_archive.remember`, AND THAT WAS THE BUG
    ITSELF PINNED IN PLACE. Reusing the fetcher was right; reusing the daily
    book's writer was not. That table is keyed by the day, so every mark
    after a contract's first was discarded and the 23:40 close could not get
    in at all. Marks go to `mark`, which is keyed by the capture time.
    Measured on the 2026-11-13 tape: 09:03 archived 336 rows, 11:20 archived
    16, and the close would have been lost.
    """
    src = textwrap.dedent(inspect.getsource(Bot._run_option_chain_capture))
    assert "import archive_options" in src
    assert "option_archive.mark" in src
    tree = ast.parse(src)
    writes = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute)
              and n.func.attr in ("execute", "executemany", "commit")]
    assert not writes, "it must go through the archive, never raw SQL"


def test_the_log_line_says_these_are_marks_not_closes():
    """A row that looks like a close and is not is how a corpus rots."""
    src = textwrap.dedent(inspect.getsource(Bot._run_option_chain_capture))
    assert "intraday mark(s)" in src
    assert "NOT the daily close" in src


def test_the_loop_calls_it_without_letting_it_break_the_cycle():
    import pathlib

    root = next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    src = (root / "src" / "bots" / "autonomous"
           / "autonomous_bot.py").read_text(encoding="utf-8")
    block = src.split("_capture_option_chain_intraday()")[1][:400]
    assert "except Exception" in block
    assert "logger.error" in block


# ================== the gate that stopped it recording anything at all
def test_it_does_not_gate_on_the_nse_feed_probe():
    """THE BUG, VERIFIED BROKEN 20 MINUTES AFTER SHIPPING: zero rows.

    The guard was copied from the candle catch-up and gated on
    `_feed_probe_ok`, which is set from `get_price("NIFTY 50")`. NSE closes
    at 15:30 and MCX runs to 23:30, so the one recorder built FOR the MCX
    evening - where 11 of 16 premium backstops happened - could never run in
    that window. It also flaps: DOWN at 16:50 ("Venue is not connected") and
    again at 17:55 on a real DNS failure. A once-a-day catch-up can wait for
    the next good minute; a 15-minute recorder cannot.
    """
    src = textwrap.dedent(inspect.getsource(Bot._capture_option_chain_intraday))
    tree = ast.parse(src)
    reads = {n.args[1].value for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and getattr(n.func, "id", None) == "getattr"
             and len(n.args) > 1 and isinstance(n.args[1], ast.Constant)}
    assert "_feed_probe_ok" not in reads, (
        "an MCX-evening recorder must not wait on an NSE index quote")


def test_the_capture_runs_after_the_nse_close(monkeypatch):
    """The window it exists for. 18:45 IST: NSE shut, MCX trading."""
    evening = dt.datetime(2026, 11, 12, 18, 45, tzinfo=IST)
    bot = object.__new__(Bot)
    bot._now_ist = lambda: evening
    bot._nothing_trades_today = lambda: False
    bot._chain_capture_running = False
    bot._started = []
    _spy(bot, monkeypatch)
    bot._capture_option_chain_intraday()
    assert len(bot._started) == 1, "the MCX evening is the whole point"


# ============================= a silent recorder is worse than none
def test_every_failure_path_is_visible_not_debug():
    """boot.py runs logging at INFO, so a `logger.debug` failure path is
    invisible. That is how this shipped broken and said nothing."""
    for name in ("_capture_option_chain_intraday", "_run_option_chain_capture",
                 "_observe_exited_contracts"):
        src = textwrap.dedent(inspect.getsource(getattr(Bot, name)))
        assert "logger.debug" not in src, (
            f"{name} still has a silent failure path")


def test_a_blocked_capture_says_so(caplog):
    import logging

    bot = object.__new__(Bot)
    bot._now_ist = lambda: dt.datetime(2026, 11, 12, 18, 45, tzinfo=IST)
    with caplog.at_level(logging.WARNING):
        bot._say_chain_capture_blocked("no broker session")
    assert "recorded NOTHING" in caplog.text
    assert "no broker session" in caplog.text
    assert "dies with the contract" in caplog.text


def test_the_same_reason_is_not_repeated_every_minute(caplog):
    """The loop ticks once a minute and a reason that holds holds for hours."""
    import logging

    bot = object.__new__(Bot)
    now = dt.datetime(2026, 11, 12, 18, 45, tzinfo=IST)
    bot._now_ist = lambda: now
    with caplog.at_level(logging.WARNING):
        for _ in range(20):
            bot._say_chain_capture_blocked("no broker session")
    assert caplog.text.count("recorded NOTHING") == 1

    # a different reason is its own alarm
    with caplog.at_level(logging.WARNING):
        bot._say_chain_capture_blocked("GOLDM could not be read")
    assert caplog.text.count("recorded NOTHING") == 2


def test_an_hour_later_the_same_reason_speaks_again(caplog):
    import logging

    bot = object.__new__(Bot)
    now = dt.datetime(2026, 11, 12, 18, 45, tzinfo=IST)
    bot._now_ist = lambda: now
    with caplog.at_level(logging.WARNING):
        bot._say_chain_capture_blocked("no broker session")
        bot._now_ist = lambda: now + dt.timedelta(hours=2)
        bot._say_chain_capture_blocked("no broker session")
    assert caplog.text.count("recorded NOTHING") == 2


def test_the_broker_handle_method_actually_exists():
    """I INVENTED `get_kite()`. It does not exist on the manager, so every
    capture raised AttributeError - caught, and logged at DEBUG where nobody
    could see it. The real name is `get_kite_client`.

    A rail on the CLASS, not on a mock: a test that stubs the manager would
    have passed with the wrong name, which is exactly how this shipped.
    """
    from integrations.brokers.kite_connection import KiteConnectionManager

    src = textwrap.dedent(inspect.getsource(Bot._run_option_chain_capture))
    called = {n.func.attr for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute)
              and n.func.attr.startswith("get_kite")}
    assert called, "the capture no longer asks for a broker handle"
    for name in called:
        assert hasattr(KiteConnectionManager, name), (
            f"KiteConnectionManager has no {name}() - the capture would "
            f"raise on every tick")


# ============ pre-market: the broker answers with yesterday's prints
def test_a_premarket_capture_is_skipped_per_segment():
    """`market_was_open` answers about the DAY, not the moment. At 08:00 on
    an ordinary Friday it says True and the broker returns YESTERDAY's
    closes, which would enter the corpus stamped as today's intraday marks -
    the same error archive_options already refuses on a shut day.

    MCX opens 09:00 and NSE 09:15, so one guard cannot serve both.
    """
    from hokage.memory import option_archive as oa

    friday = dt.date(2026, 11, 13)

    def at(h, m):
        return dt.datetime.combine(friday, dt.time(h, m), tzinfo=IST)

    assert oa.is_before_open(at(8, 0), "GOLDM") is True
    assert oa.is_before_open(at(8, 0), "NIFTY") is True
    # MCX is trading while NSE is not
    assert oa.is_before_open(at(9, 5), "GOLDM") is False
    assert oa.is_before_open(at(9, 5), "NIFTY") is True
    # both open
    assert oa.is_before_open(at(9, 20), "GOLDM") is False
    assert oa.is_before_open(at(9, 20), "NIFTY") is False


def test_a_special_session_open_is_consulted_first():
    """Muhurat opens at 14:20. The ordinary 09:15 would call the whole
    morning open on a day the exchange is shut until the afternoon."""
    from hokage.memory import option_archive as oa

    muhurat = dt.date(2026, 11, 8)

    def at(h, m):
        return dt.datetime.combine(muhurat, dt.time(h, m), tzinfo=IST)

    assert oa.is_before_open(at(10, 0), "NIFTY") is True
    assert oa.is_before_open(at(14, 30), "NIFTY") is False


def test_an_unknown_symbol_is_held_back_rather_than_recorded_stale():
    """The conservative direction here is the LATER open - the opposite of
    session_end_for, where permissive is the earlier close. Both choices are
    the one that cannot put a stale price in the corpus."""
    from hokage.memory import option_archive as oa

    assert oa.session_start_for("SOMETHING_NEW") == oa.SESSION_START_BY_SEGMENT["NSE"]
    assert oa.session_start_for("GOLDM") == dt.time(9, 0)


def test_the_capture_consults_the_open_not_only_the_day():
    src = textwrap.dedent(inspect.getsource(Bot._run_option_chain_capture))
    assert "is_before_open(" in src
    assert "market_was_open(" in src, "the day guard must stay too"


# ================ an alarm that fires for correct behaviour is noise
def test_a_premarket_tick_is_quiet_not_an_alarm(monkeypatch, caplog):
    """OBSERVED ON THE FIRST BOOT AFTER THE PRE-MARKET GUARD SHIPPED:

        08:17:57 WARNING Option chain capture recorded NOTHING: every
        underlying was skipped ... The premium path will not exist later

    At 08:17 that skip is CORRECT. An alarm worded as a failure, firing
    every morning for right behaviour, is how a real alarm gets ignored -
    the parked-asset noise of 2026-10-13 in a new costume.
    """
    import logging

    bot = _runner(monkeypatch, capture=lambda *a, **k: [])
    import hokage.memory.option_archive as oa
    monkeypatch.setattr(oa, "is_before_open", lambda when, sym: True)

    with caplog.at_level(logging.DEBUG):
        bot._run_option_chain_capture()
    assert "recorded NOTHING" not in caplog.text, (
        "a shut market is not a fault")
    assert "Not a fault" in caplog.text


def test_an_open_market_returning_nothing_IS_an_alarm(monkeypatch, caplog):
    """The inverse. If a segment is open and still yields no contracts,
    something is broken and silence would hide it."""
    import logging

    bot = _runner(monkeypatch, capture=lambda *a, **k: [])
    import hokage.memory.option_archive as oa
    monkeypatch.setattr(oa, "is_before_open", lambda when, sym: False)

    with caplog.at_level(logging.WARNING):
        bot._run_option_chain_capture()
    assert "recorded NOTHING" in caplog.text
    assert "returned no contracts" in caplog.text
