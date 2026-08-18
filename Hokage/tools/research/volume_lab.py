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

from signal_lab import Ctx  # noqa: E402
from entry_module_lab import build_context  # noqa: E402

from bots.autonomous.intelligence import VolumeEngine  # noqa: E402
from bots.strategy.components.entries import ENTRY_MODULES  # noqa: E402

#: Mirrors AutonomousTradingBot._VOLUME_PROFILE_LOOKBACK_DAYS / _MIN_PRIOR_SESSIONS.
LOOKBACK_DAYS = 14
MIN_PRIOR_SESSIONS = 3

HORIZON = 4          # 60 minutes, the primary horizon everywhere else
MIN_N = 30

TRAIN = ("2026-03-01", "2026-06-15")
HOLDOUT = ("2026-06-16", "2026-08-13")

#: Only the futures-backed underlyings can be measured: SENSEX has no volume
#: series at all, which is the finding rather than a limitation of this tool.
SYMBOLS = ("NIFTY", "BANKNIFTY")


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


def split_by_gate(symbol: str, bars: list[dict], module) -> dict[str, list[float]]:
    """Forward edge of the signals the gate PASSES vs the ones it BLOCKS."""
    engine = VolumeEngine()
    out = {"passed": [], "blocked": []}
    for i in range(42, len(bars) - HORIZON):
        window = bars[: i + 1]
        day = window[-1]["date"].date()
        session = [b for b in window if b["date"].date() == day]
        if len(session) < 6 or bars[i + HORIZON]["date"].date() != day:
            continue
        ctx = Ctx(window, session)
        if not ctx.atr:
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
        ok, _ = engine.validate_breakout(ratio, 1.0, "breakout")
        call = 1 if sig.direction == "long" else -1
        edge = ((bars[i + HORIZON]["close"] - ctx.price) * call) / ctx.atr
        out["passed" if ok else "blocked"].append(edge)
    return out


def main() -> int:
    print("=" * 88)
    print("  VOLUME LAB — does the gate add edge or remove it?")
    print("  Breakout bar is " + format(VolumeEngine.BREAKOUT_MIN_RATIO, ".2f")
          + "x of the time-of-day-normalised baseline.")
    print("  Measured on FRONT-MONTH FUTURES, the series production reads volume from.")
    print("  SENSEX is absent because it has no volume series — see the docstring.")
    print("=" * 88)

    modules = {getattr(m, "module_id", k): m for k, m in ENTRY_MODULES.items()}
    for symbol in SYMBOLS:
        for label, (a, b) in (("TRAIN   ", TRAIN), ("HOLD-OUT", HOLDOUT)):
            try:
                bars = load_futures_bars(symbol, a, b)
            except Exception as exc:
                print("  " + symbol + ": could not load bars (" + str(exc) + ")")
                continue
            print("")
            print("  " + symbol + "  " + label + "  " + a + ".." + b
                  + "   (" + str(len(bars)) + " bars)")
            print("      " + "module".ljust(26) + "gate".ljust(9)
                  + "n".rjust(5) + "edge_atr".rjust(11) + "t".rjust(8))
            for mid in sorted(modules):
                res = split_by_gate(symbol, bars, modules[mid])
                if len(res["passed"]) + len(res["blocked"]) < MIN_N:
                    continue
                for side in ("passed", "blocked"):
                    n, mean, t = _stats(res[side])
                    if n < 2:
                        print("      " + mid.ljust(26) + side.ljust(9)
                              + str(n).rjust(5) + "  too few")
                        continue
                    print("      " + mid.ljust(26) + side.ljust(9) + str(n).rjust(5)
                          + format(mean, "+.3f").rjust(11) + format(t, "+.2f").rjust(8))
    print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
