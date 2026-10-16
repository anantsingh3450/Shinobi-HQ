"""One vocabulary for a proposal, and the basis it was measured on.

THREE FAULTS MET HERE, found 2026-10-16, and they compound.

1. TWO WORDS FOR PENDING. `improvement_bot` writes "PENDING_APPROVAL";
   `sweep_lab` and `weekly_audit` -- the two that produce MEASURED, evidence
   backed proposals -- write "PENDING". Every reader was written against one
   word or the other.

2. SO THE MEASURED ONES WERE INVISIBLE. `hokage proposals` filters on
   "PENDING_APPROVAL" and answered "No pending proposals" while three sat in
   the table: a RangeFade knob from 08-26 and a SessionShift window and a
   MeanReversion retirement from 09-22. There is no dashboard view of them at
   all, so that command was the only surface.

3. AND UNAPPLIABLE. `apply_improvement_proposal` returns False for any status
   that is not "PENDING_APPROVAL". Had the commander found one and said yes,
   the apply path would have refused it and logged that it was "already in
   PENDING status".

The whole method of this system is measure, propose, let the commander decide.
It terminated in a table nobody read behind an apply path that refused it.

THE FOURTH FAULT IS THE WORST ONE. `already_answered` in sweep_lab suppresses
a re-proposal while a PENDING row exists for the same change -- correctly, so
a weekly job does not re-ask an answered question. But all three rows were
measured on a basis this codebase has since abandoned: the audit moved to full
geometry with a per-cell stop on 10-14 and its bar rose from 2.0 to 3.16, and
sweep_lab now corrects for its own search size. The SessionShift row says in
its own rationale "measured with the 1.25 ATR production stop" while GOLDM has
run 3.0 ATR since 08-13. So a dead row measured on a retired basis was
SILENCING the corrected measurement of the same question.

THE DOCTRINE IS ALREADY HERE, in evolution._same_geometry: a basis change
resets the evidence rather than continuing it, because there is no trend
across a change of instrument. This applies the same rule to proposals. A
proposal now carries the basis it was measured on, an unstamped one is stale
by definition, and a stale proposal neither suppresses a fresh measurement nor
gets applied.

NOTHING HERE REWRITES A STORED ROW. The three are the record of questions that
were genuinely asked, and the commander has not answered them. They stay
PENDING and visible; they are shown as measured on a retired basis, which is
what they are.
"""
from __future__ import annotations

#: Every spelling of "waiting for the commander" that exists in the ledger.
#: Readers accept both. Writers should use PENDING_APPROVAL, which is the one
#: the apply path and the improvement bot have always used.
PENDING = "PENDING"
PENDING_APPROVAL = "PENDING_APPROVAL"
PENDING_STATUSES = (PENDING, PENDING_APPROVAL)

#: Marks a proposal the commander ruled on. Kept here so the suppression rules
#: and the display agree on the words.
REJECTED = "REJECTED"
APPLIED = "APPLIED"

#: HOW THE LABS MEASURE, as of 2026-10-14. Byte-identical to the prefix of
#: weekly_audit.GEOMETRY, which is compared against stored snapshots by
#: evolution._same_geometry -- changing this string resets the retirement
#: clock, which is the intended consequence of a real basis change and a
#: serious accident otherwise.
#:
#:   holdout-split   train and hold-out halves, never one pooled window
#:   stop-per-cell   the production stop for THAT (strategy, symbol), not 1.25
#:   target          production's target applied, because a target truncates
#:                   exactly the winners a horizon exit counts in full
#:   tradedbars      entries on bars that never traded are excluded
MEASUREMENT_BASIS = "holdout-split+stop-per-cell+target+tradedbars"

#: HOW THE IMPROVEMENT BOT MEASURES, which is not how the labs do. Its
#: proposals come from drift against a strategy's recorded baseline: no
#: hold-out split, no production stop, no t-statistic. That is a weaker basis
#: and it is stamped as its own thing rather than left blank, because blank
#: means "nobody recorded it" and those are different facts. A drift proposal
#: never claimed to clear a bar, so a change of bar does not stale it.
DRIFT_BASIS = "drift-heuristic"

#: Bases still in use. Anything else was measured on an instrument this system
#: has retired.
CURRENT_BASES = (MEASUREMENT_BASIS, DRIFT_BASIS)


def is_pending(status: str | None) -> bool:
    """True for either spelling of waiting-on-the-commander."""
    return (status or "").strip().upper() in PENDING_STATUSES


def stamp(bar: float) -> str:
    """The basis string a proposal measured today should carry.

    The BAR is part of it. A proposal is a claim that something clears the
    bar, so a change of bar changes what the claim means -- the same reasoning
    that folded the bar into the audit's own geometry stamp.
    """
    return f"{MEASUREMENT_BASIS}+bar{bar:.2f}"


def parse_stamp(stamped: str | None) -> tuple[str, float | None]:
    """Split a stamp into (basis, bar). Returns ("", None) for nothing."""
    if not stamped:
        return "", None
    text = str(stamped).strip()
    basis, sep, tail = text.rpartition("+bar")
    if not sep:
        return text, None
    try:
        return basis, float(tail)
    except ValueError:
        return text, None


def is_stale(stamped: str | None, current_bar: float | None = None) -> bool:
    """Was this proposal measured on a basis the system no longer uses?

    An UNSTAMPED proposal is stale. That is deliberate and it is the same
    choice _same_geometry made for snapshots written before the field existed:
    a measurement whose basis is unrecorded cannot be shown to match the
    current one, and assuming it does is how a number from a retired
    instrument gets treated as current evidence.

    `current_bar` is optional because the two callers know different things.
    The labs know the bar they would judge this question at today, so they
    pass it and a proposal measured at an EASIER bar is stale. The bot and the
    router do not compute a bar at all, so they check the basis only and
    display whatever bar the stamp carries.
    """
    basis, bar = parse_stamp(stamped)
    if basis not in CURRENT_BASES:
        return True
    if basis == DRIFT_BASIS:
        return False          # it never claimed a bar, so no bar can stale it
    if current_bar is None:
        return False
    if bar is None:
        return True
    return bar < current_bar - 1e-9


def describe(stamped: str | None) -> str:
    """One line for the commander, naming the basis or its absence."""
    basis, bar = parse_stamp(stamped)
    if not basis:
        return ("measured on an UNRECORDED basis — predates basis stamping, "
                "so it cannot be shown to match how the labs measure today")
    if basis == DRIFT_BASIS:
        return ("drift against the recorded baseline — no hold-out split, no "
                "production stop, no t-statistic")
    if basis != MEASUREMENT_BASIS:
        return f"measured on a RETIRED basis ({basis}); current is {MEASUREMENT_BASIS}"
    if bar is None:
        return f"{basis}, bar unrecorded"
    return f"{basis}, judged at t>={bar:.2f}"
