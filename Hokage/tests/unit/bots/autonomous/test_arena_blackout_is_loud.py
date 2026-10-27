"""The MCX arena went dark for two sessions and the log said nothing useful.

2026-10-26: no live market context for GOLDM, SILVERM and NATURALGAS from
09:31 to 14:24. 2026-10-27: the same, 09:31 to 13:34. About ten trading hours
with the arena idle. Both days the index league ran normally alongside — 183
decisions on the second — so the process was alive, authenticated, scanning,
and reporting itself healthy.

THE ONLY EVIDENCE WAS A SENTENCE WITH NO REASON IN IT:

    MCX Arena: no live market context for GOLDM; standing aside.

sixty times. The exception that would have named the fault was caught one
level down and logged at DEBUG, which is off. So the single fact that
mattered was computed and discarded on every scan, for two days.

WHAT THIS FILE PROTECTS is not the cause — which is still unknown, and this
file does not pretend otherwise. It protects the two properties whose
absence made a bug cost ten hours instead of ten minutes:

  1. THE REASON TRAVELS WITH THE REFUSAL. A stand-aside that cannot say why
     is indistinguishable from a quiet market.
  2. A BLACKOUT BECOMES AN ALARM. One failed scan is bad luck; four in a row
     on one asset is a blackout, and the commander hears about it within the
     hour rather than at the end of the day.

Same family as every other wound here: a dead token that reported Health
Score 100/100, a watcher blind for four days whose error was swallowed as "no
change", a liveness probe that shared the machine it was watching. A check
that silently stops checking is worse than one that was never added.
"""
from __future__ import annotations

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot


class _Telegram:
    def __init__(self):
        self.sent: list[str] = []

    def send_message(self, text):
        self.sent.append(text)


def _bot(telegram=None):
    bot = object.__new__(Bot)
    bot.telegram_bot = telegram
    bot.orchestrator = type("O", (), {"price_source": None})()
    return bot


# ------------------------------------------- 1. the reason travels along
def test_the_refusal_carries_the_reason_it_failed():
    bot = _bot()
    bot._ctx_failure["GOLDM"] = "TokenException: Incorrect api_key or access_token"
    line = bot._note_context_miss("GOLDM")
    assert "GOLDM" in line
    assert "TokenException" in line, "the exception is the whole point"
    assert "miss 1" in line


def test_a_failure_with_no_recorded_reason_says_so_rather_than_implying_calm():
    """UNKNOWN IS NOT 'nothing happened'. An empty reason reads as a quiet
    market, which is exactly how this hid for two days."""
    line = _bot()._note_context_miss("SILVERM")
    assert "no reason recorded" in line


def test_a_short_series_is_a_different_fault_from_a_failed_fetch():
    """Twelve candles and a thrown exception both produced None and were
    indistinguishable in the log."""
    bot = _bot()
    bot._ctx_failure["NATURALGAS"] = "only 12 candles, need 21"
    assert "only 12 candles" in bot._note_context_miss("NATURALGAS")


# ------------------------------------------------- 2. it becomes an alarm
def test_four_consecutive_misses_raise_a_critical_and_telegram(caplog):
    tg = _Telegram()
    bot = _bot(tg)
    bot._ctx_failure["GOLDM"] = "ValueError: no live futures contract"
    with caplog.at_level("CRITICAL"):
        for _ in range(Bot._CTX_FAILURES_BEFORE_ALARM):
            bot._note_context_miss("GOLDM")
    assert "ARENA BLACKOUT" in caplog.text
    assert len(tg.sent) == 1
    assert "GOLDM" in tg.sent[0] and "no live futures contract" in tg.sent[0]


def test_the_alarm_fires_once_not_on_every_scan_after(caplog):
    """An alarm that repeats every fifteen minutes for five hours teaches the
    commander to ignore it — the exact reasoning that put CRUDEOIL in
    PARKED_ASSETS rather than letting the orphan audit scream on every boot."""
    tg = _Telegram()
    bot = _bot(tg)
    for _ in range(12):
        bot._note_context_miss("GOLDM")
    assert len(tg.sent) == 1


def test_three_misses_are_bad_luck_and_stay_quiet(caplog):
    tg = _Telegram()
    bot = _bot(tg)
    with caplog.at_level("CRITICAL"):
        for _ in range(Bot._CTX_FAILURES_BEFORE_ALARM - 1):
            bot._note_context_miss("GOLDM")
    assert "ARENA BLACKOUT" not in caplog.text
    assert tg.sent == []


def test_each_asset_is_counted_separately():
    """Gas failing must not arm the alarm for gold. On both affected days all
    three failed together, but one asset losing its contract is the more
    likely fault and must not be masked."""
    bot = _bot()
    for _ in range(Bot._CTX_FAILURES_BEFORE_ALARM - 1):
        bot._note_context_miss("GOLDM")
    assert "miss 1" in bot._note_context_miss("SILVERM")


def test_a_recovered_context_ends_the_streak(caplog):
    bot = _bot()
    for _ in range(3):
        bot._note_context_miss("GOLDM")
    with caplog.at_level("INFO"):
        bot._clear_context_miss("GOLDM")
    assert "is back" in caplog.text
    assert "miss 1" in bot._note_context_miss("GOLDM"), "the count restarts"


def test_clearing_a_symbol_that_never_failed_says_nothing(caplog):
    """Every healthy scan calls this. It must not narrate."""
    with caplog.at_level("INFO"):
        _bot()._clear_context_miss("GOLDM")
    assert caplog.text == ""


def test_a_missing_telegram_never_breaks_the_scan():
    bot = _bot(None)
    for _ in range(Bot._CTX_FAILURES_BEFORE_ALARM):
        bot._note_context_miss("GOLDM")      # must not raise


def test_a_telegram_that_throws_never_breaks_the_scan():
    class _Broken:
        def send_message(self, text):
            raise RuntimeError("telegram down")

    bot = _bot(_Broken())
    for _ in range(Bot._CTX_FAILURES_BEFORE_ALARM):
        bot._note_context_miss("GOLDM")      # must not raise


# --------------------------------------- 3. the one bounded recovery attempt
def test_the_futures_cache_is_cleared_once_after_enough_failures(caplog):
    """A HYPOTHESIS TESTED IN PRODUCTION WITH ITS RESULT WRITTEN DOWN, not a
    silent retry loop. If the next scan succeeds, a stale contract resolution
    was the cause and the log says so. If not, the exception is there to
    read. The cause is NOT yet known and this does not claim otherwise."""
    bot = _bot()
    cache = {("MCX", "GOLDM"): ("2026-10-26", "GOLDM26OCTFUT")}
    bot.orchestrator = type("O", (), {
        "price_source": type("P", (), {"_futures_symbol_cache": cache})()})()

    with caplog.at_level("WARNING"):
        for _ in range(Bot._CTX_FAILURES_BEFORE_RESET):
            bot._note_context_miss("GOLDM")
    assert cache == {}, "the cache should have been cleared"
    assert "clearing the futures-symbol cache once" in caplog.text


def test_the_reset_happens_once_not_every_scan_thereafter():
    bot = _bot()
    cache = {("MCX", "GOLDM"): ("2026-10-26", "GOLDM26OCTFUT")}
    bot.orchestrator = type("O", (), {
        "price_source": type("P", (), {"_futures_symbol_cache": cache})()})()
    for _ in range(Bot._CTX_FAILURES_BEFORE_RESET + 6):
        bot._note_context_miss("GOLDM")
    cache[("MCX", "SILVERM")] = ("2026-10-27", "SILVERM26NOVFUT")
    bot._note_context_miss("GOLDM")
    assert cache, "a later scan must not keep wiping it"


def test_the_reset_comes_after_the_alarm_never_before():
    """The commander hears about it first. A self-heal that fires before the
    alarm can mask the fault it was meant to surface."""
    assert Bot._CTX_FAILURES_BEFORE_RESET > Bot._CTX_FAILURES_BEFORE_ALARM


def test_a_provider_without_that_cache_is_not_an_error():
    bot = _bot()
    bot.orchestrator = type("O", (), {"price_source": object()})()
    for _ in range(Bot._CTX_FAILURES_BEFORE_RESET):
        bot._note_context_miss("GOLDM")      # must not raise


def test_the_thresholds_are_about_an_hour_not_a_whole_session():
    """Scans run roughly every 15 minutes. Ten hours were lost across
    2026-10-26 and 10-27 with no alarm at all; the alarm must arrive while
    the session can still be saved."""
    assert 2 <= Bot._CTX_FAILURES_BEFORE_ALARM <= 6
    assert Bot._CTX_FAILURES_BEFORE_ALARM * 15 <= 90
