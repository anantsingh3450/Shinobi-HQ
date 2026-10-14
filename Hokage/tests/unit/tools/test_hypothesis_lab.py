"""Hokage could prune but never propose, so he could only get smaller.

2026-10-14, from his own brain:

    applied_improvements .......... 0
    learning_records .............. 0
    improvement proposals ......... 3, all PENDING, all stale
    cells measured ............... 27
    cells clearing t>=2.0 ......... 2

Evolution needs VARIATION and SELECTION. weekly_audit re-scores the same eight
modules, sweep_lab tunes their knobs, evolution.py retires what decays —
selection, all of it. Nothing had ever proposed an idea that was not already
there, so every week re-measured the same 27 cells and found the same answer.

THE DANGER IS THE DESIGN PROBLEM. Searching N hypotheses and keeping the best
FINDS NOISE. Measured on the first real run: of 536 candidates over GOLDM and
SENSEX, **21 cleared the ordinary t>=2.0 bar on both halves and 0 cleared the
bar corrected for having looked in 536 places**. A generator without that
correction would have handed over 21 confident, measured-looking reasons to
risk money.

So the correction is not a nicety here, it is the entire difference between a
hypothesis generator and a noise machine, and these tests exist to stop it
being weakened later by someone who wants the tool to find something.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

import signal_lab  # noqa: E402

signal_lab._fetch_from_kite = lambda *a, **k: []

_spec = importlib.util.spec_from_file_location(
    "hypothesis_lab", ROOT / "tools" / "research" / "hypothesis_lab.py"
)
hl = importlib.util.module_from_spec(_spec)
sys.modules["hypothesis_lab"] = hl
_spec.loader.exec_module(hl)


# ------------------------------------------- the bar rises with the search
def test_a_wider_search_must_clear_a_higher_bar():
    """The honest price of looking in more places."""
    assert hl.corrected_t(1) < hl.corrected_t(50) < hl.corrected_t(500)


def test_the_measured_case():
    """536 candidates demanded t>=3.90. Widened to conjunctions, GOLDM alone
    produced 21,718 candidates and a t>=4.72 bar - which took the count of
    "discoveries" from 194 to 0."""
    assert hl.corrected_t(536) == pytest.approx(3.90, abs=0.05)
    assert hl.corrected_t(21718) == pytest.approx(4.72, abs=0.05)


def test_a_small_search_never_earns_an_easier_bar():
    """Everything else in this system ships against t>=2.0. A generator must
    not get a discount for searching narrowly."""
    for n in (0, 1, 2, 5):
        assert hl.corrected_t(n) >= hl.BASE_T


def test_the_family_alpha_is_stated_not_tuned():
    """A generator that tunes its own significance threshold is marking its
    own homework."""
    assert hl.FAMILY_ALPHA == 0.05


def test_the_correction_is_applied_across_the_whole_run_not_per_asset():
    """Correcting per asset and reporting the union reintroduces the
    multiple-comparisons problem one level up."""
    src = (ROOT / "tools" / "research" / "hypothesis_lab.py").read_text(
        encoding="utf-8"
    )
    assert "ONE family across the whole run" in src
    assert "report(all_results, total_tested)" in src


# ----------------------------------------------- both halves, always
def test_a_candidate_must_clear_on_both_halves(capsys):
    """Train-only is a search result. The hold-out half is the test."""
    bar = hl.corrected_t(2)
    train_only = {
        "symbol": "X", "key": ((("p", "above", 1),), "long", "band"),
        "train_n": 100, "train_edge": 0.4, "train_t": bar + 1,
        "hold_n": 100, "hold_edge": 0.0, "hold_t": 0.1,
    }
    hl.report([train_only], 2)
    assert "0 clear the corrected bar" in capsys.readouterr().out


def test_a_thin_sample_is_not_eligible_however_good_its_t(capsys):
    thin = {
        "symbol": "X", "key": ((("p", "above", 1),), "long", "band"),
        "train_n": hl.MIN_N - 1, "train_edge": 2.0, "train_t": 99.0,
        "hold_n": hl.MIN_N - 1, "hold_edge": 2.0, "hold_t": 99.0,
    }
    hl.report([thin], 2)
    out = capsys.readouterr().out
    assert "0 had n >= " in out
    assert "0 clear the corrected bar" in out


def test_the_search_size_is_always_reported(capsys):
    """A t without its search size is not interpretable."""
    hl.report([], 300)
    out = capsys.readouterr().out
    assert "300 hypotheses tested" in out
    assert "corrected bar" in out


def test_the_uncorrected_count_is_shown_so_the_correction_can_be_judged(capsys):
    """Seeing '21 would clear uncorrected, 0 corrected' is what makes the
    correction believable rather than a black box."""
    ok = {
        "symbol": "X", "key": ((("p", "above", 1),), "long", "band"),
        "train_n": 100, "train_edge": 0.4, "train_t": 2.5,
        "hold_n": 100, "hold_edge": 0.4, "hold_t": 2.5,
    }
    hl.report([ok], 500)
    out = capsys.readouterr().out
    assert "would clear the UNCORRECTED" in out
    assert "0 clear the corrected bar" in out


# ------------------------------------------------- it proposes, never ships
def test_nothing_is_written_anywhere():
    """A new entry module is a capital decision. This reports and stops."""
    src = (ROOT / "tools" / "research" / "hypothesis_lab.py").read_text(
        encoding="utf-8"
    )
    for banned in ("write_proposal", "INSERT INTO", "write_text", "json.dump"):
        assert banned not in src, f"the generator writes something: {banned}"


def test_the_output_calls_them_hypotheses(capsys):
    ok = {
        "symbol": "X", "key": ((("stretch_vs_vwap", "above", 1),), "long", "09:15-11:00"),
        "train_n": 100, "train_edge": 0.9, "train_t": 9.0,
        "hold_n": 100, "hold_edge": 0.9, "hold_t": 9.0,
    }
    hl.report([ok], 2)
    out = capsys.readouterr().out
    assert "HYPOTHESES, not strategies" in out
    assert "commander approval" in out


# --------------------------------------- it measures on the shipping basis
def test_it_scores_with_the_same_realised_as_the_audit():
    """A generator measured on a looser ruler proposes edges that evaporate
    on contact with production geometry."""
    import sweep_lab

    assert hl.realised is sweep_lab.realised
    assert hl.HORIZON is sweep_lab.HORIZON


def test_hypotheses_are_scoped_to_a_session_band():
    """Edge that exists only in one part of the day is the most repeated
    finding in this codebase. Pooling the day hides it."""
    assert len(hl.BANDS) >= 4
    for label, lo, hi in hl.BANDS:
        assert lo < hi


# ------------------------------ an index carries no volume, and that is fine
def test_an_index_series_is_measurable():
    """THE SILENT EXCLUSION. candle_archive stores an index's volume as 0, not
    NULL - all 4,075 bars of NIFTY, BANKNIFTY and SENSEX - so a rule reading
    'present and zero means it did not trade' rejected every index bar, and
    with it every index asset in every lab calling measurable(). SENSEX
    returned 0 candidates until this was fixed."""
    from signal_lab import Ctx, measurable

    bars = [{"date": None, "open": 100 + i, "high": 101 + i, "low": 99 + i,
             "close": 100 + i, "volume": 0} for i in range(60)]
    ctx = Ctx.__new__(Ctx)
    ctx.bars = bars
    ctx.session = bars
    ctx.price = 130.0
    ctx.vwap = 129.0
    ctx.atr = 1.5
    ctx.ema9 = 130.0
    ctx.ema21 = 129.0
    assert measurable(ctx, bars[-1]) is True


def test_a_quiet_bar_on_a_traded_series_is_still_rejected():
    """The guard still does its job where it was needed: a futures contract
    that has not traded for hours repeats its last print, and an ATR built
    from those is fiction."""
    from signal_lab import Ctx, measurable

    bars = [{"date": None, "open": 100, "high": 101, "low": 99,
             "close": 100, "volume": 500} for _ in range(59)]
    quiet = {"date": None, "open": 100, "high": 100, "low": 100,
             "close": 100, "volume": 0}
    bars.append(quiet)
    ctx = Ctx.__new__(Ctx)
    ctx.bars = bars
    ctx.session = bars
    ctx.price = 100.0
    ctx.vwap = 100.0
    ctx.atr = 1.5
    ctx.ema9 = 100.0
    ctx.ema21 = 100.0
    assert measurable(ctx, quiet) is False


def test_the_volume_probe_is_bounded():
    """measurable() runs once per candidate bar and ctx.bars grows to the
    whole archive; an unbounded scan would make every lab quadratic."""
    assert signal_lab._VOLUME_PROBE_BARS <= 1000

# --------------------------------------------- the widened space stays sane
def test_conjunctions_are_searched():
    """Pairs are where the interesting ideas live: "stretched from VWAP AND
    volatility expanding" is a different claim from either half."""
    assert hl.MAX_CONDITIONS >= 2


def test_the_primitive_set_is_interpretable():
    """A search over hundreds of opaque features would clear the corrected bar
    occasionally and teach nobody anything. Every condition here is a sentence
    a human can argue with."""
    prims = hl._primitives()
    assert 8 <= len(prims) <= 20
    for name, (fn, thresholds) in prims.items():
        assert callable(fn)
        assert len(thresholds) >= 3, f"{name} has too few thresholds to be a sweep"
        assert "_" in name, f"{name} should read as a phrase"


def test_every_primitive_reads_only_the_context():
    """Ctx by construction cannot see the future. A primitive reaching past it
    would be lookahead, and lookahead always clears any bar."""
    src = (ROOT / "tools" / "research" / "hypothesis_lab.py").read_text(
        encoding="utf-8"
    )
    body = src[src.index("def _primitives("):src.index("#: A hypothesis may be")]
    for banned in ("bars[i +", "bars[i+", "future", "lookahead", "HORIZON"):
        assert banned not in body, f"a primitive reaches outside Ctx: {banned}"


def test_the_outcome_is_computed_per_bar_not_per_candidate():
    """With conjunctions the space is tens of thousands of candidates; a
    forward walk inside the innermost loop recomputes an identical result for
    each and the search never finishes.

    COUNTS CALLS VIA AST, not occurrences of the name - this function's own
    docstring mentions it, and text cannot tell a call from a description of
    one.
    """
    import ast

    src = (ROOT / "tools" / "research" / "hypothesis_lab.py").read_text(
        encoding="utf-8"
    )
    fn = next(
        n for n in ast.walk(ast.parse(src))
        if isinstance(n, ast.FunctionDef) and n.name == "search"
    )
    calls = [
        n for n in ast.walk(fn)
        if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "realised"
    ]
    assert len(calls) == 2, (
        f"expected one forward walk per side per bar, found {len(calls)}"
    )


def test_only_testable_candidates_count_toward_the_family():
    """Counting keys too thin to be tested would inflate the correction and
    make the bar meaninglessly high - dishonest in the other direction."""
    src = (ROOT / "tools" / "research" / "hypothesis_lab.py").read_text(
        encoding="utf-8"
    )
    body = src[src.index("def search("):src.index("def report(")]
    assert "if tn < MIN_N or hn < MIN_N:" in body
    assert "return out, len(out)" in body


def test_a_conjunction_is_rendered_readably(capsys):
    two = {
        "symbol": "GOLDM", "key": (
            (("stretch_vs_vwap", "above", 0.75), ("atr_expansion", "above", 1.1)),
            "long", "17:00-18:30"),
        "train_n": 100, "train_edge": 0.9, "train_t": 9.0,
        "hold_n": 100, "hold_edge": 0.9, "hold_t": 9.0,
    }
    hl.report([two], 2)
    out = capsys.readouterr().out
    assert "AND" in out
    assert "stretch_vs_vwap above 0.75" in out
