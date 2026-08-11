"""Measure the modules that actually CHOOSE direction.

WHY THIS EXISTS, AND WHY signal_lab.py WAS NOT ENOUGH
signal_lab measured candidate directional signals and the winners were wired
into `_compute_underlying_bias`. But the bias engine is a VETO: it can block a
trade, it never picks CE vs PE. The direction comes from the winning strategy's
EntryModule (`original_entry = _signal.direction`, autonomous_bot.py:4714).

So the measured edge was installed as a filter on an unmeasured decision-maker.
That gap is the most likely reason live direction accuracy sat at 33% across 21
trades while the lab's chosen signals measured 53-59%.

This harness runs the REAL EntryModule objects — the same classes production
imports — against historical bars, and scores the direction they propose by the
same standard: n, mean forward move in ATR units, and a t-statistic.

USAGE
    python tools/research/entry_module_lab.py                 # index modules
    python tools/research/entry_module_lab.py CRUDEOIL GOLDM  # MCX modules
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from signal_lab import HORIZONS, Ctx, load_bars, _SPOT, _MCX_FUTURES  # noqa: E402

from bots.strategy.components.models import MarketContext  # noqa: E402
from bots.strategy.components.entries import ENTRY_MODULES  # noqa: E402
from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES  # noqa: E402


def build_context(symbol: str, bars: list[dict], ctx: Ctx, session: list[dict]) -> MarketContext:
    """The same shape production builds, from the same kind of candles.

    minutes_into_session is computed from the symbol's OWN first bar of the day,
    exactly as _build_market_context does, so window-gated modules see the real
    clock rather than an assumed NSE open.
    """
    first = session[0]["date"]
    now = session[-1]["date"]
    return MarketContext(
        symbol=symbol,
        price=ctx.price,
        ema9=ctx.ema9,
        ema21=ctx.ema21,
        vwap=ctx.vwap,
        closes=tuple(b["close"] for b in bars),
        highs=tuple(b["high"] for b in bars),
        lows=tuple(b["low"] for b in bars),
        atr=ctx.atr,
        regime="UNKNOWN",
        vix_percentile=None,
        minutes_into_session=int((now - first).total_seconds() // 60),
    )


def evaluate(symbol: str, bars: list[dict], modules: dict, horizon: int) -> dict:
    results = {name: {"n": 0, "hits": 0, "edges": [], "longs": 0, "shorts": 0}
               for name in modules}
    for i in range(42, len(bars) - horizon):
        window = bars[: i + 1]
        day = window[-1]["date"].date()
        session = [b for b in window if b["date"].date() == day]
        if len(session) < 6:
            continue
        if bars[i + horizon]["date"].date() != day:
            continue
        ctx = Ctx(window, session)
        if not ctx.atr:
            continue
        mkt = build_context(symbol, window, ctx, session)
        forward = bars[i + horizon]["close"] - ctx.price
        for name, module in modules.items():
            try:
                sig = module.evaluate(mkt)
            except Exception:
                continue
            if not getattr(sig, "should_enter", False):
                continue
            call = 1 if sig.direction == "long" else -1
            r = results[name]
            r["n"] += 1
            r["longs" if call == 1 else "shorts"] += 1
            r["hits"] += 1 if (forward * call) > 0 else 0
            r["edges"].append((forward * call) / ctx.atr)
    return results


def report(symbol: str, results: dict, horizon: int) -> None:
    print(f"\n  {symbol}  |  forward horizon {horizon} bars ({horizon * 15} min)")
    print(f"    {'entry module':22s} {'n':>5s} {'L/S':>9s} {'accuracy':>9s} {'edge_atr':>9s} {'t':>6s}  verdict")
    rows = []
    for name, r in results.items():
        n = r["n"]
        if n < 30:
            print(f"    {name:22s} {n:>5d} {'':>9s} {'--':>9s} {'--':>9s} {'--':>6s}  too few to judge")
            continue
        acc = r["hits"] / n * 100.0
        mean = sum(r["edges"]) / n
        var = sum((e - mean) ** 2 for e in r["edges"]) / (n - 1)
        t = mean / (math.sqrt(var / n) or 1e-9)
        rows.append((t, name, n, f"{r['longs']}/{r['shorts']}", acc, mean))
    for t, name, n, ls, acc, mean in sorted(rows, reverse=True):
        verdict = "EDGE" if t >= 2.0 and mean > 0 else ("negative" if mean < 0 else "noise")
        print(f"    {name:22s} {n:>5d} {ls:>9s} {acc:>8.1f}% {mean:>+9.3f} {t:>+6.2f}  {verdict}")


def main() -> int:
    symbols = [s.upper() for s in sys.argv[1:]] or ["NIFTY", "BANKNIFTY"]
    start, end = "2026-05-01 09:15:00", "2026-08-11 15:30:00"
    print("=" * 82)
    print("  ENTRY MODULE LAB — the modules that actually pick CALL vs PUT")
    print("  These CHOOSE direction; the bias engine only vetoes. They have never")
    print("  been measured. Ship only: n large, edge_atr positive, t >= 2.")
    print("=" * 82)
    for symbol in symbols:
        modules = MCX_ENTRY_MODULES if symbol in _MCX_FUTURES else ENTRY_MODULES
        named = {getattr(m, "module_id", k): m for k, m in modules.items()}
        try:
            bars = load_bars(symbol, start, end)
        except Exception as exc:
            print(f"  {symbol}: could not load bars ({exc})")
            continue
        for horizon in HORIZONS:
            report(symbol, evaluate(symbol, bars, named, horizon), horizon)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
