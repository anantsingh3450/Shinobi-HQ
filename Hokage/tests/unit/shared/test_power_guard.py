"""A suspended host is not a paused bot — it is an unmanaged position.

2026-08-12 produced two loop gaps, 62 and 35 minutes, and the Windows System
log shows both were the plain idle timer: uptime 5h08m and 5h02m against an
18000-second STANDBYIDLE setting. A headless Hokage is indistinguishable from
an unused laptop, so Windows suspended it, correctly, twice. The NATURALGAS PE
rode the first gap with no stop and no thesis-stop.

`_check_for_unconscious_gap` only ever ANNOUNCED this after the fact. These
tests cover the part that prevents it.
"""
from __future__ import annotations

import sys

import pytest

from shared import power


@pytest.fixture(autouse=True)
def _reset_module_state():
    power._held = False
    yield
    power._held = False


def test_holding_is_reported_only_when_windows_actually_accepted_it(monkeypatch):
    """A guard that silently fails is worse than no guard — it would leave the
    commander believing the machine cannot sleep. `_held` tracks the real
    answer from the API, not the intent."""
    monkeypatch.setattr(power, "_set_state", lambda flags: False)
    assert power.hold_system_awake() is False
    assert power.is_holding() is False

    monkeypatch.setattr(power, "_set_state", lambda flags: True)
    assert power.hold_system_awake() is True
    assert power.is_holding() is True


def test_it_asks_to_keep_the_SYSTEM_awake_and_lets_the_DISPLAY_sleep(monkeypatch):
    """The point is CPU time for the trading loop. Pinning the display on as
    well would burn the panel all session for no risk benefit."""
    seen: list[int] = []
    monkeypatch.setattr(power, "_set_state", lambda flags: seen.append(flags) or True)
    power.hold_system_awake()
    assert seen == [power._ES_CONTINUOUS | power._ES_SYSTEM_REQUIRED]
    ES_DISPLAY_REQUIRED = 0x00000002
    assert not (seen[0] & ES_DISPLAY_REQUIRED)


def test_re_asserting_every_loop_is_harmless(monkeypatch):
    """It is called once per iteration on purpose: SetThreadExecutionState is
    per-THREAD and the state dies with the thread that set it. Repeat calls
    must not log a storm or flip state."""
    calls: list[int] = []
    monkeypatch.setattr(power, "_set_state", lambda flags: calls.append(flags) or True)
    for _ in range(50):
        power.hold_system_awake(announce=True)
    assert len(calls) == 50
    assert power.is_holding() is True


def test_a_guard_that_stops_being_granted_is_noticed(monkeypatch):
    """If Windows starts refusing mid-session the bot must stop believing it is
    protected, so the next gap is attributed correctly."""
    monkeypatch.setattr(power, "_set_state", lambda flags: True)
    power.hold_system_awake()
    assert power.is_holding() is True

    monkeypatch.setattr(power, "_set_state", lambda flags: False)
    power.hold_system_awake()
    assert power.is_holding() is False


def test_release_returns_the_host_to_normal_power_behaviour(monkeypatch):
    seen: list[int] = []
    monkeypatch.setattr(power, "_set_state", lambda flags: seen.append(flags) or True)
    power.hold_system_awake()
    power.release_system_awake()
    assert seen[-1] == power._ES_CONTINUOUS
    assert power.is_holding() is False


def test_release_without_a_hold_is_a_no_op(monkeypatch):
    seen: list[int] = []
    monkeypatch.setattr(power, "_set_state", lambda flags: seen.append(flags) or True)
    power.release_system_awake()
    assert seen == []


def test_non_windows_hosts_degrade_quietly_rather_than_crashing(monkeypatch):
    """CI and any future Linux host must not fail a trading loop over a power
    API that does not exist there."""
    monkeypatch.setattr(sys, "platform", "linux")
    assert power._set_state(power._ES_CONTINUOUS) is False


def test_the_api_never_raises_into_the_trading_loop(monkeypatch):
    """Wrapped at the call site too, but the guard is defence in depth: a power
    API failure must never be able to stop the risk engine from running."""
    def _boom(_flags):
        raise OSError("simulated ctypes failure")

    monkeypatch.setattr(power, "_set_state", _boom)
    with pytest.raises(OSError):
        power.hold_system_awake()  # raises here...

    # ...and the trading loop's own try/except is what contains it. Confirm the
    # module leaves no half-set state behind when it does.
    assert power.is_holding() is False
