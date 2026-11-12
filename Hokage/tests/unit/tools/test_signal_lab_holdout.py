"""Hold-out mode exists so the bench cannot fool itself twice over.

signal_lab's pooled `main()` verdicts at t >= 2 on a single window. Two things
are missing from that, and each has already fooled this project once:

  1. NO HOLD-OUT. `holdout_lab`'s own docstring records session_lab finding
     SessionShift +3.52 and TrendRider +2.43 on NATURALGAS, and the split
     "destroyed all of it, with the signs flipping".
  2. NO CORRECTION FOR THE SEARCH. Of 116,360 hypotheses measured on this
     tape, 2,808 cleared t >= 2 on both halves and not one cleared the bar
     corrected for having looked in 116,360 places.

Run live on GOLDM the day this was added, `persist+ema_noVWAP` went from
+3.21 on train to -0.34 on hold-out at the 60-minute horizon - the sign
flipped, exactly as predicted. These tests pin the machinery that reports
that rather than hiding it.
"""
from __future__ import annotations


import pathlib
import sys

import pytest


def _repo_root() -> pathlib.Path:
    return next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())


SRC = _repo_root() / "tools" / "research" / "signal_lab.py"

# IMPORT IT, DO NOT REPLACE IT. A fresh spec_from_file_location under the name
# "signal_lab" evicts the shared module, and `test_sweep_bar_is_corrected`
# asserts `sweep_lab.corrected_t is signal_lab.corrected_t` - an identity that
# a second module object silently breaks. Two tests failed only when run
# together with this file, which is the worst kind of failure to diagnose.
_RESEARCH = str(_repo_root() / "tools" / "research")
if _RESEARCH not in sys.path:
    sys.path.insert(0, _RESEARCH)

import signal_lab as SL  # noqa: E402


# ============================================================ the statistic
def test_t_of_reports_n_mean_and_t():
    result = {"n": 4, "hits": 3, "edges": [1.0, 1.0, 1.0, 1.0]}
    n, mean, t = SL._t_of(result)
    assert n == 4
    assert mean == pytest.approx(1.0)
    assert t > 100, "zero variance is a huge t, not a crash"


def test_t_of_survives_an_empty_bucket():
    n, mean, t = SL._t_of({"n": 0, "hits": 0, "edges": []})
    assert (n, mean, t) == (0, 0.0, 0.0)


# ====================================================== the corrected bar
def test_the_bar_rises_with_the_number_of_places_looked():
    """A wider search must earn a higher bar, or the search is free."""
    assert SL.corrected_t(1) == SL.BASE_SHIP_T
    assert SL.corrected_t(27) > SL.corrected_t(9) > SL.corrected_t(1)
    assert SL.corrected_t(27) == pytest.approx(3.11, abs=0.02)


def test_the_bar_never_drops_below_the_base():
    assert SL.corrected_t(0) >= SL.BASE_SHIP_T
    assert SL.corrected_t(1) >= SL.BASE_SHIP_T


# ====================================================== the verdicts
def _fake(monkeypatch, train_t: float, hold_t: float, n: int = 300):
    """Drive holdout_report with synthetic buckets, no database.

    `edges` are built so the t comes out where the test wants it: n copies of
    a mean with a spread chosen to hit the target t.
    """
    import math

    def bucket(target_t: float):
        # t = mean / (sd/sqrt(n)) -> pick sd = 1, mean = t/sqrt(n)
        mean = target_t / math.sqrt(n)
        half = n // 2
        return {"n": n, "hits": half,
                "edges": [mean + 1.0] * half + [mean - 1.0] * (n - half)}

    monkeypatch.setattr(SL, "halves", lambda s: (("2026-01-01 09:15:00",
                                                  "2026-06-01 15:30:00"),
                                                 ("2026-06-01 09:15:00",
                                                  "2026-11-01 15:30:00")))
    monkeypatch.setattr(SL, "load_bars", lambda s, a, b: ["train" if "01-01" in a else "hold"])
    monkeypatch.setattr(SL, "HORIZONS", (4,))

    def evaluate(bars, horizon):
        t = train_t if bars == ["train"] else hold_t
        return {name: bucket(t) for name in SL.CANDIDATES}

    monkeypatch.setattr(SL, "evaluate", evaluate)


def test_a_sign_flip_on_the_holdout_is_negative(monkeypatch, capsys):
    """THE FAILURE THIS MODE EXISTS TO CATCH. Strong on train, negative mean
    on hold-out - what noise looks like after a search."""
    _fake(monkeypatch, train_t=+4.0, hold_t=-1.6)
    SL.holdout_report(["GOLDM"])
    out = capsys.readouterr().out
    assert "NEGATIVE" in out
    assert "CONFIRMED" not in out.split("verdict")[-1].split("NOTHING")[0]


def test_train_only_is_fragile_not_confirmed(monkeypatch, capsys):
    _fake(monkeypatch, train_t=+4.0, hold_t=+1.0)
    SL.holdout_report(["GOLDM"])
    out = capsys.readouterr().out
    assert "FRAGILE" in out
    assert "NOTHING CONFIRMED" in out


def test_failing_both_halves_is_weak(monkeypatch, capsys):
    _fake(monkeypatch, train_t=+0.5, hold_t=+0.4)
    SL.holdout_report(["GOLDM"])
    out = capsys.readouterr().out
    assert "WEAK" in out
    assert "NOTHING CONFIRMED" in out


def test_clearing_the_corrected_bar_on_both_halves_confirms(monkeypatch, capsys):
    """The mode must be capable of a positive verdict, or it is just a
    rejection stamp and proves nothing when it rejects."""
    _fake(monkeypatch, train_t=+5.0, hold_t=+5.0)
    SL.holdout_report(["GOLDM"])
    out = capsys.readouterr().out
    assert "CONFIRMED" in out
    assert "NOTHING CONFIRMED" not in out


def test_a_thin_sample_is_not_judged(monkeypatch, capsys):
    _fake(monkeypatch, train_t=+5.0, hold_t=+5.0, n=10)
    SL.holdout_report(["GOLDM"], min_n=30)
    out = capsys.readouterr().out
    assert "too few to judge" in out
    assert "NOTHING CONFIRMED" in out


def test_the_header_states_the_family_and_both_bars(monkeypatch, capsys):
    """A corrected bar nobody can see is a corrected bar nobody checks."""
    _fake(monkeypatch, train_t=+1.0, hold_t=+1.0)
    SL.holdout_report(["GOLDM"])
    out = capsys.readouterr().out
    assert "places looked" in out
    assert "uncorrected would be" in out


def test_a_null_result_is_reported_as_a_result(monkeypatch, capsys):
    """Silence after a wide search reads as 'nothing to say'. It is a
    finding, and the whole point of having a bar."""
    _fake(monkeypatch, train_t=+0.2, hold_t=+0.1)
    SL.holdout_report(["GOLDM"])
    out = capsys.readouterr().out
    assert "NOTHING CONFIRMED" in out
    assert "expected outcome of a search this wide" in out


def test_an_unloadable_symbol_does_not_abort_the_run(monkeypatch, capsys):
    monkeypatch.setattr(SL, "halves",
                        lambda s: (_ for _ in ()).throw(RuntimeError("no tape")))
    SL.holdout_report(["GOLDM"])
    out = capsys.readouterr().out
    assert "could not load halves" in out


# ============================================= the pooled mode is untouched
def test_pooled_main_still_exists_and_is_separate():
    """Hold-out mode is an addition. The pooled view is what the weekly audit
    and several other tools were built against."""
    import inspect

    source = inspect.getsource(SL.main)
    assert "--holdout" in source
    assert "holdout_report" in source
    assert "2026-05-01" in source, "the pooled window is still there"
