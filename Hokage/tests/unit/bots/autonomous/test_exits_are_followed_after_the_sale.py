"""Recording an exit and watching the contract afterwards.

Commander-approved 2026-11-12. Phases 1 and 2 of the post-exit roadmap: write
down what we sold, then keep quoting that exact contract while the window is
open. `post_exit_lab` judges; this is the plumbing that gives it something to
judge.

THREE WAYS THE PLUMBING COULD DO HARM, each tested:

  1. BREAKING AN EXIT. The recording sits in the exit path, immediately after
     the fill is booked. A measurement that can raise there is a measurement
     that can leave a position open - the 2026-07-15 shape, where a discarded
     exit response produced 207 phantoms.
  2. DOUBLE-COUNTING. The exit path can be reached twice for one position (a
     partial fill, then the remainder). A second row would count that exit
     twice in every aggregate.
  3. QUOTING THE WRONG CONTRACT. A post-exit quote needs
     EXCHANGE:TRADINGSYMBOL, and MCX options are not on NFO. Getting it wrong
     silently records nothing, which reads as "the exit was fine".
"""
from __future__ import annotations

import datetime as dt
import inspect
import textwrap
from types import SimpleNamespace

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A real exit_followup store, pointed at a throwaway brain."""
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path))
    import importlib

    from hokage.memory import exit_followup as ef
    importlib.reload(ef)
    return ef


# ===================================================== Phase 1: recording
def test_an_exit_is_written_down_with_its_target_and_floor(store):
    """The whole point: the target it abandoned and the stop it avoided,
    taken from the LIVE tracking dict, which is the only record of what this
    position was aiming at."""
    bot = object.__new__(Bot)
    bot._active_positions_tracking = {
        "GOLDM26NOV138500PE": {"target_price": 3149.42, "stop_price": 2669.0,
                               "_traced_peak": 2808.0,
                               "strategy_id": "strat-sessionshift-mcx-v1"}}
    pos = SimpleNamespace(position_id="pos-1", quantity=10.0,
                          average_price=2669.0)

    bot._remember_exit_for_followup(
        symbol="GOLDM26NOV138500PE", pos=pos, fill_price=2608.0,
        exit_reason="TRAIL_LOCK: breakeven floor held", live_pnl=-610.0,
        charges=87.13)

    rows = store.followups()
    assert len(rows) == 1
    row = rows[0]
    assert row["contract"] == "GOLDM26NOV138500PE"
    assert row["exit_price"] == pytest.approx(2608.0)
    assert row["target_price"] == pytest.approx(3149.42)
    assert row["stop_price"] == pytest.approx(2669.0)
    assert row["peak_price"] == pytest.approx(2808.0)
    assert row["gross_pnl"] == pytest.approx(-610.0)
    assert row["charges"] == pytest.approx(87.13)


def test_the_exchange_is_resolved_so_the_quote_key_works(store):
    """GUARD 3. MCX options are not on NFO. The archiver already maps every
    underlying to its segment, so that map is the single source."""
    bot = object.__new__(Bot)
    bot._active_positions_tracking = {}
    pos = SimpleNamespace(position_id="pos-2", quantity=10.0,
                          average_price=100.0)
    bot._remember_exit_for_followup(
        symbol="GOLDM26NOV138500PE", pos=pos, fill_price=99.0,
        exit_reason="x", live_pnl=-1.0, charges=None)
    row = store.followups()[0]
    assert row["underlying"] == "GOLDM"
    assert row["exchange"] == "MCX", "an MCX quote key must not say NFO"


def test_the_same_exit_recorded_twice_stores_one_row(store):
    """GUARD 2. A partial fill then the remainder reaches this path twice."""
    bot = object.__new__(Bot)
    bot._active_positions_tracking = {}
    pos = SimpleNamespace(position_id="pos-3", quantity=10.0,
                          average_price=100.0)
    for _ in range(3):
        bot._remember_exit_for_followup(
            symbol="GOLDM26NOV1PE", pos=pos, fill_price=99.0,
            exit_reason="x", live_pnl=-1.0, charges=None)
    assert len(store.followups()) == 1


@pytest.mark.parametrize("broken", ["tracking", "pos"])
def test_a_recording_fault_cannot_break_the_exit(store, broken):
    """GUARD 1. This runs inside the exit path, right after the fill is
    booked. A raise here is a position left open."""
    bot = object.__new__(Bot)
    if broken == "tracking":
        bot._active_positions_tracking = "not a dict"
        pos = SimpleNamespace(position_id="p", quantity=1.0, average_price=1.0)
    else:
        bot._active_positions_tracking = {}
        pos = None
    bot._remember_exit_for_followup(            # must not raise
        symbol="GOLDM26NOV1PE", pos=pos, fill_price=1.0,
        exit_reason="x", live_pnl=0.0, charges=None)


def test_the_recorder_is_called_from_the_exit_path_after_the_fill():
    """Recorded where the FILL price and the ladder's target are both in
    scope. Anywhere later would read a different number than the exit was
    judged against."""
    import pathlib

    root = next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    src = (root / "src" / "bots" / "autonomous"
           / "autonomous_bot.py").read_text(encoding="utf-8")
    assert "_remember_exit_for_followup(" in src
    before, after = src.split("_remember_exit_for_followup(\n", 1)
    # it must come after the fill price is established, not before
    assert "fill_price = float(getattr(resp" in before


# ================================================== Phase 2: the watching
def test_only_contracts_inside_their_window_are_watched(store):
    now = dt.datetime(2026, 11, 12, 18, 0, tzinfo=dt.timezone.utc)
    store.remember_exit(
        position_id="open-one", contract="A", underlying="GOLDM",
        exchange="MCX", strategy_id=None, quantity=1, entry_price=1,
        exit_price=1, exit_reason="x", target_price=None, stop_price=None,
        peak_price=None, gross_pnl=None, charges=None,
        exited_at=now, follow_minutes=120)
    store.remember_exit(
        position_id="expired-one", contract="B", underlying="GOLDM",
        exchange="MCX", strategy_id=None, quantity=1, entry_price=1,
        exit_price=1, exit_reason="x", target_price=None, stop_price=None,
        peak_price=None, gross_pnl=None, charges=None,
        exited_at=now - dt.timedelta(hours=5), follow_minutes=120)

    watching = store.watchlist(now + dt.timedelta(minutes=30))
    assert [w["position_id"] for w in watching] == ["open-one"]


def test_the_watch_quotes_everything_in_one_call(store):
    """A call per contract would multiply broker traffic for no resolution."""
    now = dt.datetime(2026, 11, 12, 18, 0, tzinfo=dt.timezone.utc)
    for pid, contract in (("p1", "GOLDM26NOV1PE"), ("p2", "NATURALGAS26NOV2CE")):
        store.remember_exit(
            position_id=pid, contract=contract, underlying="GOLDM",
            exchange="MCX", strategy_id=None, quantity=1, entry_price=1,
            exit_price=100.0, exit_reason="x", target_price=None,
            stop_price=None, peak_price=None, gross_pnl=None, charges=None,
            exited_at=now)

    calls = []

    class _Kite:
        def quote(self, keys):
            calls.append(list(keys))
            return {k: {"last_price": 110.0,
                        "depth": {"buy": [{"price": 109.0}],
                                  "sell": [{"price": 111.0}]}} for k in keys}

    bot = object.__new__(Bot)
    bot._observe_exited_contracts(_Kite(), now + dt.timedelta(minutes=15))

    assert len(calls) == 1, "one quote call for the whole watchlist"
    assert sorted(calls[0]) == ["MCX:GOLDM26NOV1PE", "MCX:NATURALGAS26NOV2CE"]
    marks = {r["position_id"]: r["observations"] for r in store.followups()}
    assert len(marks["p1"]) == 1
    assert marks["p1"][0]["last_price"] == pytest.approx(110.0)
    assert marks["p1"][0]["bid"] == pytest.approx(109.0)


def test_a_broken_quote_does_not_raise(store):
    class _Kite:
        def quote(self, keys):
            raise RuntimeError("broker timed out")

    now = dt.datetime(2026, 11, 12, 18, 0, tzinfo=dt.timezone.utc)
    store.remember_exit(
        position_id="p1", contract="X", underlying="GOLDM", exchange="MCX",
        strategy_id=None, quantity=1, entry_price=1, exit_price=1,
        exit_reason="x", target_price=None, stop_price=None, peak_price=None,
        gross_pnl=None, charges=None, exited_at=now)
    bot = object.__new__(Bot)
    bot._observe_exited_contracts(_Kite(), now)      # must not raise


def test_an_empty_watchlist_makes_no_broker_call(store):
    calls = []

    class _Kite:
        def quote(self, keys):
            calls.append(keys)
            return {}

    bot = object.__new__(Bot)
    bot._observe_exited_contracts(_Kite(), dt.datetime.now(dt.timezone.utc))
    assert calls == []


def test_the_capture_loop_calls_the_watch():
    src = textwrap.dedent(inspect.getsource(Bot._run_option_chain_capture))
    assert "_observe_exited_contracts(" in src


# ========================================= coverage is reported honestly
def test_coverage_separates_watched_from_unwatched(store):
    now = dt.datetime(2026, 11, 12, 18, 0, tzinfo=dt.timezone.utc)
    for pid in ("seen", "unseen"):
        store.remember_exit(
            position_id=pid, contract=pid, underlying="GOLDM",
            exchange="MCX", strategy_id=None, quantity=1, entry_price=1,
            exit_price=100.0, exit_reason="x", target_price=None,
            stop_price=None, peak_price=None, gross_pnl=None, charges=None,
            exited_at=now)
    store.observe("seen", 101.0, when=now)

    cover = store.coverage()
    assert cover["exits"] == 2
    assert cover["with_observations"] == 1
    assert cover["without_observations"] == 1


def test_a_mark_without_a_price_is_not_stored(store):
    """None is not a price. Storing it would read as a trade at zero."""
    now = dt.datetime(2026, 11, 12, 18, 0, tzinfo=dt.timezone.utc)
    store.remember_exit(
        position_id="p", contract="X", underlying="GOLDM", exchange="MCX",
        strategy_id=None, quantity=1, entry_price=1, exit_price=1,
        exit_reason="x", target_price=None, stop_price=None, peak_price=None,
        gross_pnl=None, charges=None, exited_at=now)
    assert store.observe("p", None, when=now) is False
    assert store.coverage()["marks"] == 0


def test_the_store_lives_beside_the_other_corpora_not_in_hokage_db(store):
    """hokage.db reached 1.5 GB on telemetry once already."""
    assert store.db_path().name == "candles.db"
