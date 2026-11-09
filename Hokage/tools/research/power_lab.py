"""How many more sessions until a cell can clear the bar? And which never will.

THE QUESTION
2026-11-09. The commander asked how far Hokage is from real money, and the
honest answer was that the binding constraint is evidence rather than code:
0 of 29 cells confirmed. "How far" then has an arithmetic answer nobody had
computed - how many sessions of tape each cell needs before its own measured
edge could reach the bar.

THE ARITHMETIC
    t = mean * sqrt(n) / sd        so       n_req = n * (bar / t)^2

That is all. The required sample scales with the SQUARE of how far short the
t-statistic falls, which is why a cell at t=0.5 needs 16x more data than one
at t=2.0 and not 4x.

Then the bar applies to BOTH halves, and the halves split whatever tape
exists. A cell firing `s` signals a session needs n_req in each half, so

    sessions_total_needed = 2 * n_req / s

and the answer is that minus the sessions already banked. The factor of two is
not pessimism, it is the hold-out rule: a number that clears on one half is
not evidence.

THE DISTINCTION THAT MATTERS MOST
A cell whose measured edge is NEGATIVE is not under-powered. More data makes
its t MORE negative, not less. Those cells are answered, and the answer is no.
Reporting them as "needs N more sessions" would be the worst kind of fabricated
hope - it would read as a schedule for something that is not coming. They are
labelled WRONG SIGN and given no estimate.

WHAT THIS IS NOT
Not a forecast. It assumes the measured mean and sd are the true ones, and at
n=40 they are themselves noisy - the true edge could be half the measured one,
which would quadruple the requirement. So every number here is a FLOOR: the
soonest this cell could possibly answer, if its edge is exactly what the last
measurement said. Treat it as an order of magnitude and a ranking, never as a
date. It also assumes the signal rate holds, and a module whose rate falls
takes proportionally longer.

GEOMETRY IS THE AUDIT'S, NOT THIS FILE'S
Every statistic comes from weekly_audit.measure_split - the production thesis
stop applied bar by bar, the target, traded bars only, the family-corrected
bar. A power estimate computed on looser geometry than the ship decision would
answer a question nobody is asking.

USAGE
    python tools/research/power_lab.py
    python tools/research/power_lab.py NIFTY GOLDM
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import weekly_audit as audit  # noqa: E402
from signal_lab import _MCX_FUTURES, available_range, halves, load_bars  # noqa: E402
from bots.strategy.components.entries import ENTRY_MODULES  # noqa: E402
from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES  # noqa: E402

BAR = audit.SHIP_BAR
MIN_N = audit.MIN_N


def bar_for_family(size: int) -> float:
    """The corrected bar for a family of this size.

    THE LEVER NOBODY HAD PRICED. The bar is 3.22 because the audit tests 40
    cells, and required sample scales with its square - so testing 40
    pre-specified cells instead of 4 costs 1.67x the data to prove the SAME
    edge. Three cells already clear a flat 2.0 today and fail only on the
    correction for having looked in 40 places.

    Pre-committing to fewer cells is therefore the cheapest data in the
    system: it buys sample size with discipline instead of time. It is only
    legitimate BEFORE the cells are chosen, and choosing them by their
    current t is exactly the selection this correction exists to punish -
    so the choice has to be made on reasoning that is not the measurement
    being corrected.
    """
    from signal_lab import corrected_t

    return round(corrected_t(size), 2)


def sessions_in(symbol: str, window: tuple[str, str]) -> int:
    """Distinct trading dates of real tape in this window.

    Counted from the bars themselves rather than from the calendar: a holiday,
    a roll or a day Hokage was down all produce a window with fewer sessions
    in it than its dates suggest, and the signal RATE is per session that
    actually existed.
    """
    try:
        bars = load_bars(symbol, window[0], window[1])
    except Exception:
        return 0
    return len({b["date"].date() for b in bars})


def required_n(n: int, t: float) -> float | None:
    """Signals per half needed for this t to reach the bar. None if hopeless."""
    if t <= 0 or n <= 0:
        return None
    return n * (BAR / t) ** 2


def classify(hold: dict | None, train: dict | None) -> str:
    if hold is None or train is None:
        return "NO READING"
    if hold["n"] < MIN_N or train["n"] < MIN_N:
        return "TOO THIN"
    if hold["edge_atr"] <= 0:
        return "WRONG SIGN"
    if hold["t"] >= BAR and train["t"] >= BAR:
        return "CONFIRMED"
    return "UNDERPOWERED"


def main() -> int:
    global BAR
    args = sys.argv[1:]
    family = None
    rest: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--family" and i + 1 < len(args):
            family = int(args[i + 1])
            i += 2
            continue
        rest.append(args[i])
        i += 1
    if family is not None:
        BAR = bar_for_family(family)
    only = {a.upper() for a in rest} or None

    print("=" * 96)
    print("  POWER LAB - how many more sessions until each cell could clear the bar")
    print("=" * 96)
    shown_family = family if family is not None else audit.FAMILY_SIZE
    print(f"  bar           t >= {BAR}  (family of {shown_family} cells, corrected)")
    if family is not None:
        print(f"                HYPOTHETICAL: the audit's own family is "
              f"{audit.FAMILY_SIZE} cells at t >= {audit.SHIP_BAR}. This run asks"
              f" what")
        print(f"                pre-committing to {family} cells would be worth, "
              f"and is only")
        print(f"                honest if the cells are chosen BEFORE seeing these"
              f" numbers.")
    print(f"  geometry      {audit.GEOMETRY}")
    print(f"  rule          the bar must be cleared on BOTH halves, so a cell")
    print(f"                needs its required n in EACH, and the halves split")
    print(f"                whatever tape exists -> sessions = 2 * n_req / rate")
    print()
    print("  A NEGATIVE cell is not under-powered. More data makes it worse.")
    print("  Every number is a FLOOR and assumes the measured edge is the true one.")
    print()

    rows: list[dict] = []
    for symbol in audit.UNIVERSE:
        if only and symbol not in only:
            continue
        modules = MCX_ENTRY_MODULES if symbol in _MCX_FUTURES else ENTRY_MODULES
        try:
            per_module, raw, windows = audit.measure_split(symbol, modules)
        except Exception as exc:
            print(f"  {symbol:<12} could not measure: {type(exc).__name__}: {exc}")
            continue

        train_window, hold_window = windows
        s_train = sessions_in(symbol, train_window)
        s_hold = sessions_in(symbol, hold_window)
        total_sessions = s_train + s_hold
        try:
            span = available_range(symbol)
        except Exception:
            span = ("?", "?")

        print(f"  {symbol}   tape {span[0][:10]} .. {span[1][:10]}   "
              f"{total_sessions} sessions ({s_train} train / {s_hold} hold-out)")

        if not per_module:
            print("      no module reached a readable n on this asset")
            print()
            continue

        for name in sorted(per_module):
            stat = per_module[name]
            hold = {"n": stat["n"], "edge_atr": stat["edge_atr"], "t": stat["t"]}
            # MISSING IS NOT ZERO. The audit stores None, not 0.0, when the
            # train half never reached MIN_N - reading it as zero once made a
            # module that fired 16 times print as "fired nothing, measured
            # flat". A cell with no train reading cannot be judged either way.
            if stat.get("train_below_min_n") or stat.get("t_train") is None:
                train = None
            else:
                train = {"n": stat["n_train"], "edge_atr": stat["edge_train"],
                         "t": stat["t_train"]}
            state = classify(hold, train)

            rate = (hold["n"] / s_hold) if s_hold else 0.0
            need_n = required_n(hold["n"], hold["t"])
            if state == "CONFIRMED":
                detail = "clears both halves"
            elif state == "WRONG SIGN":
                detail = (f"hold-out edge {hold['edge_atr']:+.3f} ATR - "
                          f"answered, and the answer is no")
            elif state == "NO READING":
                detail = ("the train half never reached MIN_N, so neither "
                          "half can be judged - not a verdict either way")
            elif state == "TOO THIN":
                detail = (f"n={hold['n']} hold-out, "
                          f"{train['n'] if train else 0} train, floor {MIN_N}")
            elif need_n is None or rate <= 0:
                detail = "cannot project: no positive t or no signal rate"
            else:
                sessions_needed = 2.0 * need_n / rate
                extra = max(0.0, sessions_needed - total_sessions)
                years = extra / 250.0
                detail = (f"n_req {need_n:,.0f}/half at {rate:.2f} signals/session "
                          f"-> {sessions_needed:,.0f} sessions total, "
                          f"{extra:,.0f} MORE ({years:.1f} yr)")
                rows.append({"symbol": symbol, "module": name, "extra": extra,
                             "t": hold["t"], "edge": hold["edge_atr"],
                             "rate": rate, "n": hold["n"]})

            print(f"      {name:<34} n={hold['n']:<5} edge={hold['edge_atr']:+.3f} "
                  f"t={hold['t']:+.2f}  {state}")
            print(f"      {'':34} {detail}")
        print()

    # ------------------------------------------------------------- the answer
    print("=" * 96)
    print("  RANKED BY REACHABILITY - the cells where more tape is the answer")
    print("=" * 96)
    if not rows:
        print("  No cell is both positive and projectable. More sessions is not")
        print("  the lever; the edge itself has to change.")
    else:
        rows.sort(key=lambda r: r["extra"])
        print(f"  {'cell':<48} {'t now':>7} {'more sessions':>15} {'years':>7}")
        for r in rows:
            cell = f"{r['module']}/{r['symbol']}"
            print(f"  {cell:<48} {r['t']:>+7.2f} {r['extra']:>15,.0f} "
                  f"{r['extra'] / 250.0:>7.1f}")
        best = rows[0]
        print()
        print(f"  Nearest: {best['module']}/{best['symbol']} needs roughly "
              f"{best['extra']:,.0f} more sessions")
        print(f"           ({best['extra'] / 250.0:.1f} years of tape at 250 a year),")
        print(f"           and that is the FLOOR, assuming its edge is real.")
    print()
    print("  READ THIS BEFORE QUOTING ANY NUMBER ABOVE")
    print("  A cell needing more sessions than a career is not a schedule - it is")
    print("  the measurement saying this edge is too small to prove at this")
    print("  horizon. The lever is a bigger edge or a cheaper test, not patience.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
