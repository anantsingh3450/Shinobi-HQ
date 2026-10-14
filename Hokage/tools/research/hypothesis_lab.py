"""Propose NEW edges, not better settings for the eight Hokage already has.

    python tools/research/hypothesis_lab.py                 # the live universe
    python tools/research/hypothesis_lab.py GOLDM SENSEX

WHY THIS EXISTS. On 2026-10-14 the commander asked why Hokage is not evolving.
His brain answered it:

    applied_improvements .......... 0
    learning_records .............. 0
    improvement proposals ......... 3, all PENDING, all stale
    cells measured ............... 27
    cells clearing t>=2.0 ......... 2

Evolution needs VARIATION and SELECTION. Hokage has only selection:
weekly_audit re-scores the same eight modules, sweep_lab tunes their knobs,
evolution.py retires what decays. Nothing has ever proposed an idea that was
not already there, so every week re-measures the same 27 cells and finds the
same answer. A pruning loop with no generator converges on a smaller system,
never a better one.

This is the missing half. It searches a space of simple, composable entry
conditions, scores each on the SAME basis the audit now uses - per-cell
production stop and production's adaptive target - and reports what survives
out of sample.

=============================================================================
THE DANGER, WHICH IS THE WHOLE DESIGN PROBLEM
=============================================================================
Searching N hypotheses and keeping the best one FINDS NOISE. With 300
candidates and a t>=2.0 bar, roughly 15 will clear by luck alone on a single
sample. A generator that reports those as discoveries is worse than no
generator: it manufactures confident, measured-looking reasons to risk money.
session_lab already says this out loud about its six buckets.

Three rails, and none is optional:

  1. TRAIN AND HOLD-OUT, BOTH. A candidate must clear on the half it was not
     selected on. This alone removes most of it.
  2. THE BAR RISES WITH THE SEARCH. The t required is corrected for how many
     hypotheses were tried (Sidak, per family), so a wider search has to clear
     a higher bar - which is the honest price of looking in more places.
  3. THE COUNT IS ALWAYS REPORTED. Every output states how many candidates
     were tried and what bar that implied. A number without its search size is
     not interpretable.

NOTHING HERE SHIPS ANYTHING. Output is HYPOTHESES, ranked, for the commander
to decide whether to pursue - never a strategy, never a PENDING proposal,
never a change to a live file. A new entry module is a capital decision.
"""
from __future__ import annotations

import argparse
import math
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

from signal_lab import Ctx, load_bars, measurable  # noqa: E402
from sweep_lab import HORIZON, realised  # noqa: E402

#: The ordinary ship bar, before any correction for the size of the search.
BASE_T = 2.0

#: Fewer than this on either half and the cell is arithmetic on noise.
MIN_N = 40

#: Family-wise error rate the correction targets. 0.05 is the conventional
#: choice and is stated rather than tuned - a generator that tunes its own
#: significance bar is marking its own homework.
FAMILY_ALPHA = 0.05


# --------------------------------------------------------------- primitives
#: Conditions a hypothesis may be built from. Each reads ONLY the Ctx, which
#: by construction cannot see the future.
#:
#: Deliberately small and interpretable. A search over hundreds of opaque
#: features would clear the corrected bar occasionally and teach nobody
#: anything; these are statements a human can argue with.
def _primitives() -> dict:
    def stretch(ctx):            # distance from VWAP in ATR
        return (ctx.price - ctx.vwap) / ctx.atr if ctx.atr else 0.0

    def trend(ctx):              # EMA separation as a fraction of price
        return (ctx.ema9 - ctx.ema21) / ctx.price if ctx.price else 0.0

    def range_pos(ctx):          # where in the session range we sit, 0..1
        highs = [b["high"] for b in ctx.session]
        lows = [b["low"] for b in ctx.session]
        hi, lo = max(highs), min(lows)
        return (ctx.price - lo) / (hi - lo) if hi > lo else 0.5

    def atr_pct(ctx):            # volatility regime, ATR as a % of price
        return 100.0 * ctx.atr / ctx.price if ctx.price else 0.0

    def momentum(ctx):           # move over the last 4 bars, in ATR
        if len(ctx.bars) < 5 or not ctx.atr:
            return 0.0
        return (ctx.price - ctx.bars[-5]["close"]) / ctx.atr

    def gap_from_open(ctx):      # move since the session opened, in ATR
        if not ctx.session or not ctx.atr:
            return 0.0
        return (ctx.price - ctx.session[0]["open"]) / ctx.atr

    def body_fraction(ctx):      # conviction of the last bar, -1..1
        bar = ctx.bars[-1]
        span = bar["high"] - bar["low"]
        return (bar["close"] - bar["open"]) / span if span else 0.0

    def atr_expansion(ctx):      # short ATR against long ATR, >1 = expanding
        from signal_lab import atr as _atr
        if len(ctx.bars) < 60:
            return 1.0
        slow = _atr(ctx.bars[-60:])
        return (ctx.atr / slow) if slow else 1.0

    def vwap_side_streak(ctx):   # consecutive bars held on one side of VWAP
        n = 0
        above = ctx.price > ctx.vwap
        for bar in reversed(ctx.session[-10:]):
            if (bar["close"] > ctx.vwap) == above:
                n += 1
            else:
                break
        return float(n if above else -n)

    return {
        "stretch_vs_vwap": (stretch, (-1.5, -0.75, -0.25, 0.25, 0.75, 1.5)),
        "ema_trend_pct": (trend, (-0.20, -0.08, -0.03, 0.03, 0.08, 0.20)),
        "range_position": (range_pos, (0.1, 0.3, 0.7, 0.9)),
        "atr_pct_of_price": (atr_pct, (0.10, 0.20, 0.35, 0.60)),
        "momentum_4bar_atr": (momentum, (-1.5, -0.6, -0.2, 0.2, 0.6, 1.5)),
        "gap_from_open_atr": (gap_from_open, (-2.0, -0.8, -0.3, 0.3, 0.8, 2.0)),
        "bar_body_fraction": (body_fraction, (-0.6, -0.25, 0.25, 0.6)),
        "atr_expansion": (atr_expansion, (0.7, 0.9, 1.1, 1.4)),
        "vwap_side_streak": (vwap_side_streak, (-5, -2, 2, 5)),
    }


#: A hypothesis may be one condition or a CONJUNCTION of two. Pairs are where
#: the interesting ideas live - "stretched from VWAP AND volatility expanding"
#: is a different claim from either half - and they multiply the search
#: enormously, which is precisely what the corrected bar is for.
MAX_CONDITIONS = 2


#: Session bands, in minutes past midnight IST. A hypothesis is always scoped
#: to one: edge that exists only in one part of the day is the single most
#: repeated finding in this codebase, and pooling the day hides it.
BANDS = (
    ("09:15-11:00", 555, 660),
    ("11:00-13:30", 660, 810),
    ("13:30-15:20", 810, 920),
    ("17:00-18:30", 1020, 1110),
    ("18:30-20:00", 1110, 1200),
)


def corrected_t(n_tested: int, alpha: float = FAMILY_ALPHA) -> float:
    """The t a candidate must clear, given how many were tried.

    Sidak: a single test at alpha becomes 1 - (1-alpha)^(1/N) across N of them.
    Converted to a two-sided z, which is the right order of magnitude for the
    sample sizes here and is deliberately the SIMPLE correction - an elaborate
    one would invite tuning.

    Never returns less than BASE_T. A small search does not earn an easier bar
    than everything else in this system ships against.
    """
    if n_tested <= 1:
        return BASE_T
    per_test = 1.0 - (1.0 - alpha) ** (1.0 / n_tested)
    # inverse normal via the Beasley-Springer-Moro-free route: bisection on erf
    target = 1.0 - per_test / 2.0
    lo, hi = 0.0, 10.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if 0.5 * (1.0 + math.erf(mid / math.sqrt(2.0))) < target:
            lo = mid
        else:
            hi = mid
    return max(BASE_T, (lo + hi) / 2.0)


def _t(xs: list[float]) -> tuple[int, float, float]:
    n = len(xs)
    if n < 2:
        return n, 0.0, 0.0
    m = st.mean(xs)
    sd = st.stdev(xs)
    return n, m, (m / (sd / math.sqrt(n)) if sd else 0.0)


def search(symbol: str, bars: list[dict]) -> tuple[list[dict], int]:
    """Every condition, and every PAIR of conditions, scored on both halves.

    EVALUATED PER BAR, NOT PER CANDIDATE. The first version called realised()
    inside the innermost loop, recomputing an identical forward walk once for
    every candidate that happened to fire on that bar. With conjunctions in
    the space that is tens of millions of redundant walks and the search never
    finishes. A bar's outcome depends only on (bar, side), so it is computed
    twice per bar and shared by every hypothesis that fired there.

    Only the conditions that actually FIRE are combined, so the pair space
    costs what co-occurrence costs rather than the full cross product.
    """
    from itertools import combinations

    prims = _primitives()
    conditions = [
        (pname, op, th)
        for pname, (_, thresholds) in prims.items()
        for th in thresholds
        for op in ("above", "below")
    ]
    mid = len(bars) // 2
    acc: dict = {}

    for i in range(42, len(bars) - HORIZON):
        window = bars[: i + 1]
        day = window[-1]["date"].date()
        session = [b for b in window if b["date"].date() == day]
        if len(session) < 6 or bars[i + HORIZON]["date"].date() != day:
            continue
        ctx = Ctx(window, session)
        if not ctx.atr or not measurable(ctx, window[-1]):
            continue

        mins = bars[i]["date"].hour * 60 + bars[i]["date"].minute
        band = next((b[0] for b in BANDS if b[1] <= mins < b[2]), None)
        if band is None:
            continue

        try:
            values = {name: fn(ctx) for name, (fn, _) in prims.items()}
        except Exception:
            continue

        fired = tuple(
            c for c in conditions
            if (values[c[0]] > c[2] if c[1] == "above" else values[c[0]] < c[2])
        )
        if not fired:
            continue

        half = "train" if i < mid else "hold"
        edges = {
            "long": realised(bars, i, 1, ctx.atr, None, symbol),
            "short": realised(bars, i, -1, ctx.atr, None, symbol),
        }

        keys = [(c,) for c in fired]
        if MAX_CONDITIONS >= 2:
            keys.extend(combinations(fired, 2))
        for conds in keys:
            for side in ("long", "short"):
                rec = acc.setdefault((conds, side, band), {"train": [], "hold": []})
                rec[half].append(edges[side])

    out = []
    for key, halves in acc.items():
        tn, tm, tt = _t(halves["train"])
        hn, hm, ht = _t(halves["hold"])
        # Anything too thin to be testable is not a test. Counting it in the
        # family size would inflate the correction and make the bar
        # meaninglessly high, which is its own way of being dishonest.
        if tn < MIN_N or hn < MIN_N:
            continue
        out.append({
            "symbol": symbol, "key": key,
            "train_n": tn, "train_edge": tm, "train_t": tt,
            "hold_n": hn, "hold_edge": hm, "hold_t": ht,
        })
    return out, len(out)


def report(results: list[dict], tested: int) -> None:
    bar = corrected_t(tested)
    print(f"\n  {tested} hypotheses tested  ->  corrected bar t >= {bar:.2f} "
          f"on BOTH halves (base {BASE_T}, family alpha {FAMILY_ALPHA})")

    eligible = [r for r in results if r["train_n"] >= MIN_N and r["hold_n"] >= MIN_N]
    survivors = [r for r in eligible
                 if r["train_t"] >= bar and r["hold_t"] >= bar]
    would_pass_uncorrected = [r for r in eligible
                              if r["train_t"] >= BASE_T and r["hold_t"] >= BASE_T]

    print(f"  {len(eligible)} had n >= {MIN_N} on both halves")
    print(f"  {len(would_pass_uncorrected)} would clear the UNCORRECTED t>={BASE_T} "
          f"- which is why the correction exists")
    print(f"  {len(survivors)} clear the corrected bar")

    if not survivors:
        print("\n  Nothing survives. That is the honest result of most searches,")
        print("  and the reason to believe the ones that do.")
        return

    print(f"\n  {'hypothesis':84} {'TRAIN n':>7} {'t':>7} {'HOLD n':>7} {'t':>7}")
    for r in sorted(survivors, key=lambda r: -min(r["train_t"], r["hold_t"])):
        conds, side, band = r["key"]
        clause = " AND ".join(f"{p} {op} {th}" for p, op, th in conds)
        label = f"{r['symbol']} {band} {side} when {clause}"
        print(f"  {label:84} {r['train_n']:>7} {r['train_t']:>+7.2f} "
              f"{r['hold_n']:>7} {r['hold_t']:>+7.2f}")

    print("\n  These are HYPOTHESES, not strategies. Each needs a module, a")
    print("  scope decision and a commander approval before it risks anything.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("symbols", nargs="*", default=None)
    args = ap.parse_args()
    symbols = [s.upper() for s in (args.symbols or
                                   ["GOLDM", "SILVERM", "CRUDEOIL", "NATURALGAS",
                                    "NIFTY", "SENSEX", "BANKNIFTY"])]

    print("=" * 94)
    print("  HYPOTHESIS LAB — search for NEW edges, with the search size priced in")
    print("  Same geometry as the audit: per-cell production stop + adaptive target.")
    print("  Train and hold-out, both. The bar RISES with the number of candidates.")
    print("=" * 94)

    all_results: list[dict] = []
    total_tested = 0
    for symbol in symbols:
        try:
            bars = load_bars(symbol, "2026-01-01", "2026-12-31")
        except Exception as exc:
            print(f"\n  {symbol}: could not load bars ({exc})")
            continue
        if len(bars) < 400:
            print(f"\n  {symbol}: only {len(bars)} bars, not enough to split")
            continue
        res, tested = search(symbol, bars)
        all_results.extend(res)
        total_tested += tested
        print(f"  {symbol}: {tested} candidates over {len(bars)} bars")

    # ONE family across the whole run. Correcting per asset and then reporting
    # the union would be the multiple-comparisons problem reintroduced at the
    # level above the correction.
    report(all_results, total_tested)
    print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
