"""Notice the outage, and only the outage.

2026-08-27, 07:44. Hokage had been dead since 04:14 — 3h39m — and his last words
were "Overall Health Score: 100.0/100." His own watchdog cannot report that he
is gone; it dies with him. On the same morning the Zerodha token had expired, so
even a living Hokage would have been scanning a market he could not see.

Third time for this class of failure: nine days blind on a dead token in July, a
7.5h battery sleep with a position open, and now a silent death. Each was
invisible while it happened.

WHAT MAKES AN ALARM WORTH HAVING is entirely in what it stays quiet about. A
false "Hokage is dead" on 2026-08-24 (a mangled `tasklist` filter) cost real
trust, and an orphan alarm that fired every boot for a decision already made is
why PARKED_ASSETS exists. So the tests below spend most of their length on
silence: overnight, at weekends, on a single missed poll, and on the sixteenth
consecutive check of the same four-hour outage.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location(
    "liveness_probe", ROOT / "tools" / "ops" / "liveness_probe.py"
)
lp = importlib.util.module_from_spec(_spec)
#: Registered BEFORE exec_module because @dataclass resolves its annotations
#: through sys.modules[cls.__module__]; without this the decorator sees None and
#: dies during collection.
sys.modules["liveness_probe"] = lp
_spec.loader.exec_module(lp)

#: Thursday 2026-08-27, mid-session.
TRADING = datetime(2026, 8, 27, 14, 30)
#: The hour Hokage actually died, which is outside MCX hours.
NIGHT = datetime(2026, 8, 27, 4, 14)
SATURDAY = datetime(2026, 8, 29, 14, 30)
#: 20:15 IST on EIA Thursday — the week's one scheduled gas event.
EIA_HOUR = datetime(2026, 8, 27, 20, 15)


def run(now, reachable, session, state=None, times=1):
    state = state or lp.State()
    msg = ""
    for _ in range(times):
        msg, state = lp.assess(now, reachable, session, state)
    return msg, state


# ---------------------------------------------------------------- the alarm
def test_a_dead_process_alarms_after_three_strikes():
    msg, state = run(TRADING, False, "UNKNOWN", times=lp.STRIKES)
    assert msg
    assert "not answering" in msg and "process is gone" in msg
    assert state.alerted


def test_a_living_but_blind_hokage_alarms_too():
    """The more dangerous failure: every dashboard green, every log line INFO,
    and nine days of July spent scanning a market he could not see."""
    msg, _ = run(TRADING, True, "EXPIRED", times=lp.STRIKES)
    assert msg
    assert "EXPIRED" in msg and "cannot see" in msg


def test_the_alarm_says_how_to_fix_it():
    msg, _ = run(TRADING, False, "UNKNOWN", times=lp.STRIKES)
    assert "Start-Hokage.ps1" in msg


def test_missing_credentials_are_reported_distinctly():
    msg, _ = run(TRADING, True, "NO_CREDENTIALS", times=lp.STRIKES)
    assert "credentials" in msg


def test_a_failed_check_is_reported_rather_than_assumed_healthy():
    """UNKNOWN means the probe itself could not run. Reading that as "fine" is
    how a monitor becomes decorative."""
    msg, _ = run(TRADING, True, "UNKNOWN", times=lp.STRIKES)
    assert msg and "could not run" in msg


# --------------------------------------------------------------- the silence
def test_one_missed_poll_says_nothing():
    """A restart takes longer than a poll interval. Alarming on a single miss
    produced the false 2026-08-24 death report."""
    msg, state = run(TRADING, False, "UNKNOWN", times=1)
    assert msg == ""
    assert state.strikes == 1


def test_two_strikes_still_says_nothing():
    msg, _ = run(TRADING, False, "UNKNOWN", times=lp.STRIKES - 1)
    assert msg == ""


def test_an_outage_alarms_exactly_once():
    """A four-hour outage at a 15-minute cadence is sixteen checks. Sixteen
    identical messages is how the commander learns to mute the channel."""
    _, state = run(TRADING, False, "UNKNOWN", times=lp.STRIKES)
    msg, _ = run(TRADING, False, "UNKNOWN", state=state, times=13)
    assert msg == ""


def test_nothing_is_said_outside_market_hours():
    """04:14 — the hour he actually died. He is SUPPOSED to be idle then, and a
    bot the commander stopped on purpose must not be nagged about."""
    msg, _ = run(NIGHT, False, "UNKNOWN", times=10)
    assert msg == ""


def test_nothing_is_said_at_the_weekend():
    msg, _ = run(SATURDAY, False, "UNKNOWN", times=10)
    assert msg == ""


def test_overnight_strikes_do_not_carry_into_the_open():
    """If the night accumulated strikes, the 09:00 check would alarm instantly
    on a bot that is merely starting up."""
    _, state = run(NIGHT, False, "UNKNOWN", times=20)
    assert state.strikes == 0
    msg, _ = run(TRADING, False, "UNKNOWN", state=state, times=1)
    assert msg == ""


# -------------------------------------------------------------- the recovery
def test_recovery_is_announced_and_re_arms_the_alarm():
    _, state = run(TRADING, False, "UNKNOWN", times=lp.STRIKES)
    msg, state = run(TRADING, True, "LIVE Anant", state=state)
    assert "back" in msg
    assert not state.alerted and state.strikes == 0

    msg, _ = run(TRADING, False, "UNKNOWN", state=state, times=lp.STRIKES)
    assert msg, "a second outage must alarm again"


def test_a_healthy_check_with_no_prior_outage_stays_quiet():
    msg, _ = run(TRADING, True, "LIVE Anant")
    assert msg == ""


def test_only_a_live_session_counts_as_healthy():
    for verdict in ("EXPIRED", "NO_CREDENTIALS", "UNKNOWN", ""):
        _, state = run(TRADING, True, verdict, times=1)
        assert state.strikes == 1, verdict


# ------------------------------------------------------- the hour that matters
def test_the_eia_hour_is_inside_the_watched_window():
    """Today's whole point: gas has one scheduled event a week, at 20:00 IST on
    a Thursday. A silent death at 19:00 would cost the entire week."""
    assert lp.in_market_hours(EIA_HOUR)
    msg, _ = run(EIA_HOUR, False, "UNKNOWN", times=lp.STRIKES)
    assert msg


@pytest.mark.parametrize("hour,watched", [
    (8, False), (9, True), (14, True), (23, True), (0, False), (4, False),
])
def test_the_watched_window_matches_mcx_hours(hour, watched):
    assert lp.in_market_hours(datetime(2026, 8, 27, hour, 15)) is watched


# ------------------------------------------------------------- it never acts
def test_the_probe_never_restarts_or_trades():
    """Reviving a crash-looping bot turns one outage into a hundred, and a bot
    stopped on purpose must stay stopped. This reports; the human decides."""
    import inspect

    src = inspect.getsource(lp)
    for forbidden in ("Popen", "Start-Process", "start.py", "place_order"):
        assert forbidden not in src, forbidden


def test_it_never_prints_a_credential():
    """It shells out to check_broker_session.py precisely because that script
    returns a verdict and never a token."""
    import inspect

    src = inspect.getsource(lp)
    assert "access_token" not in src and "api_key" not in src


# --------------------------------------------------------------- state on disk
def test_state_survives_a_round_trip(tmp_path):
    path = tmp_path / "liveness.json"
    state = lp.State(strikes=2, alerted=True, last_reason="dashboard down")
    state.save(path)
    back = lp.State.load(path)
    assert (back.strikes, back.alerted, back.last_reason) == (2, True, "dashboard down")


def test_a_missing_or_corrupt_state_file_starts_clean(tmp_path):
    """A monitor that crashes on its own state file is worse than no monitor."""
    assert lp.State.load(tmp_path / "nope.json").strikes == 0
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert lp.State.load(bad).strikes == 0
