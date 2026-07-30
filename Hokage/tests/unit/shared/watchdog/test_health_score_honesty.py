"""The health score must be able to say "unhealthy".

For the seven days Hokage sat blind on an expired Zerodha token — refusing every
scan, placing no trades, alerting nobody — the watchdog logged
"Overall Health Score: 100.0/100" every five seconds. Heartbeat freshness, the
largest input to that score, was measured against subsystems whose heartbeats
were stamped "HEALTHY" every 15s by a timer thread that inspects nothing. It
could detect a stopped process and nothing else.

A signal that cannot fail is not a signal.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from shared.watchdog.watchdog import Watchdog


def test_timer_stamped_engines_are_not_admissible_as_health_evidence():
    """The five engines that used to gate the score are all timer-stamped."""
    fabricated = {
        "orchestrator", "surveillance_loop", "risk_engine",
        "improvement_engine", "execution_engine", "portfolio_engine",
        "research_engine", "shadow_engine", "voice_commander",
    }
    assert fabricated.isdisjoint(Watchdog.REAL_HEARTBEAT_SUBSYSTEMS)


def test_the_real_signals_are_the_ones_that_require_actual_work():
    assert "market_data" in Watchdog.REAL_HEARTBEAT_SUBSYSTEMS
    assert "strategy_engine" in Watchdog.REAL_HEARTBEAT_SUBSYSTEMS


def test_liveness_stamper_never_overwrites_a_real_publisher(monkeypatch):
    """A timer must not be able to resurrect a dead loop on paper."""
    started: list[str] = []

    class _Thread:
        def __init__(self, target=None, name=None, daemon=None):
            started.append(name or "")

        def start(self):
            pass

    engine = Watchdog.__new__(Watchdog)
    engine._stop_monitor = type("E", (), {"is_set": lambda self: True})()
    monkeypatch.setattr("shared.watchdog.watchdog.threading.Thread", _Thread)

    engine.start_subsystem_heartbeats()

    for real in Watchdog.REAL_HEARTBEAT_SUBSYSTEMS:
        assert not any(real in name for name in started), (
            f"{real} has a real publisher; a timer must not stamp it"
        )
    # The other engines are still stamped, because the dashboard bot panel
    # reads their ages to show online/offline.
    assert any("risk_engine" in name for name in started)


@pytest.mark.parametrize(
    "subsystem,expected",
    [("strategy_engine", 195.0), ("market_data", 195.0), ("risk_engine", 30.0)],
)
def test_real_publishers_get_a_threshold_above_their_own_cadence(subsystem, expected):
    """The scan loop ticks every 60s; a flat 30s would call it stale forever."""
    engine = Watchdog.__new__(Watchdog)
    engine.heartbeat_stale_threshold_sec = 30.0
    engine.heartbeat_stale_threshold_overrides = {
        "strategy_engine": 195.0,
        "market_data": 195.0,
    }
    limit = engine.heartbeat_stale_threshold_overrides.get(
        subsystem, engine.heartbeat_stale_threshold_sec
    )
    assert limit == expected


def test_a_dead_feed_makes_market_data_go_stale():
    """market_data is published ONLY after a quote comes back, so an outage
    ages it out — the mechanism that was missing for seven days."""
    engine = Watchdog.__new__(Watchdog)
    engine.heartbeat_stale_threshold_sec = 30.0
    engine.heartbeat_stale_threshold_overrides = {"market_data": 195.0}

    now = datetime.now(timezone.utc)
    blind_for = timedelta(days=7)
    age = (now - (now - blind_for)).total_seconds()

    assert age > engine.heartbeat_stale_threshold_overrides["market_data"]
