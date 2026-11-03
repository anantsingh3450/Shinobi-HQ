"""Snapshot today's option chain, so that one day a spread can be measured.

    python tools/ops/archive_options.py            # capture and report
    python tools/ops/archive_options.py --status   # report only, no broker call

WHY THIS EXISTS. The mandate changed on 2026-10-19 to allow defined-risk
short-premium spreads. They cannot be measured, and the reason is data:

    NIFTY26NOV22900CE    37 daily bars, listed 2026-08-26
    NIFTY26DEC22900CE    13 daily bars, listed 2026-09-30

An option carries history only from its listing, and an expired contract is
delisted along with its token. Options expire weekly, so the premium history
of the past does not exist and never will. The only corpus that can exist is
the one that starts now.

ONE QUOTE CALL, NOT A BACKFILL. It reads the live chain around the money for
the nearest expiries and writes what it cost today. Run it AFTER 15:30 IST so
the prices are closes; run it earlier and the rows are honestly stamped as
intraday marks and `closing_snapshots` will exclude them.

It needs a live broker session. With no session it exits non-zero rather than
reporting success over nothing.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

from hokage.memory import option_archive, trading_calendar  # noqa: E402

#: The underlyings the confirmed variance-premium result lives on, and the two
#: cheapest lots in the universe. BANKNIFTY is deliberately absent: it showed
#: nothing on either half, and its worst day was -26.1%.
UNDERLYINGS = {
    "NIFTY": ("NFO", "NSE:NIFTY 50"),
    "SENSEX": ("BFO", "BSE:SENSEX"),
    # MCX, added 2026-11-03. The mirror experiment ("every time it takes a
    # call, take a put") runs on NATURALGAS and could not be settled, because
    # the losing side never fills and so has no premium path — and there was
    # no MCX chain here to reconstruct one from. A mirror only wins where the
    # original was wrong about DIRECTION rather than about MOVEMENT, and both
    # sides pay theta, so that distinction exists ONLY in premium terms.
    #
    # The anchor is None because an MCX option is written on the FRONT FUTURE,
    # not on a spot index, and that future rolls. It is resolved from the
    # instrument dump on every run; hardcoding it is how a roll silently
    # prices a chain off a contract that stopped trading.
    "NATURALGAS": ("MCX", None),
    "GOLDM": ("MCX", None),
    "SILVERM": ("MCX", None),
    "CRUDEOIL": ("MCX", None),
}

#: One instrument dump per segment per run. The four MCX underlyings share a
#: single dump, and it is a large download to repeat four times.
_DUMP_CACHE: dict[str, list] = {}


def _instruments(kite, segment: str) -> list:
    if segment not in _DUMP_CACHE:
        _DUMP_CACHE[segment] = kite.instruments(segment)
    return _DUMP_CACHE[segment]


def _front_future(instruments: list, symbol: str, today) -> str | None:
    """`EXCHANGE:TRADINGSYMBOL` of the nearest future still alive, or None.

    Nearest EXPIRY, not nearest alphabetically: NATURALGAS26NOVFUT sorts
    before NATURALGAS26OCTFUT, and October is the live contract until it
    expires. Sorting the wrong way prices a chain off a contract that has
    stopped trading — the same error that once deleted three months of tape.
    """
    futures = []
    for i in instruments:
        if i.get("name") != symbol or i.get("instrument_type") != "FUT":
            continue
        expiry = i.get("expiry")
        expiry = expiry.date() if hasattr(expiry, "date") else expiry
        if expiry and expiry >= today:
            futures.append((expiry, f"{i['exchange']}:{i['tradingsymbol']}"))
    return min(futures)[1] if futures else None

#: How many expiries forward to keep. A short-premium structure lives in the
#: front two; beyond that the quotes thin out and the rows are noise.
EXPIRIES_FORWARD = 2


def capture(kite, symbol: str, segment: str, spot_key: str,
            when: dt.datetime) -> list[dict]:
    """The rows for one underlying's chain around the money.

    `spot_key` of None means the anchor is this underlying's front future,
    resolved from the dump — the MCX case, where options are written on the
    future rather than on a spot index.
    """
    dump = _instruments(kite, segment)
    today = when.date()

    if spot_key is None:
        spot_key = _front_future(dump, symbol, today)
        if spot_key is None:
            print(f"  {symbol}: no live future to anchor strikes to")
            return []

    try:
        spot = kite.ltp(spot_key)[spot_key]["last_price"]
    except Exception as exc:
        print(f"  {symbol}: could not read spot ({str(exc)[:70]})")
        return []

    instruments = [i for i in dump
                   if i["name"] == symbol
                   and i["instrument_type"] in ("CE", "PE")]
    if not instruments:
        print(f"  {symbol}: no option contracts in the {segment} dump")
        return []

    expiries = sorted({
        (i["expiry"].date() if hasattr(i["expiry"], "date") else i["expiry"])
        for i in instruments
    })
    # A contract expiring TODAY is not forward-looking premium and its last
    # hours are not comparable with anything. The 2-DTE floor production
    # already applies to entries applies here too.
    expiries = [e for e in expiries if (e - today).days >= 2][:EXPIRIES_FORWARD]
    if not expiries:
        print(f"  {symbol}: no expiry at least 2 days out")
        return []

    wanted: dict[str, dict] = {}
    for expiry in expiries:
        for option_type in ("CE", "PE"):
            chain = [i for i in instruments
                     if i["instrument_type"] == option_type
                     and (i["expiry"].date() if hasattr(i["expiry"], "date")
                          else i["expiry"]) == expiry]
            keep = set(option_archive.atm_strikes(
                [c["strike"] for c in chain], spot))
            for c in chain:
                if c["strike"] in keep:
                    wanted[f"{c['exchange']}:{c['tradingsymbol']}"] = {
                        "symbol": symbol, "expiry": expiry,
                        "strike": c["strike"], "option_type": option_type,
                        "spot": spot,
                    }

    if not wanted:
        print(f"  {symbol}: no strikes resolved around {spot:,.0f}")
        return []

    rows: list[dict] = []
    keys = list(wanted)
    # quote() takes a few hundred instruments at a time.
    for i in range(0, len(keys), 200):
        batch = keys[i:i + 200]
        try:
            quotes = kite.quote(batch)
        except Exception as exc:
            print(f"  {symbol}: quote batch failed ({str(exc)[:70]})")
            continue
        for key, q in quotes.items():
            meta = wanted.get(key)
            if meta is None:
                continue
            rows.append({**meta,
                         "last_price": q.get("last_price"),
                         "oi": q.get("oi"),
                         "volume": q.get("volume")})
    print(f"  {symbol:8} spot {spot:>10,.2f}   {len(expiries)} expiries   "
          f"{len(rows)} contracts quoted")
    return rows


def report() -> dict:
    cover = option_archive.coverage()
    print(f"  archive   {option_archive.db_path()}")
    if not cover["rows"]:
        print("  EMPTY — no option chain has ever been archived.")
        return cover
    print(f"  rows      {cover['rows']:,}")
    usable = cover.get("usable_days")
    if usable is not None and usable != cover["days"]:
        print(f"  sessions  {cover['days']} stored, {usable} usable")
        print(f"            ({cover['days'] - usable} held back: captured "
              f"intraday, or on a day the market was shut)")
    else:
        print(f"  sessions  {cover['days']}")
    print(f"  span      {cover['first']} .. {cover['last']}")
    print(f"  symbols   {', '.join(cover['symbols'])}")
    return cover


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--status", action="store_true",
                    help="report what is held; never touch the broker")
    args = ap.parse_args()

    print("=" * 76)
    print("  OPTION CHAIN ARCHIVE")
    print("  A spread cannot be backtested: option history dies with the")
    print("  contract. This starts the corpus that makes it measurable later.")
    print("=" * 76)
    before = report()
    if args.status:
        return 0 if before["rows"] else 1

    when = option_archive.now_ist()

    # Say the day out loud BEFORE spending quota on a chain that will be
    # refused, and before a holiday's stale prints look like a successful run.
    open_today = {s: option_archive.market_was_open(s, when.date())
                  for s in UNDERLYINGS}
    if all(v is False for v in open_today.values()):
        print("")
        print(f"  {trading_calendar.describe(when.date())}")
        print("  Every underlying here is shut today. The broker would still")
        print("  answer with the previous session's prints, and those rows")
        print("  would be indistinguishable from today's closes. Not capturing.")
        return 0
    unknown = [s for s, v in open_today.items() if v is None]
    if unknown:
        print("")
        print(f"  NOTE: the calendar does not cover {when.date()}, so "
              f"it cannot confirm {', '.join(unknown)} traded.")
        print("  Capturing anyway — unknown is not the same as shut — but a "
              "holiday would pass unnoticed here.")

    # PER MARKET, not one 15:30 for both: at 16:00 a NIFTY row is a close
    # and a NATURALGAS row is a live intraday mark, and saying "the
    # session ends at 15:30" over an MCX capture would simply be untrue.
    live = [s for s in UNDERLYINGS
            if not option_archive.is_after_close(when, s)]
    if live:
        print(f"\n  NOTE: it is {when.strftime('%H:%M')} IST and "
              f"{', '.join(live)} {'has' if len(live) == 1 else 'have'} "
              f"not closed yet.")
        print("  Those rows will be stamped as intraday marks, and")
        print("  closing_snapshots() will correctly exclude them.")

    from signal_lab import _kite

    try:
        kite = _kite()
    except Exception as exc:
        print(f"\n  no broker session ({str(exc)[:90]})")
        return 1

    print("")
    rows: list[dict] = []
    for symbol, (segment, spot_key) in UNDERLYINGS.items():
        try:
            rows.extend(capture(kite, symbol, segment, spot_key, when))
        except Exception as exc:
            print(f"  {symbol}: FAILED ({str(exc)[:90]})")

    added = option_archive.remember(rows, when)
    print(f"\n  captured  {len(rows)} contracts")
    print(f"  added     {added} new rows")
    print("  (a contract already recorded for today is never overwritten)")
    print("")
    report()
    return 0 if added or not rows else 0


if __name__ == "__main__":
    raise SystemExit(main())
