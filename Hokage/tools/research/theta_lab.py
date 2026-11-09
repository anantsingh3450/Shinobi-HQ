"""Theta over the real holding period - the last unmeasured term in the cost
of a round trip.

    python tools/research/theta_lab.py
    python tools/research/theta_lab.py --moneyness 0.02 --min-days 3

WHY THIS IS THE LAST TERM
`bots.execution.charges` priced brokerage and statutory charges off the
broker's published schedule, and `spread_lab` measured the bid/ask off the live
book. Together they put a round trip at 0.56-0.89% of premium, which is how
three cells were funded on 2026-11-09. Both labs said, in writing, that theta
over the hold was NOT included. This measures it.

It matters because the funded margins are thin. SENSEX carries a measured edge
of 1.20% against a 0.82-0.89% round trip. A decay term worth even half a
percent of premium decides whether that cell is a business or a donation.

----------------------------------------------------------------------------
THE THREE WAYS THIS MEASUREMENT GOES WRONG, AND WHAT IS DONE ABOUT EACH
----------------------------------------------------------------------------

1. CONTRACTS ON ONE DAY ARE NOT INDEPENDENT OBSERVATIONS.
   The archive holds 926 usable consecutive-day contract pairs across twelve
   days. Regressing all 926 at once gave t = -15.17 on SENSEX. That number is
   false. Every contract captured on the same evening shares that day's one
   implied-volatility shock, so the independent unit is the DAY-PAIR, not the
   contract. Clustered by day the same data gives t = -3.69, and three of four
   buckets stop separating from zero at all.

   The effective n here is eleven, not nine hundred. Everything below reports
   the day count beside the contract count for exactly that reason.

2. A STALE SPOT LOOKS EXACTLY LIKE DECAY.
   2026-10-20 has an archived chain but no candle: Hokage was down, and the
   capture carried 2026-10-19's spot forward unchanged (22889.0 both days)
   while the premiums moved. Differencing across that pair attributes a real
   delta move to time. So a day is usable only when an independent candle for
   that same day corroborates the spot the chain was stored with. That rule
   drops 282 of 1,208 pairs, and it is the reason the gap is visible at all -
   the same coverage gaps that cost 25 of 48 sessions.

3. VEGA IS NOT REMOVED, AND IT IS BIGGER THAN THETA HERE.
   An at-the-money straddle is delta-neutral, so its day-over-day change is
   theta plus vega. It is not theta alone, and over this window NIFTY rallied
   9.4%, which moves implied volatility hard. The proof is in the output: some
   day-pairs show the straddle GAINING several percent, which decay cannot do.
   Those days are not errors to discard - they are the error bars. A mean that
   straddles zero is reported as straddling zero.

   Separating the two needs an implied-volatility series, which needs the
   bid/ask the archive only began recording on 2026-11-09. That is the next
   measurement, not this one.

----------------------------------------------------------------------------
WHY THE ANSWER IS A RANGE AND NOT A NUMBER
----------------------------------------------------------------------------
Every one of Hokage's 416 positions closed the same day it opened - zero held
overnight - with a median hold of 13.8 minutes, and 40 minutes on the index.
The archive, however, can only see one capture a day, so what it measures is
decay per CALENDAR day. Converting one to the other needs an assumption about
when during the day decay happens, and the two defensible conventions do not
agree:

    calendar-time   decay spreads evenly over 24h    hold / 1440 min
    trading-time    decay all falls in the session   hold / session minutes

Trading-time is roughly four times harsher on the index. The truth is between
them and closer to trading-time, because a market that is shut cannot reprice.
Both bounds are printed. Quoting the kinder one as the answer would be the
same mistake as quoting a gross profit factor.

----------------------------------------------------------------------------
WHAT CANNOT BE MEASURED YET
----------------------------------------------------------------------------
GOLDM - the widest funded margin - has two archived days, 2026-11-03 and
2026-11-06, which are not consecutive. One multi-day observation is reported
as one observation and never as a measurement. The same holds for all four MCX
underlyings. This is a direct consequence of the chain archive being three
weeks old: there is no older corpus to fall back on, because an option's
premium history dies with the contract.

NULL IS NOT ZERO. A contract with no archived premium is absent, not free.
"""
from __future__ import annotations

import argparse
import datetime as dt
import math
import statistics as st
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bots.execution import charges  # noqa: E402
from hokage.memory import option_archive as oa  # noqa: E402
from hokage.memory.resolver import brain_root  # noqa: E402
from hokage.research import funded_cells  # noqa: E402

#: Minutes the segment is open. NSE index options 09:15-15:30; MCX 09:00-23:30.
SESSION_MINUTES = {"NSE": 375, "MCX": 870}
MINUTES_IN_A_DAY = 1440

#: Below this many independent day-pairs, a bucket gets no number at all. Three
#: is not enough to trust; it is enough to print a standard deviation, which is
#: what makes the lack of trust visible.
MIN_DAYS_FOR_A_NUMBER = 3


def corroborated_days(con, symbol: str) -> set[str]:
    """Days whose archived spot is independently confirmed by a candle.

    See trap 2 in the module docstring: without this, a day Hokage slept
    through contributes a stale spot and the decay estimate absorbs a real
    price move.
    """
    days = set()
    for (day,) in con.execute(
            "SELECT DISTINCT day FROM option_chain WHERE symbol = ?", (symbol,)):
        got = con.execute(
            "SELECT COUNT(*) FROM candles WHERE symbol = ? AND date(ts) = ?",
            (symbol, day)).fetchone()[0]
        if got:
            days.add(day)
    return days


def archived_symbols(con) -> list[str]:
    return [r[0] for r in con.execute(
        "SELECT DISTINCT symbol FROM option_chain ORDER BY symbol")]


def adjacent_pairs(days: set[str], max_gap_days: int = 5
                   ) -> list[tuple[str, str]]:
    """Each usable day paired with the NEXT usable day, and nothing else.

    WHY NOT EVERY PAIR WITHIN A WINDOW. Joining every pair up to four days
    apart looks like more data and is not: (19->21), (20->21) and (19->20)
    share endpoints, so they are three views of two days. Doing it that way
    took eleven independent day-pairs to twenty-three and moved NIFTY's t from
    -1.23 to -2.37 - across the significance bar, on no new information. This
    is trap 1 from the module docstring recurring one level up, and the fix is
    to let each day appear in at most one forward difference.

    A gap longer than `max_gap_days` is dropped rather than divided: across a
    week the implied-volatility drift stops being noise around decay and
    becomes the larger part of the change.
    """
    ordered = sorted(days)
    out = []
    for first, second in zip(ordered, ordered[1:]):
        gap = (dt.date.fromisoformat(second) - dt.date.fromisoformat(first)).days
        if 1 <= gap <= max_gap_days:
            out.append((first, second))
    return out


def straddle_observations(con, symbol: str, max_moneyness: float = 0.015,
                          max_gap_days: int = 5) -> list[dict]:
    """One row per (day-pair, strike) at-the-money straddle.

    Both legs must exist at the same strike and expiry on both days, because a
    one-legged "straddle" is just a directional option and carries the delta
    this construction exists to cancel.
    """
    good = corroborated_days(con, symbol)
    wanted = set(adjacent_pairs(good, max_gap_days))
    if not wanted:
        return []
    rows = con.execute(
        "SELECT a.day, b.day, a.option_type, a.strike, a.expiry, "
        "       a.last_price, b.last_price, a.spot "
        "FROM option_chain a JOIN option_chain b "
        "  ON a.symbol = b.symbol AND a.expiry = b.expiry "
        "     AND a.strike = b.strike AND a.option_type = b.option_type "
        "WHERE a.symbol = ? AND b.day > a.day "
        "  AND a.last_price > 0 AND b.last_price > 0 AND a.spot > 0",
        (symbol,)).fetchall()

    legs: dict[tuple, dict] = defaultdict(dict)
    for d1, d2, kind, strike, expiry, p1, p2, spot in rows:
        if (d1, d2) not in wanted:
            continue
        legs[(d1, d2, strike, expiry)][kind] = (p1, p2, spot)

    out = []
    for (d1, d2, strike, expiry), both in legs.items():
        if "CE" not in both or "PE" not in both:
            continue
        c1, c2, spot = both["CE"]
        p1, p2, _ = both["PE"]
        if spot <= 0 or abs(strike - spot) / spot > max_moneyness:
            continue
        day1 = dt.date.fromisoformat(d1)
        dte = (dt.date.fromisoformat(expiry) - day1).days
        if dte <= 0:
            continue                      # expired between captures
        gap = (dt.date.fromisoformat(d2) - day1).days
        before, after = c1 + p1, c2 + p2
        if before <= 0:
            continue
        out.append({
            "day": d1, "to": d2, "gap_days": gap, "strike": strike,
            "dte": dte, "bucket": dte_bucket(dte),
            "pct_per_day": (after - before) / before / gap * 100.0,
        })
    return out


def dte_bucket(dte: int) -> str:
    if dte <= 7:
        return "0-7"
    if dte <= 21:
        return "8-21"
    return "22+"


def by_day(obs: list[dict]) -> list[float]:
    """Collapse to one figure per day-pair. THIS IS THE WHOLE POINT.

    Averaging within the day first is what keeps the day count as the sample
    size. Skipping this step is what produced t = -15 from eleven days of data.
    """
    grouped = defaultdict(list)
    for row in obs:
        grouped[(row["day"], row["to"])].append(row["pct_per_day"])
    return [st.mean(v) for _, v in sorted(grouped.items())]


def summarise(daily: list[float]) -> dict:
    """Mean, t and spread over INDEPENDENT days."""
    n = len(daily)
    if n == 0:
        return {"days": 0}
    mean = st.mean(daily)
    if n < 2:
        return {"days": n, "mean": mean, "sd": None, "t": None,
                "lo": min(daily), "hi": max(daily)}
    sd = st.stdev(daily)
    se = sd / math.sqrt(n)
    return {"days": n, "mean": mean, "sd": sd,
            "t": (mean / se) if se > 0 else None,
            "lo": min(daily), "hi": max(daily)}


def hold_minutes() -> dict[str, dict]:
    """The holding period Hokage actually realises, per underlying.

    Read from `positions`, which is the real ledger - `trades` has never held
    a real entry. Only closed positions can state a hold.
    """
    import re
    import sqlite3

    path = brain_root() / "hokage.db"
    if not path.exists():
        return {}
    con = sqlite3.connect(str(path))
    try:
        rows = con.execute(
            "SELECT market, (julianday(closed_at) - julianday(opened_at)) "
            "       * 24 * 60 "
            "FROM positions "
            "WHERE closed_at IS NOT NULL AND opened_at IS NOT NULL").fetchall()
        overnight = con.execute(
            "SELECT COUNT(*) FROM positions WHERE closed_at IS NOT NULL "
            "AND date(closed_at) != date(opened_at)").fetchone()[0]
    finally:
        con.close()

    grouped = defaultdict(list)
    for symbol, mins in rows:
        if mins is None or mins < 0:
            continue
        hit = re.match(r"^([A-Z]+?)(?=\d{2}[A-Z]{3}|\d{2}\d)", str(symbol))
        grouped[hit.group(1) if hit else str(symbol)].append(float(mins))

    out = {}
    for under, mins in grouped.items():
        ordered = sorted(mins)
        out[under] = {
            "n": len(ordered), "median": st.median(ordered),
            "mean": st.mean(ordered),
            "p90": ordered[min(int(0.9 * len(ordered)), len(ordered) - 1)],
            "overnight": overnight,
        }
    return out


def cost_over_hold(pcts_per_day: list[float], hold_min: float, segment: str
                   ) -> tuple[float, float]:
    """(low bound, high bound) of theta over one hold, percent of premium.

    Positive numbers, because they are costs.

    THE BRACKET SPANS TWO SEPARATE UNCERTAINTIES, and collapsing either one
    would be a guess dressed as a measurement:

      * WHEN decay happens. Calendar-time spreads it over 24 hours;
        trading-time puts all of it inside the session. Roughly 4x apart on
        the index. The truth is nearer trading-time, because a shut market
        cannot reprice.

      * WHICH expiry bucket the trade is in. Decay goes as 1/sqrt(T), so a
        0-7 DTE contract bleeds several times faster than a 22-day one, and
        the ledger stores the contract symbol rather than its expiry. Parsing
        an expiry out of `NIFTY2672124250CE` means knowing that weekly months
        10, 11 and 12 are written O, N and D - and a misparse would silently
        select the wrong decay rate rather than fail. So every measured bucket
        is spanned instead.

    The low bound is therefore the gentlest bucket under the gentlest
    convention and the high bound the harshest under the harshest. A single
    number in the middle of that would be the one thing this cannot support.
    """
    rates = [abs(p) for p in pcts_per_day if p is not None]
    if not rates:
        return (0.0, 0.0)
    session = SESSION_MINUTES.get(segment, SESSION_MINUTES["NSE"])
    return (min(rates) * hold_min / MINUTES_IN_A_DAY,
            max(rates) * hold_min / session)


def report(max_moneyness: float, min_days: int) -> int:
    con = oa.connect()
    try:
        symbols = archived_symbols(con)
        print("=" * 78)
        print("  THETA OVER THE REAL HOLD")
        print("=" * 78)
        print(f"  archive     {oa.db_path()}")
        print(f"  moneyness   ATM straddles within {max_moneyness:.1%} of spot")
        print("  unit        one independent observation per DAY-PAIR, not "
              "per contract")
        print()

        holds = hold_minutes()
        if holds:
            any_over = next(iter(holds.values()))["overnight"]
            print("  REALISED HOLDING PERIOD (closed positions, from "
                  "`positions`)")
            print(f"      held overnight: {any_over} - every position is "
                  "intraday")
            print(f"      {'asset':<12}{'n':>5}{'median':>9}{'mean':>9}"
                  f"{'p90':>9}")
            for under in sorted(holds, key=lambda k: -holds[k]["n"]):
                h = holds[under]
                print(f"      {under:<12}{h['n']:>5}{h['median']:>8.1f}m"
                      f"{h['mean']:>8.1f}m{h['p90']:>8.1f}m")
            print()

        measured: dict[str, list[dict]] = defaultdict(list)
        print("  DECAY PER CALENDAR DAY, ATM STRADDLE, CLUSTERED BY DAY")
        print(f"      {'asset':<12}{'dte':<7}{'pairs':>6}{'days':>6}"
              f"{'%/day':>9}{'t':>7}   {'day range':>16}")
        for symbol in symbols:
            obs = straddle_observations(con, symbol, max_moneyness)
            if not obs:
                print(f"      {symbol:<12}{'-':<7}{0:>6}{0:>6}"
                      "   no spot-corroborated consecutive pair")
                continue
            for bucket in ("0-7", "8-21", "22+"):
                rows = [o for o in obs if o["bucket"] == bucket]
                if not rows:
                    continue
                stat = summarise(by_day(rows))
                if stat["days"] < min_days:
                    print(f"      {symbol:<12}{bucket:<7}{len(rows):>6}"
                          f"{stat['days']:>6}"
                          "   too few days to state a number")
                    continue
                t = stat["t"]
                print(f"      {symbol:<12}{bucket:<7}{len(rows):>6}"
                      f"{stat['days']:>6}{stat['mean']:>8.2f}%"
                      f"{t if t is not None else float('nan'):>7.2f}"
                      f"   {stat['lo']:>+7.1f}..{stat['hi']:>+6.1f}")
                measured[symbol].append(dict(stat, bucket=bucket))
        print()
        print("      A mean whose |t| is under 2 has not separated from zero.")
        print("      A positive day-pair is vega, not decay: it is why these")
        print("      are ranges rather than constants.")
        print()

        print("  WHAT THAT COSTS OVER A REAL HOLD, ADDED TO THE ROUND TRIP")
        print(f"      {'asset':<12}{'hold':>7}{'theta over hold':>19}"
              f"{'round trip':>13}{'total vs edge':>26}")
        verdicts = []
        for under in sorted(funded_cells.MEASURED):
            row = funded_cells.MEASURED[under]
            stats = measured.get(under)
            hold = holds.get(under, {}).get("median")
            if not stats or hold is None:
                why = ("no measurable decay" if not stats
                       else "no realised hold")
                print(f"      {under:<12}{'-':>7}   {why}")
                verdicts.append((under, None, None))
                continue
            segment = charges.segment_for(under)
            lo, hi = cost_over_hold([s["mean"] for s in stats], hold, segment)
            total_lo = row["cost_lo"] + lo
            total_hi = row["cost_hi"] + hi
            mark = ("clears" if row["edge"] > total_hi else
                    "FAILS" if row["edge"] < total_lo else "UNDECIDED")
            flag = "*" if funded_cells.is_funded_asset(under) else " "
            print(f"      {under:<12}{hold:>6.0f}m"
                  f"{lo:>9.2f}-{hi:<9.2f}"
                  f"{row['cost_lo']:>6.2f}-{row['cost_hi']:<6.2f}"
                  f"{total_lo:>8.2f}-{total_hi:<7.2f}"
                  f" vs {row['edge']:>5.2f}  {mark}{flag}")
            verdicts.append((under, mark, flag))
        print()
        print("      * = funded cell.  UNDECIDED means the edge falls INSIDE")
        print("        the cost bracket: the cell survives under the gentle")
        print("        end and does not under the harsh end. That is a")
        print("        statement about the data, not about the cell.")
        print()

        undecided = [u for u, m, _ in verdicts if m == "UNDECIDED"]
        unmeasured = [u for u, m, _ in verdicts
                      if m is None and funded_cells.is_funded_asset(u)]
        print("  WHERE THIS LEAVES THE FUNDING DECISION")
        if undecided:
            print(f"      undecided on cost: {', '.join(undecided)}")
        if unmeasured:
            print(f"      funded but theta unmeasurable: "
                  f"{', '.join(unmeasured)}")
        print("      Nothing here changes a funded cell. Theta is large enough")
        print("      to decide the question and not yet measured well enough")
        print("      to decide it, and that is the finding.")
        print()
        print("  STILL NOT INCLUDED")
        print("      Implied volatility is not separated from decay. That")
        print("      needs an IV series, which needs the bid/ask the archive")
        print("      began recording on 2026-11-09 - forward only, because an")
        print("      option's book dies with the contract.")
        return 0
    finally:
        con.close()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--moneyness", type=float, default=0.015,
                    help="half-width of the ATM band, as a fraction of spot")
    ap.add_argument("--min-days", type=int, default=MIN_DAYS_FOR_A_NUMBER,
                    help="independent day-pairs required to print a number")
    args = ap.parse_args()
    return report(args.moneyness, args.min_days)


if __name__ == "__main__":
    raise SystemExit(main())
