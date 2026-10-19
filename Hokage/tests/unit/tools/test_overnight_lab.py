"""The most replicated return pattern in the literature is not in this tape.

2026-10-19: asked for a new strategy, and the request is well-founded — the
improvement loop has SELECTION (sweep_lab prunes and tunes) and no VARIATION.
Nothing in Hokage has ever proposed a new module.

The one strategy family with real published evidence that is also testable on
the data here is the overnight/intraday decomposition. Cliff, Cooper and Gulen
(2008) and Lou, Polk and Skouras document, on US equities and index futures,
that close-to-open returns are strongly positive while open-to-close returns
are near zero or negative. A search on 2026-10-19 found NO peer-reviewed study
of the Indian index — only blogs and practitioner notes with undocumented
methods and unverified samples.

Measured on the archive, 166 sessions, train/hold split, bar t>=2.63
corrected for six tests:

    NIFTY      overnight   train -0.090% t-0.91 | hold +0.017% t+0.40
    BANKNIFTY  overnight   train -0.158% t-1.37 | hold -0.031% t-0.67
    SENSEX     overnight   train -0.071% t-0.65 | hold +0.081% t+1.86

Nothing. Up-rates of 44-55% are a coin flip, and BANKNIFTY leans the OPPOSITE
way to the US finding — overnight negative, intraday positive. Eight months of
2026 is not a refutation of the literature, which runs on decades; it is a
refutation of the claim ON THE TAPE HOKAGE TRADES, which is the only one that
can take his money.

THE TESTS BELOW ARE ABOUT THE MEASUREMENT, NOT THE ANSWER. If a later sample
makes this pattern appear, these still have to hold: the legs must not be
computed across the session boundary the wrong way round, the bar must stay
corrected for the whole search, and the file must keep saying out loud that it
measures the UNDERLYING and not an option — a night of theta and any overnight
IV move are unmodelled and both work against a buyer.
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
    "overnight_lab", ROOT / "tools" / "research" / "overnight_lab.py"
)
ol = importlib.util.module_from_spec(_spec)
sys.modules["overnight_lab"] = ol
_spec.loader.exec_module(ol)


def _bar(day: dt.date, minute: int, o, c):
    return {"date": dt.datetime(day.year, day.month, day.day, 9, 15)
            + dt.timedelta(minutes=minute),
            "open": o, "high": max(o, c), "low": min(o, c), "close": c,
            "volume": 0}


# ------------------------------------------------- the legs are the right legs
def test_a_session_is_its_first_open_and_its_last_close():
    day = dt.date(2026, 6, 1)
    rows = ol.sessions([_bar(day, 0, 100.0, 101.0),
                        _bar(day, 15, 101.0, 102.0),
                        _bar(day, 30, 102.0, 103.0)])
    assert rows == [(day, 100.0, 103.0)]


def test_overnight_pairs_a_close_with_the_NEXT_open():
    """The direction of this pairing is the whole measurement. Reversed, it
    would compute the intraday move and call it the gap."""
    d1, d2 = dt.date(2026, 6, 1), dt.date(2026, 6, 2)
    rows = [(d1, 100.0, 110.0), (d2, 121.0, 130.0)]
    overnight, intraday = ol.legs(rows)
    assert overnight == pytest.approx([10.0])     # 110 -> 121
    assert intraday == pytest.approx([10.0, 7.438016], rel=1e-4)


def test_there_is_one_fewer_overnight_than_intraday():
    """By construction: the last session has no following open. An equal count
    would mean something was paired with itself."""
    rows = [(dt.date(2026, 6, d), 100.0, 101.0) for d in range(1, 6)]
    overnight, intraday = ol.legs(rows)
    assert len(intraday) == 5
    assert len(overnight) == 4


def test_a_single_session_has_no_overnight_at_all():
    overnight, intraday = ol.legs([(dt.date(2026, 6, 1), 100.0, 101.0)])
    assert overnight == []
    assert len(intraday) == 1


def test_a_zero_or_negative_print_is_dropped_rather_than_dividing():
    """A zero in the archive would raise, and a run of them would take the lab
    down mid-measurement."""
    rows = [(dt.date(2026, 6, 1), 100.0, 0.0),
            (dt.date(2026, 6, 2), 100.0, 101.0),
            (dt.date(2026, 6, 3), 102.0, 103.0)]
    overnight, intraday = ol.legs(rows)
    assert len(intraday) == 2        # the zero-close session is dropped
    assert len(overnight) == 1       # and so is the pair spanning it


def test_an_empty_archive_produces_nothing_rather_than_a_number():
    assert ol.sessions([]) == []
    assert ol.legs([]) == ([], [])


# ----------------------------------------------------- the bar is not awarded
def test_the_bar_is_corrected_for_every_test_in_the_search():
    """Three symbols and two legs is a search of six. Reporting the best of
    six at a flat t>=2 is the multiple-comparisons mistake this codebase
    removed everywhere else on 2026-10-14."""
    from signal_lab import corrected_t

    assert ol.N_TESTS == 6
    assert ol.BAR == round(corrected_t(6), 2)
    assert ol.BAR > 2.0


def test_the_bar_comes_from_the_shared_function():
    from signal_lab import corrected_t

    assert ol.corrected_t is corrected_t


def test_a_half_too_small_to_judge_is_refused():
    assert ol.MIN_N >= 30


# -------------------------------------------------------- it refuses to oversell
def test_it_says_it_measures_the_underlying_and_not_an_option():
    """A positive drift in the index is a PREREQUISITE for the trade. The
    option also pays a night of theta and eats any overnight IV move, and
    neither is modelled here."""
    doc = ol.__doc__ or ""
    assert "NOT AN OPTION" in doc.upper()
    assert "theta" in doc.lower()


def test_it_states_that_an_overnight_hold_cannot_be_stopped_out():
    """The market is shut. The thesis stop — Hokage's most common exit —
    cannot fire, so this is the least protected position he can take, and
    that is structural rather than tunable."""
    doc = (ol.__doc__ or "").lower()
    assert "cannot be stopped" in doc or "cannot fire" in doc
    assert "market is closed" in doc or "market is shut" in doc


def test_it_reports_the_worst_night_beside_every_mean():
    src = (ROOT / "tools" / "research" / "overnight_lab.py").read_text(
        encoding="utf-8")
    assert "worst" in src


def test_it_does_not_import_a_claim_it_has_not_measured():
    """The literature is US equities. The docstring must say the Indian case
    is unestablished rather than borrow the US result."""
    doc = ol.__doc__ or ""
    assert "NOT established" in doc or "not established" in doc.lower()
    assert "peer-reviewed" in doc
