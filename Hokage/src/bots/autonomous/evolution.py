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

FIVE SAFETY RAILS ON TIER 1
  1. TWO consecutive weeks. One bad week is noise and would churn the lineup
     every quiet fortnight.
  2. THE MODULE-WIDE READING MUST AGREE. The action is module-wide, so a cell
     measuring badly inside a module that pools POSITIVE across its league is
     a scope question, not a retirement. Pooled evidence can only ever
     CONTRADICT a retirement, never clear one on its own: a league's assets
     move together, so the pooled t is an upper bound on significance.
  3. NEVER leave an asset unowned. If archiving would remove the last live
     strategy scoped to an asset, it is downgraded to a proposal. Silently
     ceasing to trade an asset is a worse failure than trading it badly, and
     it is invisible — nothing alarms when nothing happens.
  4. NEVER archive more than one strategy per run. A correlated measurement
     error across a whole league must not empty the arena in one pass.
  5. EVERY action records the evidence that justified it, so it can be read
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

#: The bar to REMOVE a strategy, which is NOT the bar to SHIP one.
#:
#: Until 2026-10-31 retirement reused `ship_bar`. That bar is Sidak-corrected
#: for the size of the measured family, so it RISES as the arena grows: at 40
#: cells it stands at 3.22, which is above every cell Hokage has. "Below the
#: bar for two consecutive audits" therefore stopped being a decline signal
#: and became a statement of membership. On 2026-10-31 `plan()` queued 13 of
#: 14 live pairs, including the two best cells in the system
#: (SessionShift/SILVERM +3.15 then +2.65, SessionShift/GOLDM +2.71 then
#: +2.81) and all three MacroBreakout cells, every one of them IMPROVING.
#: Only MAX_ARCHIVES_PER_RUN and RAIL 2 stood between that list and an empty
#: arena, and the one cell cleared was RangeFade/NATURALGAS at -0.92 -> -0.63,
#: also improving.
#:
#: Removal needs evidence a cell is LOSING, not merely unproven. Measured at
#: zero, because a negative edge is money going the wrong way whatever the
#: family size, while "did not clear a corrected significance bar" says only
#: that the arena got bigger. Cells below the ship bar but above this one are
#: still REPORTED - they just cannot be retired, and their reason says which
#: of the two bars they failed.
RETIRE_T = 0.0

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


def _parked_assets(snapshot: dict) -> set[str]:
    """Assets Hokage deliberately does not trade.

    Until 2026-10-31 RAIL 2 could not see this - `grep -c PARKED
    evolution.py` returned 0 - and so blocked EventRider's retirement on ALL
    FOUR of its assets with "retiring EventRider outright would leave
    CRUDEOIL with no live strategy at all". CRUDEOIL has been parked since the
    seven sweeps that all failed out of sample. The guard was defending
    coverage of an asset the bot refuses to trade, which meant a module that
    is the sole nominal coverer of a parked asset could never be retired.

    The snapshot's own stamp wins, so a decision stays reproducible from the
    snapshot alone - the same reason `geometry` is stamped. Snapshots written
    before the field existed fall back to the live constant; if even that
    cannot be read, nothing is treated as parked, which is the conservative
    direction because it only ever BLOCKS a retirement.
    """
    stamped = snapshot.get("parked_assets")
    if stamped is not None:
        return {str(a).upper() for a in stamped}
    try:  # lazy: keeps this module importable on its own, as its tests require
        from bots.autonomous.autonomous_bot import AutonomousTradingBot as _Bot
        return {str(a).upper() for a in (getattr(_Bot, "PARKED_ASSETS", {}) or {})}
    except Exception:
        return set()


def _leagues(snapshot: dict) -> dict[str, tuple[str, ...]]:
    """league -> the assets pooled under it, as the audit stamped it.

    Stamped rather than imported: `src` reaching into `tools/research` is the
    wrong direction, and a retirement has to stay reproducible from the
    snapshot alone - the same reason `geometry` and `parked_assets` are
    stamped. Absent means `_pooled_stat` has to work the league out from the
    pooled table itself.
    """
    stamped = snapshot.get("leagues")
    if not isinstance(stamped, dict):
        return {}
    return {str(name): tuple(str(a).upper() for a in (assets or ()))
            for name, assets in stamped.items()}


def _pooled_stat(snapshot: dict, asset: str, module: str) -> dict | None:
    """The module's reading pooled across its whole league, or None.

    WHY TIER 1 READS THIS AT ALL (2026-10-31). A retirement is module-wide -
    RAIL 3 asks what survives if the module were retired OUTRIGHT - but the
    evidence attached to it was a single CELL, and the one autonomous slot
    went to whichever cell measured worst. That cleared EventRider justified
    by its CRUDEOIL cell: a PARKED asset, tape Hokage does not trade and never
    has. The right outcome - EventRider is negative on all four of its assets
    and 39.7% accurate pooled - reached by the weakest-relevance reason
    available. The module-wide number is the one that justifies a module-wide
    action.

    IT IS A VETO, NEVER A CLEARANCE. A league's assets move together, so
    pooled signals are correlated and the effective sample is far below the
    printed n; POOLED_CAVEAT in weekly_audit says the pooled t is an UPPER
    BOUND on significance and "never enough on its own to move capital". So
    this can retire nothing by itself - the per-cell two-week rule must clear
    first, and the pooled reading can only CONTRADICT it. Correlation inflates
    the MAGNITUDE of a pooled t, not its SIGN, and this rail asks only about
    the sign.

    None when the league cannot be identified or the module never reached the
    audit's reporting floor pooled. None BLOCKS, so a module too rare to
    measure across its league is never retired unattended - the same answer
    the per-cell rule already gives a module too rare to measure on one asset.
    """
    pooled = snapshot.get("pooled") or {}
    if not pooled:
        return None
    leagues = _leagues(snapshot)
    if leagues:
        names = [lg for lg, assets in leagues.items()
                 if str(asset).upper() in assets]
    else:
        # Snapshots written before `leagues` existed still carry `pooled`.
        # Module ids are league-specific in practice (`...-mcx-v1`), but that
        # is a naming convention, not a guarantee: a module found under two
        # leagues has an ambiguous league, and ambiguous must block.
        names = [lg for lg, mods in pooled.items() if module in (mods or {})]
    if len(names) != 1:
        return None
    stat = (pooled.get(names[0]) or {}).get(module)
    if not isinstance(stat, dict) or "t" not in stat:
        return None
    return {**stat, "league": names[0]}


def _same_geometry(current: dict, previous: dict | None) -> bool:
    """True when two snapshots measured the same way.

    2026-08-28: the weekly audit moved from a 105-day POOLED window on raw
    forward edge with no stop, to a train/hold split measured inside the
    production 1.25 ATR stop. That is a strictly better basis, and comparing one
    against the other would be nonsense — a module's number can move a full
    point purely from including the stop, which is precisely what happened to
    crude (+2.06 raw, +0.82 with geometry).

    A retirement is justified by a TREND, and there is no trend across a change
    of instrument. So a basis change RESETS the consecutive-week evidence rather
    than continuing it: nothing can be retired until two audits agree on the new
    footing. Snapshots written before the field existed carry no geometry, which
    correctly never matches the current one.
    """
    if previous is None:
        return False
    return bool(current.get("geometry")) and \
        current.get("geometry") == previous.get("geometry")


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
    comparable = (_far_enough_apart(current, previous)
                  and _same_geometry(current, previous))
    live_now = _live_pairs(current)
    live_before = _live_pairs(previous) if comparable else {}
    archives: list[Decision] = []

    # WHICH CELL TAKES THE ONE AUTONOMOUS SLOT. The key used to be the cell's
    # own `t` ascending, so the slot went to the single worst CELL. The action
    # is module-wide, so the module the MODULE-WIDE reading condemns goes
    # first; and within one module the named evidence should be tape Hokage
    # actually trades, so a parked asset's cell sorts last. On 2026-10-31 the
    # old key cleared EventRider on CRUDEOIL - parked, never traded - while
    # its NATURALGAS cell waited in the queue behind it.
    parked = _parked_assets(current)

    def _worst_first(kv: tuple[tuple[str, str], dict]) -> tuple:
        (module, asset), stat = kv
        pooled = _pooled_stat(current, asset, module)
        return (
            pooled["t"] if pooled else float("inf"),
            1 if str(asset).upper() in parked else 0,
            stat["t"],
        )

    for (module, asset), stat in sorted(live_now.items(), key=_worst_first):
        if stat["t"] >= bar:
            continue
        before = live_before.get((module, asset))
        if before is None or before["t"] >= bar:
            continue  # not two consecutive weeks
        info = lineup.get(module) or {}
        name = info.get("name", module)
        pooled_now = _pooled_stat(current, asset, module)
        pooled_before = _pooled_stat(previous, asset, module) if previous else None
        is_parked = str(asset).upper() in parked
        evidence = {
            "t_now": round(stat["t"], 2),
            "t_previous": round(before["t"], 2),
            "n_now": stat["n"],
            "ship_bar": bar,
            "retire_bar": RETIRE_T,
            "measured_on": current.get("date"),
            "compared_to": previous.get("date") if previous else None,
            # The module-wide picture, recorded whether or not it agreed, so
            # the decision can be read back against what justified it.
            "league": (pooled_now or {}).get("league"),
            "t_pooled_now": round(pooled_now["t"], 2) if pooled_now else None,
            "t_pooled_previous": (round(pooled_before["t"], 2)
                                  if pooled_before else None),
            "n_pooled": (pooled_now or {}).get("n"),
            "accuracy_pooled": (round(pooled_now["accuracy"], 1)
                                if pooled_now and "accuracy" in pooled_now
                                else None),
            "asset_is_parked": is_parked,
        }
        reason = (f"measured below the t>={bar:g} bar for two consecutive "
                  f"audits ({before['t']:+.2f} then {stat['t']:+.2f})")
        if pooled_now and pooled_before:
            reason += (f"; {name} measures {pooled_before['t']:+.2f} then "
                       f"{pooled_now['t']:+.2f} pooled across the "
                       f"{pooled_now['league']}, n={pooled_now['n']}")
            if "accuracy" in pooled_now:
                reason += f" at {pooled_now['accuracy']:.1f}% accuracy"
        if is_parked:
            # Said, not hidden. The cell is only the trigger; on a parked
            # asset the module-wide reading is the entire substance, and
            # "EventRider on CRUDEOIL" must not read as evidence from tape
            # that was ever traded.
            reason += (f". {asset} is PARKED, so this cell is measured tape "
                       f"Hokage does not trade - the module-wide reading is "
                       f"the substance here")
        decision = Decision(
            action="archive",
            tier=TIER_AUTONOMOUS,
            strategy_id=info.get("strategy_id", module),
            strategy_name=name,
            asset=asset,
            reason=reason,
            evidence=evidence,
        )

        # RAIL 1: unconfirmed is not the same as harmful. See RETIRE_T.
        if stat["t"] >= RETIRE_T or before["t"] >= RETIRE_T:
            decision.tier = TIER_PROPOSE
            decision.blocked_reason = (
                f"below the t>={bar:g} SHIP bar but not measurably harmful: "
                f"{before['t']:+.2f} then {stat['t']:+.2f}, neither below "
                f"{RETIRE_T:+.2f}. The ship bar rises with the size of the "
                f"measured family, so on a family this size it sits above "
                f"every cell; removing a strategy needs evidence it is "
                f"LOSING, not merely unproven."
            )

        # RAIL 2: the module-wide reading must AGREE with the cell.
        #
        # A veto, never a clearance - see _pooled_stat. One bad asset inside a
        # module that pools positive is a SCOPE question, and rescoping is
        # Tier 2. First reason stands, as below.
        if decision.blocked_reason is None:
            if pooled_now is None or pooled_before is None:
                decision.tier = TIER_PROPOSE
                decision.blocked_reason = (
                    f"no pooled reading for {name} in both snapshots, so the "
                    f"module-wide picture cannot corroborate this cell. The "
                    f"action is module-wide, and retiring on one asset's cell "
                    f"alone is what cleared EventRider on a PARKED asset on "
                    f"2026-10-31."
                )
            elif pooled_now["t"] >= RETIRE_T or pooled_before["t"] >= RETIRE_T:
                decision.tier = TIER_PROPOSE
                decision.blocked_reason = (
                    f"{name} measures badly on {asset} but not module-wide: "
                    f"{pooled_before['t']:+.2f} then {pooled_now['t']:+.2f} "
                    f"pooled across the {pooled_now['league']} "
                    f"(n={pooled_now['n']}), neither below {RETIRE_T:+.2f}. "
                    f"One bad asset inside a module that pools positive is a "
                    f"SCOPE question, and rescoping is Tier 2."
                )

        # RAIL 3: never leave an asset with no live strategy.
        #
        # The CHECK is module-wide on purpose — `_assets_still_covered` asks
        # what survives if this module were retired outright, not merely
        # descoped from one asset. That is the conservative reading and it
        # stays.
        #
        # The MESSAGE has to say so. It used to read "archiving this would
        # leave <assets> with no live strategy", attached to a decision about
        # one asset, so the 2026-10-09 audit told the commander that archiving
        # MacroBreakout **on NIFTY** would orphan **BANKNIFTY** — a
        # non-sequitur on the face of it, and the sentence he is meant to
        # decide on. Name the module, and the sentence is true.
        remaining = _assets_still_covered(current, module)
        orphaned = [a for a in (info.get("scope") or [])
                    if remaining.get(a, 0) == 0 and str(a).upper() not in parked]
        # An earlier rail wins if it already spoke: for a cell that is not
        # harmful at all, "retiring this would orphan BANKNIFTY" is true but
        # implies coverage is the ONLY obstacle, when in fact it should not be
        # retired on its own numbers either. First reason stands.
        if orphaned and decision.blocked_reason is None:
            decision.tier = TIER_PROPOSE
            decision.blocked_reason = (
                f"retiring {decision.strategy_name} outright would leave "
                f"{', '.join(sorted(orphaned))} with no live strategy at all, and "
                f"nothing else currently covers {'them' if len(orphaned) > 1 else 'it'}. "
                f"Ceasing to trade an asset silently is a worse failure than trading "
                f"it badly, so this needs a decision."
            )
        if orphaned:
            decision.tier = TIER_PROPOSE

        archives.append(decision)

    # RAIL 4: at most one autonomous archive per run; the rest are proposals.
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
            # 2026-11-10: an applier does exist and is reachable, so the old
            # wording ("no applier exists") was itself the thing it warns
            # against - a report describing a state that had moved. What is
            # still true is that NOTHING HERE APPLIES IT: this job runs at
            # 23:45 while Hokage is up, and he rewrites the portfolio book
            # from memory, so a write made underneath him vanishes at his next
            # save with nothing logged. It takes one deliberate command.
            lines.append(
                "CLEARED TO RETIRE (Tier 1 — reduces risk only; NOT APPLIED "
                "here, so the lineup is unchanged. Apply with "
                "`hokage improve <proposal_id>`, from `hokage proposals`):"
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
