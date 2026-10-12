"""Measure what the UNDERLYING THESIS STOP does to each module's edge.

WHY THIS EXISTS
Across Hokage's whole history the thesis stop is the single most common way a
trade ends — 23 exits against 12 targets, 12 square-offs, 11 backstops and 9
trail-locks. It is therefore the exit rule with the most influence on results,
and its distance (`_OPTION_THESIS_STOP_ATR = 1.25` ATR of the underlying) has
never been measured. It was chosen.

On 2026-08-13 it fired on both trades of the day. One of them, RangeFade's
NATURALGAS CE, was RIGHT: stopped near 264.70, after which the underlying ran
to 267.40 against a 265.50 entry. 1.25 x ATR(0.54) is 0.68 points on a 265.50
tape — 0.26% of price. That may be too short a leash to let a signal work.

"May be" is the whole problem. Three days were once spent tuning exit geometry
while the direction chooser had no edge at all; the lesson recorded from that
is to measure the thing before moving it. So this scores stop distance the same
way signal_lab and entry_module_lab score everything else, on real candles,
with a t-statistic.

WHAT IT MEASURES
For each module signal, walk forward bar by bar to the horizon:
  - if the underlying trades k x ATR against the position first, exit there
  - otherwise exit at the horizon
Realised edge is the outcome INCLUDING the stop, in ATR units. Sweeping k shows
whether the stop is protecting the edge or amputating it.

  no-stop      the module's raw edge, the ceiling a stop can preserve
  k = 1.25     what production does today
  k = 1.5 .. 3 wider leashes

Stops are detected on the bar's LOW (long) or HIGH (short), not the close,
because a stop fires intrabar in real life. Exits are priced AT the stop level,
which is generous — real fills slip — so a wide stop's advantage here is an
upper bound, never an underestimate of its cost.

IMPORTANT LIMIT: this measures the UNDERLYING, because the thesis stop is
defined on the underlying. Option P&L additionally carries theta and spread,
which punish long holds. A wider stop that looks better here is NOT
automatically better in premium terms. Treat a positive result as permission to
test in paper, not as proof.

USAGE
    python tools/research/stop_lab.py                    # MCX arena
    python tools/research/stop_lab.py NIFTY BANKNIFTY SENSEX
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

#: Stop distances in ATR units. None means "no stop at all" — the ceiling.
STOPS: tuple[float | None, ...] = (None, 1.25, 1.5, 2.0, 2.5, 3.0)

#: Bars held before a time exit. 4 x 15min = 1 hour, the horizon at which the
#: live modules were measured and roughly how long trades have actually lived.
HORIZON = 4

#: Only the strategies currently scoped to each symbol are worth reading; the
#: rest are archived. Keyed by module_id.
LIVE_SCOPE = {
    "entry-sessionshift-mcx-v1": {"GOLDM", "SILVERM"},
    "entry-rangefade-mcx-v1": {"NATURALGAS"},
    "entry-macrobreakout-v1": {"NIFTY", "BANKNIFTY", "SENSEX"},
    "entry-meanreversion-v1": {"NIFTY", "BANKNIFTY", "SENSEX"},
}

MIN_N = 30


def _t(edges: list[float]) -> tuple[int, float, float]:
    n = len(edges)
    if n < 2:
        return n, 0.0, 0.0
    mean = sum(edges) / n
    var = sum((e - mean) ** 2 for e in edges) / (n - 1)
    return n, mean, mean / (math.sqrt(var / n) or 1e-9)


def simulate(bars: list[dict], i: int, call: int, atr: float, k: float | None) -> tuple[float, bool]:
    """Return (realised move in ATR units, was_stopped) for one signal."""
    entry = bars[i]["close"]
    stop_level = None
    if k is not None:
        stop_level = entry - k * atr if call == 1 else entry + k * atr

    for j in range(i + 1, min(i + 1 + HORIZON, len(bars))):
        bar = bars[j]
        if bar["date"].date() != bars[i]["date"].date():
            break
        if stop_level is not None:
            hit = bar["low"] <= stop_level if call == 1 else bar["high"] >= stop_level
            if hit:
                return (stop_level - entry) * call / atr, True
        exit_price = bar["close"]
    else:
        exit_price = bars[min(i + HORIZON, len(bars) - 1)]["close"]
    return (exit_price - entry) * call / atr, False


def evaluate(symbol: str, bars: list[dict], modules: dict) -> dict:
    out = {name: {k: [] for k in STOPS} | {"stopped": {k: 0 for k in STOPS}}
           for name in modules}
    for i in range(42, len(bars) - HORIZON):
        window = bars[: i + 1]
        day = window[-1]["date"].date()
        session = [b for b in window if b["date"].date() == day]
        if len(session) < 6 or bars[i + HORIZON]["date"].date() != day:
            continue
        ctx = Ctx(window, session)
        # A bar that did not trade is not an entry point, and an ATR
        # built from a run of them is fiction. See signal_lab.measurable.
        if not measurable(ctx, window[-1]):
            continue
        mkt = build_context(symbol, window, ctx, session)
        for name, module in modules.items():
            try:
                sig = module.evaluate(mkt)
            except Exception:
                continue
            if not getattr(sig, "should_enter", False):
                continue
            call = 1 if sig.direction == "long" else -1
            for k in STOPS:
                edge, stopped = simulate(bars, i, call, ctx.atr, k)
                out[name][k].append(edge)
                if stopped:
                    out[name]["stopped"][k] += 1
    return out


def report(symbol: str, results: dict) -> None:
    printed = False
    for name, rec in sorted(results.items()):
        scope = LIVE_SCOPE.get(name)
        if scope is not None and symbol not in scope:
            continue  # archived here, or not scoped to this asset
        if scope is None:
            continue  # archived module
        n_raw = len(rec[None])
        if n_raw < MIN_N:
            continue
        if not printed:
            print(f"\n  {symbol}   (horizon {HORIZON} bars = {HORIZON * 15} min)")
            printed = True
        print(f"    {name}")
        print(f"      {'stop':>10s} {'n':>5s} {'stopped':>8s} {'edge_atr':>9s} {'t':>7s}")
        base_mean = None
        for k in STOPS:
            n, mean, t = _t(rec[k])
            if base_mean is None:
                base_mean = mean
            label = "none" if k is None else f"{k:.2f} ATR"
            pct = rec["stopped"][k] / n * 100.0 if n else 0.0
            flag = "  <- production" if k == 1.25 else ""
            print(f"      {label:>10s} {n:>5d} {pct:>7.0f}% {mean:>+9.3f} {t:>+7.2f}{flag}")
        n125, m125, t125 = _t(rec[1.25])
        best_k, best_m, best_t = None, -9e9, 0.0
        for k in STOPS:
            _, m, t = _t(rec[k])
            if m > best_m:
                best_k, best_m, best_t = k, m, t
        cost = base_mean - m125
        verdict = (
            f"production stop costs {cost:+.3f} ATR/trade vs no stop"
            if cost > 0 else
            f"production stop ADDS {-cost:+.3f} ATR/trade vs no stop"
        )
        best_label = "none" if best_k is None else f"{best_k:.2f} ATR"
        print(f"      -> {verdict}; best of the sweep is {best_label} "
              f"({best_m:+.3f} ATR, t={best_t:+.2f})")


def main() -> int:
    symbols = [s.upper() for s in sys.argv[1:]] or ["NATURALGAS", "GOLDM", "SILVERM"]
    print("=" * 84)
    print("  STOP LAB — is the thesis stop protecting the edge or amputating it?")
    print("  The stop is the most common exit in Hokage's history and its distance")
    print("  has never been measured. Underlying only: option theta is NOT modelled,")
    print("  so a wider stop looking better here is permission to test, not proof.")
    print("=" * 84)
    for symbol in symbols:
        modules = MCX_ENTRY_MODULES if symbol in _MCX_FUTURES else ENTRY_MODULES
        named = {getattr(m, "module_id", k): m for k, m in modules.items()}
        try:
            bars = load_bars(symbol, "2026-05-01 09:15:00", "2026-08-13 23:30:00")
        except Exception as exc:
            print(f"  {symbol}: could not load bars ({exc})")
            continue
        report(symbol, evaluate(symbol, bars, named))
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
