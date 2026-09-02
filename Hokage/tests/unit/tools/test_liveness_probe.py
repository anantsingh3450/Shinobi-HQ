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


# ----------------------------------------------- a stop the commander ordered
def test_a_deliberate_stop_is_not_an_outage():
    """2026-08-28 21:22: the commander said "stop hokage for today". Three
    checks later, at 22:00, this probe would have Telegrammed him "HOKAGE IS NOT
    TRADING" about a stop he had just ordered.

    The docstring already said a bot stopped on purpose must stay stopped; the
    probe simply had no way to tell which kind of silence it was looking at."""
    # Exactly STRIKES calls: going further would return "" because an outage
    # alarms ONCE, which is the rule tested above.
    msg, _ = run(TRADING, False, "UNKNOWN", times=lp.STRIKES)
    assert msg, "sanity: an unexplained outage must still alarm"

    state = lp.State()
    for _ in range(lp.STRIKES * 3):
        msg, state = lp.assess(TRADING, False, "UNKNOWN", state,
                               "stopped for the day")
    assert msg == ""
    assert state.strikes == 0, "a deliberate stop must not bank strikes"
    assert "stopped on purpose" in state.last_reason


def test_the_marker_does_not_silence_a_LIVING_but_blind_hokage():
    """The marker explains a process that is GONE. If Hokage is up and his token
    is dead, that is a real fault regardless of any stale marker."""
    msg, _ = lp.assess(TRADING, True, "EXPIRED", lp.State(), "stopped for the day")
    _, state = run(TRADING, True, "EXPIRED", times=lp.STRIKES - 1)
    msg, _ = lp.assess(TRADING, True, "EXPIRED", state, "stopped for the day")
    assert msg, "an expired token on a running Hokage must still alarm"


def test_seeing_him_up_again_clears_the_marker(tmp_path, monkeypatch):
    """The self-healing property. Without it, one deliberate stop would leave
    the alarm permanently deaf — a far worse failure than the false alarm it
    prevents."""
    marker = tmp_path / "stopped.json"
    monkeypatch.setattr(lp, "STOP_MARKER", marker)
    monkeypatch.setattr(lp, "STATE_PATH", tmp_path / "liveness.json")
    monkeypatch.setattr(lp, "dashboard_answers", lambda *a, **k: True)
    monkeypatch.setattr(lp, "broker_session", lambda: "LIVE Anant")
    monkeypatch.setattr(lp, "send", lambda text: True)
    monkeypatch.setattr(lp.sys, "argv", ["liveness_probe.py"])

    lp.mark_stopped("stopped for the day", marker)
    assert marker.exists()
    lp.main()
    assert not marker.exists(), "seeing Hokage up must re-arm the alarm"


def test_the_marker_survives_a_round_trip(tmp_path):
    marker = tmp_path / "stopped.json"
    lp.mark_stopped("stopped for the day", marker)
    assert lp.deliberate_stop(marker) == "stopped for the day"


def test_no_marker_reads_as_no_deliberate_stop(tmp_path):
    assert lp.deliberate_stop(tmp_path / "absent.json") is None


def test_a_corrupt_marker_counts_as_absent(tmp_path):
    """A monitor that crashes on its own state file is worse than no monitor —
    and failing OPEN here means the alarm stays armed, which is the safe
    direction for a corrupt marker."""
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert lp.deliberate_stop(bad) is None


def test_boot_clears_the_marker_so_it_cannot_go_stale():
    """2026-09-02: the marker written on 08-28 21:26 was STILL on disk when
    Hokage was restarted at 08:33 after several days away, because only the
    probe cleared it and the probe does not run before 09:00. Had he died at
    08:40, the 09:00 check would have seen him down, found the marker, and said
    nothing.

    A stale marker masking a real death is the "permanently deaf" failure the
    self-healing design exists to prevent, so boot clears it at the moment the
    stop actually ends. The probe still clears it too, as the backstop for any
    start path that bypasses boot."""
    import ast
    import inspect

    from hokage.boot import HokageBootManager as BootManager

    src = inspect.getsource(BootManager)
    assert "_clear_deliberate_stop_marker" in src

    import textwrap

    tree = ast.parse(textwrap.dedent(
        inspect.getsource(BootManager._clear_deliberate_stop_marker)))
    assert any(getattr(n.func, "attr", None) == "unlink"
               for n in ast.walk(tree) if isinstance(n, ast.Call)), \
        "the boot hook must actually delete the marker"

    # It must never be able to stop him booting.
    assert any(isinstance(n, ast.Try) for n in ast.walk(tree))


def test_the_boot_hook_actually_deletes_the_file(tmp_path, monkeypatch):
    """RUN it, do not merely read its shape.

    The first version of this hook used `self.brain_root`, which is None unless
    a caller passes one — start.py does not — and died with "argument should be
    a str or an os.PathLike object ... not 'NoneType'". The try/except kept
    Hokage booting and the AST test above passed, so the marker survived a real
    restart on 2026-09-02 and nothing said so.

    Verifying the SHAPE of a call and never executing it is exactly how the
    `_symbol` NameError reached production on 2026-08-24."""
    from hokage.boot import HokageBootManager

    marker = tmp_path / "state" / "stopped_deliberately.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text('{"reason": "stopped for the day"}', encoding="utf-8")

    boot = object.__new__(HokageBootManager)
    boot.brain_root = None          # exactly what start.py leaves it as

    class _Resolver:
        def __init__(self, _root=None):
            pass

        def resolve_brain_root(self):
            return tmp_path

    monkeypatch.setattr("hokage.boot.PathResolver", _Resolver)
    HokageBootManager._clear_deliberate_stop_marker(boot)

    assert not marker.exists(), "boot must delete the marker, not log a warning"


def test_clearing_a_marker_that_is_not_there_is_silent(tmp_path, monkeypatch):
    from hokage.boot import HokageBootManager

    class _Resolver:
        def __init__(self, _root=None):
            pass

        def resolve_brain_root(self):
            return tmp_path

    monkeypatch.setattr("hokage.boot.PathResolver", _Resolver)
    boot = object.__new__(HokageBootManager)
    boot.brain_root = None
    HokageBootManager._clear_deliberate_stop_marker(boot)   # must not raise


def test_boot_and_probe_agree_on_the_marker_path():
    """Two clearers, one file. A path that drifts would leave the marker
    uncleared by boot and the window open again."""
    from hokage.boot import HokageBootManager as BootManager

    assert BootManager._STOP_MARKER.replace("/", "\\").endswith(
        "stopped_deliberately.json")
    assert lp.STOP_MARKER.name == "stopped_deliberately.json"
    assert lp.STOP_MARKER.parent.name == "state"
    assert BootManager._STOP_MARKER.split("/")[0] == "state"
