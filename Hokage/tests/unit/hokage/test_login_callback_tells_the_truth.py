"""The login page must not report failure for a login that succeeded.

2026-10-13, the one operation Hokage cannot survive a day without:

    06:21:45  Telegram: HOKAGE IS BLIND - ZERODHA LOGIN NEEDED
    06:22:05  GET /broker/zerodha/login              302
    06:22:37  .env written, broker session refreshed in place
    06:22:37  <- boot A's log ends here, mid-request
    06:22:43  boot B online, kite_main connected
    06:22:45  GET /broker/zerodha/callback...        500

The login worked. Hokage was live. The commander was shown "Authentication
failed" in red.

Start-Hokage.ps1 had been polling for exactly the token the callback had just
written, and its unconditional "login detected -> restart" killed the process
in the 0.3s between the token hitting .env and the handler answering the
browser. The browser retried; the retry reached the new process carrying a
request_token that is single-use and had just been used; generate_session
refused it; the outer handler turned that into a 500.

TWO SEPARATE DEFECTS, and the pair is what made it invisible:

  1. a spent request_token read as a failed login (fixed here)
  2. the launcher restarted a process that had already healed itself
     (fixed in Start-Hokage.ps1, pinned by test_launcher_kills_only_hokage)

Teaching the commander to distrust the login page is the real cost. It is the
only screen that tells him whether Hokage can trade today.
"""
from __future__ import annotations

import pytest

from hokage.dashboard.api import (
    _process_sees_market,
    describe_spent_login_link,
)


# --------------------------------------------------------------- stand-ins
class _State:
    def __init__(self, name: str) -> None:
        self.name = name


class _Status:
    def __init__(self, name: str) -> None:
        self.state = _State(name)
        self.message = ""


class _Venue:
    def __init__(self, name: str) -> None:
        self._name = name

    def get_status(self) -> _Status:
        return _Status(self._name)


class _ExplodingVenue:
    def get_status(self):
        raise RuntimeError("venue is not connected")


class _Registry:
    def __init__(self, venue) -> None:
        self._venue = venue

    def get_venue(self, name: str):
        if self._venue is None:
            raise KeyError(name)
        return self._venue


class _Manager:
    def __init__(self, name: str) -> None:
        self.connection_state = _State(name)


_DEFAULT = object()


class _Orchestrator:
    def __init__(self, venue_state="CONNECTED", data_state="CONNECTED",
                 venue=_DEFAULT, manager=_DEFAULT) -> None:
        # A sentinel, not None: "no venue is registered" is one of the states
        # under test, so None has to stay expressible.
        self.registry = _Registry(
            _Venue(venue_state) if venue is _DEFAULT else venue
        )
        self.kite_connection = (
            _Manager(data_state) if manager is _DEFAULT else manager
        )


# ------------------------------------------------- both halves, not one
def test_a_fully_connected_process_sees_the_market():
    assert _process_sees_market(_Orchestrator()) is True


def test_a_connected_venue_with_a_dead_data_session_does_not_count():
    """THE 2026-08-05 FAILURE. kite_main filled orders fine while the object
    every scan reads quotes through still held the token it booted on. Hokage
    stood aside all day and every panel read healthy."""
    o = _Orchestrator(venue_state="CONNECTED", data_state="DISCONNECTED")
    assert _process_sees_market(o) is False


def test_a_live_data_session_behind_a_dead_venue_does_not_count():
    o = _Orchestrator(venue_state="DISCONNECTED", data_state="CONNECTED")
    assert _process_sees_market(o) is False


def test_a_missing_data_manager_is_not_a_yes():
    """An orchestrator without the attribute must not read as connected. 'I
    could not tell' and 'yes' are different answers."""
    o = _Orchestrator(manager=None)
    assert _process_sees_market(o) is False


@pytest.mark.parametrize("broken", [
    _Orchestrator(venue=_ExplodingVenue()),
    _Orchestrator(venue=None),
])
def test_it_never_raises_and_never_guesses_yes(broken):
    """Every caller is deciding how to word a message or whether to kill a
    process. Neither is improved by a traceback, and both are made worse by a
    confident wrong yes."""
    assert _process_sees_market(broken) is False


# ----------------------------------------- the spent link says the truth
def test_a_spent_link_on_a_live_session_is_not_an_error():
    body, code = describe_spent_login_link(_Orchestrator(), "Token is invalid")
    assert code == 200
    assert "already" in body.lower()
    assert "live zerodha session" in body.lower()


def test_a_spent_link_on_a_live_session_never_says_authentication_failed():
    """The exact words the commander saw. If they come back for a login that
    worked, this whole fix has been undone."""
    body, _ = describe_spent_login_link(_Orchestrator(), "Token is invalid")
    assert "authentication failed" not in body.lower()
    assert "failed" not in body.lower()


def test_a_spent_link_with_no_session_tells_him_what_to_do():
    o = _Orchestrator(data_state="DISCONNECTED")
    body, code = describe_spent_login_link(o, "Token is invalid or has expired")
    assert code == 400
    assert "login to zerodha again" in body.lower()


def test_a_spent_link_is_never_a_500():
    """A 500 is a red error page for an expected event on the one screen that
    says whether he can trade today."""
    for o in (_Orchestrator(), _Orchestrator(data_state="DISCONNECTED")):
        _, code = describe_spent_login_link(o, "Token is invalid")
        assert code != 500


def test_the_real_cause_is_still_reported_when_it_matters():
    """Softening the page must not hide the broker's own reason, or the next
    genuine expiry becomes undiagnosable."""
    o = _Orchestrator(data_state="DISCONNECTED")
    body, _ = describe_spent_login_link(o, "api_key is invalid")
    assert "api_key is invalid" in body
