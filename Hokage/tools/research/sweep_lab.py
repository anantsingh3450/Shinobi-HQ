"""Sweep a live module's own knobs and PROPOSE the ones that survive out of sample.

WHY THIS EXISTS
On 2026-08-26 the commander asked why Hokage is not improving on his own. The
honest answer, straight from his own brain:

    trade autopsies written .......... 117  (430 lifetime)
    improvement proposals ............   0
    improvements applied .............   0   EVER

Hokage can MEASURE — weekly_audit re-scores every module against every asset —
and since 2026-08-25 he can PRUNE, because evolution.py Tier 1 may archive a
module that has measured below the bar two weeks running. What he has never been
able to do is the middle step: take a module that works, try its knobs at other
settings, and say "this one is better, and here is the evidence."

Every parameter change in Hokage's history was swept by Claude, by hand, in a
chat session. That is the loop this closes.

WHAT IT DOES
For each LIVE (module, asset) pair, for each knob the module DECLARES tunable,
measure every candidate value on two disjoint periods and compare it against the
value production is running today.

A candidate is written as a PROPOSAL only if ALL of these hold:

    1. n >= MIN_N on BOTH halves      — a verdict on 20 signals is a coin flip
    2. t >= SHIP_BAR on BOTH halves   — the rule every shipped change has met
    3. it beats the incumbent on BOTH — not only on the half that was searched
    4. hold-out gain >= MIN_GAIN_ATR  — a rounding error is not an improvement

Rule 3 is the one that matters. Sweeping seven values and keeping the best of
seven is how a search manufactures an edge; requiring the winner to beat the
incumbent on the half it was NOT selected on is what makes the answer mean
something. The number of cells tried is recorded in every proposal, so the
commander can always see the size of the search that produced it.

FULL GEOMETRY, ALWAYS
Every number here is measured WITH the production thesis stop (1.25 ATR of the
underlying) applied bar by bar, on the bar's low/high rather than the close.
This is not optional. On 2026-08-26 a 240-minute crude horizon measured +2.06
without a stop and +0.82 with one, and the same trap cost a SILVERM decision on
08-15. A knob measured on raw signal edge is measured on a system that does not
exist.

WHAT IT WILL NOT DO
It never writes to a portfolio, never edits a module, and never touches a knob
tiered ASK — anything that widens a stop, raises a cap, or increases size. Those
are printed and left for the commander. Tier PROPOSE knobs, which only change
WHEN a module fires, become PENDING rows in improvement_proposals.

USAGE
    python tools/research/sweep_lab.py                 # every live pair
    python tools/research/sweep_lab.py NATURALGAS      # one asset
    python tools/research/sweep_lab.py --write         # persist proposals
"""
from __future__ import annotations

import copy
import json
import math
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from signal_lab import Ctx, load_bars  # noqa: E402
from entry_module_lab import build_context  # noqa: E402
from holdout_lab import HOLDOUT, TRAIN, live_pairs  # noqa: E402

from bots.strategy.components.entries import ENTRY_MODULES  # noqa: E402
from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES  # noqa: E402

DB = ROOT / "hokage_brain" / "hokage.db"

#: Bars held before the time exit. 4 x 15min = 1 hour, the horizon every other
#: lab reports as primary.
HORIZON = 4

#: The production thesis stop, in ATR of the underlying. NOT a sweep target —
#: it is the geometry every candidate is measured inside.
PROD_STOP_ATR = 1.25

#: The bar a candidate must clear on BOTH halves.
SHIP_BAR = 2.0

#: Below this a half is not judged.
MIN_N = 40

#: Hold-out edge a candidate must ADD over the incumbent, in ATR per trade.
#: Below this the two settings are the same setting wearing different decimals.
MIN_GAIN_ATR = 0.05

TIER_PROPOSE = "propose"
TIER_ASK = "ask"


# --------------------------------------------------------------- measurement
def _stats(edges: list[float]) -> tuple[int, float, float]:
    n = len(edges)
    if n < 2:
        return n, 0.0, 0.0
    mean = sum(edges) / n
    var = sum((e - mean) ** 2 for e in edges) / (n - 1)
    return n, mean, mean / (math.sqrt(var / n) or 1e-9)


def realised(bars: list[dict], i: int, call: int, atr: float) -> float:
    """Edge in ATR units with the production stop applied, same-day only.

    Lifted from stop_lab.simulate at k = PROD_STOP_ATR. Stops are detected on
    the bar's low (long) or high (short) because a stop fires intrabar in real
    life, and the exit is priced AT the stop level, which is generous — real
    fills slip — so this never understates a setting's cost.
    """
    entry = bars[i]["close"]
    stop_level = entry - PROD_STOP_ATR * atr if call == 1 else entry + PROD_STOP_ATR * atr
    exit_price = entry
    for j in range(i + 1, min(i + 1 + HORIZON, len(bars))):
        bar = bars[j]
        if bar["date"].date() != bars[i]["date"].date():
            break
        hit = bar["low"] <= stop_level if call == 1 else bar["high"] >= stop_level
        if hit:
            return (stop_level - entry) * call / atr
        exit_price = bar["close"]
    return (exit_price - entry) * call / atr


def effective(module, knob: str, spec: dict, asset: str):
    """What production actually uses for THIS asset today.

    A knob may carry a per-asset override dict — RangeFade reads
    `STRETCH_PCT_BY_ASSET.get(symbol, STRETCH_PCT)` — because edge does not
    travel between assets. Sweeping the class-level scalar while an override
    silently wins would measure a setting the asset never sees.
    """
    per_asset = spec.get("per_asset")
    if per_asset:
        table = getattr(module, per_asset, None) or {}
        if asset in table:
            return table[asset]
        if "default" in spec:
            #: A knob that lives ONLY as a per-asset table — direction, say —
            #: has no class-level scalar to fall back to. Its declared default
            #: is what an asset with no entry actually gets.
            return spec["default"]
    return getattr(module, knob)


def variants(module, knob: str, spec: dict, asset: str, values: tuple) -> list[tuple]:
    """(value, module-carrying-that-value) — deep copies, never the live object.

    Per-asset knobs are written into the override table for the asset under
    test, so the clone is scoped exactly the way a shipped change would be.
    """
    per_asset = spec.get("per_asset")
    out = []
    for v in values:
        clone = copy.deepcopy(module)
        if per_asset:
            table = dict(getattr(clone, per_asset, None) or {})
            if v is None:
                table.pop(asset, None)   # None means "no override" — e.g. both sides
            else:
                table[asset] = v
            setattr(clone, per_asset, table)
        else:
            setattr(clone, knob, v)
        out.append((v, clone))
    return out


def pick(grid: tuple, qualified: set, scored: dict, knob: str):
    """Which qualifying value to actually propose.

    NOT simply the best-scoring one. A sweep that keeps the maximum of seven
    cells is selecting on noise as hard as it is selecting on edge, and the
    winner is disproportionately likely to sit on a boundary that happened to
    fall right. When several ADJACENT values in the grid qualify, they form a
    plateau, and the interior of a plateau is the robust choice: it is the
    setting whose neighbours also work, so a small error in the measurement
    does not land outside the region that does.

    Shipped by hand first, on NATURALGAS 2026-08-26. The trend guard confirmed
    at 0.08, 0.10 and 0.12; 0.08 scored best and 0.10 was chosen, because 0.06
    was already below the sample floor — 0.08 sat one step from the cliff.

    Falls back to the best hold-out edge when no two qualifying values are
    adjacent, since then there is no plateau to sit inside.
    """
    runs, current = [], []
    for v in grid:
        if v in qualified:
            current.append(v)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    if not runs:
        return None
    longest = max(runs, key=len)
    if len(longest) >= 3:
        return longest[len(longest) // 2]
    return max(qualified, key=lambda v: scored[(knob, v)]["hold"][1])


def measure_all(symbol: str, bars: list[dict], cells: list[tuple]) -> dict:
    """One pass over the bars, every cell evaluated against the same context.

    Building the MarketContext is the expensive part; evaluating a module
    against one is not. Sharing the context across cells also guarantees every
    candidate is judged on identical tape rather than on its own re-derivation
    of it.
    """
    edges: dict = {key: [] for key, _ in cells}
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
        for key, module in cells:
            try:
                sig = module.evaluate(mkt)
            except Exception:
                continue
            if not getattr(sig, "should_enter", False):
                continue
            call = 1 if sig.direction == "long" else -1
            edges[key].append(realised(bars, i, call, ctx.atr))
    return edges


# ------------------------------------------------------------------ the rule
def survives(cand_tr, cand_ho, inc_tr, inc_ho) -> tuple[bool, str]:
    """(is this a proposal, and if not why not). Each argument is (n, mean, t)."""
    if cand_tr[0] < MIN_N or cand_ho[0] < MIN_N:
        return False, "too few signals (train %d, hold %d)" % (cand_tr[0], cand_ho[0])
    if cand_tr[2] < SHIP_BAR or cand_ho[2] < SHIP_BAR:
        return False, "below the ship bar (t %+.2f / %+.2f)" % (cand_tr[2], cand_ho[2])
    if cand_ho[1] <= inc_ho[1] or cand_tr[1] <= inc_tr[1]:
        return False, "loses to today's setting on one half"
    #: Compared with a tolerance, because binary floats make the boundary lie.
    #: 0.35 - 0.30 is 0.04999999999999999, so a gain of exactly MIN_GAIN_ATR was
    #: refused with the message "gain +0.050 ATR is inside the noise" — a
    #: sentence that contradicts itself, and the same tolerance-free comparison
    #: that produced a wrong autopsy verdict on 2026-08-23.
    if (cand_ho[1] - inc_ho[1]) < MIN_GAIN_ATR - 1e-9:
        return False, "gain %+.3f ATR is inside the noise" % (cand_ho[1] - inc_ho[1])
    return True, ""


# ------------------------------------------------------------------- writing
def already_answered(row: dict) -> str | None:
    """Has the commander already ruled on exactly this change?

    A weekly loop that re-proposes a rejected change every Friday is a loop
    that teaches him to stop reading its proposals — the same reasoning that
    put CRUDEOIL in PARKED_ASSETS rather than letting the orphan alarm fire on
    every boot. A standing PENDING row is suppressed for the same reason: one
    unanswered proposal is a decision waiting, ten copies of it are noise.

    Deliberately keyed on the exact (strategy, asset, new value) triple, so a
    DIFFERENT value for the same knob is still allowed through — new evidence
    deserves a new hearing, a repeat of an answered question does not.
    """
    if not DB.exists():
        return None
    want = json.dumps(row["new"])
    with sqlite3.connect(DB) as conn:
        for status, in conn.execute(
            "SELECT status FROM improvement_proposals WHERE strategy_id=? AND "
            "asset=? AND new_values=? AND status IN ('REJECTED','PENDING')",
            (row["strategy_id"], row["asset"], want),
        ):
            return status
    return None


def write_proposal(row: dict) -> str:
    pid = "sweep-" + uuid.uuid4().hex[:12]
    with sqlite3.connect(DB) as conn:
        conn.execute(
            "INSERT INTO improvement_proposals (proposal_id, strategy_id, "
            "strategy_name, asset, timestamp, action, previous_values, "
            "new_values, rationale, expected_improvement, status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (pid, row["strategy_id"], row["strategy_name"], row["asset"],
             datetime.now(timezone.utc).isoformat(), "TUNE_PARAMETER",
             json.dumps(row["previous"]), json.dumps(row["new"]),
             row["rationale"], row["expected"], "PENDING"),
        )
    return pid


def sweep(only: set[str] | None = None, do_write: bool = False) -> tuple[list, list]:
    """(proposals, ask-tier findings). Prints the full grid as it goes."""
    modules = {getattr(m, "module_id", k): m
               for k, m in {**ENTRY_MODULES, **MCX_ENTRY_MODULES}.items()}

    bars_cache: dict[tuple[str, str], list[dict]] = {}
    proposals: list[dict] = []
    asked: list[str] = []

    for mid, asset, sname in sorted(live_pairs(), key=lambda p: (p[1], p[2])):
        if only and asset not in only:
            continue
        module = modules.get(mid)
        tunables = getattr(module, "TUNABLES", None)
        if module is None or not tunables:
            continue

        try:
            halves = {}
            for label, (a, b) in (("train", TRAIN), ("hold", HOLDOUT)):
                key = (asset, label)
                if key not in bars_cache:
                    bars_cache[key] = load_bars(asset, a, b)
                halves[label] = bars_cache[key]
        except Exception as exc:
            print("\n  %s: could not load bars (%s)" % (asset, exc))
            continue

        print("\n  %s / %s" % (sname, asset))

        for knob, spec in tunables.items():
            tier = spec["tier"]
            incumbent = effective(module, knob, spec, asset)
            #: Declared order is preserved, because `pick` reads adjacency off
            #: it to find a plateau. Sorting here would also crash the moment a
            #: grid mixes None with strings, as the direction knob does.
            grid = tuple(spec["values"])
            if incumbent not in grid:
                grid = grid + (incumbent,)

            cells = [((knob, v), m)
                     for v, m in variants(module, knob, spec, asset, grid)]
            scored: dict = {}
            for label in ("train", "hold"):
                for key, e in measure_all(asset, halves[label], cells).items():
                    scored.setdefault(key, {})[label] = _stats(e)

            inc = scored[(knob, incumbent)]
            print("    %s  (tier %s, %d cells, today %s)"
                  % (knob, tier, len(grid), incumbent))
            print("      %10s %8s %8s %7s   %8s %8s %7s   %s"
                  % ("value", "TRAIN n", "edge", "t", "HOLD n", "edge", "t", "verdict"))

            qualified = set()
            for v in grid:
                tr, ho = scored[(knob, v)]["train"], scored[(knob, v)]["hold"]
                ok, why = survives(tr, ho, inc["train"], inc["hold"])
                mark = "TODAY" if v == incumbent else ("qualifies" if ok else why)
                print("      %10s %8d %+8.3f %+7.2f   %8d %+8.3f %+7.2f   %s"
                      % (v, tr[0], tr[1], tr[2], ho[0], ho[1], ho[2], mark))
                if ok:
                    qualified.add(v)

            v = pick(grid, qualified, scored, knob)
            if v is None:
                continue
            sc = scored[(knob, v)]
            gain = sc["hold"][1] - inc["hold"][1]
            print("      -> proposing %s (of %d qualifying)" % (v, len(qualified)))
            rationale = (
                "%s/%s: %s %s -> %s. "
                "TRAIN n=%d edge=%+.3f t=%+.2f (today %+.3f) | "
                "HOLD n=%d edge=%+.3f t=%+.2f (today %+.3f). "
                "Beats the incumbent on both halves; %d cells tried; "
                "measured with the %s ATR production stop."
                % (sname, asset, knob, incumbent, v,
                   sc["train"][0], sc["train"][1], sc["train"][2], inc["train"][1],
                   sc["hold"][0], sc["hold"][1], sc["hold"][2], inc["hold"][1],
                   len(grid), PROD_STOP_ATR)
            )
            if tier == TIER_ASK:
                asked.append(rationale)
                continue
            proposals.append({
                "strategy_id": mid, "strategy_name": sname, "asset": asset,
                "previous": {knob: incumbent}, "new": {knob: v},
                "rationale": rationale, "expected": gain,
            })

    return proposals, asked


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    do_write = "--write" in sys.argv
    only = {a.upper() for a in args} or None

    print("=" * 92)
    print("  SWEEP LAB — try each live module's own knobs, propose what survives")
    print("  Train %s..%s   Hold-out %s..%s"
          % (TRAIN[0][:10], TRAIN[1][:10], HOLDOUT[0][:10], HOLDOUT[1][:10]))
    print("  Every cell measured WITH the production %s ATR thesis stop." % PROD_STOP_ATR)
    print("  A proposal must clear t>=%.1f on BOTH halves AND beat today's "
          "setting on BOTH." % SHIP_BAR)
    print("=" * 92)

    proposals, asked = sweep(only, do_write)

    print("\n" + "=" * 92)
    if not proposals and not asked:
        print("  No knob beat its incumbent on both halves. Nothing to propose —")
        print("  which is the honest result most weeks, and the reason to believe")
        print("  the weeks it does find something.")
    for p in proposals:
        seen = already_answered(p)
        if seen:
            print("  (skipped, already %s)  %s" % (seen, p["rationale"]))
            continue
        print("  PROPOSE  " + p["rationale"])
        if do_write:
            print("           written as %s (PENDING)" % write_proposal(p))
    for r in asked:
        print("  ASK      " + r)
    if proposals and not do_write:
        print("\n  Re-run with --write to persist these as PENDING proposals.")
    print("")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
