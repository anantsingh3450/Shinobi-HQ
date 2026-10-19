"""Does the index earn its return overnight, and could Hokage buy that?

    python tools/research/overnight_lab.py
    python tools/research/overnight_lab.py NIFTY

WHY THIS EXISTS. 2026-10-19: the commander asked for a new strategy, and he
is right that the system needs one. The improvement loop has SELECTION
(sweep_lab prunes and tunes) and no VARIATION — nothing in Hokage has ever
proposed a new module. Seven live cells, five of them behind a VIX gate, two
tradeable for ninety minutes a day.

THE ONE FAMILY WITH REAL PUBLISHED EVIDENCE that is also testable here is the
overnight/intraday decomposition. Cliff, Cooper and Gulen (2008) and Lou,
Polk and Skouras ("A Tug of War") document, on US equities and index futures,
that close-to-open returns are strongly positive while open-to-close returns
are near zero or negative. It is one of the most replicated return patterns
in the literature.

ON NIFTY IT IS NOT ESTABLISHED. A search of the literature on 2026-10-19
found no peer-reviewed study of the Indian index. What exists is blogs and
practitioner notes with undocumented methods, inconsistent return definitions
and unverified samples — weaker evidence than this codebase produces for
itself. So this does not import the claim. It MEASURES it, on the archive, at
a corrected bar, split in half.

WHAT IT MEASURES
    overnight   last close of day D  ->  first open of day D+1
    intraday    first open of day D  ->  last close of day D

WHAT IT IS NOT. It is not an option strategy and it does not pretend to be.
It measures the UNDERLYING. An option bought at the close and sold at the
open also pays a night of theta and eats whatever implied volatility does
overnight, and neither is modelled here. A positive underlying drift is a
PREREQUISITE for the trade, never the trade's edge. theta_breakeven_lab is
where that second question gets asked, and it has to be asked before a single
rupee follows this.

AND THE HONEST WARNING ABOUT "FAILSAFE". An overnight hold is the least
protected position Hokage can take: the market is closed, so the thesis stop
cannot fire, and the gap that is the whole point of the trade is also the only
thing that can hurt it without warning. Every other module here can be stopped
out. This one cannot. That is a structural cost, not a tuning parameter, and
it is why the worst single night is printed beside every mean.
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

from candle_archive import load as archive_load  # noqa: E402
from signal_lab import corrected_t  # noqa: E402

#: The indices Hokage can actually buy options on.
SYMBOLS = ("NIFTY", "BANKNIFTY", "SENSEX")

#: Tests in this search: 3 symbols x 2 legs (overnight, intraday). The bar is
#: corrected for all of them, because looking at six numbers and reporting the
#: best is a search whether or not it is called one.
N_TESTS = len(SYMBOLS) * 2
BAR = round(corrected_t(N_TESTS), 2)

#: Fewer than this on a HALF and the mean is arithmetic on noise. The archive
#: begins 2026-02-13 for the indices, so this is the binding limit on what can
#: be said here at all.
MIN_N = 30


def sessions(bars: list[dict]) -> list[tuple[object, float, float]]:
    """(day, first open, last close) for each session, in order."""
    by_day: dict = {}
    for b in bars:
        day = b["date"].date()
        if day not in by_day:
            by_day[day] = [b["open"], b["close"]]
        else:
            by_day[day][1] = b["close"]
    return [(d, v[0], v[1]) for d, v in sorted(by_day.items())]


def legs(rows: list[tuple[object, float, float]]) -> tuple[list, list]:
    """Percent returns for each leg. Overnight pairs day D's close with D+1's
    open, so it is one shorter than intraday by construction."""
    overnight, intraday = [], []
    for (_, o, c) in rows:
        if o > 0 and c > 0:
            intraday.append((c / o - 1.0) * 100.0)
    for (_, _, c), (_, o2, _) in zip(rows, rows[1:]):
        if c > 0 and o2 > 0:
            overnight.append((o2 / c - 1.0) * 100.0)
    return overnight, intraday


def _stats(xs: list[float]) -> tuple[int, float, float]:
    n = len(xs)
    if n < 2:
        return n, 0.0, 0.0
    m = st.mean(xs)
    sd = st.stdev(xs)
    return n, m, (m / (sd / math.sqrt(n)) if sd else 0.0)


def report(symbol: str) -> None:
    try:
        bars = archive_load(symbol, "2000-01-01", "2100-01-01")
    except Exception as exc:
        print(f"\n  {symbol}: {exc}")
        return
    rows = sessions(bars)
    if len(rows) < MIN_N * 2:
        print(f"\n  {symbol}: {len(rows)} sessions in the archive — too few to "
              f"split and judge.")
        return

    mid = len(rows) // 2
    halves = {"TRAIN": rows[:mid + 1], "HOLD": rows[mid:]}

    print(f"\n  {symbol}   {len(rows)} sessions   "
          f"{rows[0][0]} .. {rows[-1][0]}")
    print(f"    {'leg':11} {'TRAIN n':>7} {'mean':>8} {'t':>7} "
          f"{'HOLD n':>7} {'mean':>8} {'t':>7} {'worst':>8}  verdict")

    for name, index in (("overnight", 0), ("intraday", 1)):
        cells = {}
        for half, part in halves.items():
            series = legs(part)[index]
            cells[half] = (_stats(series),
                           min(series) if series else 0.0)
        (tn, tm, tt), tw = cells["TRAIN"]
        (hn, hm, ht), hw = cells["HOLD"]

        if tn < MIN_N or hn < MIN_N:
            verdict = f"too few sessions (train {tn}, hold {hn})"
        elif tt >= BAR and ht >= BAR:
            verdict = "POSITIVE on both halves"
        elif tt <= -BAR and ht <= -BAR:
            verdict = "NEGATIVE on both halves"
        else:
            verdict = "one half at best — not evidence"
        print(f"    {name:11} {tn:>7} {tm:>+7.3f}% {tt:>+7.2f} "
              f"{hn:>7} {hm:>+7.3f}% {ht:>+7.2f} {min(tw, hw):>+7.2f}%  {verdict}")

    overnight, intraday = legs(rows)
    for name, series in (("overnight", overnight), ("intraday", intraday)):
        n, mean, t = _stats(series)
        up = sum(1 for x in series if x > 0) / n * 100.0 if n else 0.0
        print(f"      all {name:10} n={n:<4} mean {mean:+.3f}%  t {t:+.2f}  "
              f"up {up:.0f}%  worst {min(series):+.2f}%")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("symbols", nargs="*")
    args = ap.parse_args()
    symbols = [s.upper() for s in (args.symbols or SYMBOLS)]

    print("=" * 94)
    print("  OVERNIGHT LAB — is the index's return earned while the market is shut?")
    print("  overnight = last close of day D -> first open of D+1")
    print("  intraday  = first open of day D -> last close of day D")
    print(f"  Train/hold split, bar t>={BAR} on BOTH halves (corrected for "
          f"{N_TESTS} tests).")
    print("  THIS MEASURES THE UNDERLYING, NOT AN OPTION. A night of theta and")
    print("  any overnight IV change are NOT modelled, and both work against a")
    print("  buyer. A positive drift here is a prerequisite, never an edge.")
    print("  An overnight hold cannot be stopped out: the market is shut.")
    print("=" * 94)

    for symbol in symbols:
        report(symbol)
    print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
