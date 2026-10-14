"""sweep_lab writes PENDING proposals, and it was writing them at a flat t>=2.0.

This lab is a SEARCH: every live (module, asset) pair, times every tunable
knob, times every candidate value, each judged on two halves. Judging the best
of that at the bar for a single pre-specified test is the multiple-comparisons
mistake, and hypothesis_lab measured its size on Hokage's own tape - of
116,360 candidates, 2,808 cleared t>=2.0 on BOTH halves and none cleared the
corrected bar.

THE CONSEQUENCE HERE IS WORSE THAN IN THE AUDIT, because this lab does not
merely report. It writes a proposal addressed to the commander, with a
t-statistic attached, recommending a parameter change. An uncorrected bar
means it can recommend an action on the strength of noise. The audit
over-reporting edge misleads; a proposal invites a decision.

Raised 2026-10-14 on the commander's decision, the same day as the audit's.
Each lab is priced for its OWN search - the audit's 32 cells give t>=3.16, this
sweep's 26 candidate values give t>=3.09 - because the bar is a function of how
much was looked at, not a global constant.
"""
from __future__ import annotations

import importlib
import pathlib
import sys

import pytest

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents
            if (p / "pyproject.toml").is_file())
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

import signal_lab  # noqa: E402

signal_lab._fetch_from_kite = lambda *a, **k: []

import sweep_lab as sl  # noqa: E402

SRC = ROOT / "tools" / "research" / "sweep_lab.py"


# ------------------------------------------------------- the bar is corrected
def test_the_bar_is_corrected_for_the_grid(monkeypatch):
    from signal_lab import corrected_t

    monkeypatch.setattr(sl, "_SHIP_BAR_CACHE", [])
    monkeypatch.setattr(sl, "_family_size", lambda: 26)
    assert sl.ship_bar() == round(corrected_t(26), 2)


def test_a_real_grid_clears_more_than_a_single_test(monkeypatch):
    """Priced against a live lineup the bar must exceed the floor. Asserted
    against a stated family size rather than the machine's own portfolios,
    which the hermetic suite deliberately does not provide."""
    from signal_lab import BASE_SHIP_T

    monkeypatch.setattr(sl, "_SHIP_BAR_CACHE", [])
    monkeypatch.setattr(sl, "_family_size", lambda: 26)
    assert sl.ship_bar() > BASE_SHIP_T
    assert sl.ship_bar() == pytest.approx(3.09, abs=0.02)


def test_no_flat_bar_remains_in_the_source():
    src = SRC.read_text(encoding="utf-8")
    assert "SHIP_BAR = 2.0" not in src
    assert "SHIP_BAR = 3.09" not in src, "the bar must be derived, not typed"


def test_the_bar_is_shared_with_the_audit_as_a_FUNCTION_not_a_number():
    """Two labs searching different amounts correctly have different bars.
    What must be shared is the function and the floor."""
    import weekly_audit as wa

    assert sl.corrected_t is signal_lab.corrected_t
    assert wa.SHIP_BAR == round(signal_lab.corrected_t(wa.FAMILY_SIZE), 2)
    # 26 candidate values against the audit's 32 cells: different searches,
    # correctly different bars.
    assert round(signal_lab.corrected_t(26), 2) != wa.SHIP_BAR


# --------------------------------------------- the family counts the right things
def test_the_incumbent_is_not_counted_as_a_candidate():
    """It is the baseline every candidate is compared AGAINST, not one of the
    things being tried. Counting it would inflate the correction."""
    src = SRC.read_text(encoding="utf-8")
    body = src[src.index("def _family_size("):src.index("def ship_bar(")]
    assert "len(grid) - 1" in body


def test_an_empty_grid_warns_instead_of_silently_weakening_the_bar(monkeypatch, capsys):
    """THE BUG THIS CAUGHT. live_pairs() returns NOTHING - no exception - when
    there is no portfolio to read, which is true in any hermetic environment
    and would be true of a misconfigured one. The first version counted that
    as a family of zero, corrected_t(0) returned the floor, and the bar
    collapsed to an uncorrected 2.0 with no warning: exactly the silent
    weakening this correction exists to prevent."""
    from signal_lab import BASE_SHIP_T

    monkeypatch.setattr(sl, "_SHIP_BAR_CACHE", [])
    monkeypatch.setattr(sl, "_family_size", lambda: 0)
    bar = sl.ship_bar()
    out = capsys.readouterr().out
    assert bar == BASE_SHIP_T
    assert "WARNING" in out and "UNCORRECTED" in out


# ------------------------------------------------- survives() asks, never assumes
def test_survives_uses_the_corrected_bar():
    """A candidate at t just over 2.0 on both halves used to become a
    proposal. It must now be refused."""
    bar = sl.ship_bar()
    n = sl.MIN_N + 10
    cand_tr = (n, 0.50, bar - 0.5)
    cand_ho = (n, 0.50, bar - 0.5)
    inc = (n, 0.10, 1.0)
    ok, why = sl.survives(cand_tr, cand_ho, inc, inc)
    assert ok is False
    assert "below the ship bar" in why


def test_the_refusal_names_the_bar_it_was_judged_against():
    """A reader comparing two runs needs to see which bar refused it."""
    bar = sl.ship_bar()
    n = sl.MIN_N + 10
    _, why = sl.survives((n, 0.5, bar - 0.5), (n, 0.5, bar - 0.5),
                         (n, 0.1, 1.0), (n, 0.1, 1.0))
    assert f"{bar:.2f}" in why


def test_a_candidate_clearing_the_corrected_bar_still_survives():
    """The correction must not make the lab incapable of ever proposing."""
    bar = sl.ship_bar()
    n = sl.MIN_N + 10
    ok, why = sl.survives((n, 0.80, bar + 1.0), (n, 0.80, bar + 1.0),
                          (n, 0.10, 1.0), (n, 0.10, 1.0))
    assert ok is True, why


# ------------------------- importing must not depend on reading the portfolios
def test_the_bar_is_not_computed_at_import():
    """weekly_audit, iv_lab and event_lab all import realised() from this
    module. Sizing the grid at import means an unreadable portfolio file takes
    all three down with it - a far worse failure than a sweep that cannot
    price its own grid."""
    for name in ("sweep_lab",):
        sys.modules.pop(name, None)
    fresh = importlib.import_module("sweep_lab")
    assert fresh._SHIP_BAR_CACHE == [], (
        "the bar was evaluated at import time"
    )


def test_a_grid_it_cannot_size_falls_back_loudly(monkeypatch, capsys):
    """A silent fallback is the worst outcome available: proposals written
    against a weaker bar than the run claims."""
    from signal_lab import BASE_SHIP_T

    monkeypatch.setattr(sl, "_SHIP_BAR_CACHE", [])
    monkeypatch.setattr(sl, "_family_size",
                        lambda: (_ for _ in ()).throw(RuntimeError("no portfolio")))
    bar = sl.ship_bar()
    out = capsys.readouterr().out
    assert bar == BASE_SHIP_T
    assert "WARNING" in out
    assert "UNCORRECTED" in out


def test_the_bar_is_cached():
    """survives() is called once per candidate; re-sizing the grid each time
    would re-read every portfolio for every row printed."""
    monkeypatch_free = sl.ship_bar()
    assert sl.ship_bar() is sl._SHIP_BAR_CACHE[0]
    assert monkeypatch_free == sl._SHIP_BAR_CACHE[0]
