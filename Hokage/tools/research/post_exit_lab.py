"""Did the exit save money or cost it? Judged on what happened next.

THE COMMANDER'S QUESTION, 2026-11-12: "what if after his exit option again
goes up and reached his target, or what if it goes further down".

Hokage has never known. `position_review` grades an exit from the REASON he
gave it - TRAIL_LOCK, TARGET_HIT, EOD - which is a label, not an outcome. Two
GOLDM puts on consecutive days both peaked above +6%, both armed the trail,
both fell back to the break-even floor, both lost (-255 and -697 net). Whether
holding either would have reached its target or collapsed further was
unanswerable, because nobody was watching the contract after the sale.

WHAT IT MEASURES, per exit:
  * the highest and lowest the contract traded AFTER we left
  * whether it reached the target we abandoned
  * whether it reached the stop we avoided
  * a verdict: EXIT SAVED US / EXIT COST US / NO DIFFERENCE

FIVE WAYS THIS COULD LIE, each guarded:

  1. HINDSIGHT. It is trivially easy to build a regret machine: you remember
     the exits that recovered and forget the ones that collapsed. So NO
     DIFFERENCE is a first-class verdict and the report prints all three
     counts together, never "n exits were premature" on its own.

  2. IT TESTS THE EXIT, NOT THE ENTRY. What happened between entry and exit
     judges the entry; what happens after judges the exit. A contract that
     keeps climbing says the DIRECTION was right and we left early - useful,
     and a different question. The report says so rather than letting the
     reader conflate them.

  3. THETA. An option bleeds value just from the clock, so "it went back up"
     flatters holding unless decay is charged for. `theta_lab` measures
     0.03-0.98% of premium on the index and NOTHING on MCX yet, so a decay
     figure is NOT invented here: the raw excursion is reported and the
     missing charge is stated. Where the hold is long enough for decay to
     dominate, that is said too.

  4. NOT LOOKING IS NOT A VERDICT. An exit with no observations means the
     capture was off or the broker unreachable, not that the exit was fine.
     Those are counted separately and excluded from every rate.

  5. IN-SAMPLE TUNING. Nothing here proposes an exit rule. The ladder's arm
     threshold, floor and backstop are commander-approved risk constants, and
     a change read off this table would be fitted to the past - which is what
     killed three hypotheses in the three days before it was written.
"""
from __future__ import annotations

import argparse
import collections
import datetime as dt
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from hokage.memory import exit_followup  # noqa: E402

#: A move smaller than this, either way, is noise rather than a verdict.
#: Expressed against the EXIT price so it scales with the premium, and set at
#: the measured GOLDM round trip (0.47%) because a difference smaller than
#: the cost of acting on it is not a difference worth a verdict.
MATERIAL_PCT = 0.5


def _pct(a: float, b: float) -> float:
    return ((a - b) / b * 100.0) if b else 0.0


class Verdict:
    SAVED = "EXIT SAVED US"
    COST = "EXIT COST US"
    SAME = "NO DIFFERENCE"
    UNWATCHED = "NOT WATCHED"


def judge(row: dict) -> dict:
    """One exit, judged on its aftermath. Pure: no clock, no database."""
    marks = row.get("observations") or []
    exit_price = float(row.get("exit_price") or 0.0)
    out = {
        "position_id": row.get("position_id"),
        "contract": row.get("contract"),
        "underlying": row.get("underlying"),
        "strategy_id": row.get("strategy_id"),
        "exit_reason": row.get("exit_reason"),
        "exit_price": exit_price,
        "target_price": row.get("target_price"),
        "stop_price": row.get("stop_price"),
        "gross_pnl": row.get("gross_pnl"),
        "marks": len(marks),
        "high_after": None, "low_after": None,
        "best_pct": None, "worst_pct": None,
        "reached_target": None, "reached_stop": None,
        "verdict": Verdict.UNWATCHED,
    }
    prices = [float(m["last_price"]) for m in marks
              if m.get("last_price") is not None]
    if not prices or exit_price <= 0:
        return out

    high, low = max(prices), min(prices)
    out["high_after"], out["low_after"] = high, low
    out["best_pct"] = _pct(high, exit_price)
    out["worst_pct"] = _pct(low, exit_price)

    target = row.get("target_price")
    stop = row.get("stop_price")
    # The position was LONG the option in every case - the mandate is
    # options buying - so "target" is above and "stop" below.
    if target:
        out["reached_target"] = high >= float(target)
    if stop:
        out["reached_stop"] = low <= float(stop)

    up, down = out["best_pct"], -out["worst_pct"]
    if up < MATERIAL_PCT and down < MATERIAL_PCT:
        out["verdict"] = Verdict.SAME
    elif up >= down:
        out["verdict"] = Verdict.COST
    else:
        out["verdict"] = Verdict.SAVED
    return out


def report(limit: int | None = None) -> str:
    rows = exit_followup.followups(limit)
    cover = exit_followup.coverage()
    judged = [judge(r) for r in rows]
    watched = [j for j in judged if j["verdict"] != Verdict.UNWATCHED]

    out: list[str] = ["", "HOKAGE POST-EXIT LAB - did the exit save or cost?",
                      "=" * 70, ""]
    out.append("COVERAGE (not looking is not a verdict)")
    out.append(f"  exits recorded            {cover['exits']}")
    out.append(f"  with aftermath observed   {cover['with_observations']}")
    out.append(f"  WITHOUT any observation   {cover['without_observations']}"
               f"   <- excluded from every rate below")
    out.append(f"  post-exit marks stored    {cover['marks']}")
    out.append("")
    if cover["exits"] == 0:
        out.append("  Nothing recorded yet. This corpus starts at the first")
        out.append("  exit after the intraday capture was switched on, and")
        out.append("  can never cover a position closed before that - an")
        out.append("  option's price history dies with the contract.")
        out.append("")
        return "\n".join(out)
    if not watched:
        out.append("  Exits are recorded but none has an aftermath yet. That")
        out.append("  is a gap in the measurement, NOT a clean bill of")
        out.append("  health for the exits.")
        out.append("")
        return "\n".join(out)

    # ------------------------------------------------ Phase 4: the pattern
    counts = collections.Counter(j["verdict"] for j in watched)
    out.append("-" * 70)
    out.append("THE PATTERN (all three verdicts, together, on purpose)")
    out.append("")
    for name in (Verdict.COST, Verdict.SAVED, Verdict.SAME):
        n = counts.get(name, 0)
        out.append(f"  {name:16s} {n:3d}  ({n / len(watched) * 100:3.0f}%)")
    out.append("")
    out.append(f"  A move under {MATERIAL_PCT:.1f}% either way counts as NO")
    out.append("  DIFFERENCE: smaller than the cheapest round trip measured")
    out.append("  on this book, so acting on it would cost more than it is")
    out.append("  worth. Reporting 'premature' without this bucket is how a")
    out.append("  measurement becomes a regret machine.")
    out.append("")

    reached = [j for j in watched if j["reached_target"]]
    hit_stop = [j for j in watched if j["reached_stop"]]
    out.append(f"  reached the target we abandoned : {len(reached):3d} of "
               f"{len(watched)}")
    out.append(f"  reached the stop we avoided     : {len(hit_stop):3d} of "
               f"{len(watched)}")
    out.append("")

    best = [j["best_pct"] for j in watched]
    worst = [j["worst_pct"] for j in watched]
    out.append("  AFTER THE EXIT, in % of the exit price")
    out.append(f"    best  median {statistics.median(best):+6.2f}%   "
               f"max {max(best):+6.2f}%")
    out.append(f"    worst median {statistics.median(worst):+6.2f}%   "
               f"min {min(worst):+6.2f}%")
    out.append("")

    # ----------------------------------------- by the mechanism that fired
    out.append("-" * 70)
    out.append("BY EXIT MECHANISM (which rule leaves money, which saves it)")
    out.append("")
    by_mech: dict = collections.defaultdict(list)
    for j in watched:
        by_mech[_mechanism(j["exit_reason"])].append(j)
    out.append(f"  {'mechanism':22s} {'n':>3s} {'cost':>5s} {'saved':>6s} "
               f"{'same':>5s} {'median best':>12s}")
    for mech, group in sorted(by_mech.items(),
                              key=lambda kv: -len(kv[1])):
        c = sum(1 for j in group if j["verdict"] == Verdict.COST)
        s = sum(1 for j in group if j["verdict"] == Verdict.SAVED)
        q = sum(1 for j in group if j["verdict"] == Verdict.SAME)
        med = statistics.median([j["best_pct"] for j in group])
        out.append(f"  {mech:22s} {len(group):3d} {c:5d} {s:6d} {q:5d} "
                   f"{med:+11.2f}%")
    out.append("")

    # ------------------------------------------------- Phase 3: per trade
    out.append("-" * 70)
    out.append("EVERY EXIT (newest first)")
    out.append("")
    for j in judged[:40]:
        if j["verdict"] == Verdict.UNWATCHED:
            out.append(f"  {j['contract']:24s} {'-- not watched --':>22s}")
            continue
        tgt = ("target HIT" if j["reached_target"]
               else ("stop HIT" if j["reached_stop"] else ""))
        out.append(f"  {j['contract']:24s} exit {j['exit_price']:>8.2f}  "
                   f"best {j['best_pct']:+6.2f}%  worst {j['worst_pct']:+6.2f}%"
                   f"  {j['verdict']:14s} {tgt}")
    out.append("")

    out.append("-" * 70)
    out.append("WHAT THIS DOES NOT SAY")
    out.append("")
    out.append("  IT JUDGES THE EXIT, NOT THE ENTRY. Entry quality is what")
    out.append("  happened BETWEEN entry and exit. A contract that kept")
    out.append("  climbing says the direction was right and we left early.")
    out.append("")
    out.append("  THETA IS NOT CHARGED HERE. An option decays just from the")
    out.append("  clock, so 'it went back up' flatters holding. theta_lab")
    out.append("  measures 0.03-0.98% of premium on the index and nothing on")
    out.append("  MCX yet, so no decay figure is invented - the raw")
    out.append("  excursion is shown and the missing charge is stated.")
    out.append("")
    out.append("  IT PROPOSES NOTHING. The arm threshold, the floor and the")
    out.append("  backstop are commander-approved risk constants, and a")
    out.append("  change read off this table would be fitted to the past.")
    out.append("")
    return "\n".join(out)


def _mechanism(reason: str | None) -> str:
    text = (reason or "").lower()
    if not text.strip():
        return "UNRECORDED"
    if "trail" in text:
        return "TRAIL_LOCK"
    if "hard backstop" in text or "backstop" in text:
        return "HARD BACKSTOP"
    if "target" in text:
        return "TARGET HIT"
    if "thesis" in text:
        return "THESIS STOP"
    if any(w in text for w in ("square", "eod", "session", "cutoff")):
        return "SESSION CLOSE"
    return "OTHER"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Judge exits on what came next.")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args(argv)
    print(report(args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
