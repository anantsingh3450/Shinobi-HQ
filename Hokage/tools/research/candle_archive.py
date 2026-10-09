"""Keep the candles. Hokage's measurable history was SHRINKING.

2026-08-27, 08:15. The gas sweep reported TRAIN n=3 where the same sweep had
reported n=55 twelve hours earlier. Nothing about the market changed — the
front-month contract rolled:

    NATURALGAS26SEPFUT   3500 bars   from 2026-05-20   <- today's front month
    NATURALGAS26OCTFUT   2825 bars   from 2026-05-27
    NATURALGAS26NOVFUT   1787 bars   from 2026-05-29

A futures contract has no history from before it listed, and expired contracts
are DELISTED — their tokens vanish from the instrument dump, so the tape they
carried becomes unfetchable forever. Yesterday RangeFade/NATURALGAS measured
+2.35 train / +2.67 hold-out on three months of tape. Today that train window
does not exist and the same pair reads +2.44 / +1.08.

THIS IS FATAL TO A SYSTEM THAT LEARNS BY MEASURING. Every week that passes,
Hokage should know MORE. Instead his evidence evaporated on a schedule nobody
was watching, and the weekly audit would have compared next Friday's five-week
train half against last Friday's three-month one and called the difference a
change in edge. The natural gas EIA event makes it concrete: 12 usable Thursdays
exist today, and 12 is what there will be next year too, because the window
slides forward as fast as it fills.

So: write every candle down, once, forever. From today the corpus GROWS. In six
months the EIA question has 25 Thursdays instead of 12, and it is answerable.

WHAT IT DOES NOT PRETEND TO DO
It cannot recover what is already gone. April's gas tape is not coming back.
This starts the clock; it does not turn it back.

ROLLS ARE RECORDED, NOT SMOOTHED. Every bar keeps the contract it came from.
Splicing two contracts produces a price discontinuity at the seam — different
absolute prices for the same underlying — and an EMA or ATR computed across
that seam is measuring the roll, not the market. `load` therefore drops the
first SETTLE_SESSIONS sessions of each new contract, which is exactly long
enough for a 42-bar trailing window to clear the seam. A gap in the series is
honest; a spliced indicator is a fabricated number, and this codebase has paid
for fabricated numbers twice already.

USAGE
    python tools/research/candle_archive.py sync            # every MCX asset
    python tools/research/candle_archive.py sync NATURALGAS
    python tools/research/candle_archive.py status
"""
from __future__ import annotations

import datetime as dt
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from hokage.memory.resolver import brain_root

#: The active brain root. NOT `BRAIN` — that ignored
#: HOKAGE_BRAIN_ROOT, so moving the brain gave Hokage one brain and this tool
#: another, silently. See hokage.memory.resolver.brain_root.
BRAIN = brain_root()

DB = BRAIN / "candles.db"

#: Assets worth keeping. Index symbols resolve to spot and never roll, so they
#: do not strictly need this — but a gap in one league's history is just as
#: blinding as a gap in the other's.
ASSETS = ("NATURALGAS", "CRUDEOIL", "GOLDM", "SILVERM",
          "NIFTY", "BANKNIFTY", "SENSEX")

#: Sessions discarded after a contract change, so no trailing indicator window
#: straddles the price seam. 42 bars is the longest window any module uses
#: (EMA21); two MCX sessions are ~120 bars.
SETTLE_SESSIONS = 2

SCHEMA = """
CREATE TABLE IF NOT EXISTS candles (
    symbol   TEXT NOT NULL,
    ts       TEXT NOT NULL,
    contract TEXT NOT NULL,
    open     REAL NOT NULL,
    high     REAL NOT NULL,
    low      REAL NOT NULL,
    close    REAL NOT NULL,
    volume   REAL,
    PRIMARY KEY (symbol, ts)
);
CREATE INDEX IF NOT EXISTS idx_candles_symbol_ts ON candles(symbol, ts);
"""


def connect() -> sqlite3.Connection:
    DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB)
    conn.executescript(SCHEMA)
    return conn


def remember(symbol: str, bars: list[dict], contract: str | None = None) -> int:
    """Write bars in, keeping whatever is already there. Returns rows added.

    INSERT OR IGNORE, never REPLACE: a bar already written is the record of what
    the tape said at the time, and a re-fetch through a DIFFERENT contract must
    not silently overwrite it with a different price. The seam is data, not an
    error to be tidied away.
    """
    if not bars:
        return 0
    from signal_lab import _front_contract

    contract = contract or _front_contract(symbol)
    rows = [(symbol, b["date"].strftime("%Y-%m-%d %H:%M:%S"), contract,
             b["open"], b["high"], b["low"], b["close"], b.get("volume"))
            for b in bars]
    with connect() as conn:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO candles "
            "(symbol, ts, contract, open, high, low, close, volume) "
            "VALUES (?,?,?,?,?,?,?,?)", rows)
        return conn.total_changes - before


def sync(symbol: str, verbose: bool = True) -> int:
    """Pull everything Kite still serves and merge it in. Returns rows added.

    INSERT OR IGNORE, never REPLACE: a bar already written is the record of what
    the tape said at the time, and a re-fetch through a different contract must
    not silently overwrite it with a different price.
    """
    from signal_lab import MAX_HISTORY_DAYS, _fetch_from_kite, _front_contract

    end = dt.date.today()
    start = end - dt.timedelta(days=MAX_HISTORY_DAYS)
    # Straight from Kite, NOT through load_bars — load_bars reads the archive
    # first, so syncing through it would ask the archive to fill itself.
    bars = _fetch_from_kite(symbol,
                            start.strftime("%Y-%m-%d") + " 09:00:00",
                            end.strftime("%Y-%m-%d") + " 23:59:00")
    if not bars:
        if verbose:
            print("  %-12s no candles returned" % symbol)
        return 0

    contract = _front_contract(symbol)
    with connect() as conn:
        before = conn.execute("SELECT COUNT(*) FROM candles WHERE symbol=?",
                              (symbol,)).fetchone()[0]
    remember(symbol, bars, contract)
    with connect() as conn:
        after = conn.execute("SELECT COUNT(*) FROM candles WHERE symbol=?",
                             (symbol,)).fetchone()[0]
        first, last = conn.execute(
            "SELECT MIN(ts), MAX(ts) FROM candles WHERE symbol=?",
            (symbol,)).fetchone()

    if verbose:
        print("  %-12s +%-5d new  (%d total, %s .. %s)  via %s"
              % (symbol, after - before, after, first[:10], last[:10], contract))
    return after - before


def load(symbol: str, start: str, end: str) -> list[dict]:
    """Archived bars in [start, end], with roll seams removed.

    Returns the same shape Kite's historical_data does, so it is a drop-in for
    load_bars everywhere the labs use it.
    """
    with connect() as conn:
        rows = conn.execute(
            "SELECT ts, contract, open, high, low, close, volume FROM candles "
            "WHERE symbol=? AND ts>=? AND ts<=? ORDER BY ts",
            (symbol, start, end)).fetchall()

    bars = [{"date": dt.datetime.strptime(r[0], "%Y-%m-%d %H:%M:%S"),
             "contract": r[1], "open": r[2], "high": r[3], "low": r[4],
             "close": r[5], "volume": r[6]} for r in rows]
    return _drop_roll_seams(bars)


def _drop_roll_seams(bars: list[dict]) -> list[dict]:
    """Discard the first SETTLE_SESSIONS sessions of each new contract.

    Two contracts on the same underlying trade at different absolute prices. An
    EMA or ATR whose trailing window spans the seam is measuring the roll. The
    honest fix is a gap, not a smoothed number.
    """
    if not bars:
        return bars

    days_by_contract: dict[str, list] = {}
    for b in bars:
        seen = days_by_contract.setdefault(b["contract"], [])
        d = b["date"].date()
        if not seen or seen[-1] != d:
            if d not in seen:
                seen.append(d)

    first_contract = bars[0]["contract"]
    blocked = set()
    for contract, days in days_by_contract.items():
        if contract == first_contract:
            continue        # nothing precedes it, so there is no seam
        blocked.update(days[:SETTLE_SESSIONS])

    return [b for b in bars if b["date"].date() not in blocked]


def status() -> None:
    with connect() as conn:
        rows = conn.execute(
            "SELECT symbol, COUNT(*), MIN(ts), MAX(ts), "
            "COUNT(DISTINCT contract) FROM candles GROUP BY symbol "
            "ORDER BY symbol").fetchall()
    if not rows:
        print("  archive is empty — run: python tools/research/candle_archive.py sync")
        return
    print("  %-12s %8s  %-12s %-12s %s" % ("symbol", "bars", "from", "to", "contracts"))
    for sym, n, first, last, contracts in rows:
        span = (dt.date.fromisoformat(last[:10]) - dt.date.fromisoformat(first[:10])).days
        print("  %-12s %8d  %-12s %-12s %d   (%d days)"
              % (sym, n, first[:10], last[:10], contracts, span))


def main() -> int:
    args = sys.argv[1:]
    command = args[0] if args else "status"
    if command == "status":
        status()
        return 0
    if command != "sync":
        print(__doc__)
        return 1

    targets = [a.upper() for a in args[1:]] or list(ASSETS)
    print("  Archiving %d symbol(s) into %s" % (len(targets), DB.name))
    total = 0
    for symbol in targets:
        try:
            total += sync(symbol)
        except Exception as exc:
            print("  %-12s FAILED: %s" % (symbol, str(exc)[:90]))
    print("  %d new bars." % total)
    print("\n  From here the corpus GROWS. Run this daily — every session kept "
          "is a session\n  that survives the next contract roll.")
    status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
