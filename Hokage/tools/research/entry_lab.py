"""Is Hokage chasing? Where in a move the entries actually happen.

WHY THIS AND NOT MORE EXIT WORK. Two measurements now point the same way.
`exit_lab` found that net tracks TARGET-HIT RATE across the whole book -
SILVERM reaches target 37% of the time and nets +20,225, SENSEX 17% and
-6,584 - and `thesis_stop_lab` found that widening the stop cannot help,
because the median stopped-out trade travels 2.56 ATR against before any
recovery and a 2.50 ATR stop still fires 51% of the time. A position whose
underlying routinely runs that far against it was entered at the wrong
moment. The stop is the messenger.

THE TESTABLE VERSION OF "WRONG MOMENT". If the entries are late - taken
after the move they are betting on has already happened - then the remaining
distance to target is short and the distance to the stop is long, which is
exactly the shape of a 20% target-hit rate. So:

    at the moment of entry, how far had the underlying ALREADY moved
    in the position's favour that session?

Measured in ATR, split by how the trade ended. If the trades that reach
target enter early in a move and the ones that stop out enter late, chasing
is real and measurable, and a refusal gate can be built on it. If both groups
enter at the same point, chasing is not the story and this is a dead end
worth closing cheaply.

THE ATR HERE IS THIS TOOL'S OWN RULER, and that is stated rather than hidden.
`thesis_stop_lab` parses ATR out of production exit reasons because it is
reproducing a decision production made; nothing like that exists for entries,
so this computes a 14-bar ATR on 15-minute candles. That makes the ABSOLUTE
numbers incomparable with production's, and the COMPARISON BETWEEN GROUPS
valid, because every group is measured with the same ruler.

IT PROPOSES NOTHING AND GATES NOTHING. It measures.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

BRAIN = Path(r"C:\Hokage\hokage_brain")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

#: Bars of true range averaged for the ATR. 14 is the convention production
#: uses elsewhere; the point is consistency across groups, not the number.
ATR_BARS = 14

UNDERLYINGS = ("CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM",
               "BANKNIFTY", "NIFTY", "SENSEX")


def underlying_of(market: str) -> str | None:
    up = str(market or "").upper()
    for name in UNDERLYINGS:
        if up.startswith(name):
            return name
    return None


def bullish(market: str) -> bool | None:
    up = str(market or "").upper()
    if up.endswith("CE"):
        return True
    if up.endswith("PE"):
        return False
    return None


def classify(exit_reason: str | None) -> str:
    text = (exit_reason or "").lower()
    if not text.strip():
        return "UNRECORDED"
    if "thesis stop" in text:
        return "THESIS STOP"
    if "hard backstop" in text:
        return "HARD BACKSTOP"
    if "target" in text:
        return "TARGET HIT"
    if "trail" in text:
        return "TRAILING"
    if any(w in text for w in ("square", "session close", "eod", "cutoff")):
        return "SESSION CLOSE"
    return "OTHER"


def _utc(stamp) -> dt.datetime | None:
    if isinstance(stamp, dt.datetime):
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)
    if not stamp:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _true_ranges(bars: list[tuple]) -> list[float]:
    out = []
    for index in range(1, len(bars)):
        _t, high, low, close = bars[index]
        _pt, _ph, _pl, prev_close = bars[index - 1]
        out.append(max(high - low, abs(high - prev_close),
                       abs(low - prev_close)))
    return out


class Entry:
    __slots__ = ("market", "underlying", "up", "mechanism", "pnl",
                 "entry_ist", "prior_move_atr", "bars_in", "atr",
                 "strategy_id", "note")

    def __init__(self, **kw):
        for key in self.__slots__:
            setattr(self, key, kw.get(key))


def measure(hokage_db: Path | None = None,
            candles_db: Path | None = None) -> tuple[list[Entry], dict]:
    hpath = Path(hokage_db) if hokage_db else (BRAIN / "hokage.db")
    cpath = Path(candles_db) if candles_db else (BRAIN / "candles.db")

    hcon = sqlite3.connect(f"{hpath.as_uri()}?mode=ro", uri=True, timeout=10)
    try:
        positions = hcon.execute(
            "SELECT market, realized_pnl, opened_at, closed_at, strategy_id"
            " FROM positions"
            " WHERE status = 'CLOSED'"
            "   AND (failure_reason IS NULL OR failure_reason NOT LIKE 'PHANTOM%')"
        ).fetchall()
        outcomes = hcon.execute(
            "SELECT timestamp, exit_reason FROM decision_outcomes").fetchall()
    finally:
        hcon.close()

    stamped = [(_utc(t), r) for t, r in outcomes]
    stamped = [(t, r) for t, r in stamped if t is not None]

    quality = {"positions": 0, "measured": 0, "no_mechanism": 0,
               "no_candles": 0, "thin_history": 0, "flat_atr": 0}
    rows: list[Entry] = []

    ccon = sqlite3.connect(f"{cpath.as_uri()}?mode=ro", uri=True, timeout=10)
    try:
        for market, pnl, opened_at, closed_at, strategy_id in positions:
            quality["positions"] += 1
            opened = _utc(opened_at)
            closed = _utc(closed_at)
            symbol = underlying_of(market)
            up = bullish(market)
            if opened is None or symbol is None or up is None:
                quality["no_mechanism"] += 1
                continue

            mechanism = None
            if closed is not None:
                for when, text in stamped:
                    if abs((when - closed).total_seconds()) <= 5.0:
                        mechanism = classify(text)
                        break
            if mechanism is None:
                quality["no_mechanism"] += 1
                continue

            entry_ist = opened.astimezone(IST)
            # Every bar for this symbol at or before entry, newest last.
            bars = ccon.execute(
                "SELECT ts, high, low, close FROM candles"
                " WHERE symbol = ? AND ts <= ? ORDER BY ts DESC LIMIT ?",
                (symbol, entry_ist.strftime("%Y-%m-%d %H:%M:%S"),
                 ATR_BARS + 1)).fetchall()
            parsed = []
            for ts, high, low, close in reversed(bars):
                if high is None or low is None or close is None:
                    continue
                try:
                    when = dt.datetime.fromisoformat(ts).replace(tzinfo=IST)
                except ValueError:
                    continue
                parsed.append((when, float(high), float(low), float(close)))
            if len(parsed) < 3:
                quality["thin_history"] += 1
                rows.append(Entry(market=market, underlying=symbol, up=up,
                                  mechanism=mechanism, pnl=pnl,
                                  entry_ist=entry_ist,
                                  note="not enough candles for an ATR"))
                continue

            ranges = _true_ranges(parsed)
            atr = statistics.fmean(ranges) if ranges else 0.0
            if atr <= 0:
                quality["flat_atr"] += 1
                rows.append(Entry(market=market, underlying=symbol, up=up,
                                  mechanism=mechanism, pnl=pnl,
                                  entry_ist=entry_ist, note="flat ATR"))
                continue

            # The session's own bars, to find where the move started.
            session = ccon.execute(
                "SELECT ts, high, low, close FROM candles"
                " WHERE symbol = ? AND substr(ts,1,10) = ? AND ts <= ?"
                " ORDER BY ts", (symbol, entry_ist.date().isoformat(),
                                 entry_ist.strftime("%Y-%m-%d %H:%M:%S"))
            ).fetchall()
            if not session:
                quality["no_candles"] += 1
                rows.append(Entry(market=market, underlying=symbol, up=up,
                                  mechanism=mechanism, pnl=pnl,
                                  entry_ist=entry_ist,
                                  note="no session candles before entry"))
                continue

            session_open = float(session[0][3])
            at_entry = float(session[-1][3])
            moved = (at_entry - session_open) if up else (session_open - at_entry)

            quality["measured"] += 1
            rows.append(Entry(
                market=market, underlying=symbol, up=up, mechanism=mechanism,
                pnl=pnl, entry_ist=entry_ist, prior_move_atr=moved / atr,
                bars_in=len(session), atr=atr, strategy_id=strategy_id,
                note=None))
    finally:
        ccon.close()

    return rows, quality


def _stats(values: list[float]) -> str:
    if not values:
        return "       -        -        -"
    ordered = sorted(values)
    p25 = ordered[int(len(ordered) * 0.25)]
    p75 = ordered[int(len(ordered) * 0.75)]
    return f"{p25:+8.2f} {statistics.median(ordered):+8.2f} {p75:+8.2f}"


def report(hokage_db: Path | None = None,
           candles_db: Path | None = None) -> str:
    rows, quality = measure(hokage_db, candles_db)
    good = [r for r in rows if r.note is None]
    lines = ["", "HOKAGE ENTRY LAB - is it chasing?", "=" * 64, ""]

    lines.append("COVERAGE (every exclusion counted)")
    lines.append(f"  real closed positions        {quality['positions']}")
    lines.append(f"  measured                     {quality['measured']}")
    lines.append(f"  no matched exit mechanism    {quality['no_mechanism']}")
    lines.append(f"  no session candles           {quality['no_candles']}")
    lines.append(f"  too few candles for an ATR   {quality['thin_history']}")
    lines.append(f"  flat ATR                     {quality['flat_atr']}")
    lines.append("")
    if not good:
        lines.append("  Nothing measurable. No conclusion, which is not the")
        lines.append("  same as chasing being ruled out.")
        lines.append("")
        return "\n".join(lines)

    lines.append("-" * 64)
    lines.append("HOW FAR THE UNDERLYING HAD ALREADY MOVED IN OUR FAVOUR")
    lines.append("AT THE MOMENT OF ENTRY, in ATR, by how the trade ended")
    lines.append("")
    lines.append(f"  {'ended as':16s} {'n':>3s} {'p25':>8s} {'median':>8s} "
                 f"{'p75':>8s} {'bars in':>8s}")
    order = ["TARGET HIT", "TRAILING", "SESSION CLOSE", "THESIS STOP",
             "HARD BACKSTOP", "OTHER", "UNRECORDED"]
    present = [m for m in order if any(r.mechanism == m for r in good)]
    for mechanism in present:
        mine = [r for r in good if r.mechanism == mechanism]
        moves = [r.prior_move_atr for r in mine]
        bars = statistics.median([r.bars_in for r in mine])
        lines.append(f"  {mechanism:16s} {len(mine):3d} {_stats(moves)} "
                     f"{bars:8.0f}")
    lines.append("")
    lines.append("  Positive = the move was already underway when we entered.")
    lines.append("  Negative = we entered against the session so far.")
    lines.append("")

    winners = [r.prior_move_atr for r in good
               if r.mechanism in ("TARGET HIT", "TRAILING")]
    losers = [r.prior_move_atr for r in good
              if r.mechanism in ("THESIS STOP", "HARD BACKSTOP")]
    if winners and losers:
        wm = statistics.median(winners)
        lm = statistics.median(losers)
        lines.append("-" * 64)
        lines.append("THE ANSWER")
        lines.append("")
        lines.append(f"  reached target or trailed out : median {wm:+.2f} ATR "
                     f"already moved  (n={len(winners)})")
        lines.append(f"  stopped out                   : median {lm:+.2f} ATR "
                     f"already moved  (n={len(losers)})")
        lines.append("")
        gap = lm - wm
        if abs(gap) < 0.15:
            lines.append(f"  The gap is {gap:+.2f} ATR - nothing. Both groups")
            lines.append("  enter at the same point in a move, so CHASING IS")
            lines.append("  NOT THE STORY and this line of enquiry is closed.")
            lines.append("  Whatever separates a winner from a loser here, it")
            lines.append("  is not how late the entry was.")
        elif gap > 0:
            lines.append(f"  Stopped-out trades enter {gap:+.2f} ATR LATER into")
            lines.append("  the move than ones that reach target. That is")
            lines.append("  chasing, it is measurable, and a refusal gate on")
            lines.append("  prior move could be built and measured.")
        else:
            lines.append(f"  Stopped-out trades enter {gap:+.2f} ATR EARLIER")
            lines.append("  than ones that reach target - the opposite of")
            lines.append("  chasing. The winners are the ones that wait for")
            lines.append("  confirmation, which is a different fix entirely.")
        lines.append("")

    # THE OBVIOUS CONFOUND. Momentum modules enter late by construction, and
    # if the momentum modules happen to own the profitable assets then the
    # gap above is a MODULE effect wearing a timing costume. Split by module
    # and the two explanations separate: a timing effect shows up INSIDE a
    # module, a module effect only between them.
    lines.append("-" * 64)
    lines.append("IS IT A MODULE EFFECT INSTEAD? (same split, within module)")
    lines.append("")
    lines.append(f"  {'module':34s} {'won':>8s} {'stopped':>9s} {'gap':>7s}")
    by_module: dict = {}
    for row in good:
        by_module.setdefault(row.strategy_id or "<none>", []).append(row)
    for module, mine in sorted(by_module.items()):
        w = [r.prior_move_atr for r in mine
             if r.mechanism in ("TARGET HIT", "TRAILING")]
        s = [r.prior_move_atr for r in mine
             if r.mechanism in ("THESIS STOP", "HARD BACKSTOP")]
        if not w or not s:
            lines.append(f"  {module[:34]:34s} {'-':>8s} {'-':>9s} {'-':>7s}"
                         f"   (one side only, n={len(mine)})")
            continue
        wm, sm = statistics.median(w), statistics.median(s)
        lines.append(f"  {module[:34]:34s} {wm:+8.2f} {sm:+9.2f} "
                     f"{sm - wm:+7.2f}")
    lines.append("")
    lines.append("  A negative gap INSIDE a module means the late entries won")
    lines.append("  for that module's own trades, which no module effect can")
    lines.append("  explain. A gap that only appears between modules means")
    lines.append("  this is about which module trades what, not about timing.")
    lines.append("")

    lines.append("-" * 64)
    lines.append("PER ASSET (median prior move at entry, in ATR)")
    lines.append("")
    lines.append(f"  {'asset':12s} {'n':>3s} {'won':>8s} {'stopped':>9s} "
                 f"{'gross':>10s}")
    for asset in sorted({r.underlying for r in good}):
        mine = [r for r in good if r.underlying == asset]
        w = [r.prior_move_atr for r in mine
             if r.mechanism in ("TARGET HIT", "TRAILING")]
        s = [r.prior_move_atr for r in mine
             if r.mechanism in ("THESIS STOP", "HARD BACKSTOP")]
        gross = sum(float(r.pnl or 0) for r in mine)
        wtxt = f"{statistics.median(w):+.2f}" if w else "-"
        stxt = f"{statistics.median(s):+.2f}" if s else "-"
        lines.append(f"  {asset:12s} {len(mine):3d} {wtxt:>8s} {stxt:>9s} "
                     f"{gross:+10,.0f}")
    lines.append("")
    lines.append("  The ATR here is this tool's own 14-bar ruler, not")
    lines.append("  production's. Absolute values are not comparable with")
    lines.append("  the audit; the comparison BETWEEN groups is, because")
    lines.append("  every group is measured the same way.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Where entries sit in a move.")
    parser.add_argument("--hokage-db", default=None)
    parser.add_argument("--candles-db", default=None)
    args = parser.parse_args(argv)
    print(report(
        Path(args.hokage_db) if args.hokage_db else None,
        Path(args.candles_db) if args.candles_db else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
