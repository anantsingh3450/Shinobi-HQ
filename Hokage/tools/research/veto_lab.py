"""Measure the bias engine in the job it actually holds: a VETO.

WHY THIS EXISTS
signal_lab scored the bias rules as STANDALONE SIGNALS — "if this rule says up,
does price go up?" — and they scored well (CRUDEOIL t=+5.13, SILVERM t=+4.49).
entry_module_lab then scored the entry modules as standalone CHOOSERS, and some
of those scored well too (SessionShift on GOLDM t=+3.17).

Neither answers the question production actually asks. In production the bias
engine never picks a direction. It sits downstream of a module that already
picked one, and its only power is to say no. Two components that each measure
positive alone can still be a bad pair: if the veto's "yes" condition is nearly
disjoint from the module's firing condition, it is not filtering, it is an off
switch.

That is not hypothetical. On 2026-08-12 SessionShift — the highest-t module in
the system — won 16 auctions on GOLDM/SILVERM and the veto blocked 15 of them,
every one with the same verdict, "tape is MIXED". The pair had never been
measured together. Look at why on SILVERM: SessionShift fires when price is
ABOVE VWAP, and the SILVERM veto (trend_pullback) only says yes when price is
WITHIN 0.5 ATR OF VWAP. They are close to mutually exclusive by construction.

WHAT IT MEASURES
For every entry module on a symbol, at each forward horizon:

  ALONE    the module's own signals              n / accuracy / edge_atr / t
  GATED    only the signals the veto let through n / accuracy / edge_atr / t
  BLOCKED  the signals the veto removed          n / accuracy / edge_atr / t

BLOCKED is the verdict. A veto earns its place when the trades it removes have
NEGATIVE edge. If the removed set has positive edge, the veto is not protecting
the account, it is spending it — and the fact that the same rule measures well
as a standalone signal is beside the point.

FIDELITY
The verdict comes from `bots.autonomous.bias_rules.classify_tape` — literally
the function production calls, not a re-implementation. The inputs are derived
by signal_lab's Ctx, which computes ema9/ema21/VWAP/ATR by the same formulas
`_compute_underlying_bias` uses. If either changes, this measurement changes.

USAGE
    python tools/research/veto_lab.py                        # MCX arena
    python tools/research/veto_lab.py GOLDM SILVERM
    python tools/research/veto_lab.py NIFTY BANKNIFTY SENSEX
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from signal_lab import HORIZONS, Ctx, load_bars, _MCX_FUTURES, measurable# noqa: E402, measurable
from entry_module_lab import build_context  # noqa: E402

from bots.autonomous import bias_rules  # noqa: E402
from bots.strategy.components.entries import ENTRY_MODULES  # noqa: E402
from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES  # noqa: E402

#: Minimum sample before a t-statistic is worth printing.
MIN_N = 30


def _stats(edges: list[float], hits: int) -> tuple[int, float, float, float]:
    n = len(edges)
    if n == 0:
        return 0, 0.0, 0.0, 0.0
    acc = hits / n * 100.0
    mean = sum(edges) / n
    if n < 2:
        return n, acc, mean, 0.0
    var = sum((e - mean) ** 2 for e in edges) / (n - 1)
    t = mean / (math.sqrt(var / n) or 1e-9)
    return n, acc, mean, t


def evaluate(symbol: str, bars: list[dict], modules: dict, horizon: int) -> dict:
    """Split every module's signals into the set the veto passes and the set it
    blocks, scoring both. Strictly no lookahead: the verdict is computed from
    the same bar window the module saw."""
    out = {
        name: {
            "alone": ([], 0),
            "gated": ([], 0),
            "blocked": ([], 0),
            "reasons": {},
        }
        for name in modules
    }

    def _push(bucket: tuple[list, int], edge: float, win: bool) -> tuple[list, int]:
        bucket[0].append(edge)
        return bucket[0], bucket[1] + (1 if win else 0)

    for i in range(42, len(bars) - horizon):
        window = bars[: i + 1]
        day = window[-1]["date"].date()
        session = [b for b in window if b["date"].date() == day]
        if len(session) < 6:
            continue
        if bars[i + horizon]["date"].date() != day:
            continue
        ctx = Ctx(window, session)
        # A bar that did not trade is not an entry point, and an ATR
        # built from a run of them is fiction. See signal_lab.measurable.
        if not measurable(ctx, window[-1]):
            continue
        mkt = build_context(symbol, window, ctx, session)
        forward = bars[i + horizon]["close"] - ctx.price

        # Production's own verdict, on production's own code path.
        verdict, reason = bias_rules.classify_tape(
            symbol=symbol,
            price=ctx.price,
            vwap=ctx.vwap,
            atr=ctx.atr,
            ema9=ctx.ema9,
            ema21=ctx.ema21,
            recent_closes=[b["close"] for b in window[-4:]],
            session_bar_count=len(session),
        )

        for name, module in modules.items():
            try:
                sig = module.evaluate(mkt)
            except Exception:
                continue
            if not getattr(sig, "should_enter", False):
                continue
            call = 1 if sig.direction == "long" else -1
            edge = (forward * call) / ctx.atr
            win = (forward * call) > 0
            rec = out[name]
            rec["alone"] = _push(rec["alone"], edge, win)

            # The exact gate from _check_conduct_gates: MIXED blocks, and a
            # named direction blocks anything pointing the other way.
            passes = (verdict == "BULLISH" and call == 1) or (
                verdict == "BEARISH" and call == -1
            )
            if passes:
                rec["gated"] = _push(rec["gated"], edge, win)
            else:
                rec["blocked"] = _push(rec["blocked"], edge, win)
                key = verdict if verdict != "MIXED" else reason.split("—")[-1].strip()
                rec["reasons"][key] = rec["reasons"].get(key, 0) + 1
    return out


def report(symbol: str, results: dict, horizon: int, counter_trend: set[str]) -> None:
    rule = bias_rules.rule_for(symbol)
    print(f"\n  {symbol}  |  horizon {horizon} bars ({horizon * 15} min)  |  veto rule: {rule}")
    for name, rec in sorted(results.items()):
        n_alone = len(rec["alone"][0])
        if n_alone < MIN_N:
            print(f"    {name:20s} n={n_alone} — too few to judge")
            continue
        note = "  (COUNTER_TREND: production skips the veto here)" if name in counter_trend else ""
        print(f"    {name}{note}")
        print(f"      {'':9s} {'n':>5s} {'accuracy':>9s} {'edge_atr':>9s} {'t':>7s}")
        for label in ("alone", "gated", "blocked"):
            n, acc, mean, t = _stats(rec[label][0], rec[label][1])
            if n == 0:
                print(f"      {label:9s} {0:>5d}        --        --      --")
                continue
            print(f"      {label:9s} {n:>5d} {acc:>8.1f}% {mean:>+9.3f} {t:>+7.2f}")

        n_b, _, mean_b, t_b = _stats(rec["blocked"][0], rec["blocked"][1])
        n_g, _, mean_g, _ = _stats(rec["gated"][0], rec["gated"][1])
        block_rate = n_b / n_alone * 100.0
        if n_b < MIN_N:
            verdict = "veto barely bites — too few blocks to judge"
        elif mean_b > 0 and t_b >= 1.0:
            verdict = ("VETO IS COSTING MONEY — the trades it removes have "
                       f"POSITIVE edge ({mean_b:+.3f} ATR, t={t_b:+.2f})")
        elif mean_b < 0:
            verdict = f"veto earns its place — blocked trades average {mean_b:+.3f} ATR"
        else:
            verdict = "veto is neutral — blocked trades are noise, it only reduces n"
        print(f"      -> blocks {block_rate:.0f}% of signals. {verdict}")
        if n_g and n_alone:
            print(f"         edge alone {sum(rec['alone'][0]) / n_alone:+.3f} "
                  f"vs gated {mean_g:+.3f} ATR")
        if rec["reasons"]:
            top = sorted(rec["reasons"].items(), key=lambda kv: -kv[1])[:2]
            for why, count in top:
                print(f"         blocked {count}x: {why}")


def main() -> int:
    symbols = [s.upper() for s in sys.argv[1:]] or list(_MCX_FUTURES)
    start, end = "2026-05-01 09:15:00", "2026-08-12 23:30:00"
    print("=" * 84)
    print("  VETO LAB — is the bias engine helping the module it gates, or replacing it?")
    print("  ALONE = module's own signals. GATED = what the veto passes.")
    print("  BLOCKED = what it removes. BLOCKED with POSITIVE edge means the veto")
    print("  is spending the account, however well the rule scores on its own.")
    print("=" * 84)
    for symbol in symbols:
        modules = MCX_ENTRY_MODULES if symbol in _MCX_FUTURES else ENTRY_MODULES
        named = {getattr(m, "module_id", k): m for k, m in modules.items()}
        counter_trend = {n for n, m in named.items() if getattr(m, "COUNTER_TREND", False)}
        try:
            bars = load_bars(symbol, start, end)
        except Exception as exc:
            print(f"  {symbol}: could not load bars ({exc})")
            continue
        for horizon in HORIZONS:
            report(symbol, evaluate(symbol, bars, named, horizon), horizon, counter_trend)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
