"""Measure what the TRAIL ARM THRESHOLD does, by replaying real premium paths.

WHY THIS EXISTS
On 2026-11-02 GOLDM26NOV138500PE lost Rs 6,325 with `floor 3376.77` printed
beside it on every poll. The floor was never enforced: the ladder's rung 4 is
PROFIT protection and only activates once the trade is
`_OPTION_TRAIL_ARM_PCT` (5%) above entry. That position peaked at +4.53% and
missed arming by 16.83 points, so it ran to the -12% hard backstop instead.

The obvious reaction is to lower the arm threshold. The obvious reaction is
what this lab exists to check, because the last time a stop was tightened on
this module the measurement said it removed 57% of SessionShift's edge.

WHAT ARMING ACTUALLY BUYS
Once armed the floor is `max(peak * (1 - TRAIL_LOCK), entry)` -- it can NEVER
sit below entry. So for any trade peaking under +11.1% (where peak*0.90 first
clears entry) arming means exactly one thing: EXIT AT BREAKEVEN IF IT COMES
BACK TO ENTRY. Lowering the threshold therefore cannot shrink a loss that
never went green; it converts near-misses into scratches, and it converts
round-trips-that-recover into scratches too. That second group is the cost.

METHOD
For each archived position, replay its real per-poll premium marks and ask, for
each candidate arm threshold, whether rung 4 would have fired before the exit
that actually happened. Rungs 1-3 (backstop, thesis stop, target) do not depend
on the arm threshold, so a lower threshold can only ever produce an EARLIER
exit at or above entry; where it does not fire, the trade keeps its real
outcome. Paired per trade, so each position is its own control.

THREE LIMITS, STATED UP FRONT
  * n is the entire population, not a sample. Option premium history dies with
    the contract, so the archive begins 2026-10-23 and holds 18 positions. No
    result here can clear a t >= 2 bar on that count, and this lab does not
    pretend otherwise -- it reports the t it finds and leaves the bar where it
    is.
  * The replay exits AT THE OBSERVED MARK, one poll after the breach at worst.
    Real fills slip: on 2026-11-02 the backstop triggered at 3138.52 and filled
    at 2934, a 13.4% drag. Every counterfactual here is therefore an UPPER
    BOUND on what a lower threshold would have saved.
  * Marks are recorded once a minute while a position is open. A breach between
    two polls is invisible to this replay exactly as it was to the bot.

USAGE
    python tools/research/trail_arm_lab.py
    python tools/research/trail_arm_lab.py --playbook MCX_SessionShift
"""
from __future__ import annotations

import argparse
import sqlite3
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot  # noqa: E402

ARCHIVE = Path(r"C:\Hokage\hokage_brain\candles.db")
LEDGER = Path(r"C:\Hokage\hokage_brain\hokage.db")

#: Production today. Read from the class so this lab cannot drift from it.
LIVE_ARM = Bot._OPTION_TRAIL_ARM_PCT
TRAIL_LOCK = Bot._OPTION_TRAIL_LOCK_FRACTION

#: 0.00 means "arm the moment the trade is green at all".
CANDIDATES = (0.00, 0.01, 0.02, 0.03, 0.04, LIVE_ARM, 0.07, 0.10)


def load_positions(playbook: str | None) -> list[dict]:
    """Every archived premium path joined to its closed ledger row."""
    arc = sqlite3.connect(f"file:{ARCHIVE}?mode=ro", uri=True)
    arc.row_factory = sqlite3.Row
    led = sqlite3.connect(f"file:{LEDGER}?mode=ro", uri=True)
    led.row_factory = sqlite3.Row

    out: list[dict] = []
    for key in arc.execute(
        "SELECT DISTINCT symbol, day FROM position_marks ORDER BY day, symbol"
    ):
        row = led.execute(
            "SELECT quantity, entry_price, realized_pnl, playbook_id"
            " FROM positions WHERE market = ? AND date(opened_at) = ?"
            " AND status = 'CLOSED'",
            (key["symbol"], key["day"]),
        ).fetchone()
        if row is None:
            continue
        if playbook and row["playbook_id"] != playbook:
            continue
        marks = [
            r["premium"] for r in arc.execute(
                "SELECT premium FROM position_marks WHERE symbol = ? AND day = ?"
                " ORDER BY observed_at",
                (key["symbol"], key["day"]),
            ) if r["premium"]
        ]
        if not marks:
            continue
        out.append({
            "symbol": key["symbol"], "day": key["day"],
            "qty": float(row["quantity"]), "entry": float(row["entry_price"]),
            "actual_pnl": float(row["realized_pnl"]),
            "playbook": row["playbook_id"], "marks": marks,
        })
    return out


def replay(pos: dict, arm_pct: float) -> tuple[float, bool]:
    """(pnl, did rung 4 fire) for this position at this arm threshold.

    Mirrors the live rung 4: the floor is `max(peak*(1-TRAIL_LOCK), entry)` and
    is only live once `peak >= entry*(1+arm_pct)`. The floor never falls.
    """
    entry, qty = pos["entry"], pos["qty"]
    peak = entry
    floor = 0.0
    for premium in pos["marks"]:
        peak = max(peak, premium)
        if peak >= entry * (1.0 + arm_pct):
            floor = max(floor, peak * (1.0 - TRAIL_LOCK), entry)
        # Checked AFTER the floor updates, as the live ladder does: a single
        # mark can both set a new peak and sit below the resulting floor only
        # if TRAIL_LOCK is 0, so the order is safe either way.
        if floor and premium <= floor:
            return (premium - entry) * qty, True
    return pos["actual_pnl"], False


def t_stat(values: list[float]) -> float | None:
    """Paired t on the per-trade differences. None when it cannot be computed."""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return None
    sd = statistics.stdev(vals)
    if sd == 0:
        return None
    return statistics.mean(vals) / (sd / (len(vals) ** 0.5))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--playbook", help="restrict to one playbook, e.g. MCX_SessionShift")
    args = ap.parse_args()

    positions = load_positions(args.playbook)
    if not positions:
        print("no archived premium paths join to a closed ledger row.")
        return 1

    baseline = sum(p["actual_pnl"] for p in positions)
    print(f"TRAIL ARM SWEEP  --  {len(positions)} positions, "
          f"{positions[0]['day']} to {positions[-1]['day']}"
          + (f", playbook {args.playbook}" if args.playbook else ""))
    print(f"production arm = {LIVE_ARM:.0%}, trail lock = {TRAIL_LOCK:.0%}, "
          f"floor can never sit below entry")
    print(f"actual realised total: Rs {baseline:,.0f}\n")

    print(f"{'arm':>6} {'fired':>6} {'total Rs':>11} {'vs live Rs':>11} "
          f"{'mean diff':>10} {'t(diff)':>8}  verdict")
    print("-" * 78)

    live_pnls = [replay(p, LIVE_ARM)[0] for p in positions]
    rows = []
    for arm in CANDIDATES:
        pnls, fired = [], 0
        for p in positions:
            pnl, did = replay(p, arm)
            pnls.append(pnl)
            fired += int(did)
        total = sum(pnls)
        diffs = [a - b for a, b in zip(pnls, live_pnls)]
        t = t_stat(diffs)
        delta = total - sum(live_pnls)
        tag = "  <-- production" if arm == LIVE_ARM else ""
        t_txt = f"{t:>8.2f}" if t is not None else f"{'--':>8}"
        print(f"{arm:>5.0%} {fired:>6} {total:>11,.0f} {delta:>+11,.0f} "
              f"{statistics.mean(diffs):>+10,.0f} {t_txt}{tag}")
        rows.append((arm, total, delta, t))

    print("-" * 78)
    best = max(rows, key=lambda r: r[1])
    print(f"\nbest total at arm = {best[0]:.0%} "
          f"(Rs {best[1]:,.0f}, {best[2]:+,.0f} vs production)")
    if best[3] is None:
        print("t could not be computed: too few trades differ to form a distribution.")
    else:
        print(f"paired t on the difference: {best[3]:.2f}  "
              f"{'CLEARS' if abs(best[3]) >= 2 else 'DOES NOT CLEAR'} the t >= 2 bar")

    # LEAVE-ONE-OUT, printed whether or not it is flattering. A threshold is
    # being judged on a handful of trades, and the trade that PROMPTED the
    # question is in the sample -- so the headline can be one row wearing a
    # total's clothes. If dropping a single position collapses the result,
    # that is the result.
    best_pnls = [replay(p, best[0])[0] for p in positions]
    diffs = [a - b for a, b in zip(best_pnls, live_pnls)]
    total_diff = sum(diffs)
    print(f"\nLEAVE-ONE-OUT at arm = {best[0]:.0%}  (full sample: "
          f"{total_diff:+,.0f})")
    worst_drop = None
    for i, pos in enumerate(positions):
        if abs(diffs[i]) < 1e-9:
            continue
        rest = diffs[:i] + diffs[i + 1:]
        t_rest = t_stat(rest)
        share = diffs[i] / total_diff * 100 if total_diff else 0.0
        print(f"  without {pos['symbol'][:22]:22} {pos['day']}  "
              f"{sum(rest):>+9,.0f}  t {t_rest:>5.2f}" if t_rest is not None
              else f"  without {pos['symbol'][:22]:22} {pos['day']}  "
                   f"{sum(rest):>+9,.0f}  t    --")
        if worst_drop is None or abs(share) > abs(worst_drop[1]):
            worst_drop = (pos, share)
    if worst_drop and abs(worst_drop[1]) >= 50.0:
        print(f"\n  ONE TRADE CARRIES {worst_drop[1]:.0f}% OF THIS RESULT "
              f"({worst_drop[0]['symbol']} {worst_drop[0]['day']}).")
        print("  Treat the headline as that trade, not as a measured edge.")
    print(f"\nn = {len(positions)}. This is the ENTIRE archive, not a sample: option\n"
          f"premium history dies with the contract and the archive begins 2026-10-23.\n"
          f"Exits are priced at the observed mark, so every figure above is an\n"
          f"UPPER BOUND -- the 2026-11-02 backstop filled 13.4% below its trigger.")

    print(f"\n{'symbol':26} {'day':11} {'actual':>9} {'at best':>9} {'diff':>9}")
    for p in positions:
        alt, _ = replay(p, best[0])
        print(f"  {p['symbol']:24} {p['day']:11} {p['actual_pnl']:>9,.0f} "
              f"{alt:>9,.0f} {alt - p['actual_pnl']:>+9,.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
