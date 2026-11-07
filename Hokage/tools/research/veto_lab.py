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

THREE THINGS THIS LAB DID NOT DO UNTIL 2026-11-07, each of which has produced a
wrong answer somewhere else in this repo before:

  * IT MEASURED A FIXED THREE-MONTH WINDOW. `start`/`end` were frozen at the
    2026-08-12 study that populated VETO_DISABLED_SYMBOLS, so re-running the
    lab re-read the same quarter however much tape had accumulated since. The
    archive now keeps every candle forever, and on gas alone there were three
    unmeasured months. The window now defaults to THE WHOLE ARCHIVE.
  * IT HAD NO HOLD-OUT. One t over one window is the geometry that put
    thirteen of fourteen cells on the retirement queue, best included. Every
    bucket is now scored on an early half and a late half, split by session
    day, and a verdict that does not survive in BOTH halves is reported as
    unproven rather than as a finding.
  * IT POOLED LONG AND SHORT. Long and short are two different bets - two of
    three live pairs were found paying for a NEGATIVE side - so a veto that
    helps one and hurts the other reads as neutral when the sides are averaged
    together. BLOCKED is now also broken out per side.

The bar is the ship bar: |t| >= 2.0 in the same direction in both halves.
Nothing below that is a result, and this lab proposes no constant.

FIDELITY
The verdict comes from `bots.autonomous.bias_rules.classify_tape` — literally
the function production calls, not a re-implementation. The inputs are derived
by signal_lab's Ctx, which computes ema9/ema21/VWAP/ATR by the same formulas
`_compute_underlying_bias` uses. If either changes, this measurement changes.

The bars come from the archive and ONLY the archive: a measurement over all
history must not depend on a live token, and `load_bars` reaches for Kite.

USAGE
    python tools/research/veto_lab.py                        # MCX arena
    python tools/research/veto_lab.py GOLDM SILVERM
    python tools/research/veto_lab.py NIFTY BANKNIFTY SENSEX
    python tools/research/veto_lab.py NATURALGAS --since 2026-05-01
"""
from __future__ import annotations

import datetime as dt
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from signal_lab import HORIZONS, Ctx, _MCX_FUTURES, measurable  # noqa: E402
from entry_module_lab import build_context  # noqa: E402

from bots.autonomous import bias_rules  # noqa: E402
from bots.strategy.components.entries import ENTRY_MODULES  # noqa: E402
from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES  # noqa: E402

#: Minimum sample before a t-statistic is worth printing.
MIN_N = 30

#: The ship bar, and deliberately the same one every other decision here uses.
#: A veto is a permanent change to what the account is allowed to do, so the
#: evidence to keep or drop one is held to what evidence to SHIP one would be.
SHIP_T = 2.0

#: The smallest blocked edge worth calling a cost, in ATR.
#:
#: t MEASURES SIGNIFICANCE, NOT SIZE, and at these sample sizes the difference
#: decides things. A blocked set averaging +0.03 ATR with n=80 clears t=+6 —
#: consistent, real, and far too small to pay for itself once the spread and a
#: holding period of theta come out of it. Without a floor, that number would
#: read as "the veto is costing money" and license removing a gate.
#:
#: 0.10 IS A STATED PRIOR, NOT A MEASUREMENT, in the same sense as
#: EIAReaction.MAX_REACTION_ATR: nobody here has measured what an option
#: buyer's round-trip costs in ATR of the underlying, and until somebody does,
#: a floor chosen openly beats a floor of zero chosen by omission. It only ever
#: makes this lab HARDER to satisfy, and it gates nothing in production.
MIN_EDGE_ATR = 0.10


def archive_span(symbol: str) -> tuple[str, str] | None:
    """The first and last archived bar for this symbol, or None if untouched."""
    import candle_archive

    with candle_archive.connect() as conn:
        row = conn.execute(
            "SELECT MIN(ts), MAX(ts) FROM candles WHERE symbol = ?",
            (symbol,)).fetchone()
    if not row or not row[0]:
        return None
    return row[0], row[1]


def load_history(symbol: str, since: str | None, until: str | None) -> list[dict]:
    """Every archived bar for this symbol in the requested range.

    ARCHIVE ONLY. `signal_lab.load_bars` falls back to Kite and writes through,
    which is right for a lab deepening the corpus and wrong here: a run over
    all history must give the same answer on a Saturday with a dead token as it
    does mid-session, or the measurement is not reproducible.
    """
    import candle_archive

    span = archive_span(symbol)
    if span is None:
        return []
    start = since or span[0]
    end = until or span[1]
    return candle_archive.load(symbol, start, end)


def _stats(recs: list[dict]) -> tuple[int, float, float, float]:
    """n, accuracy %, mean edge_atr, t."""
    n = len(recs)
    if n == 0:
        return 0, 0.0, 0.0, 0.0
    edges = [r["edge"] for r in recs]
    acc = sum(1 for r in recs if r["win"]) / n * 100.0
    mean = sum(edges) / n
    if n < 2:
        return n, acc, mean, 0.0
    var = sum((e - mean) ** 2 for e in edges) / (n - 1)
    t = mean / (math.sqrt(var / n) or 1e-9)
    return n, acc, mean, t


def split_days(recs: list[dict]) -> dt.date | None:
    """The first day of the LATE half, splitting on session days not rows.

    Splitting on row count would put a busy day on both sides of the line and
    let the same session inform train and hold-out at once.
    """
    days = sorted({r["day"] for r in recs})
    if len(days) < 4:
        return None
    return days[len(days) // 2]


def observations(symbol: str, bars: list[dict], modules: dict,
                 horizon: int) -> dict[str, list[dict]]:
    """One record per module signal: which side, which day, did the veto pass
    it, and what did the underlying do next.

    Strictly no lookahead: the verdict is computed from the same bar window the
    module saw.
    """
    out: dict[str, list[dict]] = {name: [] for name in modules}

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

            # The exact gate from _check_conduct_gates: MIXED blocks, and a
            # named direction blocks anything pointing the other way.
            passed = (verdict == "BULLISH" and call == 1) or (
                verdict == "BEARISH" and call == -1
            )
            out[name].append({
                "day": day,
                "side": call,
                "passed": passed,
                "edge": (forward * call) / ctx.atr,
                "win": (forward * call) > 0,
                "verdict": verdict,
                "reason": (verdict if verdict != "MIXED"
                           else reason.split("—")[-1].strip()),
            })
    return out


def _row(label: str, recs: list[dict]) -> str:
    n, acc, mean, t = _stats(recs)
    if n == 0:
        return f"      {label:16s} {0:>5d}        --        --      --"
    return (f"      {label:16s} {n:>5d} {acc:>8.1f}% {mean:>+9.3f} {t:>+7.2f}")


def blocked_verdict(recs: list[dict], cut: dt.date | None) -> str:
    """What the BLOCKED set supports, held to the ship bar in BOTH halves.

    The asymmetry is deliberate. "The veto is costing money" licenses removing
    a gate, which is a loosening, so it has to clear the ship bar twice. "The
    veto earns its place" only licenses leaving production exactly as it is,
    so a consistently negative blocked edge is enough to say so.
    """
    n, _, mean, t = _stats(recs)
    if n < MIN_N:
        return f"veto barely bites — only {n} blocks, too few to judge"
    if cut is None:
        return "not enough distinct days to hold out a half — unproven"

    early = [r for r in recs if r["day"] < cut]
    late = [r for r in recs if r["day"] >= cut]
    n_e, _, mean_e, t_e = _stats(early)
    n_l, _, mean_l, t_l = _stats(late)
    halves = f"early n={n_e} {mean_e:+.3f} t={t_e:+.2f} | late n={n_l} {mean_l:+.3f} t={t_l:+.2f}"

    if n_e < MIN_N or n_l < MIN_N:
        return f"one half too thin to confirm anything — {halves}"

    # Significant in both halves AND big enough to be worth something. See
    # MIN_EDGE_ATR: the size test is what stops a consistent +0.03 ATR from
    # licensing the removal of a gate.
    costing = (mean_e >= MIN_EDGE_ATR and t_e >= SHIP_T) and (
        mean_l >= MIN_EDGE_ATR and t_l >= SHIP_T)
    if costing:
        return (f"VETO IS COSTING MONEY in both halves — it removes trades with "
                f"POSITIVE edge (pooled {mean:+.3f} ATR, t={t:+.2f}) — {halves}")
    if mean_e < 0 and mean_l < 0:
        return (f"veto earns its place — blocked trades average {mean:+.3f} ATR "
                f"and are negative in both halves — {halves}")
    if mean >= MIN_EDGE_ATR and t >= SHIP_T:
        return (f"pooled says the veto costs money ({mean:+.3f} ATR, t={t:+.2f}) "
                f"but it DOES NOT HOLD OUT — unproven — {halves}")
    if mean > 0 and t >= SHIP_T:
        return (f"blocked edge is real but tiny ({mean:+.3f} ATR, t={t:+.2f}, "
                f"floor {MIN_EDGE_ATR}) — too small to pay for itself — {halves}")
    return f"blocked set is noise — the veto only reduces n — {halves}"


def report(symbol: str, results: dict, horizon: int, counter_trend: set[str],
           span: tuple[str, str]) -> None:
    rule = bias_rules.rule_for(symbol)
    disabled = symbol.upper() in bias_rules.VETO_DISABLED_SYMBOLS
    off = "  [VETO STOOD DOWN IN PRODUCTION]" if disabled else ""
    print(f"\n  {symbol}  |  horizon {horizon} bars ({horizon * 15} min)  |  "
          f"veto rule: {rule}{off}")
    for name, recs in sorted(results.items()):
        if len(recs) < MIN_N:
            print(f"    {name:22s} n={len(recs)} — too few to judge")
            continue
        note = ("  (COUNTER_TREND: production skips the veto here)"
                if name in counter_trend else "")
        print(f"    {name}{note}")
        print(f"      {'':16s} {'n':>5s} {'accuracy':>9s} {'edge_atr':>9s} {'t':>7s}")

        gated = [r for r in recs if r["passed"]]
        blocked = [r for r in recs if not r["passed"]]
        print(_row("alone", recs))
        print(_row("gated", gated))
        print(_row("blocked", blocked))

        # PER SIDE, because long and short are two different bets and a veto
        # that helps one and hurts the other averages to "neutral".
        for side, label in ((1, "blocked long"), (-1, "blocked short")):
            part = [r for r in blocked if r["side"] == side]
            if part:
                print(_row(label, part))

        cut = split_days(recs)
        rate = len(blocked) / len(recs) * 100.0
        print(f"      -> blocks {rate:.0f}% of signals. {blocked_verdict(blocked, cut)}")
        n_g, _, mean_g, _ = _stats(gated)
        if n_g:
            print(f"         edge alone {sum(r['edge'] for r in recs) / len(recs):+.3f} "
                  f"vs gated {mean_g:+.3f} ATR")
        reasons: dict[str, int] = {}
        for r in blocked:
            reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
        for why, count in sorted(reasons.items(), key=lambda kv: -kv[1])[:2]:
            print(f"         blocked {count}x: {why}")


def main() -> int:
    args = [a for a in sys.argv[1:]]
    since = until = None
    for flag, setter in (("--since", "since"), ("--until", "until")):
        if flag in args:
            i = args.index(flag)
            value = args[i + 1]
            args = args[:i] + args[i + 2:]
            if setter == "since":
                since = value
            else:
                until = value
    symbols = [s.upper() for s in args] or list(_MCX_FUTURES)

    print("=" * 84)
    print("  VETO LAB — is the bias engine helping the module it gates, or replacing it?")
    print("  ALONE = module's own signals. GATED = what the veto passes.")
    print("  BLOCKED = what it removes. BLOCKED with POSITIVE edge means the veto")
    print("  is spending the account, however well the rule scores on its own.")
    print(f"  Held to |t| >= {SHIP_T} IN BOTH HALVES. One window is not a result.")
    print("=" * 84)
    for symbol in symbols:
        modules = MCX_ENTRY_MODULES if symbol in _MCX_FUTURES else ENTRY_MODULES
        named = {getattr(m, "module_id", k): m for k, m in modules.items()}
        counter_trend = {n for n, m in named.items()
                         if getattr(m, "COUNTER_TREND", False)}
        bars = load_history(symbol, since, until)
        if not bars:
            print(f"\n  {symbol}: nothing archived in that range — not measured.")
            continue
        span = (str(bars[0]["date"]), str(bars[-1]["date"]))
        days = len({b["date"].date() for b in bars})
        print(f"\n  {symbol}: {len(bars)} archived bars over {days} sessions, "
              f"{span[0][:10]} to {span[1][:10]}")
        for horizon in HORIZONS:
            report(symbol, observations(symbol, bars, named, horizon),
                   horizon, counter_trend, span)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
