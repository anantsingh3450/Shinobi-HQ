"""Signal Lab — measure a directional signal's edge before trusting it.

WHY THIS EXISTS
On 2026-08-05 Hokage's live record was 24 closed trades, 33.3% wins, -15,490.
The bias engine that picks CALL vs PUT was measured at ~47% accuracy across 622
signals: a coin flip, slightly worse. Every attempted improvement up to that
point had been an intuition shipped on plausibility. The one filter that WAS
measured first (EMA9 slope, "momentum still building") moved accuracy from
47.7% to 47.8% and was deleted the same hour.

An option BUYER cannot survive a coin flip. Premium decays every day it is held
and the spread is paid on entry and exit, so a directional read must be right
materially more than half the time, or right by a materially larger margin than
it is wrong. Nothing about exit geometry rescues that; it only changes how fast
the account bleeds.

So the bottleneck was never a missing feature — it was the absence of a way to
tell a real edge from a plausible story. This module is that way.

WHAT IT MEASURES
For each candidate signal, on real Kite candles:
  - n            how many times it fired (a signal that never fires is useless
                 however good it looks; MeanReversion fired 16 times in 6 weeks)
  - accuracy     % of times the underlying moved the predicted way
  - edge_atr     MEAN forward move in ATR units, signed by the prediction.
                 This is the number that actually matters. Accuracy ignores
                 magnitude, and an option buyer is paid in magnitude: being
                 right 50% of the time with big wins and small losses is a
                 living, being right 55% with the reverse is not.
  - t_stat       edge divided by its standard error. Below ~2 the result is
                 indistinguishable from luck no matter how pretty the accuracy.

A candidate is only worth shipping when n is large, edge_atr is positive, and
t_stat clears 2. Anything else is a story.

USAGE
    python tools/research/signal_lab.py                # default universe
    python tools/research/signal_lab.py NIFTY BANKNIFTY
"""
from __future__ import annotations

import datetime as _dt

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

#: Forward horizons in 15-minute bars. 4 bars = 1 hour, roughly how long
#: Hokage's trades have actually lived.
HORIZONS = (2, 4, 8)

_SPOT = {
    "NIFTY": ("NSE", "NIFTY 50"),
    "BANKNIFTY": ("NSE", "NIFTY BANK"),
    "SENSEX": ("BSE", "SENSEX"),
}

#: MCX has no spot instrument — the futures contract IS the tradable series, and
#: MCX options are options ON that future, so it is also the correct reference.
#: Unlike NSE index spot (volume 0, which silently degraded VWAP to a plain mean
#: of closes and destroyed the old bias engine's edge), these carry REAL traded
#: volume, so the volume-dependent candidates can finally be judged here.
_MCX_FUTURES = ("CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM")


# ----------------------------------------------------------------- indicators
def ema(values: list[float], period: int) -> float:
    k = 2.0 / (period + 1.0)
    out = values[0]
    for v in values[1:]:
        out = v * k + out * (1.0 - k)
    return out


def atr(bars: list[dict], period: int = 14) -> float:
    trs = [
        max(cur["high"] - cur["low"],
            abs(cur["high"] - prev["close"]),
            abs(cur["low"] - prev["close"]))
        for prev, cur in zip(bars[-(period + 1):-1], bars[-period:])
    ]
    return (sum(trs) / len(trs)) if trs else 0.0


def session_vwap(session: list[dict]) -> float:
    vol = sum(b["volume"] or 0.0 for b in session)
    if vol > 0:
        return sum(((b["high"] + b["low"] + b["close"]) / 3.0) * (b["volume"] or 0.0)
                   for b in session) / vol
    return sum(b["close"] for b in session) / len(session)


class Ctx:
    """Everything a candidate signal is allowed to see. Strictly no future."""

    __slots__ = ("bars", "session", "price", "vwap", "atr", "ema9", "ema21")

    def __init__(self, bars: list[dict], session: list[dict]) -> None:
        closes = [b["close"] for b in bars]
        self.bars = bars
        self.session = session
        self.price = closes[-1]
        self.vwap = session_vwap(session)
        self.atr = atr(bars)
        self.ema9 = ema(closes[-30:], 9)
        self.ema21 = ema(closes[-42:], 21)


#: Smallest ATR, as a fraction of price, a context may carry and still be
#: measured. Edge is reported in ATR units, so a near-zero ATR divides a normal
#: price move by almost nothing and the ratio is unbounded.
MIN_ATR_FRACTION_OF_PRICE = 0.0001   # 1 basis point


def measurable(ctx: "Ctx", entry_bar: dict) -> bool:
    """Whether this bar is a legitimate place to measure an entry FROM.

    WHY THIS EXISTS, AND IT IS NOT THEORETICAL
    2026-10-12, iv_lab reported SessionShift BLOCKED on GOLDM train at +7.545
    edge_atr, t=+2.22, n=36 — a mean realised edge of seven and a half ATR over
    four bars against a 1.25 ATR stop, which is not a thing that happens. Four
    identical observations carried the whole bucket:

        2026-03-18 16:30  o=h=l=c=167,373.00  vol=0   GOLDM26SEPFUT
        ... six identical bars, a far-month contract ...
        2026-03-18 18:00  o=167,373  l=164,485  vol=1

    The contract had not traded for hours. Kite repeats the last price when
    nothing trades, the archive stores that verbatim, and every lab treated
    them as entry points: ATR computed across flat bars is tiny, the "forward
    move" is really the gap to the next genuine trade, and each scored +63.97
    ATR. Removing them dropped that bucket from n=36 to n=6 — 83% of it was
    fiction.

    Zero-volume bars are 13.5% of GOLDM, 13.0% of CRUDEOIL, 12.2% of
    NATURALGAS and 4.7% of SILVERM. `if not ctx.atr` only ever rejected an ATR
    of EXACTLY zero, which is why a decade of near-zero ones went through.

    YOU CANNOT ENTER ON A BAR THAT DID NOT TRADE. That is the whole rule.
    """
    if not ctx.atr or not ctx.price:
        return False
    if ctx.atr / ctx.price < MIN_ATR_FRACTION_OF_PRICE:
        return False
    # Volume is only evidence of trading on a series that HAS volume.
    #
    # This read "absent means an index, present-and-zero means it did not
    # trade" — the right idea, defeated by the data. candle_archive stores an
    # index's volume as 0, not NULL: all 4,075 bars of NIFTY, BANKNIFTY and
    # SENSEX carry volume=0, because an index is a calculation and nothing
    # trades it. So this rejected EVERY index bar, and with it every index
    # asset in every lab that calls measurable — sweep_lab could not propose a
    # knob for NIFTY, stop_lab could not measure one, hypothesis_lab found
    # zero candidates on SENSEX. Three of seven assets, silently, including
    # the one carrying a confirmed cell.
    #
    # So ask the SERIES, not the bar. If nothing in this window ever traded,
    # the instrument carries no volume and volume cannot be a trade filter. If
    # something did, a zero means this bar is one of the repeated prints Kite
    # emits when a contract is quiet — which is what the guard is for.
    volume = entry_bar.get("volume")
    if volume is not None and volume <= 0 and _series_carries_volume(ctx):
        return False
    return True


#: Bars of recent history consulted to decide whether an instrument carries
#: volume at all. Bounded because measurable() runs once per candidate bar and
#: ctx.bars grows to the whole archive; an instrument that trades shows it
#: within a few hundred bars.
_VOLUME_PROBE_BARS = 300


def _series_carries_volume(ctx: "Ctx") -> bool:
    """True when this instrument reports real traded volume somewhere nearby."""
    for bar in ctx.bars[-_VOLUME_PROBE_BARS:]:
        v = bar.get("volume")
        if v is not None and v > 0:
            return True
    return False


# ----------------------------------------------------------------- candidates
# Each returns +1 (expect up), -1 (expect down) or 0 (stand aside).

def sig_current_bias(c: Ctx) -> int:
    """Hokage's live rule, as the baseline every candidate must beat."""
    margin = 0.5 * c.atr
    if c.ema9 > c.ema21 and (c.price - c.vwap) >= margin:
        return 1
    if c.ema9 < c.ema21 and (c.vwap - c.price) >= margin:
        return -1
    return 0


def sig_vwap_reversion(c: Ctx) -> int:
    """Fade a stretch from VWAP. The opposite bet to the baseline."""
    if not c.atr:
        return 0
    stretch = (c.price - c.vwap) / c.atr
    if stretch >= 1.5:
        return -1
    if stretch <= -1.5:
        return 1
    return 0


def sig_opening_range(c: Ctx) -> int:
    """Break of the first hour's range, in the direction of the break."""
    if len(c.session) < 4:
        return 0
    opening = c.session[:4]
    hi = max(b["high"] for b in opening)
    lo = min(b["low"] for b in opening)
    if c.price > hi:
        return 1
    if c.price < lo:
        return -1
    return 0


def sig_roc(c: Ctx) -> int:
    """Raw rate of change over the last 4 bars, thresholded on ATR."""
    if len(c.bars) < 5 or not c.atr:
        return 0
    move = c.price - c.bars[-5]["close"]
    if move >= c.atr:
        return 1
    if move <= -c.atr:
        return -1
    return 0


def sig_trend_pullback(c: Ctx) -> int:
    """Uptrend, but buy only when price has pulled back toward VWAP."""
    if not c.atr:
        return 0
    dist = (c.price - c.vwap) / c.atr
    if c.ema9 > c.ema21 and -0.5 <= dist <= 0.5:
        return 1
    if c.ema9 < c.ema21 and -0.5 <= dist <= 0.5:
        return -1
    return 0


def sig_volume_thrust(c: Ctx) -> int:
    """Directional bar on volume well above the session's own average."""
    if len(c.session) < 6 or not c.atr:
        return 0
    vols = [b["volume"] or 0.0 for b in c.session]
    avg = sum(vols[:-1]) / max(1, len(vols) - 1)
    last = c.bars[-1]
    if avg <= 0 or (last["volume"] or 0.0) < 1.5 * avg:
        return 0
    body = last["close"] - last["open"]
    if body >= 0.5 * c.atr:
        return 1
    if body <= -0.5 * c.atr:
        return -1
    return 0


def sig_persistence(c: Ctx) -> int:
    """Three consecutive closes in the same direction."""
    if len(c.bars) < 4:
        return 0
    d = [c.bars[-i]["close"] - c.bars[-i - 1]["close"] for i in (1, 2, 3)]
    if all(x > 0 for x in d):
        return 1
    if all(x < 0 for x in d):
        return -1
    return 0


def sig_persistence_plus_structure(c: Ctx) -> int:
    """Persistence AND the existing structure filter, both agreeing.

    Never assume a combination inherits its parts' edge — measure it. The
    baseline has no edge on its own (t ~ 0) but it is not harmful, so gating
    persistence with it may keep the edge while cutting the weakest signals.
    """
    p = sig_persistence(c)
    if p == 0:
        return 0
    b = sig_current_bias(c)
    return p if p == b else 0


def sig_persistence_no_vwap(c: Ctx) -> int:
    """Persistence gated only by EMA structure, with VWAP removed entirely.

    NSE index spot reports volume 0, so session VWAP degrades to a plain mean
    of closes. If that leg is noise, dropping it should not cost edge.
    """
    p = sig_persistence(c)
    if p == 0:
        return 0
    if p == 1 and c.ema9 > c.ema21:
        return 1
    if p == -1 and c.ema9 < c.ema21:
        return -1
    return 0


CANDIDATES = {
    "current_bias(baseline)": sig_current_bias,
    "vwap_reversion": sig_vwap_reversion,
    "opening_range_break": sig_opening_range,
    "roc_1atr": sig_roc,
    "trend_pullback": sig_trend_pullback,
    "volume_thrust": sig_volume_thrust,
    "persistence_3bar": sig_persistence,
    "persist+structure": sig_persistence_plus_structure,
    "persist+ema_noVWAP": sig_persistence_no_vwap,
}


# ------------------------------------------------------------------- harness
#: Kite's ceiling for a single 15-minute history request.
MAX_HISTORY_DAYS = 195

#: Fewest bars a measurement half may contain before it is refused outright.
#: A half is roughly six weeks of MCX tape, which is ~1,400 fifteen-minute bars;
#: 500 is the point below which a "result" is really a statement about missing
#: data wearing a t-statistic.
MIN_BARS_PER_HALF = 500


def available_range(symbol: str) -> tuple[str, str]:
    """The first and last 15-minute bar Kite will actually serve for `symbol`.

    WHY THIS EXISTS. 2026-08-27, 08:15: the gas sweep reported TRAIN n=3 where
    the same sweep had reported n=55 the previous evening. Nothing about the
    market changed — the front-month contract rolled. `load_bars` resolves MCX
    symbols to the nearest live expiry, and a freshly-fronted contract has no
    history from before it listed:

        NATURALGAS26SEPFUT   3500 bars   from 2026-05-20   <- today's front
        NATURALGAS26OCTFUT   2825 bars   from 2026-05-27
        NATURALGAS26NOVFUT   1787 bars   from 2026-05-29

    So the fixed TRAIN window (2026-05-01..06-30) had walked off the front of
    the data and was silently measuring six days instead of two months. It did
    not error. It returned n=3 and a t-statistic of +2.00.

    That is the most dangerous shape a bug can take here: a measurement that
    still looks like a measurement. Every MCX pair degrades this way on every
    roll, and the weekly audit would have compared next Friday's six-week train
    half against last Friday's three-month one and called the difference a
    change in edge.

    Deeper history is not available to buy: gas's oldest live contract starts
    2026-05-20 and nothing in Kite's instrument dump reaches further, because
    expired contracts are delisted along with their tokens.
    """
    end = _dt.date.today()
    start = end - _dt.timedelta(days=MAX_HISTORY_DAYS)
    bars = load_bars(symbol,
                     start.strftime("%Y-%m-%d") + " 09:00:00",
                     end.strftime("%Y-%m-%d") + " 23:59:00")
    if not bars:
        raise ValueError(f"no candles available for {symbol}")
    return (bars[0]["date"].strftime("%Y-%m-%d %H:%M:%S"),
            bars[-1]["date"].strftime("%Y-%m-%d %H:%M:%S"))


def halves(symbol: str) -> tuple[tuple[str, str], tuple[str, str]]:
    """(train, hold-out) windows derived from what this symbol actually has.

    Split at the midpoint of the available range, train older. Derived rather
    than hardcoded so a contract roll shortens BOTH halves honestly instead of
    hollowing out one of them. Callers must record the dates they were given —
    comparability across weeks comes from recording the window, not from
    pretending it never moves.
    """
    first, last = available_range(symbol)
    a = _dt.datetime.strptime(first, "%Y-%m-%d %H:%M:%S")
    b = _dt.datetime.strptime(last, "%Y-%m-%d %H:%M:%S")
    mid = a + (b - a) / 2
    cut = mid.strftime("%Y-%m-%d")
    return ((first, cut + " 23:59:00"), (cut + " 00:00:00", last))


def _kite():
    from dotenv import load_dotenv
    load_dotenv(str(ROOT / ".env"))
    from integrations.brokers.secrets import SecretManager
    from kiteconnect import KiteConnect

    secrets = SecretManager()
    kite = KiteConnect(api_key=secrets.get_secret("api_key", broker="zerodha"))
    kite.set_access_token(secrets.get_secret("access_token", broker="zerodha"))
    return kite


def _live_futures(kite, symbol: str) -> list[dict]:
    today = _dt.date.today()
    futures = [
        i for i in kite.instruments("MCX")
        if i["name"] == symbol and i["instrument_type"] == "FUT"
        and (i["expiry"].date() if hasattr(i["expiry"], "date") else i["expiry"]) >= today
    ]
    if not futures:
        raise ValueError(f"no live {symbol} futures contract")
    return futures


def _front_contract(symbol: str) -> str:
    """Tradingsymbol of the contract `load_bars` will actually read.

    Recorded alongside every archived bar, because two contracts on the same
    underlying trade at different absolute prices and an indicator computed
    across the seam is measuring the roll rather than the market.
    """
    if symbol in _SPOT:
        return _SPOT[symbol][1]
    return min(_live_futures(_kite(), symbol),
               key=lambda i: i["expiry"])["tradingsymbol"]


def load_bars(symbol: str, start: str, end: str) -> list[dict]:
    """Bars for [start, end], ARCHIVE FIRST, Kite as the fallback.

    A futures contract carries no history from before it listed, and an expired
    one is delisted along with its token — so what Kite will serve SHRINKS on
    every roll. On 2026-08-27 that turned a three-month gas train window into
    five weeks overnight, silently, and the sweep reported "TRAIN n=3, t=+2.00"
    rather than an error.

    Reading the archive first makes the series grow instead: anything ever seen
    stays seen. Anything the archive is missing is fetched from Kite and WRITTEN
    THROUGH, so simply using the labs deepens the corpus.
    """
    from candle_archive import load as archive_load, remember

    cached = archive_load(symbol, start, end)
    if cached:
        fresh = _fetch_from_kite(symbol, start, end)
        if len(fresh) > len(cached):
            remember(symbol, fresh)
            return archive_load(symbol, start, end)
        return cached

    bars = _fetch_from_kite(symbol, start, end)
    if bars:
        remember(symbol, bars)
    return bars


def _fetch_from_kite(symbol: str, start: str, end: str) -> list[dict]:
    from dotenv import load_dotenv
    load_dotenv(str(ROOT / ".env"))
    from integrations.brokers.secrets import SecretManager
    from kiteconnect import KiteConnect

    secrets = SecretManager()
    kite = KiteConnect(api_key=secrets.get_secret("api_key", broker="zerodha"))
    kite.set_access_token(secrets.get_secret("access_token", broker="zerodha"))

    if symbol in _SPOT:
        exchange, tradingsymbol = _SPOT[symbol]
        token = next(i["instrument_token"] for i in kite.instruments(exchange)
                     if i["tradingsymbol"] == tradingsymbol)
    elif symbol in _MCX_FUTURES:
        # Front-month future: the contract with the nearest expiry still ahead
        # of us. Anything already expired has a dead, unrepresentative tape —
        # and its token is gone from the dump entirely, which is why the archive
        # in candle_archive.py exists.
        futures = _live_futures(kite, symbol)
        token = min(futures, key=lambda i: i["expiry"])["instrument_token"]
    else:
        raise ValueError(f"unknown symbol {symbol}")
    return kite.historical_data(token, start, end, "15minute")


def evaluate(bars: list[dict], horizon: int) -> dict[str, dict]:
    results = {name: {"n": 0, "hits": 0, "edges": []} for name in CANDIDATES}
    for i in range(42, len(bars) - horizon):
        window = bars[: i + 1]
        day = window[-1]["date"].date()
        session = [b for b in window if b["date"].date() == day]
        if len(session) < 6:
            continue
        # Never measure across a session boundary: an overnight gap is not
        # something an intraday signal predicted.
        if bars[i + horizon]["date"].date() != day:
            continue
        ctx = Ctx(window, session)
        # A bar that did not trade is not an entry point, and an ATR
        # built from a run of them is fiction. See signal_lab.measurable.
        if not measurable(ctx, window[-1]):
            continue
        forward = bars[i + horizon]["close"] - ctx.price
        for name, fn in CANDIDATES.items():
            call = fn(ctx)
            if call == 0:
                continue
            r = results[name]
            r["n"] += 1
            r["hits"] += 1 if (forward * call) > 0 else 0
            r["edges"].append((forward * call) / ctx.atr)
    return results


def report(symbol: str, results: dict[str, dict], horizon: int) -> None:
    print(f"\n  {symbol}  |  forward horizon {horizon} bars "
          f"({horizon * 15} minutes)")
    print(f"    {'signal':24s} {'n':>5s} {'accuracy':>9s} {'edge_atr':>9s} {'t':>6s}  verdict")
    rows = []
    for name, r in results.items():
        n = r["n"]
        if n < 30:
            print(f"    {name:24s} {n:>5d} {'--':>9s} {'--':>9s} {'--':>6s}  too few to judge")
            continue
        acc = r["hits"] / n * 100.0
        mean = sum(r["edges"]) / n
        var = sum((e - mean) ** 2 for e in r["edges"]) / (n - 1)
        t = mean / (math.sqrt(var / n) or 1e-9)
        rows.append((t, name, n, acc, mean))
    for t, name, n, acc, mean in sorted(rows, reverse=True):
        verdict = "EDGE" if t >= 2.0 and mean > 0 else ("negative" if mean < 0 else "noise")
        print(f"    {name:24s} {n:>5d} {acc:>8.1f}% {mean:>+9.3f} {t:>+6.2f}  {verdict}")


def main() -> int:
    symbols = [s.upper() for s in sys.argv[1:]] or ["NIFTY", "BANKNIFTY"]
    start, end = "2026-05-01 09:15:00", "2026-08-05 15:30:00"
    print("=" * 78)
    print("  SIGNAL LAB — does this signal actually predict, or does it just look good?")
    print(f"  {start[:10]} to {end[:10]}   edge_atr = mean forward move in ATR units")
    print("  Ship only: n large, edge_atr positive, t >= 2. Everything else is a story.")
    print("=" * 78)
    for symbol in symbols:
        try:
            bars = load_bars(symbol, start, end)
        except Exception as exc:
            print(f"  {symbol}: could not load bars ({exc})")
            continue
        for horizon in HORIZONS:
            report(symbol, evaluate(bars, horizon), horizon)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
