"""Silence has to be the alarm, because the alarm cannot live here.

2026-09-23 06:27: Hokage's process wrote its last line. 2026-10-09 18:26: the
next one started. Sixteen days, eleven market sessions, no process, no
decisions, no log file. The commander was travelling and the laptop was off.

The external liveness probe — written after a 3h39m death Hokage reported as
"Health Score 100/100", on the principle that his own watchdog dies with him
— did not fire either. It is a Windows scheduled task on the same laptop,
running as LogonType=Interactive like every other Hokage task. Independent of
the PROCESS, not of the MACHINE, and the machine is what went away.

So the signal is inverted: Hokage pushes a heartbeat OUT, and the service
alarms when it stops arriving. The watch no longer needs to reach him; he
needs to keep reaching it.

NO TEST HERE TOUCHES THE NETWORK. The transport is injected, conftest sets
HOKAGE_DISABLE_DEADMAN and strips HOKAGE_DEADMAN_URL from the environment,
and a test that forgot both would still have no URL to reach. The ping URL is
a capability token: anyone holding it can forge a heartbeat, which is exactly
how this watch would get switched off without anyone noticing.
"""
from __future__ import annotations

import logging

import pytest

from shared.watchdog import deadman
from shared.watchdog.deadman import DeadMansSwitch

URL = "https://hc-ping.example/00000000-1111-2222-3333-444444444444"


class _Transport:
    """Records calls instead of making them."""

    def __init__(self, ok=True):
        self.calls: list[tuple[str, str]] = []
        self.ok = ok

    def __call__(self, url, body, timeout):
        self.calls.append((url, body))
        if isinstance(self.ok, Exception):
            raise self.ok
        return self.ok


# ------------------------------------------------------- the suite is sealed
def test_the_suite_cannot_reach_the_real_service():
    """conftest both disables the switch and removes the URL. Either alone
    would do; both, because a forged heartbeat turns the watch off in
    silence and there is no way to notice afterwards."""
    import os

    assert os.environ.get(deadman.DISABLE_ENV) == "true"
    assert deadman.URL_ENV not in os.environ
    assert deadman.configured_url() is None


def test_the_disable_flag_beats_a_configured_url(monkeypatch):
    monkeypatch.setenv(deadman.URL_ENV, URL)
    monkeypatch.setenv(deadman.DISABLE_ENV, "true")
    assert deadman.configured_url() is None


# --------------------------------------------------------- the URL is secret
def test_the_url_path_never_reaches_a_log(monkeypatch, caplog):
    """The path IS the credential. The host is enough to debug with."""
    caplog.set_level(logging.DEBUG, logger="Hokage.DeadMansSwitch")
    sw = DeadMansSwitch(url=URL, transport=_Transport(ok=False))
    sw.ping()
    sw.ping()
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert text, "it must say something when a heartbeat fails"
    assert "444444444444" not in text
    assert URL not in text
    assert "hc-ping.example" in text


def test_safe_host_keeps_only_the_host():
    assert deadman.safe_host(URL) == "hc-ping.example"
    assert deadman.safe_host(None) == "(not configured)"
    assert "/" not in deadman.safe_host("https://x.example/secret/path")


def test_a_url_that_is_not_http_is_refused(monkeypatch):
    """A pasted placeholder, or a path, would otherwise be handed to the
    transport and fail every ten minutes forever."""
    monkeypatch.delenv(deadman.DISABLE_ENV, raising=False)
    monkeypatch.setenv(deadman.URL_ENV, "paste-your-url-here")
    assert deadman.configured_url() is None


def test_whitespace_around_a_pasted_url_does_not_disable_it(monkeypatch):
    monkeypatch.delenv(deadman.DISABLE_ENV, raising=False)
    monkeypatch.setenv(deadman.URL_ENV, f"  {URL}  ")
    assert deadman.configured_url() == URL


# ----------------------------------------------------------------- the ping
def test_a_heartbeat_carries_the_status_line():
    t = _Transport()
    sw = DeadMansSwitch(url=URL, transport=t, status_fn=lambda: "PAPER | feed ok")
    assert sw.ping() is True
    assert t.calls == [(URL, "PAPER | feed ok")]
    assert sw.pings == 1


def test_a_broken_status_function_does_not_cost_the_heartbeat():
    """The heartbeat is the signal. The status beside it is a convenience,
    and a convenience must never be able to silence a signal."""
    def boom():
        raise RuntimeError("portfolio unavailable")

    t = _Transport()
    sw = DeadMansSwitch(url=URL, transport=t, status_fn=boom)
    assert sw.ping() is True
    assert "status unavailable" in t.calls[0][1]


def test_a_transport_that_raises_is_not_an_exception_to_the_caller():
    sw = DeadMansSwitch(url=URL, transport=_Transport(ok=RuntimeError("DNS")))
    assert sw.ping() is False          # must not raise


def test_a_rejected_ping_is_not_counted_as_delivered():
    sw = DeadMansSwitch(url=URL, transport=_Transport(ok=False))
    assert sw.ping() is False
    assert sw.pings == 0


def test_repeated_failures_warn_once_then_fall_to_debug(caplog):
    """This laptop lost DNS for 44 distinct minutes on 10-14 and 10-15 and
    produced 144 identical WARNING lines. A log nobody can read is a log
    nobody reads."""
    caplog.set_level(logging.DEBUG, logger="Hokage.DeadMansSwitch")
    sw = DeadMansSwitch(url=URL, transport=_Transport(ok=RuntimeError("DNS")))
    for _ in range(5):
        sw.ping()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert len([r for r in caplog.records if r.levelno == logging.DEBUG]) == 4


def test_recovery_is_announced(caplog):
    caplog.set_level(logging.INFO, logger="Hokage.DeadMansSwitch")
    t = _Transport(ok=False)
    sw = DeadMansSwitch(url=URL, transport=t)
    sw.ping()
    t.ok = True
    sw.ping()
    assert any("restored" in r.getMessage() for r in caplog.records)


# ------------------------------------------------------- not configured
def test_an_unconfigured_switch_pings_nothing():
    sw = DeadMansSwitch(url=None, transport=_Transport())
    assert sw.enabled is False
    assert sw.ping() is False


def test_an_unconfigured_switch_says_so_once_and_loudly(caplog):
    """An unconfigured switch is a real gap — it is the gap that cost eleven
    market sessions — so it must be visible at boot. Once, not per cycle."""
    caplog.set_level(logging.DEBUG, logger="Hokage.DeadMansSwitch")
    sw = DeadMansSwitch(url=None, transport=_Transport())
    sw.start()
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "NOT configured" in warnings[0].getMessage()


def test_stopping_an_unconfigured_switch_is_harmless():
    sw = DeadMansSwitch(url=None, transport=_Transport())
    sw.stop("clean shutdown")          # must not raise


# --------------------------------------------------------------- shutdown
def test_a_clean_stop_reports_a_reason_rather_than_vanishing():
    """The check goes DOWN either way. This replaces "vanished" with a
    sentence the commander can read without investigating."""
    t = _Transport()
    sw = DeadMansSwitch(url=URL, transport=t)
    sw.stop("clean shutdown")
    assert t.calls
    url, body = t.calls[-1]
    assert url.endswith("/fail")
    assert "clean shutdown" in body


def test_a_deliberate_stop_is_not_suppressed():
    """NO MUTE FROM IN HERE, deliberately. Any mechanism that silences a
    planned absence can silence a real one, and the deliberate-stop marker
    has already failed to survive a scheduled task once (2026-10-09)."""
    src = __import__("pathlib").Path(deadman.__file__).read_text(encoding="utf-8")
    assert "NO SUPPRESSION" in src
    for banned in ("def pause", "def mute", "stop_marker", "suppress("):
        assert banned not in src, f"a mute path crept in: {banned}"


# ------------------------------------------------------------- the schedule
def test_the_interval_cannot_be_set_absurdly_low():
    """A per-second heartbeat gets the account rate-limited, and a
    rate-limited heartbeat is silence."""
    assert DeadMansSwitch(url=URL, interval_seconds=1)._interval == 30


def test_the_default_interval_is_shorter_than_a_sensible_service_period():
    """Recommended service period is 15 minutes. Pinging every 10 means one
    lost ping is not a missed deadline."""
    assert deadman.DEFAULT_INTERVAL_SECONDS == 600


def test_it_pings_immediately_on_start_not_an_interval_later():
    """A boot that crashes in its first minutes would otherwise look exactly
    like a healthy start until the first interval elapsed."""
    t = _Transport()
    sw = DeadMansSwitch(url=URL, interval_seconds=3600, transport=t)
    sw.start()
    try:
        for _ in range(100):
            if t.calls:
                break
            import time
            time.sleep(0.01)
        assert t.calls, "no heartbeat was sent at start"
    finally:
        sw.stop("test over")


# --------------------------------------------------------------- the bot
def test_the_bot_arms_and_stands_it_down():
    import ast
    import pathlib

    root = next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    tree = ast.parse((root / "src" / "bots" / "autonomous" / "autonomous_bot.py")
                     .read_text(encoding="utf-8"))
    start = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "start")
    stop = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "stop")
    assert "DeadMansSwitch" in ast.dump(start)
    assert "_deadman" in ast.dump(stop)


def test_the_status_line_does_not_touch_the_database():
    """It runs on the heartbeat thread, whose one job is to prove the process
    is alive. Reaching for the database would put a lock between that proof
    and the thing it proves."""
    import ast
    import pathlib

    root = next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    tree = ast.parse((root / "src" / "bots" / "autonomous" / "autonomous_bot.py")
                     .read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_deadman_status")
    dumped = ast.dump(fn)
    for banned in ("portfolio_store", "load_account", "journal", "execute"):
        assert banned not in dumped, f"the status line reaches for {banned}"


def test_the_status_line_carries_nothing_sensitive():
    """An outside service displays it."""
    import ast
    import pathlib

    root = next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    tree = ast.parse((root / "src" / "bots" / "autonomous" / "autonomous_bot.py")
                     .read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_deadman_status")
    dumped = ast.dump(fn).lower()
    for banned in ("token", "secret", "api_key", "access_token", "account_id",
                   "password"):
        assert banned not in dumped, f"the status line carries {banned}"
