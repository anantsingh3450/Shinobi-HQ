"""Does implied volatility exceed what the index actually delivers?

    python tools/research/variance_premium_lab.py
    python tools/research/variance_premium_lab.py NIFTY

WHY THIS EXISTS. Hokage only ever BUYS premium, and the IV guard correctly
refuses to buy above the 80th VIX percentile. On 2026-10-14 that refused all
thirteen signals he found, at VIX 94-96%; on 2026-10-15 it refused eleven
more. In a high-IV regime a premium-buying system is structurally unable to
act, and no amount of tuning changes that.

The idea that inverts the problem is SELLING premium, which profits from the
same elevated IV that blocks buying. But before building anything, the premise
has to be measured, and until now it could not be: there is no option premium
history anywhere in the brain, so decay cannot be measured directly.

IT CAN BE MEASURED INDIRECTLY, AND HONESTLY. A short-premium position is, in
essence, a bet that the underlying will move LESS than the option market
implied. That comparison needs no option prices at all:

    implied   = India VIX, an annualised % the market is charging
    realised  = the annualised % the index actually delivered over the
                following horizon, from real candles

Their difference is the variance risk premium. If implied exceeds realised on
average, sellers are paid for carrying the risk - and if the gap is WIDEST at
high VIX, then selling is best exactly where buying is forbidden.

WHAT THIS IS NOT. It is not a strategy, it does not model a spread, and it
ignores everything that makes selling dangerous: gap risk, margin, assignment,
and the fact that the premium is compensation for real tail losses. A positive
average gap is a licence to design carefully, never proof of profit. The
losses live in the tail this average hides, so the worst realised excess is
reported beside the mean.

NO SYNTHETIC PRICES. VIX comes from Kite, the index path from the candle
archive. Nothing is modelled.
"""
from __future__ import annotations

import argparse
import math
import statistics as st
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools" / "research"))

from iv_lab import load_vix_closes, percentile_on  # noqa: E402
# THE ARCHIVE DIRECTLY, not signal_lab.load_bars. That helper tops the
# archive up from Kite, and Kite refuses a historical span over 200 days
# with "interval exceeds max limit" - this lab wants the whole year. The
# archive already holds every bar through yesterday, and VIX (which does
# need the live session) is fetched separately.
from candle_archive import load as archive_load  # noqa: E402
from bots.autonomous.autonomous_bot import AutonomousTradingBot as _Bot  # noqa: E402

#: Trading days ahead over which realised volatility is measured. A seller's
#: exposure is the life of the option; a week is the shortest horizon with
#: enough observations per bucket to say anything.
HORIZON_DAYS = 5

#: Trading days in a year, for annualising realised volatility onto the same
#: scale VIX is quoted in.
TRADING_DAYS = 252

#: The percentile at and above which production refuses to BUY premium. The
#: question is what a seller would have earned in exactly that regime.
BUY_BLOCK = _Bot._VIX_PERCENTILE_BLOCK

#: Fewer than this in a bucket HALF and the mean is arithmetic on noise.
MIN_N = 20

#: The bar, corrected for the number of buckets this lab tests: 3 VIX buckets
#: across 3 indices. Shared with everything else that judges a t here, so a
#: search cannot quietly award itself an easier standard.
from signal_lab import corrected_t  # noqa: E402

BAR = round(corrected_t(3 * 3), 2)


def daily_closes(bars: list[dict]) -> list[tuple[object, float]]:
    """One close per session, from intraday bars: the last bar of each day."""
    out: dict = {}
    for b in bars:
        out[b["date"].date()] = b["close"]
    return sorted(out.items())


def realised_vol(closes: list[float]) -> float | None:
    """Annualised realised volatility, in percent, from daily log returns."""
    rets = []
    for a, b in zip(closes, closes[1:]):
        if a > 0 and b > 0:
            rets.append(math.log(b / a))
    if len(rets) < 2:
        return None
    return st.stdev(rets) * math.sqrt(TRADING_DAYS) * 100.0


def _stats(xs: list[float]) -> tuple[int, float, float]:
    n = len(xs)
    if n < 2:
        return n, 0.0, 0.0
    m = st.mean(xs)
    sd = st.stdev(xs)
    return n, m, (m / (sd / math.sqrt(n)) if sd else 0.0)


def measure(symbol: str, vix: list[tuple[object, float]]) -> list[dict]:
    """One row per day: the VIX percentile, implied, realised, and the excess."""
    bars = archive_load(symbol, "2026-01-01", "2026-12-31")
    if not bars:
        raise ValueError("no archived bars")
    series = daily_closes(bars)
    vix_on = dict(vix)

    rows = []
    for i in range(len(series) - HORIZON_DAYS):
        day, _ = series[i]
        implied = vix_on.get(day)
        if implied is None:
            continue
        pct = percentile_on(vix, day)
        if pct is None:
            continue
        window = [c for _, c in series[i: i + HORIZON_DAYS + 1]]
        rv = realised_vol(window)
        if rv is None:
            continue
        rows.append({
            "day": day, "pct": pct, "implied": implied, "realised": rv,
            "excess": implied - rv,
        })
    return rows


def report(symbol: str, rows: list[dict]) -> None:
    if not rows:
        print(f"\n  {symbol}: no overlapping VIX and candle days")
        return

    print(f"\n  {symbol}   {len(rows)} days   "
          f"{rows[0]['day']} .. {rows[-1]['day']}")
    print(f"    {'VIX percentile':22} {'TRAIN n':>5} {'excess':>8} {'t':>7} "
          f"{'HOLD n':>5} {'excess':>8} {'t':>7} {'worst':>8}  verdict")

    # TRAIN AND HOLD-OUT, like everything else here. Three buckets on one
    # period is a search, and a bucket that looks good on the whole sample is
    # a hypothesis until the half it was not chosen on agrees.
    mid = len(rows) // 2
    halves = {"TRAIN": rows[:mid], "HOLD": rows[mid:]}

    buckets = [
        ("below 50th", 0.0, 0.50),
        ("50th-80th", 0.50, BUY_BLOCK),
        (f"{BUY_BLOCK:.0%}+ (blocked)", BUY_BLOCK, 1.01),
    ]
    for label, lo, hi in buckets:
        cells = {}
        for half, part in halves.items():
            sel = [r for r in part if lo <= r["pct"] < hi]
            cells[half] = (_stats([r["excess"] for r in sel]),
                           min((r["excess"] for r in sel), default=0.0),
                           st.mean([r["implied"] for r in sel]) if sel else 0.0,
                           st.mean([r["realised"] for r in sel]) if sel else 0.0)
        (tn, tm, tt), tw, _, _ = cells["TRAIN"]
        (hn, hm, ht), hw, himp, hrea = cells["HOLD"]

        verdict = ""
        if tn < MIN_N or hn < MIN_N:
            verdict = f"too few days (train {tn}, hold {hn})"
        elif tt >= BAR and ht >= BAR and tm > 0 and hm > 0:
            verdict = "SELLERS PAID on both halves"
        elif tt <= -BAR and ht <= -BAR:
            verdict = "SELLERS LOST on both halves"
        else:
            verdict = "one half only - not evidence"
        print(f"    {label:22} {tn:>5} {tm:>+7.1f}% {tt:>+7.2f} "
              f"{hn:>5} {hm:>+7.1f}% {ht:>+7.2f} {min(tw, hw):>+8.1f}%  {verdict}")

    n, mean, t = _stats([r["excess"] for r in rows])
    worst = min(r["excess"] for r in rows)
    print(f"    {'ALL DAYS':22} {n:>5} "
          f"{st.mean([r['implied'] for r in rows]):>8.1f}% "
          f"{st.mean([r['realised'] for r in rows]):>8.1f}% "
          f"{mean:>+7.1f}% {t:>+7.2f} {worst:>+8.1f}%")
    print(f"      worst single day: implied fell short of realised by "
          f"{abs(worst):.1f} points — that day is where a seller's loss lives.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("symbols", nargs="*")
    args = ap.parse_args()
    symbols = [s.upper() for s in (args.symbols or ["NIFTY", "SENSEX", "BANKNIFTY"])]

    print("=" * 92)
    print("  VARIANCE PREMIUM — is implied volatility above what the index delivers?")
    print(f"  implied = India VIX (Kite). realised = the next {HORIZON_DAYS} "
          f"sessions, annualised, from real candles.")
    print("  A positive excess means SELLERS were paid. Bucketed by the VIX")
    print(f"  percentile, because buying is blocked at {BUY_BLOCK:.0%}+ and the")
    print("  question is what a seller would have earned exactly there.")
    print("  NOT a strategy: no spread, no margin, no gap risk. The mean hides")
    print("  the tail, so the WORST day is reported beside it.")
    print(f"  Train/hold split, bar t>={BAR} on BOTH halves (corrected for 9 buckets).")
    print("=" * 92)

    try:
        vix = load_vix_closes()
    except Exception as exc:
        print(f"\n  could not load India VIX ({exc}).")
        print("  This needs a live Zerodha session - VIX is not archived.")
        return 1
    print(f"\n  India VIX: {len(vix)} daily closes, {vix[0][0]} .. {vix[-1][0]}")

    for symbol in symbols:
        try:
            report(symbol, measure(symbol, vix))
        except Exception as exc:
            print(f"\n  {symbol}: {exc}")
    print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
