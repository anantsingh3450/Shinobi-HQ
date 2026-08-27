"""Measure a WEEKLY event honestly: one observation per event, not per bar.

WHY THIS LAB EXISTS SEPARATELY
Every other lab here walks bars and treats each firing as an observation. That
is correct for a module that can fire any time, and badly wrong for a scheduled
weekly release. The EIA natural gas storage report prints once a Thursday at
20:00 IST. Four 15-minute bars inside one release window are ONE event seen four
times — pooling them would quadruple n, shrink the standard error by half, and
manufacture a t-statistic out of nothing.

That is the same trick in a new costume. Pooled t-statistics on a searched
dataset are what convinced this system it had a crude edge it did not have, and
the correction there was to split train from hold-out. The correction here is to
count events.

THE HARD LIMIT, STATED UP FRONT
Kite serves at most 200 days of 15-minute candles. That is roughly 28 Thursdays
in total, so about 14 per half. MIN_N in every other lab is 40. **This event
cannot reach the ship bar on the data that exists**, and no amount of care
changes that. What this lab can honestly answer:

    1. Is there ANY structure in the release bar at all? (the unconditional
       baseline, which needs no module and no threshold)
    2. Does the release move CONTINUE or REVERSE over the following hour?
    3. Do train and hold-out at least AGREE on the sign?

Agreement on sign across two disjoint halves, with a large effect, is weak
evidence. It is not a confirmed edge and must never be reported as one.

FULL GEOMETRY
Realised edge is measured with the production 1.25 ATR thesis stop applied bar
by bar on the low/high, exactly as sweep_lab does. A raw-signal number here
would repeat the crude mistake: +2.06 without a stop, +0.82 with one.

USAGE
    python tools/research/event_lab.py                    # NATURALGAS
    python tools/research/event_lab.py NATURALGAS CRUDEOIL
"""
from __future__ import annotations

import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from signal_lab import MAX_HISTORY_DAYS, Ctx, load_bars  # noqa: E402
from entry_module_lab import build_context  # noqa: E402
from sweep_lab import HORIZON, PROD_STOP_ATR, _stats, realised  # noqa: E402

from bots.strategy.components.mcx_entries import EIAReactionEntry  # noqa: E402

#: Thursday. Monday = 0.
EIA_WEEKDAY = 3

#: 20:00 IST on a 09:00 MCX open.
RELEASE_MIN = 660

def load_max(asset: str) -> list[dict]:
    end = date.today()
    start = end - timedelta(days=MAX_HISTORY_DAYS)
    return load_bars(asset,
                     start.strftime("%Y-%m-%d") + " 09:00:00",
                     end.strftime("%Y-%m-%d") + " 23:30:00")


def sessions(bars: list[dict]) -> dict:
    out = defaultdict(list)
    for b in bars:
        out[b["date"].date()].append(b)
    return out


def release_index(bars: list[dict], day_bars: list[dict]) -> int | None:
    """Index into `bars` of the bar stamped 20:00 on this session."""
    if not day_bars:
        return None
    opened = day_bars[0]["date"]
    for b in day_bars:
        if int((b["date"] - opened).total_seconds() // 60) == RELEASE_MIN:
            return bars.index(b)
    return None


def baseline(asset: str, bars: list[dict]) -> list[tuple]:
    """(date, release move in ATR, what the NEXT HOUR did, in ATR).

    No module, no threshold, no direction. Just: the print moved the tape this
    much, and then the tape did this. If there is no relationship here, every
    threshold and stance tested on top of it is decoration.
    """
    rows = []
    by_day = sessions(bars)
    for day, day_bars in sorted(by_day.items()):
        if day.weekday() != EIA_WEEKDAY:
            continue
        i = release_index(bars, day_bars)
        if i is None or i + 1 + HORIZON >= len(bars):
            continue
        window = bars[: i + 1]
        session = [b for b in window if b["date"].date() == day]
        if len(session) < 6:
            continue
        ctx = Ctx(window, session)
        if not ctx.atr:
            continue
        move = bars[i]["close"] - bars[i - 1]["close"]
        # What the hour after the release bar did, signed the same way as the
        # release move. Positive = the move CONTINUED, negative = it REVERSED.
        call = 1 if move > 0 else -1
        after = realised(bars, i, call, ctx.atr)
        rows.append((day, move / ctx.atr, after))
    return rows


def module_events(asset: str, bars: list[dict], module) -> list[tuple]:
    """(date, direction, realised edge) — at most ONE row per Thursday."""
    rows = []
    by_day = sessions(bars)
    for day, day_bars in sorted(by_day.items()):
        if day.weekday() != EIA_WEEKDAY:
            continue
        opened = day_bars[0]["date"]
        for b in day_bars:
            m = int((b["date"] - opened).total_seconds() // 60)
            if not (module.WINDOW_START_MIN <= m < module.WINDOW_END_MIN):
                continue
            i = bars.index(b)
            if i + HORIZON >= len(bars):
                break
            window = bars[: i + 1]
            session = [x for x in window if x["date"].date() == day]
            if len(session) < 6:
                break
            ctx = Ctx(window, session)
            if not ctx.atr:
                break
            sig = module.evaluate(build_context(asset, window, ctx, session))
            if not sig.should_enter:
                continue
            call = 1 if sig.direction == "long" else -1
            rows.append((day, sig.direction, realised(bars, i, call, ctx.atr)))
            break   # one event, one observation
    return rows


def halve(rows: list[tuple]) -> tuple[list, list]:
    """Older half is train, newer half is hold-out — the hold-out should be the
    tape that most resembles what gets traded next."""
    mid = len(rows) // 2
    return rows[:mid], rows[mid:]


def report(asset: str) -> None:
    print("=" * 88)
    print("  EVENT LAB — the EIA storage print on %s" % asset)
    print("  One observation per Thursday. Realised edge includes the %s ATR "
          "production stop." % PROD_STOP_ATR)
    print("=" * 88)

    try:
        bars = load_max(asset)
    except Exception as exc:
        print("  could not load bars (%s)" % exc)
        return
    print("  %d bars, %s .. %s" % (len(bars), bars[0]["date"].date(), bars[-1]["date"].date()))

    base = baseline(asset, bars)
    print("\n  BASELINE — no module. Does the release move continue or reverse?")
    print("  %-12s %10s %12s" % ("Thursday", "print ATR", "next hour"))
    for day, move, after in base:
        print("  %-12s %+10.2f %+12.3f   %s"
              % (day, move, after, "continued" if after > 0 else "reversed"))
    if base:
        n, mean, t = _stats([r[2] for r in base])
        rev = sum(1 for r in base if r[2] < 0)
        print("  %d Thursdays: mean %+.3f ATR, t=%+.2f, reversed %d/%d"
              % (n, mean, t, rev, n))
        tr, ho = halve(base)
        for label, half in (("train", tr), ("hold ", ho)):
            if half:
                hn, hmean, ht = _stats([r[2] for r in half])
                print("    %s n=%-3d mean %+.3f  t=%+.2f" % (label, hn, hmean, ht))
        print("\n  Positive mean = the print's move CONTINUES, so FOLLOW it.")
        print("  Negative mean = it REVERSES, so FADE it. Sign agreement across")
        print("  both halves is the most this sample size can honestly support.")

    module = EIAReactionEntry()
    for stance in (True, False):
        module.FADE_THE_PRINT = stance
        rows = module_events(asset, bars, module)
        label = "FADE the print" if stance else "FOLLOW the print"
        print("\n  MODULE, %s (reaction bar >= %.2f ATR)"
              % (label, module.MIN_REACTION_ATR))
        if not rows:
            print("    never fired")
            continue
        for day, d, edge in rows:
            print("    %-12s %-6s %+8.3f" % (day, d, edge))
        n, mean, t = _stats([r[2] for r in rows])
        print("    %d events: mean %+.3f ATR, t=%+.2f" % (n, mean, t))
        tr, ho = halve(rows)
        for lbl, half in (("train", tr), ("hold ", ho)):
            if len(half) >= 2:
                hn, hmean, ht = _stats([r[2] for r in half])
                print("      %s n=%-3d mean %+.3f  t=%+.2f" % (lbl, hn, hmean, ht))

    print("\n  REMINDER: ~28 Thursdays exist in total. Nothing here can clear")
    print("  t>=2 on both halves at this sample size, and nothing here should")
    print("  be described as confirmed. Sign agreement plus a large effect is")
    print("  weak evidence — enough to justify watching, not enough to size.\n")


def main() -> int:
    for asset in (sys.argv[1:] or ["NATURALGAS"]):
        report(asset.upper())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
