"""Was the 1.25 ATR thesis stop too tight? Measured on the underlying.

THE BIGGEST SINGLE LINE IN THE EXIT RECORD. `exit_lab` measured the thesis
stop at 37 exits and -62,321 net - more than any other mechanism, and 29% of
all exits. It fires when the UNDERLYING moves 1.25 x ATR against the position.

WHY THIS ONE CAN BE ANSWERED AND THE PREMIUM BACKSTOP CANNOT. The thesis stop
is a decision about the underlying, and 15-minute underlying candles go back
to 2026-02-13 in candles.db. The premium backstop needs each trade's premium
PATH, and the option chain archive holds one snapshot a day - gone, not
missing, for any closed trade.

IT MEASURES IN ATR, NOT IN RUPEES, AND THAT IS NOT A SHORTCUT. Saying what a
wider stop would have PAID requires pricing the option at an exit that never
happened. That is a synthetic price, and this project does not produce them.
What the tape can answer without inventing anything:

    after the stop fired, did the underlying come back?

If it usually did, 1.25 ATR is cutting off recoveries and the losses are
self-inflicted. If it usually did not, the stop is doing its job and the
money was lost by the entry, not the exit. Those are opposite conclusions
with opposite fixes, and nobody has ever checked which is true.

THE ATR COMES FROM THE PRODUCTION EXIT REASON, parsed out of lines like

    Underlying Thesis Stop: NIFTY moved 55.00 against position (>= 1.25 x ATR 42.82)

rather than recomputed here. A re-derived ATR would be a different ruler from
the one that actually fired the stop, which is the mistake that reset the
audit's retirement clock.

IT PROPOSES NOTHING. The stop multiple is a commander-approved risk constant
and values have been awaiting his decision since before they could be priced.
This gives that decision numbers; it does not take it.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sqlite3
import statistics
import sys
from pathlib import Path

BRAIN = Path(r"C:\Hokage\hokage_brain")
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))

#: Wider stops to price against the tape, as multiples of ATR. 1.25 is
#: production; the rest are the question.
CANDIDATE_MULTIPLES = (1.25, 1.5, 1.75, 2.0, 2.5)

#: How long after the stop a recovery still counts. The weekly audit measures
#: a 60-minute horizon, so a recovery inside it is one the system could
#: plausibly have held for. `session` is to the last candle of that day.
RECOVERY_WINDOWS_MIN = (30, 60, 120)

UNDERLYINGS = ("CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM",
               "BANKNIFTY", "NIFTY", "SENSEX")


def underlying_of(market: str) -> str | None:
    up = str(market or "").upper()
    for name in UNDERLYINGS:
        if up.startswith(name):
            return name
    return None


def bullish(market: str) -> bool | None:
    """A long CE is a bet the underlying rises; a long PE that it falls.

    Every position in this book is an option BUY (the mandate is
    options-buying plus defined-risk spreads), so the option type is the
    direction.
    """
    up = str(market or "").upper()
    if up.endswith("CE"):
        return True
    if up.endswith("PE"):
        return False
    return None


def parse_atr(exit_reason: str) -> float | None:
    found = re.search(r"ATR\s+([0-9]+(?:\.[0-9]+)?)", exit_reason or "")
    return float(found.group(1)) if found else None


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


class Replay:
    """One thesis-stop exit, walked forward on the underlying tape."""

    __slots__ = ("market", "underlying", "up", "atr", "pnl", "entry_ist",
                 "entry_price", "mae_atr", "mfe_after_atr", "recovered",
                 "hit_wider", "bars", "note")

    def __init__(self, **kw):
        for key in self.__slots__:
            setattr(self, key, kw.get(key))


def _candles(conn, symbol: str, day: dt.date) -> list[tuple]:
    rows = conn.execute(
        "SELECT ts, high, low, close FROM candles"
        " WHERE symbol = ? AND substr(ts,1,10) = ? ORDER BY ts",
        (symbol, day.isoformat())).fetchall()
    out = []
    for ts, high, low, close in rows:
        try:
            when = dt.datetime.fromisoformat(ts).replace(tzinfo=IST)
        except ValueError:
            continue
        if high is None or low is None:
            continue
        out.append((when, float(high), float(low), float(close)))
    return out


def replay_all(hokage_db: Path | None = None,
               candles_db: Path | None = None) -> tuple[list[Replay], dict]:
    hpath = Path(hokage_db) if hokage_db else (BRAIN / "hokage.db")
    cpath = Path(candles_db) if candles_db else (BRAIN / "candles.db")

    hcon = sqlite3.connect(f"{hpath.as_uri()}?mode=ro", uri=True, timeout=10)
    try:
        positions = hcon.execute(
            "SELECT market, realized_pnl, opened_at, closed_at FROM positions"
            " WHERE status = 'CLOSED'"
            "   AND (failure_reason IS NULL OR failure_reason NOT LIKE 'PHANTOM%')"
        ).fetchall()
        outcomes = hcon.execute(
            "SELECT timestamp, exit_reason FROM decision_outcomes"
            " WHERE exit_reason LIKE '%Thesis Stop%'").fetchall()
    finally:
        hcon.close()

    stamped = [(_utc(t), r) for t, r in outcomes]
    stamped = [(t, r) for t, r in stamped if t is not None]

    quality = {"thesis_exits": len(outcomes), "matched": 0, "no_atr": 0,
               "no_candles": 0, "no_entry_bar": 0, "replayed": 0,
               "no_direction": 0}
    out: list[Replay] = []

    ccon = sqlite3.connect(f"{cpath.as_uri()}?mode=ro", uri=True, timeout=10)
    try:
        for market, pnl, opened_at, closed_at in positions:
            closed = _utc(closed_at)
            opened = _utc(opened_at)
            if closed is None or opened is None:
                continue
            reason = None
            for when, text in stamped:
                if abs((when - closed).total_seconds()) <= 5.0:
                    reason = text
                    break
            if reason is None:
                continue
            quality["matched"] += 1

            atr = parse_atr(reason)
            symbol = underlying_of(market)
            up = bullish(market)
            if atr is None or not atr:
                quality["no_atr"] += 1
                continue
            if up is None:
                quality["no_direction"] += 1
                continue

            entry_ist = opened.astimezone(IST)
            bars = _candles(ccon, symbol, entry_ist.date())
            if not bars:
                quality["no_candles"] += 1
                out.append(Replay(market=market, underlying=symbol, up=up,
                                  atr=atr, pnl=pnl, entry_ist=entry_ist,
                                  note="no candles for that day"))
                continue

            at_or_before = [b for b in bars if b[0] <= entry_ist]
            if not at_or_before:
                quality["no_entry_bar"] += 1
                out.append(Replay(market=market, underlying=symbol, up=up,
                                  atr=atr, pnl=pnl, entry_ist=entry_ist,
                                  note="entry precedes the first candle"))
                continue
            entry_price = at_or_before[-1][3]
            forward = [b for b in bars if b[0] > entry_ist]
            if not forward:
                quality["no_entry_bar"] += 1
                out.append(Replay(market=market, underlying=symbol, up=up,
                                  atr=atr, pnl=pnl, entry_ist=entry_ist,
                                  entry_price=entry_price,
                                  note="no candles after entry"))
                continue

            # Adverse and favourable are signed by the position's direction.
            def adverse(bar) -> float:
                _when, high, low, _close = bar
                return (entry_price - low) if up else (high - entry_price)

            def favourable(bar) -> float:
                _when, high, low, _close = bar
                return (high - entry_price) if up else (entry_price - low)

            mae = max(adverse(b) for b in forward)

            # When would each candidate stop have fired?
            hit_wider = {}
            fired_at = {}
            for mult in CANDIDATE_MULTIPLES:
                threshold = mult * atr
                when_hit = next((b[0] for b in forward
                                 if adverse(b) >= threshold), None)
                hit_wider[mult] = when_hit is not None
                fired_at[mult] = when_hit

            # After the PRODUCTION stop fired, did the underlying come back?
            production_fire = fired_at.get(1.25)
            recovered: dict = {}
            mfe_after = None
            if production_fire is not None:
                after = [b for b in forward if b[0] > production_fire]
                if after:
                    mfe_after = max(favourable(b) for b in after)
                    for window in RECOVERY_WINDOWS_MIN:
                        cutoff = production_fire + dt.timedelta(minutes=window)
                        inside = [b for b in after if b[0] <= cutoff]
                        recovered[window] = bool(
                            inside and max(favourable(b) for b in inside) >= 0.0)
                    rest = max(favourable(b) for b in after)
                    recovered["session"] = rest >= 0.0

            quality["replayed"] += 1
            out.append(Replay(
                market=market, underlying=symbol, up=up, atr=atr, pnl=pnl,
                entry_ist=entry_ist, entry_price=entry_price,
                mae_atr=mae / atr, mfe_after_atr=(mfe_after / atr)
                if mfe_after is not None else None,
                recovered=recovered, hit_wider=hit_wider,
                bars=len(forward), note=None))
    finally:
        ccon.close()

    return out, quality


def report(hokage_db: Path | None = None,
           candles_db: Path | None = None) -> str:
    rows, quality = replay_all(hokage_db, candles_db)
    good = [r for r in rows if r.note is None and r.mae_atr is not None]
    lines: list[str] = ["", "HOKAGE THESIS-STOP LAB - was 1.25 ATR too tight?",
                        "=" * 64, ""]

    lines.append("COVERAGE (every exclusion counted, none dropped)")
    lines.append(f"  thesis-stop outcome rows      {quality['thesis_exits']}")
    lines.append(f"  matched to a real position    {quality['matched']}")
    lines.append(f"  replayed on the tape          {quality['replayed']}")
    lines.append(f"  no ATR in the reason          {quality['no_atr']}")
    lines.append(f"  no candles for that day       {quality['no_candles']}")
    lines.append(f"  entry outside the candle day  {quality['no_entry_bar']}")
    lines.append(f"  direction unreadable          {quality['no_direction']}")
    lines.append("")
    if not good:
        lines.append("  Nothing replayable. No conclusion is available, which")
        lines.append("  is not the same as the stop being fine.")
        lines.append("")
        return "\n".join(lines)

    lines.append("-" * 64)
    lines.append("DID THE UNDERLYING COME BACK AFTER THE STOP FIRED?")
    lines.append("")
    with_fire = [r for r in good if r.recovered]
    unreproduced = len(good) - len(with_fire)
    if unreproduced:
        lines.append(f"  {unreproduced} of {len(good)} stops DO NOT REPRODUCE on"
                     f" 15-minute candles:")
        lines.append("  production saw 1.25 ATR of adverse move that these bars")
        lines.append("  do not contain, so it was watching a finer tick or a")
        lines.append("  different reference price. They are excluded from the")
        lines.append("  rates below rather than counted as 'did not recover',")
        lines.append("  which would flatter the stop.")
        lines.append("")
    for window in RECOVERY_WINDOWS_MIN:
        back = [r for r in with_fire if r.recovered.get(window)]
        if with_fire:
            lines.append(f"  within {window:3d} min : {len(back):3d} of "
                         f"{len(with_fire)}  ({len(back) / len(with_fire) * 100:.0f}%)")
    back_session = [r for r in with_fire if r.recovered.get("session")]
    if with_fire:
        lines.append(f"  by session end : {len(back_session):3d} of "
                     f"{len(with_fire)}  "
                     f"({len(back_session) / len(with_fire) * 100:.0f}%)")
    lines.append("")
    lines.append("  'Came back' means the underlying traded at or through the")
    lines.append("  ENTRY price again, in the position's favour, after the")
    lines.append("  stop had already closed it. It does not mean the option")
    lines.append("  would have been profitable - premium decays while the")
    lines.append("  underlying round-trips, and pricing that would require a")
    lines.append("  synthetic price this project does not produce.")
    lines.append("")

    lines.append("-" * 64)
    lines.append("HOW FAR IT ACTUALLY WENT AGAINST (max adverse, in ATR)")
    lines.append("")
    maes = sorted(r.mae_atr for r in good)
    lines.append(f"  n={len(maes)}  median {statistics.median(maes):.2f}  "
                 f"p75 {maes[int(len(maes) * 0.75)]:.2f}  "
                 f"max {maes[-1]:.2f}")
    lines.append("")
    lines.append("  WOULD A WIDER STOP HAVE BEEN HIT AT ALL THAT DAY?")
    for mult in CANDIDATE_MULTIPLES:
        hit = [r for r in good if r.hit_wider.get(mult)]
        lines.append(f"    {mult:4.2f} ATR : {len(hit):3d} of {len(good)} "
                     f"({len(hit) / len(good) * 100:3.0f}%) would still "
                     f"have stopped out")
    lines.append("")
    lines.append("  A multiple that still stops out nearly as often buys")
    lines.append("  nothing but a bigger loss on each one. A multiple that")
    lines.append("  stops out far less often is only better if those trades")
    lines.append("  then recovered - which is the table above.")
    lines.append("")

    lines.append("-" * 64)
    lines.append("PER ASSET (the stop is per module, and cost is per asset)")
    lines.append("")
    lines.append(f"  {'asset':12s} {'n':>3s} {'median MAE':>11s} "
                 f"{'back in 60m':>12s} {'gross':>10s}")
    for asset in sorted({r.underlying for r in good}):
        mine = [r for r in good if r.underlying == asset]
        fired = [r for r in mine if r.recovered]
        back = [r for r in fired if r.recovered.get(60)]
        med = statistics.median([r.mae_atr for r in mine])
        gross = sum(float(r.pnl or 0) for r in mine)
        rate = f"{len(back)}/{len(fired)}" if fired else "-"
        lines.append(f"  {asset:12s} {len(mine):3d} {med:11.2f} "
                     f"{rate:>12s} {gross:+10,.0f}")
    lines.append("")
    lines.append("  Nothing here proposes a stop multiple. That is a")
    lines.append("  commander-approved risk constant.")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay the thesis stop.")
    parser.add_argument("--hokage-db", default=None)
    parser.add_argument("--candles-db", default=None)
    args = parser.parse_args(argv)
    print(report(
        Path(args.hokage_db) if args.hokage_db else None,
        Path(args.candles_db) if args.candles_db else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
