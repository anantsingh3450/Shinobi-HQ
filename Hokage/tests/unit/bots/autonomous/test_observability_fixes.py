"""Four silences and one flood, all found in a single day's log.

2026-08-27 produced 26,875 log lines. What they did and did not contain:

  1. GOLDM26SEP157000PE was entered at 3750, PEAKED +6.7%, and exited three
     hours later at 3741 for -90. The only line the exit ladder ever wrote was
     the exit itself. Every rung's state was computed on every tick and thrown
     away, so nobody could reconstruct why a position up 6.7% ended at zero.

  2. 135 ERROR lines in thirteen minutes: "Subsystem 'market_data' has a stale
     heartbeat (age: 13471.1s > 195s)". Four hours of staleness — measured
     against a heartbeat written by the process that had DIED at 04:14.
     Heartbeats are persisted to disk and outlive the process that wrote them.

  3. 19,845 of the 26,875 lines — 74% — were the watchdog announcing "Overall
     Health Score: 100.0/100" every six seconds. The same score read 100.0/100
     while Hokage was dying and while his broker token was expired. It has never
     once been right, and it buried the day's 135 genuine errors.

  4. Two round trips opened and closed and the log carried NO evidence either
     was announced. `send_message` returned True silently and logged only on
     failure, so the single Telegram line all day was a DNS error at 16:11:58.
     The commander could not audit what Hokage had told him.

The common shape: a subsystem that cannot be questioned after the fact. Each fix
is about being able to answer "why did that happen?" tomorrow, and each is
constrained by the opposite failure — #3 is what happens when a component
narrates itself constantly, so none of these may become that.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot


# ============================================================ 1. exit ladder
class _Ladder:
    """Just enough bot to exercise _trace_ladder."""

    _OPTION_TRAIL_ARM_PCT = Bot._OPTION_TRAIL_ARM_PCT
    _LADDER_TRACE_PEAK_STEP = Bot._LADDER_TRACE_PEAK_STEP
    _trace_ladder = Bot._trace_ladder


def _trace(caplog, entry, current, peak, tracking):
    with caplog.at_level(logging.INFO, logger="Hokage.AutonomousTrading"):
        _Ladder._trace_ladder(_Ladder(), "GOLDM26SEP157000PE",
                              entry, current, peak, tracking)
    return [r.getMessage() for r in caplog.records]


def test_the_trail_arming_is_announced_once(caplog):
    """The moment that decided the GOLDM trade: the trail armed at +5%, which is
    what made a breakeven floor the binding rung."""
    tracking = {}
    lines = _trace(caplog, 3750.0, 4000.0, 4000.0, tracking)
    assert any("ARMED" in ln for ln in lines)

    caplog.clear()
    assert not _trace(caplog, 3750.0, 3990.0, 4000.0, tracking), (
        "arming must be reported on the transition, not on every tick"
    )


def test_a_ratcheting_floor_is_announced(caplog):
    tracking = {"_traced_armed": True, "_traced_peak": 4000.0, "stop_price": 3750.0}
    lines = _trace(caplog, 3750.0, 3900.0, 4000.0, tracking)
    assert any("RATCHETED" in ln for ln in lines)

    caplog.clear()
    assert not _trace(caplog, 3750.0, 3900.0, 4000.0, tracking), "same floor, no line"


def test_a_materially_new_peak_is_announced_but_a_tiny_one_is_not(caplog):
    tracking = {"_traced_armed": True, "_traced_peak": 4000.0}
    caplog.clear()
    assert not _trace(caplog, 3750.0, 4005.0, 4005.0, tracking), (
        "a 0.1% new high is not worth a line — that is how 74% of a log happens"
    )
    caplog.clear()
    assert any("new peak" in ln for ln in _trace(caplog, 3750.0, 4200.0, 4200.0, tracking))


def test_a_quiet_position_says_nothing_at_all(caplog):
    """The constraint that keeps this from becoming the watchdog."""
    tracking = {"_traced_armed": True, "_traced_peak": 4000.0, "_traced_floor": 3750.0,
                "stop_price": 3750.0}
    assert _trace(caplog, 3750.0, 3800.0, 4000.0, tracking) == []


def test_the_line_carries_what_is_needed_to_reconstruct_a_round_trip(caplog):
    lines = _trace(caplog, 3750.0, 3741.0, 4001.0,
                   {"stop_price": 3750.0, "target_price": 4300.0})
    joined = " ".join(lines)
    for token in ("peak", "floor", "target", "3741"):
        assert token in joined, token


def test_a_zero_entry_premium_cannot_divide_by_zero(caplog):
    assert _trace(caplog, 0.0, 10.0, 10.0, {}) == []


def test_the_ladder_calls_the_trace_before_returning_no_exit():
    """A trace nothing invokes is not observability."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(
        inspect.getsource(Bot._evaluate_option_exit_ladder)))
    assert any(getattr(n.func, "attr", None) == "_trace_ladder"
               for n in ast.walk(tree) if isinstance(n, ast.Call))


# ========================================================= 2 & 3. watchdog
@pytest.fixture
def watchdog(tmp_path):
    from hokage.memory.resolver import PathResolver
    from shared.watchdog.watchdog import Watchdog

    return Watchdog(PathResolver(str(tmp_path)))


def _write_pre_boot_heartbeat(watchdog, age_hours=4):
    """Exactly the 2026-08-27 boot state: the newest heartbeat on disk was
    written four hours ago by the process that died at 04:14."""
    from shared.watchdog.heartbeat import Heartbeat

    stamp = watchdog.process_started_at - timedelta(hours=age_hours)
    for sub in watchdog.REAL_HEARTBEAT_SUBSYSTEMS:
        watchdog.store.save_heartbeat(Heartbeat(
            subsystem=sub, timestamp=stamp, status="HEALTHY", uptime=100.0,
            last_successful_cycle=stamp, execution_latency=5.0,
            memory_usage=15.0, cpu_usage=1.0,
        ))


def test_a_dead_processes_heartbeat_no_longer_floods_the_boot(watchdog, caplog):
    """135 ERROR lines in thirteen minutes, every one of them reporting four
    hours of staleness that belonged to a process which no longer existed."""
    _write_pre_boot_heartbeat(watchdog)
    with caplog.at_level(logging.DEBUG, logger="Hokage.Watchdog.Engine"):
        watchdog.check_system_health()

    errors = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert not errors, errors
    assert not any("13471" in r.getMessage() or "stale heartbeat" in r.getMessage()
                   for r in caplog.records)


def test_after_the_grace_a_silent_subsystem_is_still_reported(watchdog, caplog):
    """The grace must not become a way to never notice. Past it, a subsystem
    that has published nothing in this run is named — as not-started, not as
    stale by four hours, because the latter is a claim about a dead process."""
    _write_pre_boot_heartbeat(watchdog)
    watchdog.process_started_at -= timedelta(seconds=watchdog.boot_grace_sec + 60)

    with caplog.at_level(logging.DEBUG, logger="Hokage.Watchdog.Engine"):
        score = watchdog.check_system_health()

    said = " ".join(r.getMessage() for r in caplog.records)
    assert "published nothing since this process started" in said
    assert score < 100.0, "a subsystem that never started must cost health"


def test_the_boot_grace_outlasts_a_pre_open_start(watchdog):
    """market_data publishes only on a SUCCESSFUL quote. Hokage boots before
    09:00 most mornings, so a grace shorter than the wait to first quote would
    fire the alarm every single day and teach the commander to ignore it."""
    assert watchdog.boot_grace_sec >= 600


def test_process_start_is_recorded_at_construction(watchdog):
    assert watchdog.process_started_at <= datetime.now(timezone.utc)


def test_the_check_compares_against_process_start_not_only_now():
    import inspect

    from shared.watchdog.watchdog import Watchdog

    src = inspect.getsource(Watchdog.check_system_health)
    assert "process_started_at" in src
    assert "boot_grace_sec" in src


def test_a_perfect_score_is_not_reannounced_every_cycle(watchdog, caplog):
    """19,845 identical lines in one day. The score is still computed and still
    returned; it is only WRITTEN when it moves."""
    import inspect

    src = inspect.getsource(watchdog.__class__.check_system_health)
    assert "_last_logged_health" in src
    assert "unchanged" in src


def test_an_unhealthy_score_is_always_logged_and_at_warning():
    import inspect

    from shared.watchdog.watchdog import Watchdog

    src = inspect.getsource(Watchdog.check_system_health)
    assert "health_score < 100.0" in src
    assert "logger.warning" in src, (
        "the not-perfect case is the one line that must survive being scrolled past"
    )


def test_the_score_is_still_returned_to_callers():
    """Quieting the log must not quieten the signal — callers and the dashboard
    still read this number every cycle."""
    import inspect

    from shared.watchdog.watchdog import Watchdog

    src = inspect.getsource(Watchdog.check_system_health)
    assert "return health_score" in src


# ============================================================ 4. telegram
def test_a_successful_send_is_recorded(caplog):
    from integrations.notifications.telegram_bot import TelegramBotUplink

    bot = object.__new__(TelegramBotUplink)
    with caplog.at_level(logging.INFO):
        TelegramBotUplink._audit(bot, "sent", "TRADE FILL ALERT NATURALGAS26SEP280CE")
    assert any("sent" in r.getMessage() for r in caplog.records)


def test_the_audit_truncates_and_never_dumps_a_whole_payload(caplog):
    from integrations.notifications.telegram_bot import TelegramBotUplink

    bot = object.__new__(TelegramBotUplink)
    with caplog.at_level(logging.INFO):
        TelegramBotUplink._audit(bot, "sent", "x" * 5000)
    message = caplog.records[-1].getMessage()
    assert len(message) < 300 and "..." in message


def test_every_send_outcome_is_audited():
    """Success, the plain-text fallback, and failure. A log that records only
    failures cannot answer 'did he tell me?'.

    Checks the whole send path, not one method. The raw POST was split out of
    send_message on 2026-10-13 so the deferred-alert queue could retry without
    recursing, and this assertion used to read send_message alone - it passed
    for the wrong reason before the split and failed for the wrong reason
    after it. What matters is that no OUTCOME goes unrecorded, wherever the
    sending lives.
    """
    import ast
    import inspect
    import textwrap

    from integrations.notifications.telegram_bot import TelegramBotUplink

    outcomes = set()
    total = 0
    for name in ("send_message", "_post", "_flush_deferred"):
        method = getattr(TelegramBotUplink, name, None)
        if method is None:
            continue
        tree = ast.parse(textwrap.dedent(inspect.getsource(method)))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "attr", None) == "_audit"):
                continue
            total += 1
            if node.args and isinstance(node.args[0], ast.Constant):
                outcomes.add(node.args[0].value)

    assert total >= 3, f"only {total} audited outcomes across the send path"
    assert "sent" in outcomes, "a successful send is not recorded"
    assert "NOT SENT" in outcomes, "a failed send is not recorded"


def test_the_audit_never_touches_the_token():
    import inspect

    from integrations.notifications.telegram_bot import TelegramBotUplink

    src = inspect.getsource(TelegramBotUplink._audit)
    assert "bot_token" not in src and "url" not in src


# ================================================== 5. log file encoding
@pytest.mark.parametrize("script", ["Watch-Hokage.ps1", "Sync-Candles.ps1"])
def test_the_task_scripts_write_utf8_logs(script):
    """Windows PowerShell 5.1's Tee-Object has no -Encoding switch and writes
    UTF-16LE, which produced a liveness.log that grep could not read. Same
    class of fault as the BOM that broke the profile JSON readers."""
    from pathlib import Path

    root = Path(__file__).resolve()
    root = next(p for p in root.parents if (p / "pyproject.toml").is_file())
    text = (root / script).read_text(encoding="utf-8")

    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue                      # a comment may name the old cmdlet
        assert "Tee-Object" not in stripped, f"{script}: {stripped}"
    assert "-Encoding utf8" in text
