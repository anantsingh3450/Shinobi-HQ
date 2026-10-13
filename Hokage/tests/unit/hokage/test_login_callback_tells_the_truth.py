"""The login page must not report failure for a login that succeeded, and must
not report success from a flag that went stale hours ago.

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

Then the day got worse, and the second half is the more dangerous one:

    06:30:06  "Morning login prompt skipped: existing session is already valid"
    06:33:21  Kite: Incorrect api_key or access_token
    06:33:24  CRITICAL: Market data feed is DOWN (auth)
    06:40     /broker/zerodha/status -> {"connected": true}

CONNECTION STATE IS NOT EVIDENCE. Both get_status() methods return whatever
connect() stored last, and nothing updates them when the token dies
underneath. The venue connected at 06:22:44, the token was invalidated around
06:33, and the endpoint kept answering connected: true for thirteen more
minutes while the feed screamed every sixty seconds. A launcher trusting that
flag skips the restart it needed; a commander reading that panel believes a
blind Hokage can see.

So neither answer here is allowed to come from a flag:

  verify_session_live  re-reads the stored token and reconnects. Rare paths
                       only - it is a round trip to Kite - and it heals the
                       process as a side effect.
  last_quote_probe     reports whether a quote actually came back, and how
                       long ago. The cheap one, safe to poll, and the only
                       fact on that endpoint that cannot go quietly stale.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from hokage.dashboard.api import (
    MAX_QUOTE_PROBE_AGE_SECONDS,
    describe_spent_login_link,
    last_quote_probe,
    verify_session_live,
)


# --------------------------------------------------------------- stand-ins
class _Manager:
    """A KiteConnectionManager stand-in. `live` is what the broker would say
    if asked right now, which is the thing a cached flag cannot know."""

    def __init__(self, live: bool, raises: bool = False) -> None:
        self.live = live
        self.raises = raises
        self.reconnects = 0

    def try_reconnect(self) -> bool:
        self.reconnects += 1
        if self.raises:
            raise RuntimeError("kite unreachable")
        return self.live


class _Bot:
    def __init__(self, ok=None, age_seconds=None, reason="") -> None:
        if ok is not None:
            self._feed_probe_ok = ok
            self._feed_probe_at = datetime.now(timezone.utc) - timedelta(
                seconds=age_seconds or 0
            )
            self._feed_probe_reason = reason


class _Orchestrator:
    def __init__(self, manager=None, bot=None) -> None:
        if manager is not None:
            self.kite_connection = manager
        if bot is not None:
            self.autonomous_bot = bot


# ------------------------------------------- the active test, for rare paths
def test_a_live_session_is_confirmed_by_asking_the_broker():
    m = _Manager(live=True)
    assert verify_session_live(_Orchestrator(manager=m)) is True
    assert m.reconnects == 1, "it must actually ask, not read a stored state"


def test_a_dead_token_is_reported_dead_however_the_flags_look():
    """THE 06:33 FAILURE. Nothing in this stand-in carries a stale 'connected'
    to be fooled by, because the answer no longer comes from one."""
    assert verify_session_live(_Orchestrator(manager=_Manager(live=False))) is False


def test_a_missing_manager_is_not_a_yes():
    assert verify_session_live(_Orchestrator()) is False
    assert verify_session_live(_Orchestrator(manager=object())) is False


def test_it_never_raises_and_never_guesses_yes():
    """Callers are wording a message or deciding whether to kill a process.
    Neither is improved by a traceback, both are made worse by a wrong yes."""
    o = _Orchestrator(manager=_Manager(live=True, raises=True))
    assert verify_session_live(o) is False


# ------------------------------------ the recorded quote, for polled paths
def test_a_fresh_successful_probe_reads_as_ok():
    ok, age, _ = last_quote_probe(_Orchestrator(bot=_Bot(ok=True, age_seconds=12)))
    assert ok is True
    assert 10 <= age <= 20


def test_a_failed_probe_carries_the_brokers_own_reason():
    ok, _, reason = last_quote_probe(
        _Orchestrator(bot=_Bot(ok=False, age_seconds=3, reason="Incorrect api_key"))
    )
    assert ok is False
    assert "api_key" in reason


def test_no_probe_yet_is_none_and_not_false():
    """'I have not looked' and 'I looked and it was broken' are different
    answers, and something deciding whether to kill the process reads this."""
    ok, age, reason = last_quote_probe(_Orchestrator(bot=_Bot()))
    assert ok is None
    assert age is None
    assert reason


def test_no_bot_in_this_process_is_none_and_not_false():
    ok, _, reason = last_quote_probe(_Orchestrator())
    assert ok is None
    assert reason


def test_the_staleness_bound_is_short_enough_to_mean_now():
    """The probe runs about once a minute. A bound long enough to span many
    cycles would let a reading from a previous market condition read as
    current - which is the whole defect being fixed."""
    assert 60 <= MAX_QUOTE_PROBE_AGE_SECONDS <= 300


def test_the_probe_reader_never_raises():
    class _Exploding:
        @property
        def _feed_probe_ok(self):
            raise RuntimeError("boom")

    ok, _, _ = last_quote_probe(_Orchestrator(bot=_Exploding()))
    assert ok is None


# ----------------------------------------- the spent link says the truth
def test_a_spent_link_on_a_live_session_is_not_an_error():
    body, code = describe_spent_login_link(
        _Orchestrator(manager=_Manager(live=True)), "Token is invalid"
    )
    assert code == 200
    assert "already" in body.lower()
    assert "live zerodha session" in body.lower()


def test_a_spent_link_on_a_live_session_never_says_authentication_failed():
    """The exact words the commander saw. If they come back for a login that
    worked, this whole fix has been undone."""
    body, _ = describe_spent_login_link(
        _Orchestrator(manager=_Manager(live=True)), "Token is invalid"
    )
    assert "authentication failed" not in body.lower()
    assert "failed" not in body.lower()


def test_a_spent_link_with_a_dead_token_tells_him_what_to_do():
    body, code = describe_spent_login_link(
        _Orchestrator(manager=_Manager(live=False)), "Token is invalid or has expired"
    )
    assert code == 400
    assert "login to zerodha again" in body.lower()


def test_the_spent_link_page_asks_the_broker_rather_than_a_flag():
    """A page that trusted a cached 'connected' would have told him "already
    connected, nothing to do" at 06:40, while Hokage was blind."""
    m = _Manager(live=False)
    describe_spent_login_link(_Orchestrator(manager=m), "Token is invalid")
    assert m.reconnects == 1


def test_a_spent_link_is_never_a_500():
    """A 500 is a red error page for an expected event, on the one screen that
    says whether he can trade today."""
    for live in (True, False):
        _, code = describe_spent_login_link(
            _Orchestrator(manager=_Manager(live=live)), "Token is invalid"
        )
        assert code != 500


def test_the_real_cause_is_still_reported_when_it_matters():
    """Softening the page must not hide the broker's own reason, or the next
    genuine expiry becomes undiagnosable."""
    body, _ = describe_spent_login_link(
        _Orchestrator(manager=_Manager(live=False)), "api_key is invalid"
    )
    assert "api_key is invalid" in body
