"""WHEN does a module have edge, not just whether.

WHY THIS EXISTS
Hokage has nothing awake on MCX between 19:30 and 22:30 IST. Open sources put
the best crude window at 19:00-23:00 — US institutional flow, tight spreads,
real price discovery — so he is awake for the thin hours and asleep for the
liquid ones.

The gap is NOT an oversight. TrendRider's window was exactly 17:00-22:30, and
it was archived on 2026-08-12 because it measured negative (NATURALGAS 60m
t=-1.64). The evening is uncovered precisely because the one module built for
it did not work. Declaring something awake there would repeat that mistake.

WHAT THIS ASKS THAT entry_module_lab CANNOT
entry_module_lab scores a module across the hours the module allows itself to
trade. It therefore cannot tell "this idea does not work" apart from "this idea
works, but not in the hours it was given". A module strongly positive from
20:00-22:00 and strongly negative from 17:00-19:00 measures as noise overall,
and gets archived for it.

So this NEUTRALISES each module's own window gate and buckets its signals by
time of session. Every module is asked the same question at every hour: if you
had been awake now, would you have had edge?

READ IT AS A SEARCH, NOT A VERDICT. Slicing one dataset into six buckets
multiplies the chances that noise clears t>=2 somewhere. A bucket that looks
good here is a HYPOTHESIS, to be confirmed on held-out data and under full
geometry in stop_lab — exactly how CRUDEOIL was confirmed before RangeFade was
scoped onto it. Nothing ships off this table alone.

USAGE
    python tools/research/session_lab.py                  # CRUDEOIL NATURALGAS
    python tools/research/session_lab.py GOLDM SILVERM
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from signal_lab import Ctx, measurable, load_bars, _MCX_FUTURES  # noqa: E402
from entry_module_lab import build_context  # noqa: E402

from bots.strategy.components.entries import ENTRY_MODULES  # noqa: E402
from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES  # noqa: E402

#: Forward horizon, in 15-minute bars. 4 = 60 minutes, the horizon every other
#: lab reports as its primary, so these numbers are comparable to theirs.
HORIZON = 4

#: Below this a bucket is not reported. Six buckets means six chances to find a
#: fluke, and a thin bucket is the easiest place for one to hide.
MIN_N = 40

#: Named by what actually happens in them on MCX, in minutes from the 09:00 open.
BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("09:00-10:30  open", 0, 90),
    ("10:30-13:30  morning drift", 90, 270),
    ("13:30-17:00  pre-US", 270, 480),
    ("17:00-19:30  US overlap", 480, 630),
    ("19:30-22:30  THE GAP", 630, 810),
    ("22:30-23:30  past cutoff", 810, 900),
)


def _unbound(module):
    """Neutralise a module's own clock so it can be asked about every hour.

    Research only, never imported by production. Returns the original values so
    the caller can put them back — a lab that permanently widened a production
    module's window would be changing the thing it is trying to measure.
    """
    original = (getattr(module, "WINDOW_START_MIN", None),
                getattr(module, "WINDOW_END_MIN", None))
    if original[0] is not None:
        module.WINDOW_START_MIN = -1
    if original[1] is not None:
        module.WINDOW_END_MIN = 10 ** 9
    return original


def _rebind(module, original) -> None:
    if original[0] is not None:
        module.WINDOW_START_MIN = original[0]
    if original[1] is not None:
        module.WINDOW_END_MIN = original[1]


def _stats(edges: list[float], hits: int) -> tuple[int, float, float, float]:
    n = len(edges)
    mean = sum(edges) / n
    var = sum((e - mean) ** 2 for e in edges) / (n - 1) if n > 1 else 0.0
    t = mean / (math.sqrt(var / n) or 1e-9)
    return n, hits / n * 100.0, mean, t


def evaluate(symbol: str, bars: list[dict], modules: dict) -> dict:
    """module -> bucket -> {edges, hits}, with every window gate neutralised."""
    results = {name: {b[0]: {"edges": [], "hits": 0} for b in BUCKETS}
               for name in modules}
    originals = {name: _unbound(m) for name, m in modules.items()}
    try:
        for i in range(42, len(bars) - HORIZON):
            window = bars[: i + 1]
            day = window[-1]["date"].date()
            session = [b for b in window if b["date"].date() == day]
            if len(session) < 6:
                continue
            if bars[i + HORIZON]["date"].date() != day:
                continue
            ctx = Ctx(window, session)
            # A bar that did not trade is not an entry point, and an ATR
            # built from a run of them is fiction. See signal_lab.measurable.
            if not measurable(ctx, window[-1]):
                continue
            mkt = build_context(symbol, window, ctx, session)
            minutes = mkt.minutes_into_session
            bucket = next((b[0] for b in BUCKETS if b[1] <= minutes < b[2]), None)
            if bucket is None:
                continue
            forward = bars[i + HORIZON]["close"] - ctx.price
            for name, module in modules.items():
                try:
                    sig = module.evaluate(mkt)
                except Exception:
                    continue
                if not getattr(sig, "should_enter", False):
                    continue
                call = 1 if sig.direction == "long" else -1
                cell = results[name][bucket]
                cell["edges"].append((forward * call) / ctx.atr)
                cell["hits"] += 1 if (forward * call) > 0 else 0
    finally:
        for name, module in modules.items():
            _rebind(module, originals[name])
    return results


def report(symbol: str, results: dict) -> None:
    print("")
    print("  " + symbol + "   (forward horizon " + str(HORIZON * 15) + " min)")
    for name in sorted(results):
        rows = []
        for label, _lo, _hi in BUCKETS:
            cell = results[name][label]
            if len(cell["edges"]) < MIN_N:
                continue
            rows.append((label,) + _stats(cell["edges"], cell["hits"]))
        if not rows:
            continue
        print("    " + name)
        print("      " + "session window".ljust(28) + "n".rjust(5)
              + "accuracy".rjust(10) + "edge_atr".rjust(10) + "t".rjust(8))
        for label, n, acc, mean, t in rows:
            verdict = "  EDGE" if (t >= 2.0 and mean > 0) else (
                "  negative" if mean < 0 else "  noise")
            gap = "   <<< the gap" if "THE GAP" in label else ""
            print("      " + label.ljust(28) + str(n).rjust(5)
                  + (format(acc, ".1f") + "%").rjust(10)
                  + format(mean, "+.3f").rjust(10)
                  + format(t, "+.2f").rjust(8) + verdict + gap)


def main() -> int:
    symbols = [s.upper() for s in sys.argv[1:]] or ["CRUDEOIL", "NATURALGAS"]
    print("=" * 84)
    print("  SESSION LAB — when does each module have edge?")
    print("  Window gates are NEUTRALISED so every module is asked about every")
    print("  hour. Six buckets means six chances for noise to clear the bar, so")
    print("  read a good bucket as a hypothesis to confirm, never as a verdict.")
    print("=" * 84)
    for symbol in symbols:
        modules = MCX_ENTRY_MODULES if symbol in _MCX_FUTURES else ENTRY_MODULES
        named = {getattr(m, "module_id", k): m for k, m in modules.items()}
        try:
            bars = load_bars(symbol, "2026-05-01 09:15:00", "2026-08-13 23:30:00")
        except Exception as exc:
            print("  " + symbol + ": could not load bars (" + str(exc) + ")")
            continue
        report(symbol, evaluate(symbol, bars, named))
    print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
