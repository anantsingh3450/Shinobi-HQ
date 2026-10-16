"""The modules did not go quiet. The lineup went from 56 cells to 7.

The last position Hokage opened was 2026-09-22. Two explanations fit that
from the outside and they call for opposite responses: either the surviving
modules stopped firing, which is a regression, or the tradeable grid shrank,
which is the consequence of five commander-approved archivals and two
parkings. The gate tally cannot tell them apart - a module that stops firing
produces FEWER tallied refusals, not more, so starvation by regression looks
exactly like a quiet market.

Measured over the archive, signals per 100 eligible contexts:

                       26-06  26-07  26-08  26-09  26-10
    MacroBreakout/NIFTY  6.90   2.39   2.62   5.48   9.00
    MeanReversion/NIFTY  8.57   3.04   1.19   3.57   4.50
    SessionShift/SILVERM 5.56   7.63   4.59   5.82   8.49

October is at or near the top of the range for six of the seven live cells.
The modules are speaking.

THE FIRST RUN OF THIS LAB WAS WRONG, and the way it was wrong is the reason
this test file exists. It hand-rolled its eligibility rules instead of calling
signal_lab.measurable, and reported "-" for every month of NIFTY, BANKNIFTY
and SENSEX. The archive stores an index's volume as 0 rather than NULL -
an index is a calculation and nothing trades it - so a flat "the entry bar
must have traded" check deletes three of the seven live cells in silence.
signal_lab.measurable already carried the fix for exactly this, found on an
earlier day when it cost sweep_lab, stop_lab and hypothesis_lab their whole
index universe. A copy of a rule is a rule that has not been fixed yet.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import pathlib
import sys

import pytest

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents
            if (p / "pyproject.toml").is_file())
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

_spec = importlib.util.spec_from_file_location(
    "signal_rate_lab", ROOT / "tools" / "research" / "signal_rate_lab.py"
)
srl = importlib.util.module_from_spec(_spec)
sys.modules["signal_rate_lab"] = srl
_spec.loader.exec_module(srl)


def _bars(days: int, start: dt.date, volume, per_day: int = 30) -> list[dict]:
    """A plausible intraday series: one session a day, trending gently."""
    out = []
    price = 100.0
    for d in range(days):
        day = start + dt.timedelta(days=d)
        when = dt.datetime(day.year, day.month, day.day, 9, 15)
        for b in range(per_day):
            price *= 1.001 if (b + d) % 3 else 0.999
            out.append({"date": when + dt.timedelta(minutes=15 * b),
                        "open": price, "high": price * 1.002,
                        "low": price * 0.998, "close": price,
                        "volume": volume})
    return out


class _AlwaysFires:
    module_id = "always"

    @staticmethod
    def evaluate(_ctx):
        return type("S", (), {"should_enter": True, "direction": "long"})()


class _NeverFires:
    module_id = "never"

    @staticmethod
    def evaluate(_ctx):
        return type("S", (), {"should_enter": False, "direction": "long"})()


class _Raises:
    module_id = "boom"

    @staticmethod
    def evaluate(_ctx):
        raise RuntimeError("module blew up")


# ---------------------------------------------- an index is not an idle future
def test_a_zero_volume_index_is_still_measured(monkeypatch):
    """THE BUG THIS LAB SHIPPED WITH. All 4,125 archived bars of NIFTY,
    BANKNIFTY and SENSEX carry volume=0, and a flat traded-bar check reads
    that as "nothing ever traded, skip everything"."""
    monkeypatch.setattr(srl, "archive_load",
                        lambda *_a, **_k: _bars(40, dt.date(2026, 6, 1), 0))
    out = srl.count_by_month("NIFTY", _AlwaysFires)
    assert out, "an index must not vanish from the measurement"
    assert sum(e for e, _ in out.values()) > 0


def test_eligibility_is_not_reimplemented():
    """A copy of signal_lab's rules is a copy that will not get the next fix.
    Checked on the source because the point is that no second copy exists."""
    src = (ROOT / "tools" / "research" / "signal_rate_lab.py").read_text(
        encoding="utf-8")
    assert "measurable(ctx, bars[i])" in src
    assert "REQUIRE_TRADED_BAR" not in src, (
        "the flat traded-bar flag is what deleted the index universe"
    )


def test_a_quiet_future_bar_is_still_skipped(monkeypatch):
    """The original guard must survive: on a series that DOES carry volume, a
    zero-volume bar is one of the repeated prints Kite emits when a contract
    is not trading, and an entry on it is fiction."""
    bars = _bars(40, dt.date(2026, 6, 1), 10.0)
    for b in bars[-50:]:
        b["volume"] = 0.0
    monkeypatch.setattr(srl, "archive_load", lambda *_a, **_k: bars)
    out = srl.count_by_month("GOLDM", _AlwaysFires)
    eligible = sum(e for e, _ in out.values())
    assert eligible > 0
    assert eligible < len(bars) - srl.WARMUP, "quiet bars must still be skipped"


# ------------------------------------------------------------ counting itself
def test_a_module_that_never_fires_rates_zero_not_missing(monkeypatch):
    """Zero and missing are different facts, and this lab's whole job is
    telling them apart."""
    monkeypatch.setattr(srl, "archive_load",
                        lambda *_a, **_k: _bars(40, dt.date(2026, 6, 1), 10.0))
    out = srl.count_by_month("GOLDM", _NeverFires)
    assert out, "eligible contexts existed, so the month is present"
    assert all(fired == 0 for _, fired in out.values())


def test_a_month_with_no_bars_is_absent_rather_than_zero(monkeypatch):
    monkeypatch.setattr(srl, "archive_load",
                        lambda *_a, **_k: _bars(20, dt.date(2026, 6, 1), 10.0))
    out = srl.count_by_month("GOLDM", _AlwaysFires)
    assert "2026-06" in out
    assert "2026-07" not in out, (
        "a month nobody asked about must not print as a silent module"
    )


def test_a_crashing_module_still_counts_the_context_as_asked(monkeypatch):
    """A module that raises is not a module that declined. Dropping the
    context from the denominator too would hide a crash as a steady rate."""
    monkeypatch.setattr(srl, "archive_load",
                        lambda *_a, **_k: _bars(40, dt.date(2026, 6, 1), 10.0))
    out = srl.count_by_month("GOLDM", _Raises)
    assert sum(e for e, _ in out.values()) > 0
    assert sum(f for _, f in out.values()) == 0


def test_an_empty_archive_does_not_invent_a_rate(monkeypatch):
    monkeypatch.setattr(srl, "archive_load", lambda *_a, **_k: [])
    assert srl.count_by_month("GOLDM", _AlwaysFires) == {}


def test_warmup_and_session_floors_match_the_other_labs():
    assert srl.WARMUP == 42, "EMA21 over 42 bars is the longest window used"
    assert srl.MIN_SESSION_BARS == 6


# -------------------------------------------------------- it refuses to oversell
def test_it_states_that_the_count_is_an_upper_bound():
    """Production asks once per scan cycle for in-scope, unparked assets
    inside their window; this asks on every eligible bar, with no regime and
    no VIX in the context. Reading the level as "entries production should
    have taken" is the mistake this paragraph exists to prevent."""
    doc = srl.__doc__ or ""
    assert "UPPER BOUND" in doc
    assert "regime" in doc and "vix_percentile" in doc


def test_it_says_no_edge_is_measured():
    doc = (srl.__doc__ or "").lower()
    assert "no edge is measured here" in doc
    assert "a high rate is not good news" in doc
