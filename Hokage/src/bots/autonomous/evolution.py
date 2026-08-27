"""Phase 2: let Hokage retire his own failures, and nothing more.

WHAT CAME BEFORE
The ImprovementBot has written 430 trade autopsies and applied ZERO
improvements, in three independent ways: it fired
`detect_patterns("strat-autotrend-equities-v1")` against an id that exists in
neither portfolio, it wrote to `risk_management.stop_loss_atr_multiplier` which
nothing in production reads, and `detect_patterns` ignored its own strategy_id
argument and blended every strategy's autopsies together. So Claude was the
evolution loop, not Hokage.

THE TIERS, AND WHY THEY ARE NOT NEGOTIABLE

  TIER 1  AUTONOMOUS.  Archive a live strategy that has measured below the
          ship bar for TWO CONSECUTIVE weekly audits. This only ever REDUCES
          risk — an archived strategy cannot open a position. It is the only
          tier that acts without asking.

  TIER 2  PROPOSE.     Scope and window changes. Reversible and bounded, but
          they can move risk sideways rather than down, so they are written as
          proposals for the commander.

  TIER 3  ASK.         Anything that widens a stop, raises a cap, or increases
          size. Never autonomous, at any confidence. This is the line that
          keeps a bad measurement from becoming a bigger position.

The asymmetry is the whole design. A loop allowed to reduce risk on its own can
be wrong and cost opportunity; a loop allowed to raise risk on its own can be
wrong and cost the account.

FOUR SAFETY RAILS ON TIER 1
  1. TWO consecutive weeks. One bad week is noise and would churn the lineup
     every quiet fortnight.
  2. NEVER leave an asset unowned. If archiving would remove the last live
     strategy scoped to an asset, it is downgraded to a proposal. Silently
     ceasing to trade an asset is a worse failure than trading it badly, and
     it is invisible — nothing alarms when nothing happens.
  3. NEVER archive more than one strategy per run. A correlated measurement
     error across a whole league must not empty the arena in one pass.
  4. EVERY action records the evidence that justified it, so it can be read
     back and reversed.

Nothing here writes to disk. `plan()` returns decisions; the caller applies
them. That keeps the policy testable without a brain.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("Hokage.Evolution")

TIER_AUTONOMOUS = "autonomous"
TIER_PROPOSE = "propose"

#: Consecutive weekly audits below the bar before a live strategy is retired.
CONSECUTIVE_WEEKS_TO_ARCHIVE = 2

#: Most strategies Tier 1 may archive in a single run.
MAX_ARCHIVES_PER_RUN = 1

#: Minimum days between two snapshots for them to count as SEPARATE weeks.
#:
#: Caught on a 2026-08-17 dry run: the policy compared that day's re-measurement
#: against the 2026-08-15 baseline and treated two readings TWO DAYS apart as
#: "two consecutive weeks below the bar". They are not — they are largely the
#: same tape measured twice, so a single bad week would masquerade as a trend
#: and retire a strategy on one week of evidence. The audit is scheduled weekly,
#: but an ad-hoc run must not be able to manufacture a trend.
MIN_DAYS_BETWEEN_SNAPSHOTS = 5

#: MASTER SWITCH FOR TIER 1, deliberately OFF for the first cycle.
#:
#: The policy is built and tested, but the 2026-08-21 audit will be only the
#: SECOND snapshot ever taken — the first moment at which anything COULD be
#: autonomous. Letting a loop's very first opportunity to act also be its first
#: unobserved action is how you find out your policy was wrong by reading the
#: aftermath.
#:
#: So the first run REPORTS what it would have done and changes nothing. Flip
#: this to True once the commander has seen one cycle and agrees the decisions
#: were the ones he would have made. Same staged pattern that let
#: `supported_assets`, the per-strategy stop table and the capital regimes land
#: safely: ship the mechanism, watch it, then arm it.
#: ARMED 2026-08-24, after exactly the observed cycle this was staged for.
#:
#: The 2026-08-21 audit was the second snapshot ever and the first separated
#: from its predecessor by enough days to count (08-15 -> 08-21, six days,
#: clearing MIN_DAYS_BETWEEN_SNAPSHOTS). It found three candidates below the
#: bar for two consecutive audits, retired the worst ONE, and escalated the
#: other two rather than emptying the league in a single pass:
#:
#:   WOULD RETIRE   MeanReversion / NIFTY      +1.46 then +1.35
#:   NEEDS A CALL   MacroBreakout / BANKNIFTY  +1.35 then +1.45
#:   NEEDS A CALL   MeanReversion / SENSEX     +1.86 then +1.58
#:
#: Every rail held under real data rather than a simulated second week, and
#: the verdict was the one the commander and I would have reached by hand.
#: That was the whole condition for arming.
#:
#: WHAT THIS DOES AND DOES NOT PERMIT. Tier 1 archives, and only archives. An
#: archived strategy cannot open a position, so the worst case of a wrong
#: autonomous decision is forgone opportunity, never a larger loss. Reviving,
#: rescoping and anything that widens a stop or raises a cap stay Tier 2/3 and
#: still require the commander - bringing a strategy BACK adds risk, and that
#: asymmetry is the entire design.
AUTONOMOUS_ENABLED = True


@dataclass
class Decision:
    """One thing Hokage wants to do, and why."""

    action: str                    # archive | revive | rescope
    tier: str                      # autonomous | propose
    strategy_id: str
    strategy_name: str
    asset: str
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)
    blocked_reason: str | None = None   # set when a rail downgraded it

    @property
    def is_autonomous(self) -> bool:
        """Whether the POLICY considers this safe to do unattended.

        Independent of AUTONOMOUS_ENABLED on purpose: the policy's verdict is
        worth reporting even while the master switch is off, which is exactly
        what the first observed cycle is for.
        """
        return self.tier == TIER_AUTONOMOUS and self.blocked_reason is None

    @property
    def will_be_applied(self) -> bool:
        """Whether this actually happens on this run."""
        return self.is_autonomous and AUTONOMOUS_ENABLED


def _live_pairs(snapshot: dict) -> dict[tuple[str, str], dict]:
    """(module_id, asset) -> stat, for pairs that are LIVE and IN SCOPE."""
    lineup = snapshot.get("lineup") or {}
    out: dict[tuple[str, str], dict] = {}
    for asset, per_module in (snapshot.get("measurements") or {}).items():
        for module, stat in per_module.items():
            info = lineup.get(module) or {}
            if info.get("status") in (None, "ARCHIVED"):
                continue
            if asset not in (info.get("scope") or []):
                continue
            out[(module, asset)] = stat
    return out


def _assets_still_covered(
    snapshot: dict, archiving_module: str
) -> dict[str, int]:
    """How many LIVE strategies would remain scoped to each asset if
    `archiving_module` were retired."""
    lineup = snapshot.get("lineup") or {}
    counts: dict[str, int] = {}
    for module, info in lineup.items():
        if info.get("status") in (None, "ARCHIVED") or module == archiving_module:
            continue
        for asset in info.get("scope") or []:
            counts[asset] = counts.get(asset, 0) + 1
    return counts


def _far_enough_apart(current: dict, previous: dict | None) -> bool:
    """True when two snapshots are separated enough to be distinct evidence.

    Unparseable dates return False: without knowing the gap we cannot claim a
    trend, and refusing to act is the safe direction.
    """
    if previous is None:
        return False
    from datetime import date as _date

    try:
        a = _date.fromisoformat(str(current.get("date")))
        b = _date.fromisoformat(str(previous.get("date")))
    except (TypeError, ValueError):
        return False
    return abs((a - b).days) >= MIN_DAYS_BETWEEN_SNAPSHOTS


def plan(snapshots: list[dict]) -> list[Decision]:
    """Decide what to do, newest snapshot first. Never applies anything.

    `snapshots[0]` is this week, `snapshots[1]` last week. With fewer than two
    snapshots nothing is autonomous — there is no trend to act on yet.
    """
    if not snapshots:
        return []
    current = snapshots[0]
    previous = snapshots[1] if len(snapshots) > 1 else None
    bar = float(current.get("ship_bar", 2.0))
    lineup = current.get("lineup") or {}
    decisions: list[Decision] = []

    # ---------------------------------------------------------- Tier 1: retire
    # Two readings taken days apart are the same tape measured twice, not two
    # weeks of evidence. Without a real gap there is no trend to act on.
    comparable = _far_enough_apart(current, previous)
    live_now = _live_pairs(current)
    live_before = _live_pairs(previous) if comparable else {}
    archives: list[Decision] = []

    for (module, asset), stat in sorted(live_now.items(), key=lambda kv: kv[1]["t"]):
        if stat["t"] >= bar:
            continue
        before = live_before.get((module, asset))
        if before is None or before["t"] >= bar:
            continue  # not two consecutive weeks
        info = lineup.get(module) or {}
        evidence = {
            "t_now": round(stat["t"], 2),
            "t_previous": round(before["t"], 2),
            "n_now": stat["n"],
            "ship_bar": bar,
            "measured_on": current.get("date"),
            "compared_to": previous.get("date") if previous else None,
        }
        decision = Decision(
            action="archive",
            tier=TIER_AUTONOMOUS,
            strategy_id=info.get("strategy_id", module),
            strategy_name=info.get("name", module),
            asset=asset,
            reason=(f"measured below the t>={bar:g} bar for two consecutive "
                    f"audits ({before['t']:+.2f} then {stat['t']:+.2f})"),
            evidence=evidence,
        )

        # RAIL 2: never leave an asset with no live strategy.
        remaining = _assets_still_covered(current, module)
        orphaned = [a for a in (info.get("scope") or []) if remaining.get(a, 0) == 0]
        if orphaned:
            decision.tier = TIER_PROPOSE
            decision.blocked_reason = (
                f"archiving this would leave {', '.join(sorted(orphaned))} with no "
                f"live strategy at all. Ceasing to trade an asset silently is a "
                f"worse failure than trading it badly, so this needs a decision."
            )
        archives.append(decision)

    # RAIL 3: at most one autonomous archive per run; the rest are proposals.
    autonomous_used = 0
    for decision in archives:
        if decision.tier == TIER_AUTONOMOUS:
            if autonomous_used >= MAX_ARCHIVES_PER_RUN:
                decision.tier = TIER_PROPOSE
                decision.blocked_reason = (
                    f"only {MAX_ARCHIVES_PER_RUN} strategy may be retired per run; "
                    f"a correlated measurement error must not empty the arena in "
                    f"one pass."
                )
            else:
                autonomous_used += 1
        decisions.append(decision)

    # ---------------------------------------------------------- revivals
    # An archived module back above the bar is worth reconsidering, but bringing
    # a strategy BACK adds risk, so it is never autonomous.
    for asset, per_module in (current.get("measurements") or {}).items():
        for module, stat in per_module.items():
            info = lineup.get(module) or {}
            if info.get("status") != "ARCHIVED" or stat["t"] < bar:
                continue
            decisions.append(Decision(
                action="revive",
                tier=TIER_PROPOSE,
                strategy_id=info.get("strategy_id", module),
                strategy_name=info.get("name", module),
                asset=asset,
                reason=(f"archived, but now measures t={stat['t']:+.2f} on {asset} "
                        f"over n={stat['n']}"),
                evidence={"t_now": round(stat["t"], 2), "n_now": stat["n"],
                          "measured_on": current.get("date")},
                blocked_reason=("reviving a strategy ADDS risk, so it is never "
                                "autonomous — commander decides"),
            ))

    return decisions


def summarise(decisions: list[Decision]) -> str:
    """Plain text for the log and Telegram. Empty when nothing to say."""
    if not decisions:
        return ""
    lines: list[str] = []
    acting = [d for d in decisions if d.is_autonomous]
    asking = [d for d in decisions if not d.is_autonomous]

    if acting:
        # "RETIRING" is a claim that something HAPPENED, and until an applier
        # exists it is false. Found 2026-08-28, hours before the Friday audit
        # that would have printed it: `plan()` returns Decisions and
        # `weekly_audit` puts `summarise()` into the report — and NOTHING in the
        # codebase writes an archive to a portfolio. AUTONOMOUS_ENABLED = True
        # only suppressed the "not yet armed" caveat, so the report would have
        # announced "RETIRING: MeanReversion on NIFTY" while the lineup stayed
        # exactly as it was.
        #
        # A system that reports an action it did not take is worse than one that
        # takes no action, because the commander stops checking. Same fault as
        # the exit that announced the floor it had COMPUTED rather than the one
        # that FIRED. The wording now describes the state that actually exists;
        # it changes back the day an applier lands.
        if AUTONOMOUS_ENABLED:
            lines.append(
                "CLEARED TO RETIRE (Tier 1 — reduces risk only; NOT YET APPLIED, "
                "no applier exists, so the lineup is unchanged):"
            )
        else:
            lines.append("WOULD RETIRE (autonomy not yet armed — nothing changed):")
        for d in acting:
            lines.append(f"  {d.strategy_name} on {d.asset} — {d.reason}")
    if asking:
        lines.append("")
        lines.append("NEEDS YOUR DECISION:")
        for d in asking:
            lines.append(f"  [{d.action}] {d.strategy_name} on {d.asset} — {d.reason}")
            if d.blocked_reason:
                lines.append(f"      why not automatic: {d.blocked_reason}")
    return "\n".join(lines)
