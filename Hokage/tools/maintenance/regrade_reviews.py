"""Re-grade historical position reviews against the fixed graders.

WHY (exit quality, 2026-08-19)
`_grade_exit_quality` tested for English phrases the exit ladder never emits, so
every TARGET_HIT and every TRAIL_LOCK fell through to PREMATURE — the worst
grade available — and `_generate_lesson` then wrote "Exit was premature, trade
closed before stop or target triggered" into the review of a trade that closed
exactly ON its target. Fixed in position_review.py on 2026-08-19; this repairs
the records written before that.

WHY (entry and sizing quality, 2026-11-01)
Both grades were constants.

Entry compared the entry price to an "ideal zone" derived from the stop and
target — which every entry path derives FROM the entry — so the price cancelled
out and the deviation was 0.2333 for every trade ever taken, past the FAIR
bound. 436 of 488 reviews read POOR, and across the 110 reviews with real money
attached the grade pointed BACKWARDS: EXCELLENT n=5 win 0.0% net -7,721.75,
POOR n=64 win 54.7% net +40,646.25. It is now graded on the adverse excursion
recorded live during the hold, which the autopsy already stores as
`max_adverse_excursion_pct` — so the historical records CAN be repaired.

Sizing read `allocation_pct`, written by only one of the three entry paths, and
defaulted the rest to 1.0, which grades CORRECT at every conviction Hokage
scores: 487 of 488. It is now graded on the premium committed as a fraction of
the strategy's war chest, and NOTHING on disk recorded that before today. So
sizing is set to UNKNOWN rather than repaired. That is not a guess — every
historical value provably came from a fabricated or wrongly-denominated input,
and UNKNOWN is the only true statement left about it.

WHAT IT CAN AND CANNOT REPAIR
The review record does NOT store the exit reason, so the grade cannot be
recomputed from the review alone. The reason lives in the autopsy record, and
the two are joined on review.decision_id == autopsy.trade_id.

The adverse excursion lives there too, and joins the same way.

That join only covers part of the corpus:

    reviews    436 total,  65 carry a decision_id,  371 carry none
    autopsies  436 total,  65 carry a trade_id,     371 carry none

The id-less reviews CANNOT be re-graded on exit or entry — there is no way to
learn what ended those trades or how far they ran against themselves. Their
exit and entry grades are left exactly as they are. Overwriting them with a
guess would be worse than leaving them wrong, because a guess is indelible and
looks like evidence.

A trade_id whose autopsies disagree about the exit reason, or about the
excursion, is also skipped, for the same reason.

Sizing is the exception: it needs no join, because the answer is UNKNOWN for
every row regardless of what is on it.

SAFETY
  * Dry run by default. --apply is required to write.
  * Timestamped backup taken before any write.
  * Atomic replace, so an interrupted run cannot truncate the corpus.
  * Only exit_quality, entry_quality, sizing_quality and lesson are touched;
    every other field is preserved byte-for-byte from the original record.
  * --sizing-only / --no-sizing scope the sizing blanking, which touches far
    more rows than the other two and is the one change that REMOVES a value
    instead of correcting it.
  * STOP HOKAGE FIRST. He appends to this file when a position closes, and a
    rewrite racing an append loses the append.

USAGE
    python tools/maintenance/regrade_reviews.py            # dry run
    python tools/maintenance/regrade_reviews.py --apply
    python tools/maintenance/regrade_reviews.py --no-sizing --apply
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

from hokage.memory.resolver import brain_root

#: The active brain root. NOT `BRAIN` — that ignored
#: HOKAGE_BRAIN_ROOT, so moving the brain gave Hokage one brain and this tool
#: another, silently. See hokage.memory.resolver.brain_root.
BRAIN = brain_root()

from bots.autonomous.position_review import PositionReviewEngine, UNKNOWN  # noqa: E402

REVIEWS = BRAIN / "reviews" / "position_reviews.jsonl"
AUTOPSIES = BRAIN / "improvement" / "trade_autopsies.jsonl"
#: Where the lessons actually land. `_forward_lesson` copies every review into
#: MemoryManager, so repairing only the reviews file would fix the paperwork
#: and leave the teaching untouched — 574 of the 596 events in here carried
#: the false entry clause on 2026-11-01.
MEMORY = BRAIN / "memory" / "market_events.jsonl"

#: Sentences emitted by graders that were measuring nothing. They are false on
#: EVERY row, whatever trade it describes, so removing them needs no join:
#:   - the entry clause came from a formula the entry price cancelled out of
#:   - the sizing clauses came from a size only one entry path ever recorded
_DEAD_CLAUSES = (
    " Entry quality was suboptimal \u2014 entry was placed too far from the "
    "ideal entry zone.",
    " Entry quality was suboptimal - entry was placed too far from the "
    "ideal entry zone.",
    " Position was oversized relative to conviction level \u2014 reduce size "
    "on similar setups.",
    " Position was undersized relative to conviction \u2014 review sizing "
    "model calibration.",
)

#: The original lesson embeds the conviction score; the review record does not
#: store it as a field. Recover it so the regenerated lesson keeps the same
#: opening sentence rather than inventing a number.
_CONVICTION = re.compile(r"conviction=(\d+)")


def _load(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _strip_dead_clauses(text: str) -> str:
    for clause in _DEAD_CLAUSES:
        # No escape round-trip here: the literals above are already the
        # real characters once Python parses them, and re-decoding them
        # through latin-1 mangled the em-dash so nothing ever matched.
        text = text.replace(clause, "")
    return text.strip()


def _write_atomically(path: Path, rows: list[dict]) -> Path:
    """Backup, write to a sibling, then replace. An interrupted run must not
    truncate the corpus."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = path.with_suffix(f".{stamp}.bak.jsonl")
    shutil.copy2(path, backup)
    tmp = path.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)
    return backup


def repair_memory(lessons: dict[str, str], apply: bool) -> tuple[int, int]:
    """Rewrite the POSITION_REVIEW events the reviews file just corrected.

    `lessons` maps event_id -> the regenerated lesson. An event whose id is in
    it is rewritten outright. An event whose id is NOT in it still has its dead
    clauses stripped: those sentences are false on every row regardless of
    which trade they belong to, so deleting them needs no join and asserts
    nothing new.

    Returns (rewritten, stripped).
    """
    if not MEMORY.exists():
        return 0, 0
    rows = _load(MEMORY)
    rewritten = stripped = 0
    out_rows: list[dict] = []
    for row in rows:
        if row.get("event_category") != "POSITION_REVIEW":
            out_rows.append(row)
            continue
        new = lessons.get(row.get("event_id", ""))
        if new is None:
            cleaned = _strip_dead_clauses(str(row.get("lessons_learned") or ""))
            if cleaned == str(row.get("lessons_learned") or ""):
                out_rows.append(row)
                continue
            new = cleaned
            stripped += 1
        else:
            if new == row.get("lessons_learned"):
                out_rows.append(row)
                continue
            rewritten += 1
        fixed = dict(row)
        fixed["event_description"] = new
        fixed["lessons_learned"] = new
        out_rows.append(fixed)
    if apply and (rewritten or stripped):
        backup = _write_atomically(MEMORY, out_rows)
        print(f"  Memory backup: {backup.name}")
    return rewritten, stripped


def exit_reasons() -> dict[str, str]:
    """trade_id -> exit_reason, only where every autopsy for that id agrees."""
    seen: dict[str, set[str]] = defaultdict(set)
    for record in _load(AUTOPSIES):
        tid = record.get("trade_id")
        if tid:
            seen[tid].add(record.get("exit_reason") or "")
    return {tid: next(iter(v)) for tid, v in seen.items() if len(v) == 1}


def adverse_excursions() -> dict[str, float]:
    """trade_id -> MAE%, only where every autopsy for that id agrees.

    Same rule as the reason: one id with two different numbers on it means the
    record cannot be trusted to say which trade it describes, so it is skipped
    rather than averaged. An absent excursion is skipped too — that is what
    UNKNOWN is for.
    """
    seen: dict[str, set[float]] = defaultdict(set)
    for record in _load(AUTOPSIES):
        tid = record.get("trade_id")
        mae = record.get("max_adverse_excursion_pct")
        if tid and isinstance(mae, (int, float)):
            seen[tid].add(float(mae))
    return {tid: next(iter(v)) for tid, v in seen.items() if len(v) == 1}


def main() -> int:
    argv = sys.argv[1:]
    apply = "--apply" in argv
    do_sizing = "--no-sizing" not in argv
    do_grades = "--sizing-only" not in argv
    engine = PositionReviewEngine()
    reasons = exit_reasons() if do_grades else {}
    maes = adverse_excursions() if do_grades else {}
    reviews = _load(REVIEWS)

    changed: list[tuple[str, str, str, str]] = []
    lessons_by_event: dict[str, str] = {}
    poisoned: set[str] = set()
    tally: Counter = Counter()
    skipped_no_id = 0
    skipped_no_reason = 0
    skipped_no_mae = 0
    out: list[dict] = []

    for row in reviews:
        did = row.get("decision_id")
        old_exit = row.get("exit_quality")
        old_entry = row.get("entry_quality")
        old_sizing = row.get("sizing_quality")
        new_exit, new_entry = old_exit, old_entry

        if do_grades:
            if not did:
                skipped_no_id += 1
            else:
                reason = reasons.get(did)
                if reason is None:
                    skipped_no_reason += 1
                else:
                    # Only the reason matters for the grades being repaired;
                    # the price arguments are used solely by the STOP branch,
                    # which this never enters for a TARGET_HIT or TRAIL_LOCK.
                    new_exit = engine._grade_exit_quality(reason, 0.0, 0.0, 0.0, 0.0)
                mae = maes.get(did)
                if mae is None:
                    skipped_no_mae += 1
                else:
                    new_entry = engine._grade_entry_quality(mae)

        # No excursion to grade from means the stored entry grade CANNOT be
        # kept. It was produced by a formula the entry price cancelled out of,
        # and the new lesson wording states the heat taken as a measured fact
        # ("ran more than 15% against itself"), so carrying the old label
        # forward would dress a number nobody measured as one somebody did.
        # UNKNOWN for the same reason sizing is UNKNOWN.
        if do_grades and new_entry == old_entry:
            if not did or maes.get(did) is None:
                new_entry = UNKNOWN

        # Sizing needs no join. Every value on disk was computed either from
        # the fabricated 1.0 default or from allocation_pct, a percentage of
        # TOTAL capital that shares no denominator with the premium cap the
        # grade is now written in. Neither is recoverable, so the only true
        # statement left is that it is not known.
        new_sizing = UNKNOWN if do_sizing else old_sizing

        if (new_exit, new_entry, new_sizing) == (old_exit, old_entry, old_sizing):
            out.append(row)
            continue

        conviction = _CONVICTION.search(row.get("lesson") or "")
        # 0.00 on disk is ambiguous: the field is a float, so an UNMEASURABLE
        # R:R and a genuine zero look identical once written. Reading it back
        # as 0.0 would re-trigger "Low R:R of 0.00 despite profit" on exactly
        # the winners that fix was written to protect, so an ambiguous zero is
        # passed through as unmeasurable.
        stored_rr = row.get("risk_reward_achieved")
        rr = None if not stored_rr else float(stored_rr)
        fixed = dict(row)
        fixed["exit_quality"] = new_exit
        fixed["entry_quality"] = new_entry
        fixed["sizing_quality"] = new_sizing
        fixed["lesson"] = engine._generate_lesson(
            symbol=row.get("symbol", "?"),
            entry_quality=new_entry,
            exit_quality=new_exit,
            sizing_quality=new_sizing,
            stop_quality=row.get("stop_quality", "CORRECT"),
            rr_achieved=rr,
            pnl=float(row.get("pnl") or 0.0),
            holding_days=int(row.get("holding_days") or 0),
            conviction_score=int(conviction.group(1)) if conviction else 0,
        )
        fixed["regraded_at"] = datetime.now().isoformat(timespec="seconds")
        fixed["regraded_from"] = {
            "entry_quality": old_entry,
            "exit_quality": old_exit,
            "sizing_quality": old_sizing,
        }
        out.append(fixed)
        # `_forward_lesson` keys memory events exactly this way. An id-less
        # review falls back to the SYMBOL, so several different trades on one
        # day collapse onto one key — which is why memory holds 593 events
        # under 127 distinct ids. Where two reviews disagree about what that
        # one event should say, neither answer is written: the id is poisoned
        # and the event is only clause-stripped instead.
        event_id = f"review_{did or row.get('symbol', '?')}_{str(row.get('timestamp', ''))[:10]}"
        if lessons_by_event.get(event_id, fixed["lesson"]) != fixed["lesson"]:
            poisoned.add(event_id)
        lessons_by_event[event_id] = fixed["lesson"]
        changed.append((row.get("symbol", "?"), old_entry, new_entry, old_exit))
        if new_exit != old_exit:
            tally[("exit", old_exit, new_exit)] += 1
        if new_entry != old_entry:
            tally[("entry", old_entry, new_entry)] += 1
        if new_sizing != old_sizing:
            tally[("sizing", old_sizing, new_sizing)] += 1

    print("=" * 72)
    print("  REGRADE POSITION REVIEWS" + ("  [APPLY]" if apply else "  [dry run]"))
    print("=" * 72)
    print(f"  reviews                       {len(reviews)}")
    print(f"  no decision_id, untouchable   {skipped_no_id}")
    print(f"  id present but reason unknown {skipped_no_reason}")
    print(f"  id present but excursion unknown {skipped_no_mae}")
    print(f"  rows rewritten                {len(changed)}")
    for (field, old, new), count in tally.most_common():
        print(f"      {field:<7} {str(old):<10} -> {str(new):<10} {count}")
    for symbol, old, new, _ in changed[:8]:
        print(f"      {symbol:<24} entry {old} -> {new}")
    if len(changed) > 8:
        print(f"      ... and {len(changed) - 8} more")

    for key in poisoned:
        lessons_by_event.pop(key, None)
    if poisoned:
        print(f"  memory ids claimed by >1 review {len(poisoned)} (strip only)")
    mem_rewritten, mem_stripped = repair_memory(lessons_by_event, apply=False)
    print(f"  memory events rewritten      {mem_rewritten}")
    print(f"  memory events clause-stripped {mem_stripped}")

    if not apply:
        print("\n  Dry run. Re-run with --apply to write.")
        return 0
    if not changed and not (mem_rewritten or mem_stripped):
        print("\n  Nothing to change.")
        return 0

    if changed:
        backup = _write_atomically(REVIEWS, out)
        print(f"\n  Backup: {backup.name}")
        print(f"  Wrote {len(out)} rows, {len(changed)} regraded.")
    done_rewritten, done_stripped = repair_memory(lessons_by_event, apply=True)
    print(f"  Memory: {done_rewritten} rewritten, {done_stripped} clause-stripped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
