"""A network failure that will not clear is a poisoned pool, not the internet.

2026-09-02, watching him live:

    08:58:39  feed DOWN (network)  — DNS blip, healed itself in ~90 seconds
    13:53:00  feed DOWN (network)
    13:45:34  ... last successful scan
    14:32     STILL DOWN. 47 minutes. 38 identical CRITICAL lines. Zero trades.

DNS resolved perfectly from a fresh process sitting beside him the entire time,
so the internet was fine — his own urllib3 connection pool was dead and every
retry went back to the same corpse. Restarting him by hand fixed it instantly.

THE SELF-HEAL ALREADY EXISTED AND WAS UNREACHABLE. `_try_broker_reconnect`
rebuilds the client and then PROVES the feed with a real quote before claiming
recovery — exactly what the manual restart did. But it was only called when
`_diagnose_feed_failure` returned "unknown", which is the mid-session-login
signature. A "network" diagnosis skipped it entirely.

So the cure existed behind the wrong door. This wires the door.

WHY NOT ON THE FIRST FAILURE. A genuine internet outage needs no rebuild, and
churning the client through one is noise — the 08:58 blip healed untouched, well
inside the threshold. After three consecutive failures the internet is no longer
the explanation; his own client is.
"""
from __future__ import annotations

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot


class _Source:
    """A price source that fails a set number of times, then works."""

    def __init__(self, fail_times: int, error: str):
        self.remaining = fail_times
        self.error = error
        self.calls = 0

    def get_price(self, symbol):
        self.calls += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise ConnectionError(self.error)
        return 100.0


DNS = ("HTTPSConnectionPool(host='api.kite.trade', port=443): Max retries "
       "exceeded (Caused by NameResolutionError(...getaddrinfo failed))")


def _bot(source, reconnect_works=True):
    bot = object.__new__(Bot)

    class _Orch:
        price_source = source

    bot.orchestrator = _Orch()
    bot.telegram_bot = None
    bot._last_feed_alert_date = None
    bot._feed_outage_announced = False
    bot._consecutive_network_failures = 0
    bot.reconnects = 0

    def _now_ist():
        from datetime import datetime
        return datetime(2026, 9, 2, 14, 0)

    bot._now_ist = _now_ist
    bot._diagnose_feed_failure = lambda reason: "network"
    # 2026-09-02 is a normal Wednesday session, so the calendar check added on
    # 2026-11-07 must not quieten anything here. This bot is a real instance,
    # so it carries the real check already - a regression that silences a
    # trading day fails these tests too.
    bot._last_feed_quiet_date = None

    def _try_reconnect():
        bot.reconnects += 1
        if reconnect_works:
            source.remaining = 0
        return reconnect_works

    bot._try_broker_reconnect = _try_reconnect
    return bot


def _probe(bot, times):
    for _ in range(times):
        Bot._check_data_feed_session(bot)


# --------------------------------------------------------- the 08:58 blip
def test_a_short_blip_is_not_worth_rebuilding_the_client():
    """It healed in ~90 seconds untouched. Churning the connection through
    every transient would be its own kind of noise."""
    bot = _bot(_Source(fail_times=1, error=DNS))
    _probe(bot, 2)
    assert bot.reconnects == 0


def test_two_failures_still_do_not_rebuild():
    bot = _bot(_Source(fail_times=Bot._NETWORK_REBUILD_AFTER - 1, error=DNS))
    _probe(bot, Bot._NETWORK_REBUILD_AFTER - 1)
    assert bot.reconnects == 0


# --------------------------------------------------------- the 13:53 outage
def test_a_persistent_network_failure_rebuilds_the_client():
    """The 47-minute case. After three consecutive failures the internet is not
    the explanation any more."""
    bot = _bot(_Source(fail_times=99, error=DNS))
    _probe(bot, Bot._NETWORK_REBUILD_AFTER)
    assert bot.reconnects == 1
    assert bot._consecutive_network_failures == 0, "a recovery resets the count"


def test_the_feed_actually_works_after_the_rebuild():
    source = _Source(fail_times=99, error=DNS)
    bot = _bot(source)
    _probe(bot, Bot._NETWORK_REBUILD_AFTER)
    assert source.get_price("NIFTY 50") == 100.0


def test_a_failed_rebuild_does_not_claim_recovery():
    """_try_broker_reconnect proves the feed with a real quote before returning
    True. If it cannot, the outage must still be reported."""
    bot = _bot(_Source(fail_times=99, error=DNS), reconnect_works=False)
    _probe(bot, Bot._NETWORK_REBUILD_AFTER + 2)
    assert bot.reconnects >= 1
    assert bot._consecutive_network_failures >= Bot._NETWORK_REBUILD_AFTER


# ------------------------------------------------------------- the counter
def test_a_success_clears_the_counter():
    """Two separate blips an hour apart must not add up into a rebuild."""
    source = _Source(fail_times=2, error=DNS)
    bot = _bot(source)
    _probe(bot, 3)                      # two failures, then a success
    assert bot._consecutive_network_failures == 0
    assert bot.reconnects == 0


def test_an_auth_failure_does_not_count_toward_the_network_rebuild():
    """A dead token is the commander's to fix by logging in. Counting it here
    would rebuild a client that is working perfectly."""
    bot = _bot(_Source(fail_times=99, error="Incorrect api_key or access_token"))
    bot._diagnose_feed_failure = lambda reason: "auth"
    _probe(bot, Bot._NETWORK_REBUILD_AFTER + 3)
    assert bot.reconnects == 0
    assert bot._consecutive_network_failures == 0


def test_the_threshold_is_small_enough_to_save_a_trading_hour():
    """The feed is probed about once a minute. 47 minutes of blindness cost a
    whole session; a threshold in the tens of minutes would repeat it."""
    assert 2 <= Bot._NETWORK_REBUILD_AFTER <= 5


def test_the_reconnect_is_still_rate_limited():
    """Rebuilding on every probe would hammer Kite's auth endpoint through a
    genuine outage."""
    assert Bot._RECONNECT_MIN_INTERVAL_SECONDS >= 60.0
