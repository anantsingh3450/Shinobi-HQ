"""Is the IV premium guard filtering, or is it an off switch?

WHY THIS EXISTS
On 2026-10-12 Hokage made 238 decisions and took no trade. The window that
mattered -- SessionShift on GOLDM/SILVERM, the only ACTIVE strategy in the
system -- opened at 17:00 on schedule, evaluated, and was refused by the IV
premium guard. It had refused 10 of the previous 11 sessions.

The guard blocks an options BUY when India VIX sits at or above the 80th
percentile OF ITS OWN TRAILING 60 DAYS. That is a purely RELATIVE measure with
no absolute anchor, and in a calm regime that gets slightly less calm it pins
itself near 100% by construction:

    2026-10-12   VIX 15.25   98th percentile of 60 days
                             75th percentile of the YEAR
                             below the year's p90 of 18.85

Across every day the guard has ever blocked, 57% had VIX under 16 and 36% had
it under 14. So it may be measuring "has volatility risen lately" rather than
"is premium expensive" -- which for a buyer is the question that matters,
because what you pay is an absolute number.

MAY BE. Nobody has measured it, and this file does not assume an answer.

    If BLOCKED is worse than PASSED, the guard earns its place and the
    drought is the market being a bad place to buy options.
    If BLOCKED matches or beats PASSED, it is an off switch and the
    commander has a measured case for an absolute floor.

THE FAILURE MODE THIS IS LOOKING FOR is the one veto_lab already found once:
"if the veto's yes-condition is nearly disjoint from the module's firing
condition, it is not filtering, it is an off switch." The bias engine blocked
15 of 16 SessionShift auctions that way. This is the same shape of question
asked of a different veto.

NOTHING HERE CHANGES A THRESHOLD. _VIX_PERCENTILE_BLOCK is a SAFETY constant
and only the commander moves it. This prints evidence.

MEASUREMENT
  * Bars come from the CANDLE ARCHIVE, which keeps expired contracts Kite
    deletes -- without it the train half does not exist (see volume_lab).
  * India VIX daily closes come from Kite. VIX is an index, so it has no
    futures roll and its history stays served.
  * The percentile at each signal is computed POINT IN TIME, from closes
    strictly up to that day. Using the full series would leak the future into
    the decision and flatter the guard.
  * Edge is realised with the production 1.25 ATR thesis stop applied bar by
    bar, via sweep_lab.realised -- the same geometry the weekly audit uses, so
    these numbers are comparable with it.
"""
from __future__ import annotations

import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from signal_lab import Ctx  # noqa: E402
from entry_module_lab import build_context  # noqa: E402
from sweep_lab import HORIZON, MIN_N, PROD_STOP_ATR, _stats, realised  # noqa: E402

from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES  # noqa: E402
from hokage.memory.resolver import brain_root  # noqa: E402

BRAIN = brain_root()

#: Production's own settings, imported rather than restated so this cannot
#: drift from the gate it is measuring.
from bots.autonomous.autonomous_bot import AutonomousTradingBot as _Bot  # noqa: E402

VIX_LOOKBACK = _Bot._VIX_LOOKBACK_DAYS
VIX_BLOCK = _Bot._VIX_PERCENTILE_BLOCK

#: The league the guard actually bites. SessionShift is the only ACTIVE
#: strategy and trades these two; the energies are parked but measured anyway
#: because a parked asset's evidence is still evidence.
SYMBOLS = ("GOLDM", "SILVERM", "CRUDEOIL", "NATURALGAS")

#: Minimum n on ONE SIDE before a statistic is printed. The combined floor
#: leaves a side free to be tiny, and a t computed on two observations formats
#: like certainty (volume_lab printed +5793103448.28 before this was added).
MIN_SIDE_N = 10

#: Smallest ATR, as a fraction of price, a context may have and still be
#: measured. Edge is reported in ATR units, so a near-zero ATR divides a
#: normal price move by almost nothing and produces an unbounded number.
#:
#: Not hypothetical. The first run of this lab reported SessionShift BLOCKED
#: on GOLDM train at +7.545 edge_atr, t=+2.22, n=36 -- a mean realised edge of
#: seven and a half ATR over a four-bar horizon against a 1.25 ATR stop, which
#: is not a thing that happens. One context, 2026-03-11 14:30, carried
#: ATR=0.214 on a price of 173,225: a single point of movement scores 5 ATR
#: there, and GOLDM's MEDIAN ATR is 195.71. One degenerate observation moved
#: the bucket mean by more than seven ATR.
#:
#: `if not ctx.atr` only rejects an ATR of exactly zero, which is why this
#: slipped through. Measured across the archive, a 1bp floor costs 19 of 2,535
#: GOLDM contexts, 2 of CRUDEOIL, 5 of NATURALGAS and 0 of SILVERM, against
#: medians of 0.15%-0.40% -- it removes stale tape, not signal.
MIN_ATR_FRACTION_OF_PRICE = 0.0001   # 1 basis point

#: Skip any bar that did not trade. THIS is what produced the +7.545.
#:
#: The archive stores zero-volume bars verbatim from Kite, which repeats the
#: last price when a contract is not trading. GOLDM26SEPFUT, a far-month
#: contract, sat flat for hours:
#:
#:   2026-03-18 16:30  o=h=l=c=167,373.00  vol=0
#:   ...  six identical bars  ...
#:   2026-03-18 18:00  o=167,373  l=164,485  c=164,485  vol=1
#:
#: Four "signals" fired on those flat bars. ATR computed from flat data is
#: tiny, and the forward move is the gap to the next real trade, so each
#: scored +63.97 ATR. Four observations in a bucket of 36 moved its mean by
#: more than seven ATR and produced a t of +2.22 out of nothing.
#:
#: You cannot enter on a bar that had no trades. 13% of GOLDM's archived bars
#: carry zero volume (1,148 of 8,527), so this is not an edge case.
REQUIRE_TRADED_BAR = True


def load_archive_bars(symbol: str, start: str, end: str) -> list[dict]:
    """Candles from the archive, which keeps the contracts Kite delists."""
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
    return [
        {"date": datetime.fromisoformat(r[0]), "open": r[1], "high": r[2],
         "low": r[3], "close": r[4], "volume": r[5] or 0.0}
        for r in rows
    ]


def load_vix_closes() -> list[tuple[object, float]]:
    """India VIX daily closes, oldest first. Kite: VIX is an index, no roll."""
    from dotenv import load_dotenv

    load_dotenv(str(ROOT / ".env"))
    from integrations.brokers.secrets import SecretManager
    from kiteconnect import KiteConnect

    secrets = SecretManager()
    kite = KiteConnect(api_key=secrets.get_secret("api_key", broker="zerodha"))
    kite.set_access_token(secrets.get_secret("access_token", broker="zerodha"))

    token = None
    for inst in kite.instruments("NSE"):
        if inst["tradingsymbol"].upper() in ("INDIA VIX", "INDIAVIX"):
            token = inst["instrument_token"]
            break
    if token is None:
        raise ValueError("could not resolve INDIA VIX")

    end = datetime.now()
    start = end - timedelta(days=500)
    candles = kite.historical_data(
        token, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), "day")
    return [(c["date"].date(), c["close"]) for c in candles]


def percentile_on(vix: list[tuple[object, float]], day) -> float | None:
    """Reproduce _india_vix_percentile AS OF `day`, with no lookahead.

    Production asks for the trailing VIX_LOOKBACK closes ending today and
    scores today against them. Here the series is truncated at `day` first, so
    a signal in March is never judged against April's volatility.
    """
    window = [v for d, v in vix if d <= day][-VIX_LOOKBACK:]
    if len(window) < 20:          # production's own floor
        return None
    current = window[-1]
    return sum(1 for c in window if c <= current) / len(window)


def split_by_guard(symbol: str, bars: list[dict], module,
                   vix: list[tuple[object, float]]) -> dict[str, list[float]]:
    """Realised edge of the signals the guard PASSES vs the ones it BLOCKS."""
    out: dict[str, list[float]] = {"passed": [], "blocked": []}
    for i in range(42, len(bars) - HORIZON):
        window = bars[: i + 1]
        day = window[-1]["date"].date()
        session = [b for b in window if b["date"].date() == day]
        if len(session) < 6 or bars[i + HORIZON]["date"].date() != day:
            continue
        ctx = Ctx(window, session)
        # A zero ATR is rejected by `not ctx.atr`; a NEAR-zero one is not, and
        # it is the dangerous case. See MIN_ATR_FRACTION_OF_PRICE.
        if not ctx.atr or not ctx.price:
            continue
        if ctx.atr / ctx.price < MIN_ATR_FRACTION_OF_PRICE:
            continue
        # A bar with no volume did not trade; an entry on it is fiction, and
        # the ATR built from a run of them is fiction too.
        if REQUIRE_TRADED_BAR and not (bars[i].get("volume") or 0) > 0:
            continue
        try:
            sig = module.evaluate(build_context(symbol, window, ctx, session))
        except Exception:
            continue
        if not getattr(sig, "should_enter", False):
            continue

        pct = percentile_on(vix, day)
        if pct is None:
            continue      # production SKIPS the guard here; not evidence either way

        call = 1 if sig.direction == "long" else -1
        edge = realised(bars, i, call, ctx.atr,
                        getattr(module, "module_id", None), symbol)
        out["blocked" if pct >= VIX_BLOCK else "passed"].append(edge)
    return out


def halves(bars: list[dict]) -> tuple[tuple[str, str], tuple[str, str]]:
    """Split the archive's own span down the middle, rather than hardcoding
    dates that silently fall outside it."""
    days = sorted({b["date"].date() for b in bars})
    mid = days[len(days) // 2]
    return ((days[0].isoformat(), mid.isoformat()),
            (mid.isoformat(), days[-1].isoformat()))


def main() -> int:
    print("=" * 86)
    print("  IV LAB - is the premium guard filtering, or an off switch?")
    print("  Production blocks an options BUY at VIX >= %.0f%% of its trailing %d days."
          % (VIX_BLOCK * 100, VIX_LOOKBACK))
    print("  Percentile computed POINT IN TIME. Edge realised with the %.2f ATR"
          % PROD_STOP_ATR)
    print("  production stop, same geometry as the weekly audit.")
    print("  PASSED better than BLOCKED -> the guard earns its place.")
    print("  BLOCKED >= PASSED          -> it is an off switch.")
    print("=" * 86)

    vix = load_vix_closes()
    print("  India VIX: %d daily closes, %s .. %s"
          % (len(vix), vix[0][0], vix[-1][0]))

    modules = {getattr(m, "module_id", k): m for k, m in MCX_ENTRY_MODULES.items()}

    for symbol in SYMBOLS:
        try:
            full = load_archive_bars(symbol, "2000-01-01", "2100-01-01")
        except ValueError as exc:
            print("\n  %s: %s" % (symbol, exc))
            continue
        train, hold = halves(full)
        for label, (a, b) in (("TRAIN   ", train), ("HOLD-OUT", hold)):
            bars = [x for x in full
                    if a <= x["date"].date().isoformat() <= b]
            print("")
            print("  %s  %s  %s..%s   (%d bars, archive)"
                  % (symbol, label, a, b, len(bars)))
            print("      %-26s%-9s%5s%11s%8s"
                  % ("module", "guard", "n", "edge_atr", "t"))
            for mid in sorted(modules):
                res = split_by_guard(symbol, bars, modules[mid], vix)
                if len(res["passed"]) + len(res["blocked"]) < MIN_N:
                    continue
                for side in ("passed", "blocked"):
                    n, mean, t = _stats(res[side])
                    if n < MIN_SIDE_N:
                        print("      %-26s%-9s%5d   (n < %d, no edge/t)"
                              % (mid, side, n, MIN_SIDE_N))
                        continue
                    print("      %-26s%-9s%5d%11s%8s"
                          % (mid, side, n, format(mean, "+.3f"), format(t, "+.2f")))
    print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
