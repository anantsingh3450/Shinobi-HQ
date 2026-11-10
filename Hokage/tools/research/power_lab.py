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
from hokage.research import funded_cells  # noqa: E402
from bots.strategy.components.entries import ENTRY_MODULES  # noqa: E402
from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES  # noqa: E402

#: THERE IS NO SINGLE BAR IN THIS SYSTEM, AND THIS FILE ASSUMED THERE WAS.
#:
#: Found 2026-11-10, one day after the funded family shipped. weekly_audit
#: grew `bar_for(module, symbol)` on 2026-11-09: a funded cell answers to the
#: bar for the three pre-committed cells, everything else to the bar for the
#: whole family it was found in. This file was written the same day and kept
#: reading SHIP_BAR for every cell.
#:
#: Required sample scales with (bar/t)^2, so judging a funded cell at 3.22
#: instead of 2.39 inflates its requirement by (3.22/2.39)^2 = 1.82x.
#:
#: WHAT IT COST, AND IT WAS NOT THEORETICAL. The two nearest cells in the
#: system are both funded. Priced at the wrong bar they read 176 and 133 more
#: sessions - two years and eighteen months - and those were the numbers put
#: to the commander on 2026-11-10 as the case for lowering the bar. They are
#: already judged at the lower one. A tool answering "how far from real money"
#: was arguing to weaken a bar that had been weakened for exactly those cells.
#:
#: `classify` was wrong the same way and more visibly: a funded cell clearing
#: its own bar on both halves is CONFIRMED by the audit and printed
#: UNDERPOWERED here.
#:
#: So `BAR` is gone rather than corrected. A module-level "the bar" is the
#: defect - it reads as universal and every caller that forgets to ask gets
#: the wide one silently. `required_n` and `classify` now REQUIRE a bar.
EXPLORATORY_BAR = audit.SHIP_BAR
FUNDED_BAR = audit.FUNDED_BAR
MIN_N = audit.MIN_N

#: Set only by --family N: judge EVERY cell at the bar for a family of N, to
#: price what pre-committing to N cells would be worth. Hypothetical by
#: definition - see bar_for_family.
FAMILY_OVERRIDE: float | None = None


def bar_for_cell(module_id: str | None, symbol: str | None) -> float:
    """The bar THIS cell is judged at - the audit's own, never a global."""
    if FAMILY_OVERRIDE is not None:
        return FAMILY_OVERRIDE
    return audit.bar_for(module_id, symbol)


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


def required_n(n: int, t: float, bar: float) -> float | None:
    """Signals per half needed for this t to reach `bar`. None if hopeless.

    `bar` is a required argument, not a default. A default would have hidden
    exactly the bug this signature exists to prevent: the caller that forgets
    to ask which bar applies gets the widest one and never finds out.
    """
    if t <= 0 or n <= 0:
        return None
    return n * (bar / t) ** 2


def effect(n: int | None, t: float | None) -> float | None:
    """Per-signal effect size, d = t / sqrt(n). None if unreadable.

    This is the quantity that does not change with sample size - the thing a
    projection has to hold fixed. t itself grows with sqrt(n), so projecting
    from t without dividing it out is projecting from the answer.
    """
    if not n or n <= 0 or t is None:
        return None
    return t / math.sqrt(n)


def pooled_effect(hold: dict, train: dict) -> float | None:
    """ONE effect size from BOTH halves, weighted by their n.

    THE SECOND WAY THIS FILE OVERSTATED AN ANSWER, found 2026-11-10 beside the
    per-cell bar. `classify` requires the bar to be cleared on BOTH halves -
    that rule is the reason every number here is doubled - and then the
    requirement itself was computed from the HOLD-OUT half alone. So a cell
    was priced on whichever half flattered it.

    It was not a rounding difference. MacroBreakout/SENSEX reads t +2.31 on
    the hold-out and +1.00 on the train half; priced on the hold-out alone it
    needed 11 more sessions, which is three weeks. Pooled, it needs about ten
    times that. "Eleven sessions" was a date for something that was not
    coming, which is the one thing this file's header forbids.

    Weighted by n rather than averaged: the halves split whatever tape exists
    and are rarely equal, so the bigger half carries more of the estimate.
    Deliberately the simple pooling - an elaborate one invites tuning.

    Returns None when the halves disagree in SIGN. A cell positive on one half
    and negative on the other has no single effect to project, and averaging
    them to a small positive would manufacture exactly the hope this file
    exists to refuse.
    """
    d_hold = effect(hold.get("n"), hold.get("t"))
    d_train = effect(train.get("n"), train.get("t"))
    if d_hold is None or d_train is None:
        return None
    if d_hold <= 0 or d_train <= 0:
        return None
    n_hold, n_train = hold["n"], train["n"]
    return (d_hold * n_hold + d_train * n_train) / (n_hold + n_train)


def required_n_pooled(hold: dict, train: dict, bar: float) -> float | None:
    """Signals per half needed, from both halves' evidence. None if hopeless."""
    d = pooled_effect(hold, train)
    if d is None or d <= 0:
        return None
    return (bar / d) ** 2


def halves_disagree(hold: dict, train: dict, ratio: float = 1.5) -> bool:
    """Whether the two halves' effect sizes differ enough to say so out loud.

    Not a verdict - a cell whose halves disagree is exactly a cell whose
    pooled estimate is doing real work, and the reader should see that rather
    than a single tidy number.
    """
    d_hold = effect(hold.get("n"), hold.get("t"))
    d_train = effect(train.get("n"), train.get("t"))
    if d_hold is None or d_train is None:
        return False
    if d_hold <= 0 or d_train <= 0:
        return True
    hi, lo = max(d_hold, d_train), min(d_hold, d_train)
    return hi / lo >= ratio


def classify(hold: dict | None, train: dict | None, bar: float) -> str:
    """The cell's state at ITS bar. See required_n on why `bar` is required."""
    if hold is None or train is None:
        return "NO READING"
    if hold["n"] < MIN_N or train["n"] < MIN_N:
        return "TOO THIN"
    if hold["edge_atr"] <= 0:
        return "WRONG SIGN"
    if hold["t"] >= bar and train["t"] >= bar:
        return "CONFIRMED"
    return "UNDERPOWERED"


def main() -> int:
    global FAMILY_OVERRIDE
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
        FAMILY_OVERRIDE = bar_for_family(family)
    only = {a.upper() for a in rest} or None

    print("=" * 96)
    print("  POWER LAB - how many more sessions until each cell could clear the bar")
    print("=" * 96)
    if family is not None:
        print(f"  bar           t >= {FAMILY_OVERRIDE}  for EVERY cell "
              f"(hypothetical family of {family})")
        print(f"                HYPOTHETICAL: the real bars are "
              f"{EXPLORATORY_BAR} for the {audit.FAMILY_SIZE}-cell family and "
              f"{FUNDED_BAR} for")
        print(f"                the {funded_cells.family_size()} funded cells. "
              f"This run asks what pre-committing to {family} cells")
        print(f"                would be worth, and is only honest if the cells "
              f"are chosen BEFORE")
        print(f"                seeing these numbers.")
    else:
        print(f"  bars          t >= {EXPLORATORY_BAR} exploratory "
              f"({audit.FAMILY_SIZE} cells)   ·   t >= {FUNDED_BAR} funded "
              f"({funded_cells.family_size()} cells)")
        print(f"                EVERY CELL IS PRICED AT ITS OWN BAR, printed on "
              f"its row. There is no")
        print(f"                single bar: a funded cell answers to the family "
              f"it was pre-committed")
        print(f"                in, an exploratory one to the family it was "
              f"found in.")
    print(f"  geometry      {audit.GEOMETRY}")
    print(f"  rule          the bar must be cleared on BOTH halves, so a cell")
    print(f"                needs its required n in EACH, and the halves split")
    print(f"                whatever tape exists -> sessions = 2 * n_req / rate")
    print()
    print("  A NEGATIVE cell is not under-powered. More data makes it worse.")
    print("  Every number is a FLOOR and assumes the measured edge is the true one.")
    print("  The requirement is POOLED over both halves, because both have to")
    print("  clear - pricing a cell on its better half is how 11 sessions gets")
    print("  printed for a cell whose other half reads t +1.00.")
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
            cell_bar = bar_for_cell(name, symbol)
            state = classify(hold, train, cell_bar)

            rate = (hold["n"] / s_hold) if s_hold else 0.0
            # BOTH HALVES, because both have to clear. See pooled_effect.
            need_n = (required_n_pooled(hold, train, cell_bar)
                      if train else None)
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
                if train and rate > 0:
                    detail = ("the two halves disagree in SIGN, so there is no "
                              "one effect to project from - not a verdict, and "
                              "not a schedule either")
                else:
                    detail = "cannot project: no positive t or no signal rate"
            else:
                sessions_needed = 2.0 * need_n / rate
                extra = max(0.0, sessions_needed - total_sessions)
                years = extra / 250.0
                detail = (f"n_req {need_n:,.0f}/half at {rate:.2f} signals/session "
                          f"-> {sessions_needed:,.0f} sessions total, "
                          f"{extra:,.0f} MORE ({years:.1f} yr)")
                if extra <= 0:
                    # "0 MORE" reads as "it is there", and it is not. The cell
                    # has banked the sample its own pooled effect needs and
                    # still reads below the bar on at least one half, which
                    # means it is inside the noise of its own answer. More
                    # tape moves it EITHER way, and that is a different fact
                    # from "three more weeks".
                    detail += (f"\n      {'':34} already AT the pooled "
                               f"requirement ({hold['n']} hold / "
                               f"{train['n']} train vs {need_n:,.0f} needed) "
                               f"- not confirmed because its halves read "
                               f"{hold['t']:+.2f} and {train['t']:+.2f} "
                               f"against bar {cell_bar}. It is inside the "
                               f"noise of its own bar: more tape answers it "
                               f"either way.")
                if halves_disagree(hold, train):
                    detail += (f"\n      {'':34} halves t {hold['t']:+.2f} "
                               f"hold / {train['t']:+.2f} train - they "
                               f"disagree, so this is the POOLED estimate")
                rows.append({"symbol": symbol, "module": name, "extra": extra,
                             "t": hold["t"], "edge": hold["edge_atr"],
                             "rate": rate, "n": hold["n"], "bar": cell_bar,
                             "funded": audit.is_funded_cell(name, symbol)})

            # THROUGH THE AUDIT, in either namespace. Asking
            # funded_cells.is_funded directly is the bug this commit fixes;
            # it happens to work here because power_lab passes strat-* keys,
            # and "happens to work" is how the audit's own call was written.
            tag = "  [FUNDED]" if audit.is_funded_cell(name, symbol) else ""
            print(f"      {name:<34} n={hold['n']:<5} edge={hold['edge_atr']:+.3f} "
                  f"t={hold['t']:+.2f}  bar {cell_bar}  {state}{tag}")
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
        print(f"  {'cell':<48} {'t now':>7} {'bar':>6} {'more sessions':>15} "
              f"{'years':>7}")
        for r in rows:
            cell = f"{r['module']}/{r['symbol']}"
            if r.get("funded"):
                cell += " *"
            print(f"  {cell:<48} {r['t']:>+7.2f} {r['bar']:>6.2f} "
                  f"{r['extra']:>15,.0f} {r['extra'] / 250.0:>7.1f}")
        if any(r.get("funded") for r in rows):
            print("  * funded cell, priced at the bar for the pre-committed "
                  "family rather than the full one")
        best = rows[0]
        print()
        if best["extra"] <= 0:
            print(f"  Nearest: {best['module']}/{best['symbol']} is ALREADY at "
                  f"its requirement and still")
            print(f"           below its bar - it is inside the noise of its "
                  f"own answer, and the")
            print(f"           next re-measure decides it either way. No "
                  f"amount of waiting is owed.")
        else:
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
