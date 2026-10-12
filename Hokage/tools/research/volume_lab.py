"""Does the volume gate add edge, or remove it?

WHY THIS EXISTS
The volume gate is the second-largest blocker in the book: 200 of 503 index
rejections, 37.5% of everything Hokage declines. Every observed ratio sits in a
narrow 0.88-0.99x band against a 1.10x bar — never wildly under, always just
under. A gate that misses by a whisker two hundred times is either protecting
the account from two hundred bad trades or denying it two hundred good ones,
and nobody has ever measured which.

Its threshold has moved three times (1.2 -> 1.1 for breakouts, 0.8 -> 0.5 for
trend), each time commander-approved and each time argued from a incident
rather than from a measurement. This asks the question directly: take every
signal the modules produced, split them by whether the gate would have passed
them, and compare the forward edge of the two halves.

  If PASSED beats BLOCKED, the gate is doing its job.
  If BLOCKED matches or beats PASSED, the gate is removing good trades.

WHAT THE GATE ACTUALLY MEASURES (found 2026-08-18, and it is not the index)
`_get_volume_context` asks `price_source` for candles, which routes through
`_kite_quote_symbol`. That method checks `_INDEX_QUOTE_SYMBOLS` BEFORE
`_FUTURES_UNDERLYINGS`, so:

    NIFTY, BANKNIFTY  ->  NFO front-month FUTURES   (real volume)
    SENSEX            ->  BSE:SENSEX, the index     (volume is always 0)

An NSE/BSE index has no traded volume of its own. `_get_volume_context` returns
None when today's volume is 0, and the caller then SKIPS the gate. So SENSEX
has never faced the volume gate in its life — confirmed against the live tally,
where all 200 volume rejections are NIFTY and BANKNIFTY and not one is SENSEX.

That matters beyond the gate itself: the arena is a tournament, and its premise
is that strategies face the same test on every asset. On SENSEX one of the two
largest gates silently does not exist.

So this lab measures on the FUTURES series for NIFTY and BANKNIFTY — the same
series production reads volume from — rather than on spot, which would have no
volume to gate on.

TRAIN AND HOLD-OUT, ALWAYS
Reported on disjoint periods. A gate verdict from a single pooled window is the
error that shipped RangeFade onto CRUDEOIL on 2026-08-18.

USAGE
    python tools/research/volume_lab.py
"""
from __future__ import annotations

import math
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from signal_lab import Ctx, measurable  # noqa: E402
from entry_module_lab import build_context  # noqa: E402

from bots.autonomous.intelligence import VolumeEngine  # noqa: E402
from bots.strategy.components.entries import ENTRY_MODULES  # noqa: E402
from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES  # noqa: E402
from hokage.memory.resolver import brain_root  # noqa: E402

BRAIN = brain_root()

#: Mirrors AutonomousTradingBot._VOLUME_PROFILE_LOOKBACK_DAYS / _MIN_PRIOR_SESSIONS.
LOOKBACK_DAYS = 14
MIN_PRIOR_SESSIONS = 3

HORIZON = 4          # 60 minutes, the primary horizon everywhere else
MIN_N = 30

#: Minimum n on ONE SIDE of the split before an edge or a t is printed.
#:
#: MIN_N guards the COMBINED count, which leaves a side free to be tiny. On
#: 2026-10-12 NATURALGAS TRAIN printed:
#:
#:     entry-sessionshift-mcx-v1 blocked  2  +5.793  +5793103448.28
#:
#: a t-statistic of 5.8 billion from two observations with almost no variance
#: between them. It formats like overwhelming significance and means nothing.
#: The COUNT is still shown below this bar -- "blocked 2" is the useful fact,
#: because it says the gate barely binds -- but the statistics are withheld.
MIN_SIDE_N = 10

TRAIN = ("2026-03-01", "2026-06-15")
HOLDOUT = ("2026-06-16", "2026-08-13")

#: Only the futures-backed underlyings can be measured: SENSEX has no volume
#: series at all, which is the finding rather than a limitation of this tool.
SYMBOLS = ("NIFTY", "BANKNIFTY", "GOLDM", "SILVERM", "CRUDEOIL", "NATURALGAS")

#: Symbols read from the candle archive instead of Kite.
#:
#: Kite DELISTS an expired futures contract along with its history, which is
#: why every TRAIN window in this lab came back "0 bars": the 2026-03..06
#: front-month contracts no longer exist to serve. The archive keeps every
#: candle forever and still holds them -- GOLDM26SEPFUT (6,946 bars, expired
#: 2026-09-01) and SILVERM26AUGFUT (7,924 bars, expired 2026-08-28) among
#: them. That is the roll problem it was built for.
#:
#: The INDICES ARE NOT HERE, and that is deliberate. The archive stores the
#: index itself (contract "NIFTY 50", "SENSEX"), and an index has no traded
#: volume of its own: all 4,028 NIFTY rows and all 4,028 SENSEX rows carry
#: volume 0.0. Reading them would compute a ratio out of zeros and print
#: numbers that look real. Production reads index volume from the NFO
#: front-month future, so this lab must too -- the same trap the module
#: docstring records for SENSEX.
ARCHIVE_SYMBOLS = ("GOLDM", "SILVERM", "CRUDEOIL", "NATURALGAS")


def load_archive_bars(symbol: str, start: str, end: str) -> list[dict]:
    """Candles from the archive, which keeps expired contracts Kite deletes.

    Returns the same shape as load_futures_bars so split_by_gate cannot tell
    them apart: dicts with date/open/high/low/close/volume.

    REFUSES a symbol whose volume is entirely zero. Measuring a volume gate
    against a series with no volume produces a ratio of zeros that formats
    like a real number and means nothing, and that is exactly how an index
    would slip in here.
    """
    import sqlite3

    db = BRAIN / "candles.db"
    if not db.exists():
        raise ValueError("no candle archive at " + str(db))

    conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT ts, open, high, low, close, volume FROM candles "
            "WHERE symbol = ? AND ts >= ? AND ts <= ? ORDER BY ts",
            (symbol, start + " 00:00:00", end + " 23:59:59"),
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        raise ValueError("archive has no " + symbol + " bars in " + start + ".." + end)

    total_volume = sum((r[5] or 0.0) for r in rows)
    if total_volume <= 0:
        raise ValueError(
            symbol + " has zero volume across all " + str(len(rows)) +
            " archived bars — this series cannot measure a volume gate"
        )

    return [
        {
            "date": datetime.fromisoformat(r[0]),
            "open": r[1], "high": r[2], "low": r[3], "close": r[4],
            "volume": r[5] or 0.0,
        }
        for r in rows
    ]


def load_bars(symbol: str, start: str, end: str) -> list[dict]:
    """Archive for MCX, Kite front-month futures for the indices."""
    if symbol in ARCHIVE_SYMBOLS:
        return load_archive_bars(symbol, start, end)
    return load_futures_bars(symbol, start, end)


def load_futures_bars(symbol: str, start: str, end: str) -> list[dict]:
    """Front-month NFO futures candles, chunked under Kite's 200-day cap.

    The futures series is what production's volume gate actually reads for
    NIFTY and BANKNIFTY, so measuring the gate on anything else would be
    measuring a different gate.
    """
    from dotenv import load_dotenv
    load_dotenv(str(ROOT / ".env"))
    from integrations.brokers.secrets import SecretManager
    from kiteconnect import KiteConnect

    secrets = SecretManager()
    kite = KiteConnect(api_key=secrets.get_secret("api_key", broker="zerodha"))
    kite.set_access_token(secrets.get_secret("access_token", broker="zerodha"))

    today = datetime.now().date()
    futures = [
        i for i in kite.instruments("NFO")
        if i["name"] == symbol and i["instrument_type"] == "FUT"
        and (i["expiry"].date() if hasattr(i["expiry"], "date") else i["expiry"]) >= today
    ]
    if not futures:
        raise ValueError("no live " + symbol + " futures contract")
    token = min(futures, key=lambda i: i["expiry"])["instrument_token"]

    out: list[dict] = []
    a = datetime.strptime(start + " 09:15:00", "%Y-%m-%d %H:%M:%S")
    z = datetime.strptime(end + " 15:30:00", "%Y-%m-%d %H:%M:%S")
    while a < z:
        b = min(a + timedelta(days=180), z)
        out += kite.historical_data(token, a.strftime("%Y-%m-%d %H:%M:%S"),
                                    b.strftime("%Y-%m-%d %H:%M:%S"), "15minute")
        a = b + timedelta(minutes=1)
    seen, uniq = set(), []
    for bar in out:
        if bar["date"] in seen:
            continue
        seen.add(bar["date"])
        uniq.append(bar)
    return uniq


def volume_ratio_at(bars: list[dict], i: int) -> float | None:
    """Reproduce _get_volume_context exactly, as of bar i.

    Today's cumulative volume at this clock time, over the average cumulative
    volume reached by the same clock time on prior sessions. Returns None
    wherever production would return None — in which case production SKIPS the
    gate, so those signals must be excluded rather than counted as passing.
    """
    day = bars[i]["date"].date()
    marker = bars[i]["date"].strftime("%H:%M")

    current = 0.0
    for bar in bars[: i + 1]:
        if bar["date"].date() == day:
            current += float(bar.get("volume") or 0)
    if current <= 0:
        return None

    cutoff = day - timedelta(days=LOOKBACK_DAYS)
    by_day: dict = {}
    for bar in bars[: i + 1]:
        d = bar["date"].date()
        if cutoff <= d < day:
            by_day.setdefault(d, []).append(bar)

    peers: list[float] = []
    for d in sorted(by_day):
        run = 0.0
        reached = False
        for bar in sorted(by_day[d], key=lambda b: b["date"]):
            run += float(bar.get("volume") or 0)
            if bar["date"].strftime("%H:%M") == marker:
                reached = True
                break
        if reached and run > 0:
            peers.append(run)
    if len(peers) < MIN_PRIOR_SESSIONS:
        return None
    return current / (sum(peers) / len(peers))


def _stats(edges: list[float]) -> tuple[int, float, float]:
    n = len(edges)
    if n < 2:
        return n, 0.0, 0.0
    mean = sum(edges) / n
    var = sum((e - mean) ** 2 for e in edges) / (n - 1)
    return n, mean, mean / (math.sqrt(var / n) or 1e-9)


def split_by_gate(symbol: str, bars: list[dict], module,
                  family: str = "breakout") -> dict[str, list[float]]:
    """Forward edge of the signals the gate PASSES vs the ones it BLOCKS.

    `family` decides WHICH BAR is being measured, and that was the hole here.
    This function used to hardcode "breakout", so every run in this lab's life
    measured BREAKOUT_MIN_RATIO (1.10x) and nothing ever measured
    TREND_MIN_RATIO (0.50x) -- the bar that production actually applies to
    trend/pullback/mean-reversion entries.

    That matters because the trend bar is the one doing the blocking. On
    2026-10-12 the index league produced seven signals and the gate refused
    all seven at 0.31x-0.50x against the 0.50x trend bar, while the breakout
    bar was never reached. The docstring above already notes the trend
    threshold moved 0.8 -> 0.5 "argued from an incident rather than from a
    measurement"; the instrument built to settle that question was only ever
    pointed at the other one.
    """
    engine = VolumeEngine()
    out = {"passed": [], "blocked": []}
    for i in range(42, len(bars) - HORIZON):
        window = bars[: i + 1]
        day = window[-1]["date"].date()
        session = [b for b in window if b["date"].date() == day]
        if len(session) < 6 or bars[i + HORIZON]["date"].date() != day:
            continue
        ctx = Ctx(window, session)
        # A bar that did not trade is not an entry point, and an ATR
        # built from a run of them is fiction. See signal_lab.measurable.
        if not measurable(ctx, window[-1]):
            continue
        mkt = build_context(symbol, window, ctx, session)
        try:
            sig = module.evaluate(mkt)
        except Exception:
            continue
        if not getattr(sig, "should_enter", False):
            continue
        ratio = volume_ratio_at(bars, i)
        if ratio is None:
            continue  # production skips the gate here; not evidence either way
        ok, _ = engine.validate_breakout(ratio, 1.0, family)
        call = 1 if sig.direction == "long" else -1
        edge = ((bars[i + HORIZON]["close"] - ctx.price) * call) / ctx.atr
        out["passed" if ok else "blocked"].append(edge)
    return out


def main() -> int:
    print("=" * 88)
    print("  VOLUME LAB — does the gate add edge or remove it?")
    print("  BOTH bars, against the time-of-day-normalised baseline:")
    print("    breakout " + format(VolumeEngine.BREAKOUT_MIN_RATIO, ".2f")
          + "x   trend " + format(VolumeEngine.TREND_MIN_RATIO, ".2f") + "x")
    print("  The trend bar is what production applies to trend/pullback/")
    print("  mean-reversion entries, and it had never been measured.")
    print("  Measured on FRONT-MONTH FUTURES, the series production reads volume from.")
    print("  MCX reads the ARCHIVE (expired contracts Kite deletes); indices read")
    print("  Kite front-month futures. SENSEX and the raw indices are absent from")
    print("  the archive path: an index carries no volume of its own.")
    print("=" * 88)

    index_modules = {getattr(m, "module_id", k): m for k, m in ENTRY_MODULES.items()}
    mcx_modules = {getattr(m, "module_id", k): m for k, m in MCX_ENTRY_MODULES.items()}
    for symbol in SYMBOLS:
        modules = mcx_modules if symbol in ARCHIVE_SYMBOLS else index_modules
        source = "archive" if symbol in ARCHIVE_SYMBOLS else "kite futures"
        for label, (a, b) in (("TRAIN   ", TRAIN), ("HOLD-OUT", HOLDOUT)):
            try:
                bars = load_bars(symbol, a, b)
            except Exception as exc:
                print("  " + symbol + ": could not load bars (" + str(exc) + ")")
                continue
            print("")
            print("  " + symbol + "  " + label + "  " + a + ".." + b
                  + "   (" + str(len(bars)) + " bars, " + source + ")")
            print("      " + "module".ljust(26) + "gate".ljust(9)
                  + "n".rjust(5) + "edge_atr".rjust(11) + "t".rjust(8))
            for family, bar in (("breakout", VolumeEngine.BREAKOUT_MIN_RATIO),
                                ("trend", VolumeEngine.TREND_MIN_RATIO)):
                print("      --- " + family + " bar " + format(bar, ".2f") + "x ---")
                for mid in sorted(modules):
                    res = split_by_gate(symbol, bars, modules[mid], family)
                    if len(res["passed"]) + len(res["blocked"]) < MIN_N:
                        continue
                    for side in ("passed", "blocked"):
                        n, mean, t = _stats(res[side])
                        if n < MIN_SIDE_N:
                            # Count shown, statistics withheld. See MIN_SIDE_N.
                            print("      " + mid.ljust(26) + side.ljust(9)
                                  + str(n).rjust(5)
                                  + "   (n < " + str(MIN_SIDE_N) + ", no edge/t)")
                            continue
                        print("      " + mid.ljust(26) + side.ljust(9) + str(n).rjust(5)
                              + format(mean, "+.3f").rjust(11) + format(t, "+.2f").rjust(8))
    print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
