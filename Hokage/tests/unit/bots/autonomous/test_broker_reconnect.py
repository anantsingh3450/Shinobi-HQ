"""A mid-session login must revive the feed without a restart.

KiteConnectionManager reads the access token exactly once, inside connect(). A
process that boots with an expired token is dead for its whole life: connect()
fails, _kite is left None, and every later call raises "Venue is not connected."
Logging in afterwards rewrites the .env, the environment and the keyring but
touches nothing in the running object.

On 2026-08-05 the commander restarted Hokage, logged in ninety seconds later,
and the fresh process stayed blind on the token it had already loaded. It took a
second restart, and there was no way for him to have known that.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from bots.autonomous.autonomous_bot import AutonomousTradingBot

_RECONNECT = AutonomousTradingBot._try_broker_reconnect


def _bot(reconnect_ok: bool = True, feed_ok: bool = True):
    manager = MagicMock()
    manager.try_reconnect.return_value = reconnect_ok

    price_source = MagicMock()
    if feed_ok:
        price_source.get_price.return_value = 24500.0
    else:
        price_source.get_price.side_effect = Exception("Venue is not connected.")

    return SimpleNamespace(
        orchestrator=SimpleNamespace(kite_connection=manager, price_source=price_source),
        _RECONNECT_MIN_INTERVAL_SECONDS=AutonomousTradingBot._RECONNECT_MIN_INTERVAL_SECONDS,
    )


def test_a_refreshed_session_revives_the_feed():
    bot = _bot()
    assert _RECONNECT(bot) is True
    bot.orchestrator.kite_connection.try_reconnect.assert_called_once()


def test_recovery_is_only_claimed_once_a_quote_actually_returns():
    """A live session is not a live feed. Never announce a recovery we cannot
    see — the whole point of the July work was to stop reporting health that
    was never measured."""
    bot = _bot(reconnect_ok=True, feed_ok=False)
    assert _RECONNECT(bot) is False


def test_a_still_dead_token_reports_failure():
    bot = _bot(reconnect_ok=False)
    assert _RECONNECT(bot) is False
    # The feed is never probed when the session itself did not come back.
    bot.orchestrator.price_source.get_price.assert_not_called()


def test_reconnect_is_rate_limited_to_once_a_minute():
    """The probe runs every 60s loop iteration and an outage can last days;
    hammering Kite's auth endpoint would be its own incident."""
    bot = _bot()
    assert _RECONNECT(bot) is True
    for _ in range(5):
        assert _RECONNECT(bot) is False
    assert bot.orchestrator.kite_connection.try_reconnect.call_count == 1


def test_missing_connection_manager_is_survivable():
    bot = SimpleNamespace(
        orchestrator=SimpleNamespace(price_source=MagicMock()),
        _RECONNECT_MIN_INTERVAL_SECONDS=60.0,
    )
    assert _RECONNECT(bot) is False


def test_try_reconnect_never_raises_on_a_dead_token():
    """Callers are recovery paths; a failed recovery must not kill the loop."""
    from integrations.brokers.kite_connection import KiteConnectionManager

    manager = KiteConnectionManager.__new__(KiteConnectionManager)
    manager.connect = MagicMock(side_effect=RuntimeError("Authentication failed: bad token"))
    assert manager.try_reconnect() is False
