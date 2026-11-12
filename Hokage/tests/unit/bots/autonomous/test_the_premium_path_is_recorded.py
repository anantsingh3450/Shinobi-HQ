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


def test_no_feed_means_no_capture(monkeypatch):
    """Same guard as the candle catch-up: no token, no point."""
    bot = _bot(feed_ok=False)
    _spy(bot, monkeypatch)
    bot._capture_option_chain_intraday()
    assert bot._started == []


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
        kite_connection=SimpleNamespace(get_kite=lambda: kite))

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
    """No second archiver, no second schema. `closing_snapshots` already
    excludes pre-close rows, and that is what keeps the spread corpus clean."""
    src = textwrap.dedent(inspect.getsource(Bot._run_option_chain_capture))
    assert "import archive_options" in src
    assert "option_archive.remember" in src
    tree = ast.parse(src)
    writes = [n for n in ast.walk(tree)
              if isinstance(n, ast.Call)
              and isinstance(n.func, ast.Attribute)
              and n.func.attr in ("execute", "executemany", "commit")]
    assert not writes, "it must go through the archive, never raw SQL"


def test_the_log_line_says_these_are_marks_not_closes():
    """A row that looks like a close and is not is how a corpus rots."""
    src = textwrap.dedent(inspect.getsource(Bot._run_option_chain_capture))
    assert "MARKS, not closes" in src
    assert "closing_snapshots" in src


def test_the_loop_calls_it_without_letting_it_break_the_cycle():
    import pathlib

    root = next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    src = (root / "src" / "bots" / "autonomous"
           / "autonomous_bot.py").read_text(encoding="utf-8")
    block = src.split("_capture_option_chain_intraday()")[1][:400]
    assert "except Exception" in block
    assert "logger.error" in block
