"""A dropped line is not an expired token, and must not say it is.

2026-11-13, 13:19 to 13:22 IST, once a minute, while the token was valid:

    CRITICAL  Hokage.KiteConnection:
    ⚠️  ZERODHA SESSION TOKEN EXPIRED OR INVALID ⚠️
    ACTION REQUIRED: ... Click 'Login to Zerodha' ...

Nothing was wrong with the session. The phone hotspot had dropped, so
`kite.profile()` raised the requests library's ConnectionError wrapping
"Failed to resolve 'api.kite.trade' [Errno 11001] getaddrinfo failed" -
`kiteconnect` re-raises those untouched - and `connect()` caught
`Exception` and printed the login instruction. Twenty minutes later the
line came back and he traded on that same token.

WHY THIS IS NOT COSMETIC.

  * It asks for an action that cannot work. No login fixes a dead line, and
    he could not even read the demand: the same outage was holding Telegram
    down, so it arrived 300 minutes late.
  * IT SPENDS THE WORDS THAT MATTER. The token really does expire, every
    day, around 06:00, and the message for that is identical. An alarm that
    fires for something else teaches him to skip it - the same defect as the
    pre-market chain alarm caught this morning, in a costlier place.

THE CLASSIFICATION IS DELIBERATELY ASYMMETRIC. Silence on a genuinely dead
token is a blind session; a needless login is noise. So auth wins whenever a
failure is both, and anything unrecognised is treated as auth.
"""
from __future__ import annotations

import logging
import socket
from unittest.mock import MagicMock

import pytest
from kiteconnect import exceptions as kite_exceptions

from integrations.brokers.kite_connection import KiteConnectionManager
from integrations.brokers.models import ConnectionState

ACTION = "ACTION REQUIRED"


@pytest.fixture
def manager(monkeypatch):
    """A manager whose credentials are present and whose profile call fails
    however the test wants it to."""
    mgr = KiteConnectionManager.__new__(KiteConnectionManager)
    mgr._secrets_manager = MagicMock()
    mgr._secrets_manager.get_secret.side_effect = lambda n: {
        "api_key": "key", "access_token": "token"}.get(n)
    mgr._kite = None
    mgr._connection_state = ConnectionState.DISCONNECTED
    return mgr


def _profile_raises(monkeypatch, exc):
    import integrations.brokers.kite_connection as mod

    client = MagicMock()
    client.profile.side_effect = exc
    monkeypatch.setattr(mod, "KiteConnect", MagicMock(return_value=client))
    return client


def _dns_failure() -> Exception:
    """What the hotspot drop actually produced, as closely as possible."""
    import requests

    inner = socket.gaierror(11001, "getaddrinfo failed")
    err = requests.exceptions.ConnectionError(
        "HTTPSConnectionPool(host='api.kite.trade', port=443): Max retries "
        "exceeded (Caused by NameResolutionError(...))")
    err.__cause__ = inner
    return err


# ================================================ the line being down
def test_a_dns_failure_does_not_demand_a_login(manager, monkeypatch, caplog):
    _profile_raises(monkeypatch, _dns_failure())
    with caplog.at_level(logging.DEBUG, logger="Hokage.KiteConnection"):
        with pytest.raises(RuntimeError) as raised:
            manager.connect()

    said = "\n".join(r.getMessage() for r in caplog.records)
    assert ACTION not in said, "no login can fix a dropped line"
    assert "TOKEN EXPIRED" not in said
    assert "UNREACHABLE" in said
    assert "Broker unreachable" in str(raised.value)


def test_a_transport_failure_is_a_warning_not_a_critical(manager, monkeypatch,
                                                         caplog):
    """CRITICAL is reserved for what he must act on."""
    _profile_raises(monkeypatch, _dns_failure())
    with caplog.at_level(logging.DEBUG, logger="Hokage.KiteConnection"):
        with pytest.raises(RuntimeError):
            manager.connect()
    assert [r.levelno for r in caplog.records] == [logging.WARNING]


@pytest.mark.parametrize("exc", [
    socket.gaierror(11001, "getaddrinfo failed"),
    socket.timeout("timed out"),
    ConnectionResetError("connection reset by peer"),
    kite_exceptions.NetworkException("gateway timeout"),
    kite_exceptions.DataException("Couldn't parse the JSON response"),
])
def test_every_shape_of_a_dead_line_is_read_as_one(manager, monkeypatch,
                                                   caplog, exc):
    """A captive portal answering with HTML arrives as a parser error, and
    that is still the network rather than the session."""
    _profile_raises(monkeypatch, exc)
    with caplog.at_level(logging.DEBUG, logger="Hokage.KiteConnection"):
        with pytest.raises(RuntimeError):
            manager.connect()
    assert ACTION not in "\n".join(r.getMessage() for r in caplog.records)


def test_a_cause_buried_under_a_wrapper_is_still_found(manager, monkeypatch,
                                                       caplog):
    """`kiteconnect` re-raises the requests exception, but a future version
    or a retry helper may wrap it. Follow the chain."""
    outer = RuntimeError("profile call failed")
    outer.__cause__ = _dns_failure()
    _profile_raises(monkeypatch, outer)
    with caplog.at_level(logging.DEBUG, logger="Hokage.KiteConnection"):
        with pytest.raises(RuntimeError):
            manager.connect()
    assert ACTION not in "\n".join(r.getMessage() for r in caplog.records)


# =================================================== the session being dead
def test_a_token_exception_still_demands_a_login(manager, monkeypatch, caplog):
    """The alarm must keep ALL of its force for the thing it was written
    for. The token expires every day around 06:00."""
    _profile_raises(monkeypatch,
                    kite_exceptions.TokenException("Invalid `api_key` or "
                                                   "`access_token`."))
    with caplog.at_level(logging.DEBUG, logger="Hokage.KiteConnection"):
        with pytest.raises(RuntimeError) as raised:
            manager.connect()

    said = "\n".join(r.getMessage() for r in caplog.records)
    assert ACTION in said
    assert "TOKEN EXPIRED" in said
    assert [r.levelno for r in caplog.records] == [logging.CRITICAL]
    assert "Authentication failed" in str(raised.value)


def test_a_permission_failure_is_also_his_to_fix(manager, monkeypatch, caplog):
    _profile_raises(monkeypatch,
                    kite_exceptions.PermissionException("not permitted"))
    with caplog.at_level(logging.DEBUG, logger="Hokage.KiteConnection"):
        with pytest.raises(RuntimeError):
            manager.connect()
    assert ACTION in "\n".join(r.getMessage() for r in caplog.records)


def test_an_unrecognised_failure_is_treated_as_the_session(manager,
                                                           monkeypatch,
                                                           caplog):
    """THE ASYMMETRY. A needless login is noise; silence on a dead token is
    a blind session. So the unknown case keeps the louder diagnosis."""
    _profile_raises(monkeypatch, ValueError("something new"))
    with caplog.at_level(logging.DEBUG, logger="Hokage.KiteConnection"):
        with pytest.raises(RuntimeError):
            manager.connect()
    assert ACTION in "\n".join(r.getMessage() for r in caplog.records)


def test_auth_wins_when_a_failure_is_both(manager, monkeypatch, caplog):
    """A TokenException raised while the network was also flaky is still a
    dead token, and he still has to log in."""
    exc = kite_exceptions.TokenException("Invalid `access_token`.")
    exc.__context__ = _dns_failure()
    _profile_raises(monkeypatch, exc)
    with caplog.at_level(logging.DEBUG, logger="Hokage.KiteConnection"):
        with pytest.raises(RuntimeError):
            manager.connect()
    assert ACTION in "\n".join(r.getMessage() for r in caplog.records)


# ======================================================== saying it once
def test_the_same_diagnosis_is_not_repeated_every_minute(manager, monkeypatch,
                                                         caplog):
    """The health loop calls connect() once a minute. On 2026-11-13 that
    printed the login block sixty times an hour for an outage no login could
    fix, and the line that mattered was always the FIRST one."""
    _profile_raises(monkeypatch, _dns_failure())
    with caplog.at_level(logging.DEBUG, logger="Hokage.KiteConnection"):
        for _ in range(5):
            with pytest.raises(RuntimeError):
                manager.connect()
    assert len(caplog.records) == 1


def test_a_new_diagnosis_is_never_held_back(manager, monkeypatch, caplog):
    """An outage that turns into a real expiry must announce itself at once,
    not after the other reason's cooldown."""
    with caplog.at_level(logging.DEBUG, logger="Hokage.KiteConnection"):
        _profile_raises(monkeypatch, _dns_failure())
        with pytest.raises(RuntimeError):
            manager.connect()
        _profile_raises(monkeypatch,
                        kite_exceptions.TokenException("Invalid token"))
        with pytest.raises(RuntimeError):
            manager.connect()

    levels = [r.levelno for r in caplog.records]
    assert levels == [logging.WARNING, logging.CRITICAL]


# ================================================ safety is unchanged
@pytest.mark.parametrize("exc", [
    _dns_failure(),
    kite_exceptions.TokenException("Invalid token"),
])
def test_either_way_he_is_left_disconnected_and_clientless(manager,
                                                           monkeypatch, exc):
    """Reclassifying the MESSAGE must not relax the STATE. A reachable-but-
    unverified client would let a scan run on a session nothing confirmed."""
    _profile_raises(monkeypatch, exc)
    with pytest.raises(RuntimeError):
        manager.connect()
    assert manager._connection_state is ConnectionState.DISCONNECTED
    assert manager._kite is None
    with pytest.raises(RuntimeError, match="Venue is not connected"):
        manager.get_kite_client()


def test_a_good_profile_still_connects(manager, monkeypatch):
    import integrations.brokers.kite_connection as mod

    client = MagicMock()
    client.profile.return_value = {"user_id": "AB1234"}
    monkeypatch.setattr(mod, "KiteConnect", MagicMock(return_value=client))

    status = manager.connect()
    assert status.state is ConnectionState.CONNECTED
    assert manager.get_kite_client() is client
