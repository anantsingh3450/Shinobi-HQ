"""Did the modules stop firing, or did the lineup stop existing?

    python tools/research/signal_rate_lab.py
    python tools/research/signal_rate_lab.py NIFTY GOLDM

WHY THIS EXISTS. The last position Hokage opened was 2026-09-22. In August he
traded most weeks. Two explanations fit that equally well from the outside and
they call for opposite responses:

    THE LINEUP SHRANK   five commander-approved archivals and two parkings
                        took the tradeable grid from 56 cells to 7. Fewer
                        cells, fewer signals, nothing broken. The drought is
                        a consequence of decisions that were each correct.

    THE CELLS WENT QUIET  the surviving modules fire less often than they
                        used to on the same kind of tape. That would be a
                        regression, and it would be invisible in the gate
                        tally, which only counts refusals of signals that
                        were FOUND.

On 2026-10-16, 69 of 78 no-trade reasons were ENTRY_SIGNAL: the module itself
declining, not a gate refusing it. That is the reading this lab exists to
disambiguate, and the gate tally cannot do it - a module that stops firing
produces fewer tallied refusals, not more, so starvation by regression looks
exactly like a quiet market.

WHAT IT MEASURES. For every live (module, asset) cell, month by month, over
the candle archive:

    eligible   contexts the module was actually asked about
    fired      how many it said yes to
    rate       fired per 100 eligible

NO EDGE IS MEASURED HERE, deliberately. This counts how often a module speaks,
not whether it is right - which is holdout_lab's and the weekly audit's job,
at a corrected bar. A high rate is not good news.

IT IS AN UPPER BOUND, AND THE NUMBER MUST NOT BE READ AS "SIGNALS PRODUCTION
SAW". Two differences, both of which push this count UP:

  * It asks on EVERY eligible bar. Production asks once per scan cycle, and
    only for assets that are in scope, unparked and inside their window.
  * The context carries regime="UNKNOWN" and vix_percentile=None, because
    neither is archived. A module that leans on either is being asked an
    easier question here than production asks it.

So a FALL in this rate is evidence of a regression, and a healthy rate is
evidence against one. Neither direction licenses a claim about how many
entries production should have taken.

MISSING IS NOT ZERO. A month with no archived bars prints "-", never 0.0. The
archive begins 2026-02-13 for the indices and 2026-05-20 for the energies, and
a zero there would read as a module that went silent when in truth nothing was
ever asked of it.

ELIGIBILITY COMES FROM signal_lab.measurable, not from a copy of its rules.
The first run of this lab made its own copy and reported "-" for every month
of NIFTY, BANKNIFTY and SENSEX: the archive stores an index's volume as 0
rather than NULL, because an index is a calculation and nothing trades it, so
a flat "the entry bar must have traded" check silently deletes three of the
seven live cells. measurable() asks whether the SERIES carries volume at all
before using a zero as evidence, and it already carried that fix.
"""
from __future__ import annotations

import argparse
import collections
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

from candle_archive import load as archive_load  # noqa: E402
from entry_module_lab import build_context  # noqa: E402
from holdout_lab import live_pairs  # noqa: E402
from signal_lab import Ctx, measurable  # noqa: E402

from bots.strategy.components.entries import ENTRY_MODULES  # noqa: E402
from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES  # noqa: E402

#: Bars of history a context needs before a module may be asked. Matches the
#: other labs: the longest trailing window any module uses is EMA21 over 42.
WARMUP = 42

#: Minimum bars of the current session before a context is built, so a module
#: gated on minutes_into_session is not asked at a time production never asks.
MIN_SESSION_BARS = 6


def _modules() -> dict:
    return {getattr(m, "module_id", k): m
            for k, m in {**ENTRY_MODULES, **MCX_ENTRY_MODULES}.items()}


def count_by_month(symbol: str, module) -> dict[str, tuple[int, int]]:
    """{month: (eligible, fired)} for one cell over the whole archive."""
    bars = archive_load(symbol, "2000-01-01", "2100-01-01")
    out: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0])
    for i in range(WARMUP, len(bars)):
        window = bars[: i + 1]
        day = window[-1]["date"].date()
        session = [b for b in window if b["date"].date() == day]
        if len(session) < MIN_SESSION_BARS:
            continue
        ctx = Ctx(window, session)
        # signal_lab.measurable, NOT a hand-rolled copy of its rules. The
        # first run of this lab rolled its own and rejected every bar of
        # NIFTY, BANKNIFTY and SENSEX - the archive stores an index's volume
        # as 0 rather than NULL, because an index is a calculation and
        # nothing trades it, so a flat "the entry bar must have traded" check
        # deletes the whole index universe. measurable() asks the SERIES
        # instead, and already carries that fix.
        if not measurable(ctx, bars[i]):
            continue

        month = day.strftime("%Y-%m")
        cell = out[month]
        cell[0] += 1
        try:
            sig = module.evaluate(build_context(symbol, window, ctx, session))
        except Exception:
            # A module that raises is not a module that declined. The context
            # still counts as asked, so a crash shows up as a collapsing rate
            # rather than disappearing from the denominator too.
            continue
        if getattr(sig, "should_enter", False):
            cell[1] += 1
    return {m: (c[0], c[1]) for m, c in out.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("symbols", nargs="*")
    args = ap.parse_args()
    want = {s.upper() for s in args.symbols}

    modules = _modules()
    cells = sorted(live_pairs(), key=lambda p: (p[2], p[1]))
    if want:
        cells = [c for c in cells if c[1] in want]

    print("=" * 96)
    print("  SIGNAL RATE — how often each LIVE cell speaks, month by month")
    print("  The last position Hokage opened was 2026-09-22. This separates a")
    print("  lineup that shrank from modules that went quiet.")
    print("  rate = signals fired per 100 eligible contexts. '-' is NO DATA,")
    print("  which is not the same fact as 0.0.")
    print("  No edge is measured here. A high rate is not good news.")
    print("  UPPER BOUND: every eligible bar is asked, and the context carries")
    print("  no regime and no VIX. A fall is evidence; the level is not.")
    print("  The newest month is partial — judge the RATE, not the count.")
    print("=" * 96)

    months: list[str] = []
    table: dict[tuple[str, str], dict[str, tuple[int, int]]] = {}
    for mid, asset, sname in cells:
        module = modules.get(mid)
        if module is None:
            print(f"\n  {sname}/{asset}: module {mid} not found")
            continue
        try:
            by_month = count_by_month(asset, module)
        except Exception as exc:
            print(f"\n  {sname}/{asset}: {exc}")
            continue
        table[(sname, asset)] = by_month
        for m in by_month:
            if m not in months:
                months.append(m)
    months.sort()

    if not table:
        print("\n  No live cells to measure.")
        return 1

    head = "  %-26s" % "cell" + "".join("%9s" % m[-5:] for m in months)
    print("\n" + head)
    print("  " + "-" * (len(head) - 2))
    for (sname, asset), by_month in sorted(table.items()):
        row = "  %-26s" % f"{sname}/{asset}"
        for m in months:
            if m not in by_month:
                row += "%9s" % "-"
                continue
            eligible, fired = by_month[m]
            row += "%9s" % ("%.2f" % (fired / eligible * 100.0) if eligible
                            else "-")
        print(row)

    print("\n  signals fired (eligible contexts in brackets)")
    for (sname, asset), by_month in sorted(table.items()):
        row = "  %-26s" % f"{sname}/{asset}"
        for m in months:
            eligible, fired = by_month.get(m, (0, 0))
            row += "%9s" % (f"{fired}/{eligible}" if m in by_month else "-")
        print(row)

    print("\n  Read it against the lineup, not on its own: a flat rate with")
    print("  fewer cells is a drought the commander chose by archiving them.")
    print("  A falling rate on a surviving cell is a regression, and the gate")
    print("  tally cannot show it — a module that stops firing produces FEWER")
    print("  tallied refusals, not more.")
    print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
