"""Does every LIVE strategy still measure out of sample?

WHY THIS EXISTS
On 2026-08-18 the realized P&L of every strategy was laid next to its measured
edge, and they agree almost perfectly:

    ARCHIVED for measuring negative      realized
      TrendPullback   no edge anywhere   -11,924
      TrendRider      NATURALGAS t=-1.64 -17,502
      Malfoy          BANKNIFTY t=-0.51   -6,208
                                        --------
                                         -35,634

    CONFIRMED edge
      RangeFade       CRUDEOIL t=+3.39   +11,135

Measurement predicted profit and loss. That is the strongest evidence Hokage
has that the discipline works, and it turns one question into the most valuable
question in the system: IS EVERY MODULE CURRENTLY HOLDING CAPITAL ACTUALLY
MEASURED, AND DOES IT STILL MEASURE ON DATA IT HAS NOT SEEN?

WHY A HOLD-OUT AND NOT ANOTHER POOLED RUN
Hours earlier, session_lab found what looked like strong edge for three modules
in a window they were not trading — SessionShift +3.52, TrendRider +2.43 on
NATURALGAS. Splitting train from hold-out destroyed all of it, with the signs
flipping. Pooled t-statistics on a searched dataset are how a system convinces
itself it has an edge it does not have. Every number here is therefore reported
twice, on disjoint periods, and a pair is only CONFIRMED if it survives both.

VERDICTS
  CONFIRMED  clears the bar on BOTH halves. Trust it with capital.
  FRAGILE    clears on train, fails on hold-out. This is what noise looks
             like after a search. Do not size up; consider standing it down.
  WEAK       fails on train too. It was never there.
  NEGATIVE   mean edge below zero on the hold-out. It loses by construction.

Reports only pairs that are LIVE and IN SCOPE, because a verdict on a pair that
cannot trade is a distraction from one that can.

USAGE
    python tools/research/holdout_lab.py
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from signal_lab import Ctx, load_bars, _MCX_FUTURES  # noqa: E402
from entry_module_lab import build_context  # noqa: E402

from bots.strategy.components.entries import ENTRY_MODULES  # noqa: E402
from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES  # noqa: E402

PORTFOLIO_DIR = ROOT / "hokage_brain" / "portfolio"

#: 60 minutes, the horizon the other labs report as primary.
HORIZON = 4

#: The bar a pair must clear on BOTH halves to be trusted with capital.
SHIP_BAR = 2.0

#: Disjoint by construction. Train is the older period so the hold-out is the
#: more recent tape — the half that actually resembles what Hokage will trade
#: next. A hold-out drawn from the past would flatter a stale edge.
TRAIN = ("2026-05-01 09:15:00", "2026-06-30 23:30:00")
HOLDOUT = ("2026-07-01 09:15:00", "2026-08-13 23:30:00")

#: Below this a half is not judged. A verdict on 20 signals is a coin flip
#: wearing a decimal point.
MIN_N = 40


def live_pairs() -> list[tuple[str, str, str]]:
    """(module_id, asset, strategy_name) for every live, in-scope pair."""
    module_id_of = {}
    for key, module in {**ENTRY_MODULES, **MCX_ENTRY_MODULES}.items():
        module_id_of[key] = getattr(module, "module_id", key)

    pairs: list[tuple[str, str, str]] = []
    for name in ("strategy_portfolio.json", "mcx_strategy_portfolio.json"):
        path = PORTFOLIO_DIR / name
        if not path.exists():
            continue
        book = json.loads(path.read_text(encoding="utf-8-sig"))
        for sid, strat in (book.get("strategies") or {}).items():
            if strat.get("status") in (None, "ARCHIVED"):
                continue
            mid = module_id_of.get(sid)
            if not mid:
                continue
            for asset in strat.get("supported_assets") or []:
                pairs.append((mid, asset.upper(), strat.get("name", sid)))
    return pairs


def _stats(edges: list[float], hits: int) -> tuple[int, float, float, float]:
    n = len(edges)
    if n < 2:
        return n, 0.0, 0.0, 0.0
    mean = sum(edges) / n
    var = sum((e - mean) ** 2 for e in edges) / (n - 1)
    t = mean / (math.sqrt(var / n) or 1e-9)
    return n, hits / n * 100.0, mean, t


def measure(symbol: str, bars: list[dict], module) -> tuple[list[float], int]:
    """Forward edge in ATR units for every signal this module fires."""
    edges: list[float] = []
    hits = 0
    for i in range(42, len(bars) - HORIZON):
        window = bars[: i + 1]
        day = window[-1]["date"].date()
        session = [b for b in window if b["date"].date() == day]
        if len(session) < 6:
            continue
        if bars[i + HORIZON]["date"].date() != day:
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
        call = 1 if sig.direction == "long" else -1
        forward = bars[i + HORIZON]["close"] - ctx.price
        edges.append((forward * call) / ctx.atr)
        hits += 1 if (forward * call) > 0 else 0
    return edges, hits


def verdict(train: tuple, hold: tuple) -> str:
    """train/hold are (n, accuracy, mean, t)."""
    if train[0] < MIN_N or hold[0] < MIN_N:
        return "TOO FEW"
    if hold[2] < 0:
        return "NEGATIVE"
    if train[3] >= SHIP_BAR and hold[3] >= SHIP_BAR:
        return "CONFIRMED"
    if train[3] >= SHIP_BAR:
        return "FRAGILE"
    return "WEAK"


def main() -> int:
    print("=" * 88)
    print("  HOLD-OUT LAB — does every live pair still measure on unseen data?")
    print("  Train " + TRAIN[0][:10] + ".." + TRAIN[1][:10]
          + "   Hold-out " + HOLDOUT[0][:10] + ".." + HOLDOUT[1][:10])
    print("  CONFIRMED clears t>=" + format(SHIP_BAR, ".1f") + " on BOTH halves."
          " Anything else is not to be trusted with capital.")
    print("=" * 88)

    modules = {getattr(m, "module_id", k): m
               for k, m in {**ENTRY_MODULES, **MCX_ENTRY_MODULES}.items()}
    bars_cache: dict[tuple[str, str], list[dict]] = {}
    rows = []

    for mid, asset, sname in sorted(live_pairs(), key=lambda p: (p[2], p[1])):
        module = modules.get(mid)
        if module is None:
            continue
        halves = []
        failed = False
        for label, (a, b) in (("train", TRAIN), ("hold", HOLDOUT)):
            key = (asset, label)
            if key not in bars_cache:
                try:
                    bars_cache[key] = load_bars(asset, a, b)
                except Exception as exc:
                    print("  " + asset + ": could not load bars (" + str(exc) + ")")
                    failed = True
                    break
            halves.append(_stats(*measure(asset, bars_cache[key], module)))
        if failed or len(halves) != 2:
            continue
        rows.append((sname, asset, halves[0], halves[1], verdict(*halves)))

    print("")
    print("  " + "strategy".ljust(15) + "asset".ljust(12)
          + "TRAIN  n     t".ljust(22) + "HOLD-OUT  n     t".ljust(24) + "verdict")
    for sname, asset, tr, ho, v in rows:
        print("  " + sname.ljust(15) + asset.ljust(12)
              + (str(tr[0]).rjust(5) + format(tr[2], "+.3f").rjust(9)
                 + format(tr[3], "+.2f").rjust(8)).ljust(22)
              + (str(ho[0]).rjust(7) + format(ho[2], "+.3f").rjust(9)
                 + format(ho[3], "+.2f").rjust(8)).ljust(24)
              + "  " + v)

    confirmed = [r for r in rows if r[4] == "CONFIRMED"]
    print("")
    print("  " + str(len(confirmed)) + " of " + str(len(rows))
          + " live pairs survive out of sample.")
    if confirmed:
        print("  Trust capital to: "
              + ", ".join(r[0] + "/" + r[1] for r in confirmed))
    doubtful = [r for r in rows if r[4] in ("FRAGILE", "WEAK", "NEGATIVE")]
    if doubtful:
        print("  Holding capital without confirmation: "
              + ", ".join(r[0] + "/" + r[1] + " (" + r[4] + ")" for r in doubtful))
    print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
