"""What the exits do to the edge, measured in rupees.

THE QUESTION THIS ANSWERS. The weekly audit measures signal edge in ATR on a
hold-out and the account measures rupees after costs, and the two disagree:
`entry-sessionshift-mcx-v1/GOLDM` returns 17% of its measured edge over 16
fills. The audit's own closing line says the next step is "to measure what
sits between them - the exits". This is that measurement.

WHAT IT FOUND ON FIRST RUN (127 outcomes, 2026-07-15 to 2026-11-11):

    THESIS STOP (1.25 ATR on underlying)   46  36%   -62,562  avg -1,360
    HARD BACKSTOP (premium -12%)           16  13%   -43,505  avg -2,719
    SESSION CLOSE                           8   6%    -8,086  avg -1,011
    TRAILING                                20  16%   +11,678  avg   +584
    TARGET HIT                              37  29%  +108,794  avg +2,940

Targets pay. The two stops are 49% of all exits and -106,066 between them,
and flat brokerage then takes about 10,500 across the 127 round trips. The
hard backstop is the worst line per trade in the system, which is the ladder
flaw in rupees: the trail arms only after +5%, so a position that never gets
there has no protection until -12%.

IT PROPOSES NOTHING. Every stop value here is a commander-approved risk
constant. This tool measures and prints; it does not tune. That separation is
the loop closed on 2026-08-26 - a system that adjusts its own stops on a
quiet month is raising its own risk with nobody deciding anything.

WHAT IT CANNOT ANSWER, AND WHY THAT MATTERS MORE THAN WHAT IT CAN.
"Would a -5% stop have been cheaper than -12%" needs the premium PATH of
each losing trade. The option chain archive holds ONE snapshot a day, at
about 15:58, starting 2026-10-19 - and these positions are held 11 to 77
minutes. Option premium history dies with the contract, so for trades
already closed this is not a gap that can be back-filled. It is gone.

The two stops split on exactly that line:

  * the THESIS stop fires on the UNDERLYING at 1.25 ATR, and 15-minute
    underlying candles go back months in candles.db -> REPLAYABLE
  * the HARD BACKSTOP fires on PREMIUM -> NOT replayable, ever, for closed
    trades. Answering it needs intraday premium capture starting now.

ATTRIBUTION IS A TIMESTAMP MATCH, NOT A KEY. `decision_outcomes.decision_id`
and `positions.position_id` are different UUID namespaces: 0 of 127 join. The
outcome row is written about a second after the position closes, so this
matches on time within a tolerance and REPORTS how many matched, how many did
not, and how many were ambiguous. A per-cell number built on a silent
drop would be a fabricated verdict, which is the defect family this project
keeps paying for.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from bots.execution import charges as charge_schedule  # noqa: E402

BRAIN = Path(r"C:\Hokage\hokage_brain")

#: How close an outcome row must sit to a position's close to be the same
#: event. Measured at about 1 second on both ends of the record; 5 gives room
#: for a slow write without reaching the next trade.
MATCH_TOLERANCE_SECONDS = 5.0

UNDERLYINGS = ("CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM",
               "BANKNIFTY", "NIFTY", "SENSEX")


def underlying_of(market: str) -> str | None:
    up = str(market or "").upper()
    for name in UNDERLYINGS:
        if up.startswith(name):
            return name
    return None


def classify(exit_reason: str | None) -> str:
    """The exit MECHANISM, not the sentence.

    The reasons embed the premium and the move, so grouping on the raw string
    gives one bucket per trade. These are the mechanisms the ladder and the
    thesis stop actually implement.
    """
    text = (exit_reason or "").lower()
    if not text.strip():
        return "UNRECORDED"
    if "thesis stop" in text:
        return "THESIS STOP (1.25 ATR on underlying)"
    if "hard backstop" in text:
        return "HARD BACKSTOP (premium floor)"
    if "target" in text:
        return "TARGET HIT"
    if "trail" in text:
        return "TRAILING"
    if any(w in text for w in ("square", "session close", "eod", "cutoff")):
        return "SESSION CLOSE"
    if "stop-loss" in text or "stop loss" in text:
        return "PREMIUM STOP"
    return f"OTHER: {text[:40]}"


def _parse(stamp) -> dt.datetime | None:
    if isinstance(stamp, dt.datetime):
        return stamp if stamp.tzinfo else stamp.replace(tzinfo=dt.timezone.utc)
    if not stamp:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(stamp))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


class Match:
    """One closed position joined to its outcome row, or not."""

    __slots__ = ("market", "underlying", "strategy_id", "premium", "gross",
                 "charges", "mechanism", "closed_at", "matched")

    def __init__(self, market, strategy_id, premium, gross, charges,
                 mechanism, closed_at, matched):
        self.market = market
        self.underlying = underlying_of(market)
        self.strategy_id = strategy_id
        self.premium = premium
        self.gross = gross
        self.charges = charges
        self.mechanism = mechanism
        self.closed_at = closed_at
        self.matched = matched

    @property
    def net(self) -> float:
        return self.gross - self.charges


def _round_trip(premium: float, underlying: str | None) -> float:
    """Schedule charges for one round trip, in rupees.

    NOT the ledger's `charges` column: that is populated on 1 of 126 real
    rows, so reading it would report a net figure that is gross for almost
    every trade - the exact mistake "every P&L number is gross" names.
    """
    try:
        result = charge_schedule.option_round_trip(premium, underlying or "NIFTY")
    except Exception:
        return 0.0
    return float(getattr(result, "total", result))


def load(db: Path | None = None) -> tuple[list[Match], dict]:
    """Every real closed position, matched to its exit mechanism.

    Returns (matches, quality) where `quality` records exactly how well the
    timestamp join worked. The caller must print it.
    """
    path = Path(db) if db else (BRAIN / "hokage.db")
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=10)
    try:
        positions = conn.execute(
            "SELECT market, quantity, entry_price, realized_pnl, closed_at,"
            " strategy_id, failure_reason FROM positions"
            " WHERE status = 'CLOSED'").fetchall()
        outcomes = conn.execute(
            "SELECT timestamp, exit_reason, pnl FROM decision_outcomes"
        ).fetchall()
    finally:
        conn.close()

    outcome_times = []
    for stamp, reason, pnl in outcomes:
        when = _parse(stamp)
        if when is not None:
            outcome_times.append((when, reason, pnl))
    outcome_times.sort(key=lambda row: row[0])

    matches: list[Match] = []
    quality = {"positions": 0, "phantoms": 0, "matched": 0, "unmatched": 0,
               "ambiguous": 0, "outcomes": len(outcomes),
               "outcomes_unused": 0}
    used: set[int] = set()

    for market, qty, price, pnl, closed_at, strategy_id, failure in positions:
        if str(failure or "").startswith("PHANTOM"):
            quality["phantoms"] += 1
            continue
        quality["positions"] += 1
        premium = float(qty or 0.0) * float(price or 0.0)
        under = underlying_of(market)
        when = _parse(closed_at)

        near = []
        if when is not None:
            for index, (stamp, reason, _opnl) in enumerate(outcome_times):
                delta = abs((stamp - when).total_seconds())
                if delta <= MATCH_TOLERANCE_SECONDS:
                    near.append((delta, index, reason))
        near.sort()
        if not near:
            quality["unmatched"] += 1
            mechanism, matched = "UNMATCHED (no outcome row)", False
        else:
            if len(near) > 1:
                quality["ambiguous"] += 1
            _delta, index, reason = near[0]
            used.add(index)
            quality["matched"] += 1
            mechanism, matched = classify(reason), True

        matches.append(Match(
            market=market, strategy_id=strategy_id, premium=premium,
            gross=float(pnl or 0.0), charges=_round_trip(premium, under),
            mechanism=mechanism, closed_at=when, matched=matched))

    quality["outcomes_unused"] = len(outcome_times) - len(used)
    return matches, quality


def _table(rows: dict, title: str, total_n: int) -> list[str]:
    out = [title, ""]
    out.append(f"  {'mechanism':40s} {'n':>4s} {'share':>6s} "
               f"{'gross':>11s} {'charges':>8s} {'net':>11s} {'avg net':>9s}")
    for key, (n, gross, chg) in sorted(rows.items(), key=lambda kv: kv[1][1] - kv[1][2]):
        net = gross - chg
        share = f"{n / total_n * 100:5.0f}%" if total_n else "    -"
        out.append(f"  {key:40s} {n:4d} {share} {gross:+11,.0f} "
                   f"{chg:8,.0f} {net:+11,.0f} {net / n:+9,.0f}")
    return out


def report(db: Path | None = None) -> str:
    matches, quality = load(db)
    lines: list[str] = []
    lines.append("")
    lines.append("HOKAGE EXIT LAB - what the exits do to the edge")
    lines.append("=" * 64)
    lines.append("")

    # MATCH QUALITY FIRST. Every number below rests on it.
    lines.append("ATTRIBUTION QUALITY (a timestamp match, not a key)")
    lines.append(f"  real closed positions      {quality['positions']}")
    lines.append(f"  phantoms excluded          {quality['phantoms']}")
    lines.append(f"  matched to an outcome row  {quality['matched']}")
    lines.append(f"  NOT matched                {quality['unmatched']}"
                 f"   <- counted, never dropped")
    lines.append(f"  ambiguous (>1 within {MATCH_TOLERANCE_SECONDS:.0f}s) "
                 f"{quality['ambiguous']}")
    lines.append(f"  outcome rows with no position {quality['outcomes_unused']}")
    if quality["unmatched"]:
        lines.append("  An unmatched position has no recorded mechanism. It is")
        lines.append("  shown as UNMATCHED below rather than silently omitted.")
    lines.append("")

    by_mech: dict = collections.defaultdict(lambda: [0, 0.0, 0.0])
    for match in matches:
        bucket = by_mech[match.mechanism]
        bucket[0] += 1
        bucket[1] += match.gross
        bucket[2] += match.charges
    total_n = len(matches)
    lines.extend(_table(by_mech, "BY EXIT MECHANISM", total_n))

    gross = sum(m.gross for m in matches)
    chg = sum(m.charges for m in matches)
    lines.append("")
    lines.append(f"  {'TOTAL':40s} {total_n:4d}        "
                 f"{gross:+11,.0f} {chg:8,.0f} {gross - chg:+11,.0f}")
    if gross:
        lines.append(f"  charges are {chg / abs(gross):.2f}x the absolute gross")
    lines.append("")

    stops = [m for m in matches if "STOP" in m.mechanism
             or "BACKSTOP" in m.mechanism]
    pays = [m for m in matches if m.mechanism in
            ("TARGET HIT", "TRAILING")]
    if stops and pays and total_n:
        lines.append(f"  the stops      : {len(stops):3d} exits "
                     f"({len(stops) / total_n * 100:.0f}%)  "
                     f"{sum(m.net for m in stops):+,.0f} net")
        lines.append(f"  target + trail : {len(pays):3d} exits "
                     f"({len(pays) / total_n * 100:.0f}%)  "
                     f"{sum(m.net for m in pays):+,.0f} net")
        lines.append("")

    # PER CELL, because a mechanism that pays on one asset can bleed on
    # another - direction and cost are both per asset here.
    lines.append("-" * 64)
    lines.append("BY ASSET x MECHANISM (net rupees)")
    lines.append("")
    per: dict = collections.defaultdict(lambda: [0, 0.0, 0.0])
    for match in matches:
        per[(match.underlying or "?", match.mechanism)][0] += 1
        per[(match.underlying or "?", match.mechanism)][1] += match.gross
        per[(match.underlying or "?", match.mechanism)][2] += match.charges
    assets = sorted({k[0] for k in per})
    for asset in assets:
        rows = {mech: vals for (a, mech), vals in per.items() if a == asset}
        asset_net = sum(v[1] - v[2] for v in rows.values())
        asset_n = sum(v[0] for v in rows.values())
        lines.append(f"  {asset}  (n={asset_n}, net {asset_net:+,.0f})")
        for mech, (n, g, ch) in sorted(rows.items(),
                                       key=lambda kv: kv[1][1] - kv[1][2]):
            lines.append(f"      {mech:38s} {n:3d} {g - ch:+10,.0f}")
    lines.append("")

    # THE DISCRIMINATOR. Target-hit rate tracks net almost perfectly across
    # the book, and it is not a per-trade number the entry can see - it is
    # how often the exit ladder gets all the way to its target before
    # something else fires first.
    lines.append("-" * 64)
    lines.append("HOW OFTEN THE LADDER REACHES ITS TARGET")
    lines.append("")
    lines.append(f"  {'asset':12s} {'n':>4s} {'targets':>8s} {'rate':>6s} "
                 f"{'backstops':>10s} {'net':>11s}")
    rate_rows = []
    for asset in assets:
        rows = {mech: vals for (a, mech), vals in per.items() if a == asset}
        n = sum(v[0] for v in rows.values())
        targets = rows.get("TARGET HIT", [0, 0.0, 0.0])[0]
        backstops = rows.get("HARD BACKSTOP (premium floor)", [0, 0.0, 0.0])[0]
        net = sum(v[1] - v[2] for v in rows.values())
        rate_rows.append((net, asset, n, targets, backstops))
    for net, asset, n, targets, backstops in sorted(rate_rows, reverse=True):
        rate = f"{targets / n * 100:5.0f}%" if n else "    -"
        lines.append(f"  {asset:12s} {n:4d} {targets:8d} {rate} "
                     f"{backstops:10d} {net:+11,.0f}")
    lines.append("")
    lines.append("  Read the two middle columns together. Target rate tracks")
    lines.append("  net across the whole book, and the premium backstop is")
    lines.append("  concentrated rather than spread: it is the mechanism that")
    lines.append("  takes a cell's target winnings back.")
    lines.append("")

    lines.append("-" * 64)
    lines.append("WHAT THIS CANNOT ANSWER")
    lines.append("")
    lines.append("  'Would a tighter stop have been cheaper' needs the premium")
    lines.append("  PATH of each losing trade. The option chain archive holds")
    lines.append("  one snapshot a day (~15:58) from 2026-10-19, and these")
    lines.append("  positions are held 11-77 minutes. Premium history dies")
    lines.append("  with the contract, so for closed trades it is GONE, not")
    lines.append("  missing. The two stops split on this:")
    lines.append("")
    lines.append("    THESIS STOP   fires on the UNDERLYING at 1.25 ATR.")
    lines.append("                  15-minute underlying candles go back")
    lines.append("                  months -> REPLAYABLE.")
    lines.append("    HARD BACKSTOP fires on PREMIUM -> NOT replayable for")
    lines.append("                  any trade already closed. Answering it")
    lines.append("                  needs intraday premium capture from now.")
    lines.append("")
    lines.append("  Nothing here proposes a stop value. Every one is a")
    lines.append("  commander-approved risk constant.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None, help="hokage.db to read")
    args = parser.parse_args(argv)
    print(report(Path(args.db) if args.db else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
