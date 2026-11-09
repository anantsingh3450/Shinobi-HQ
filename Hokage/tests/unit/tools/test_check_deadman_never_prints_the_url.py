"""A setup check that cannot leak the thing it is checking.

The ping URL is a capability: anyone holding it can forge a heartbeat and turn
the watch off with nothing appearing wrong. So the obvious ways to confirm it
is set - `type .env`, a grep for the key, pasting it into a chat to ask "is
this right?" - all defeat the point, and one of them has already happened in
this project's history: a request_token reached eighteen log files because
werkzeug logged a callback URL.

This tool exists so the question "is it configured?" has an answer that is
safe to run on a shared screen. These tests hold that down with a secret that
would be unmistakable if it ever appeared.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools" / "ops"))
sys.path.insert(0, str(ROOT / "src"))

#: Unmistakable if it leaks, and shaped like the real thing.
SECRET_PATH = "e7a1b2c3-dead-4beef-9999-0123456789ab"
FAKE_URL = f"https://hc-ping.com/{SECRET_PATH}"


@pytest.fixture
def tool(monkeypatch, tmp_path):
    """Load the tool with a .env that cannot reach the real one."""
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: False)
    import check_deadman

    return check_deadman


def _run(tool, capsys) -> str:
    try:
        tool.main()
    except SystemExit:
        pass
    return capsys.readouterr().out


# ================================================= the secret never appears
def test_the_path_is_never_printed(tool, monkeypatch, capsys):
    monkeypatch.setenv("HOKAGE_DEADMAN_URL", FAKE_URL)
    monkeypatch.delenv("HOKAGE_DISABLE_DEADMAN", raising=False)
    out = _run(tool, capsys)
    assert SECRET_PATH not in out
    assert FAKE_URL not in out


def test_the_host_is_printed_because_it_is_not_secret(tool, monkeypatch, capsys):
    monkeypatch.setenv("HOKAGE_DEADMAN_URL", FAKE_URL)
    monkeypatch.delenv("HOKAGE_DISABLE_DEADMAN", raising=False)
    out = _run(tool, capsys)
    assert "hc-ping.com" in out
    assert "set" in out


def test_a_rejected_value_is_diagnosed_without_being_quoted(tool, monkeypatch,
                                                            capsys):
    """The commonest paste error is a missing scheme. Saying so is useful;
    echoing the value back to prove it is not."""
    monkeypatch.setenv("HOKAGE_DEADMAN_URL", f"hc-ping.com/{SECRET_PATH}")
    monkeypatch.delenv("HOKAGE_DISABLE_DEADMAN", raising=False)
    out = _run(tool, capsys)
    assert "REJECTED" in out
    assert SECRET_PATH not in out


def test_an_absent_switch_says_so_and_points_at_the_runbook(tool, monkeypatch,
                                                            capsys):
    monkeypatch.delenv("HOKAGE_DEADMAN_URL", raising=False)
    monkeypatch.delenv("HOKAGE_DISABLE_DEADMAN", raising=False)
    out = _run(tool, capsys)
    assert "NOT CONFIGURED" in out
    assert "DEAD_MANS_SWITCH.md" in out
    # and it names the cost, so the line is not ignorable
    assert "eleven market sessions" in out


def test_a_deliberately_disabled_switch_is_reported_as_off(tool, monkeypatch,
                                                           capsys):
    """The test suite sets HOKAGE_DISABLE_DEADMAN so no test can ping the real
    service. A tool that reported that as 'configured' would be lying."""
    monkeypatch.setenv("HOKAGE_DEADMAN_URL", FAKE_URL)
    monkeypatch.setenv("HOKAGE_DISABLE_DEADMAN", "true")
    out = _run(tool, capsys)
    assert "deliberately OFF" in out
    assert "NO" in out
    assert SECRET_PATH not in out


# ================================================== the exit code is usable
def test_it_returns_non_zero_when_not_configured(tool, monkeypatch, capsys):
    """`main` RETURNS the code; only `__main__` raises it. A test that waits
    for SystemExit here passes for the wrong reason the day main starts
    raising, and fails for the wrong reason today."""
    monkeypatch.delenv("HOKAGE_DEADMAN_URL", raising=False)
    monkeypatch.delenv("HOKAGE_DISABLE_DEADMAN", raising=False)
    assert tool.main() == 1
    capsys.readouterr()


def test_it_returns_zero_when_configured(tool, monkeypatch, capsys):
    monkeypatch.setenv("HOKAGE_DEADMAN_URL", FAKE_URL)
    monkeypatch.delenv("HOKAGE_DISABLE_DEADMAN", raising=False)
    assert tool.main() == 0
    capsys.readouterr()


def test_a_disabled_switch_is_not_reported_as_ready(tool, monkeypatch, capsys):
    monkeypatch.setenv("HOKAGE_DEADMAN_URL", FAKE_URL)
    monkeypatch.setenv("HOKAGE_DISABLE_DEADMAN", "true")
    assert tool.main() == 1
    capsys.readouterr()


# ========================================== it does not reach the network
def test_it_never_pings(tool):
    """Checking the setup must not consume a heartbeat. A tool that pinged
    would make the check green while Hokage was down."""
    src = (ROOT / "tools" / "ops" / "check_deadman.py").read_text(encoding="utf-8")
    assert "requests" not in src
    assert "DeadMansSwitch(" not in src
    assert ".ping(" not in src


def test_it_only_ever_formats_the_safe_host():
    """safe_host strips the path. Any other formatting of the url in this file
    would be a direct route to printing it."""
    src = (ROOT / "tools" / "ops" / "check_deadman.py").read_text(encoding="utf-8")
    body = src.split("def main")[1]
    # the only places `url` is interpolated must be through safe_host
    for line in body.splitlines():
        if "{url" in line or "+ url" in line or "% url" in line:
            pytest.fail(f"the url is formatted directly: {line.strip()}")
    assert "safe_host(url)" in body
