"""A wider stop holds longer. Does the extra underlying edge beat the decay?

    python tools/research/theta_breakeven_lab.py
    python tools/research/theta_breakeven_lab.py SILVERM GOLDM

WHY THIS EXISTS. stop_lab measured the thesis stop on 2026-10-14 and found it
amputating the edge:

    GOLDM   SessionShift   no stop +0.565 t+2.70 | 1.25 ATR +0.303 t+1.49
    SILVERM SessionShift   no stop +0.343 t+2.76 | 1.25 ATR +0.302 t+2.52

The 1.25 ATR stop is the reason GOLDM is not a confirmed cell. But stop_lab
models the UNDERLYING only, and Hokage buys options: a wider stop holds the
position longer, and premium decays while it waits. Its own conclusion was
"permission to test, not proof".

WHAT THIS CANNOT DO, AND WHY IT STILL HELPS. There is no option premium
history anywhere in the brain - candle_archive holds the seven underlyings and
nothing else - so theta cannot be MEASURED here. Modelling a premium with
Black-Scholes would be a synthetic price, which this project does not trade on
and will not research on either.

So this does not invent the answer. It reduces the unknown to ONE number:

    the wider stop pays  <=>  decay over the extra holding time
                              < delta x extra underlying gain

Both sides of that are reported. The left is the unknown; the right is
measured from real candles. The output is the decay rate at which the choice
flips - a threshold the commander can check against a single live option chain
in thirty seconds, instead of a question nobody can answer at all.

DELTA IS AN ASSUMPTION, NOT A MEASUREMENT, and is labelled as one everywhere
it appears. Hokage buys ATM, where delta is near 0.5, so 0.5 is the centre and
0.40/0.60 bound the sensitivity. Nothing here should be read as a premium.
"""
from __future__ import annotations

import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

from signal_lab import Ctx, load_bars, measurable, _MCX_FUTURES  # noqa: E402
from entry_module_lab import build_context  # noqa: E402

# Reused so the two tables are directly comparable: the same horizon, the same
# minimum sample, and the same view of which modules are live where.
from stop_lab import HORIZON, LIVE_SCOPE, MIN_N  # noqa: E402

from bots.strategy.components.entries import ENTRY_MODULES  # noqa: E402
from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES  # noqa: E402

#: The SHARED default. Production does not run one stop for everything:
#: _THESIS_ATR_MULT_BY_STRATEGY_ASSET already gives SessionShift/GOLDM 3.0,
#: approved 2026-08-13. Comparing GOLDM against 1.25 would price a change that
#: shipped two months ago and report a break-even for a decision already made.
#: production_stop_for() asks the bot instead of assuming.
DEFAULT_STOP = 1.25


def production_stop_for(module_id: str, symbol: str) -> float:
    """What production actually runs for this cell, asked of the bot itself.

    The lab must never hold its own copy of a production constant. The two
    stop tables are per-strategy and per (strategy, asset), and the module ids
    the labs speak are not the strategy ids those tables are keyed by, so this
    maps across rather than guessing.
    """
    from bots.autonomous.autonomous_bot import AutonomousTradingBot as _Bot

    strategy_id = module_id.replace("entry-", "strat-", 1)
    return _Bot._thesis_atr_mult_for(_Bot, strategy_id, symbol)

#: Candidates, matching stop_lab so the two tables line up.
STOPS: tuple[float | None, ...] = (1.25, 1.5, 2.0, 2.5, 3.0, None)

#: ATM delta. AN ASSUMPTION. Hokage buys at the money, where delta sits near
#: one half; the outer values are the sensitivity band, not a forecast.
DELTA_CENTRE = 0.50
DELTA_LOW = 0.40
DELTA_HIGH = 0.60

#: One bar.
MINUTES_PER_BAR = 15


def walk(bars: list[dict], i: int, call: int, atr: float, k: float | None):
    """Realised edge in ATR and the bar the position actually exited on.

    stop_lab.simulate returns whether the stop fired but not WHEN, and when is
    the whole question here: the cost of a wider stop is the time it spends
    waiting.
    """
    entry = bars[i]["close"]
    if k is not None:
        stop_level = entry - call * k * atr
        for j in range(i + 1, min(i + HORIZON + 1, len(bars))):
            bar = bars[j]
            hit = bar["low"] <= stop_level if call == 1 else bar["high"] >= stop_level
            if hit:
                return (stop_level - entry) * call / atr, j - i
    j = min(i + HORIZON, len(bars) - 1)
    return (bars[j]["close"] - entry) * call / atr, j - i


def evaluate(symbol: str, bars: list[dict], modules: dict) -> dict:
    out = {
        name: {"edge": {k: [] for k in STOPS}, "held": {k: [] for k in STOPS},
               "atr": []}
        for name in modules
    }
    for i in range(42, len(bars) - HORIZON):
        window = bars[: i + 1]
        day = window[-1]["date"].date()
        session = [b for b in window if b["date"].date() == day]
        if len(session) < 6 or bars[i + HORIZON]["date"].date() != day:
            continue
        ctx = Ctx(window, session)
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
            out[name]["atr"].append(ctx.atr)
            for k in STOPS:
                edge, held = walk(bars, i, call, ctx.atr, k)
                out[name]["edge"][k].append(edge)
                out[name]["held"][k].append(held)
    return out


def report(symbol: str, results: dict) -> None:
    printed = False
    for name, rec in sorted(results.items()):
        scope = LIVE_SCOPE.get(name)
        if scope is None or symbol not in scope:
            continue
        prod = production_stop_for(name, symbol)
        if prod not in rec["edge"]:
            print(f"    {name}: production runs {prod} ATR here, which is not "
                  f"in the sweep — cannot compare.")
            continue
        n = len(rec["edge"][prod])
        if n < MIN_N:
            continue
        if not printed:
            print(f"\n  {symbol}   (horizon {HORIZON} bars = {HORIZON * MINUTES_PER_BAR} min)")
            printed = True

        atr_pts = st.mean(rec["atr"])
        base_edge = st.mean(rec["edge"][prod])
        base_held = st.mean(rec["held"][prod])
        print(f"    {name}   n={n}   mean ATR {atr_pts:.2f} pts")
        print(f"      production {prod} ATR (as the bot resolves it): "
              f"edge {base_edge:+.3f} ATR, held {base_held * MINUTES_PER_BAR:.0f} min")
        print(f"      {'stop':>8s} {'edge_atr':>9s} {'d_edge':>8s} {'held_min':>9s} "
              f"{'d_hold':>7s} {'gain_pts':>9s} {'break-even decay':>18s}")

        for k in STOPS:
            if k == prod:
                continue
            edge = st.mean(rec["edge"][k])
            held = st.mean(rec["held"][k])
            d_edge = edge - base_edge
            d_hold_min = (held - base_held) * MINUTES_PER_BAR
            # The extra underlying move the wider stop captures, in points.
            gain_pts = d_edge * atr_pts
            label = f"{k} ATR" if k is not None else "none"

            if d_hold_min <= 0 or d_edge <= 0:
                why = ("no extra edge" if d_edge <= 0 else "no extra time")
                print(f"      {label:>8s} {edge:+9.3f} {d_edge:+8.3f} "
                      f"{held * MINUTES_PER_BAR:9.0f} {d_hold_min:+7.0f} "
                      f"{gain_pts:+9.2f} {why:>18s}")
                continue

            # The option must lose less than delta x gain over the extra wait.
            per_hour = DELTA_CENTRE * gain_pts / (d_hold_min / 60.0)
            lo = DELTA_LOW * gain_pts / (d_hold_min / 60.0)
            hi = DELTA_HIGH * gain_pts / (d_hold_min / 60.0)
            print(f"      {label:>8s} {edge:+9.3f} {d_edge:+8.3f} "
                  f"{held * MINUTES_PER_BAR:9.0f} {d_hold_min:+7.0f} "
                  f"{gain_pts:+9.2f} {per_hour:11.2f} pts/hr")
            print(f"      {'':>8s} {'':>9s} {'':>8s} {'':>9s} {'':>7s} {'':>9s} "
                  f"  (delta {DELTA_LOW}-{DELTA_HIGH}: {lo:.2f}-{hi:.2f})")

        print(f"      READ: widening to k pays if the option decays SLOWER than")
        print(f"            the break-even. Decay is NOT measured here - there is")
        print(f"            no option premium history in the brain.")


def main() -> int:
    symbols = [s.upper() for s in sys.argv[1:]] or ["SILVERM", "GOLDM"]
    print("=" * 84)
    print("  THETA BREAK-EVEN — what decay rate makes a wider stop a bad trade?")
    print("  stop_lab showed the 1.25 ATR stop amputating edge on the UNDERLYING.")
    print("  Hokage buys options, so a longer hold costs premium. Theta is NOT")
    print("  measured here (no option history exists); this reduces the unknown")
    print("  to one checkable threshold. Delta is an ASSUMPTION, labelled as one.")
    print("=" * 84)

    for symbol in symbols:
        modules = MCX_ENTRY_MODULES if symbol in _MCX_FUTURES else ENTRY_MODULES
        # Key by module_id, not by strategy id. LIVE_SCOPE and every other lab
        # speak "entry-sessionshift-mcx-v1"; the registry is keyed
        # "strat-sessionshift-mcx-v1", so without this every scope lookup
        # returns None and the whole report silently prints nothing.
        modules = {getattr(m, "module_id", k): m for k, m in modules.items()}
        try:
            bars = load_bars(symbol, "2026-01-01", "2026-12-31")
        except Exception as exc:
            print(f"\n  {symbol}: could not load bars ({exc})")
            continue
        if len(bars) < 200:
            print(f"\n  {symbol}: only {len(bars)} bars, not enough")
            continue
        report(symbol, evaluate(symbol, bars, modules))

    print("\n" + "=" * 84)
    print("  TO CLOSE THIS PROPERLY: archive ATM option candles alongside the")
    print("  underlyings, then this becomes a measurement instead of a bound.")
    print("=" * 84)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
