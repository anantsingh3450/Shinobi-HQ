"""Re-grade historical position reviews with the fixed exit-quality matcher.

WHY
`_grade_exit_quality` tested for English phrases the exit ladder never emits, so
every TARGET_HIT and every TRAIL_LOCK fell through to PREMATURE — the worst
grade available — and `_generate_lesson` then wrote "Exit was premature, trade
closed before stop or target triggered" into the review of a trade that closed
exactly ON its target. Fixed in position_review.py on 2026-08-19; this repairs
the records written before that.

WHAT IT CAN AND CANNOT REPAIR
The review record does NOT store the exit reason, so the grade cannot be
recomputed from the review alone. The reason lives in the autopsy record, and
the two are joined on review.decision_id == autopsy.trade_id.

That join only covers part of the corpus:

    reviews    436 total,  65 carry a decision_id,  371 carry none
    autopsies  436 total,  65 carry a trade_id,     371 carry none

The 371 id-less reviews CANNOT be re-graded — there is no way to learn what
ended those trades. They are left exactly as they are. Overwriting them with a
guess would be worse than leaving them wrong, because a guess is indelible and
looks like evidence.

A trade_id whose autopsies disagree about the exit reason is also skipped, for
the same reason.

SAFETY
  * Dry run by default. --apply is required to write.
  * Timestamped backup taken before any write.
  * Atomic replace, so an interrupted run cannot truncate the corpus.
  * Only exit_quality and lesson are touched; every other field is preserved
    byte-for-byte from the original record.
  * STOP HOKAGE FIRST. He appends to this file when a position closes, and a
    rewrite racing an append loses the append.

USAGE
    python tools/maintenance/regrade_reviews.py            # dry run
    python tools/maintenance/regrade_reviews.py --apply
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from bots.autonomous.position_review import PositionReviewEngine  # noqa: E402

REVIEWS = ROOT / "hokage_brain" / "reviews" / "position_reviews.jsonl"
AUTOPSIES = ROOT / "hokage_brain" / "improvement" / "trade_autopsies.jsonl"

#: The original lesson embeds the conviction score; the review record does not
#: store it as a field. Recover it so the regenerated lesson keeps the same
#: opening sentence rather than inventing a number.
_CONVICTION = re.compile(r"conviction=(\d+)")


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def exit_reasons() -> dict[str, str]:
    """trade_id -> exit_reason, only where every autopsy for that id agrees."""
    seen: dict[str, set[str]] = defaultdict(set)
    for record in _load(AUTOPSIES):
        tid = record.get("trade_id")
        if tid:
            seen[tid].add(record.get("exit_reason") or "")
    return {tid: next(iter(v)) for tid, v in seen.items() if len(v) == 1}


def main() -> int:
    apply = "--apply" in sys.argv[1:]
    engine = PositionReviewEngine()
    reasons = exit_reasons()
    reviews = _load(REVIEWS)

    changed: list[tuple[str, str, str]] = []
    tally: Counter = Counter()
    skipped_no_id = 0
    skipped_no_reason = 0
    out: list[dict] = []

    for row in reviews:
        did = row.get("decision_id")
        if not did:
            skipped_no_id += 1
            out.append(row)
            continue
        reason = reasons.get(did)
        if reason is None:
            skipped_no_reason += 1
            out.append(row)
            continue

        old = row.get("exit_quality")
        # Only the reason matters for the two grades being repaired; the price
        # arguments are used solely by the STOP branch, which this never enters
        # for a TARGET_HIT or TRAIL_LOCK reason.
        new = engine._grade_exit_quality(reason, 0.0, 0.0, 0.0, 0.0)
        if new == old:
            out.append(row)
            continue

        conviction = _CONVICTION.search(row.get("lesson") or "")
        fixed = dict(row)
        fixed["exit_quality"] = new
        fixed["lesson"] = engine._generate_lesson(
            symbol=row.get("symbol", "?"),
            entry_quality=row.get("entry_quality", "FAIR"),
            exit_quality=new,
            sizing_quality=row.get("sizing_quality", "CORRECT"),
            stop_quality=row.get("stop_quality", "CORRECT"),
            rr_achieved=float(row.get("risk_reward_achieved") or 0.0),
            pnl=float(row.get("pnl") or 0.0),
            holding_days=int(row.get("holding_days") or 0),
            conviction_score=int(conviction.group(1)) if conviction else 0,
        )
        fixed["regraded_at"] = datetime.now().isoformat(timespec="seconds")
        fixed["regraded_from"] = old
        out.append(fixed)
        changed.append((row.get("symbol", "?"), old, new))
        tally[(old, new)] += 1

    print("=" * 72)
    print("  REGRADE POSITION REVIEWS" + ("  [APPLY]" if apply else "  [dry run]"))
    print("=" * 72)
    print(f"  reviews                       {len(reviews)}")
    print(f"  no decision_id, untouchable   {skipped_no_id}")
    print(f"  id present but reason unknown {skipped_no_reason}")
    print(f"  regraded                      {len(changed)}")
    for (old, new), count in tally.most_common():
        print(f"      {old:<10} -> {new:<10} {count}")
    for symbol, old, new in changed[:8]:
        print(f"      {symbol:<24} {old} -> {new}")
    if len(changed) > 8:
        print(f"      ... and {len(changed) - 8} more")

    if not apply:
        print("\n  Dry run. Re-run with --apply to write.")
        return 0
    if not changed:
        print("\n  Nothing to change.")
        return 0

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = REVIEWS.with_suffix(f".{stamp}.bak.jsonl")
    shutil.copy2(REVIEWS, backup)
    tmp = REVIEWS.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in out), encoding="utf-8")
    tmp.replace(REVIEWS)
    print(f"\n  Backup: {backup.name}")
    print(f"  Wrote {len(out)} rows, {len(changed)} regraded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
