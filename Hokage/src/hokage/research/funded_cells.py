"""The cells that carry capital, pre-committed, with the reasoning that chose
them.

APPROVED BY THE COMMANDER 2026-11-09.

WHY A PRE-COMMITTED FAMILY AT ALL
The audit scores every (module, asset) pair it can and the ship bar is
corrected for how many it looked at: 40 cells gives t >= 3.22. Three cells
already cleared a flat 2.0 and failed only on that correction. Testing forty
things and demanding each survive the penalty for forty is a way of proving
nothing - the correction is right, and the answer to it is to look in fewer
places rather than to weaken it.

At three cells the bar is 2.39, and the nearest answer moves from 133 sessions
to twelve.

HOW THESE THREE WERE CHOSEN, AND WHY THAT IS LEGITIMATE
Not by their t-statistic. Picking the top three by t is exactly the selection
the correction exists to punish, and a bar lowered around a choice made that
way is a bar lowered around nothing.

They were chosen on COST, which is reasoning independent of the statistics
being corrected. Measured live on 2026-11-09 against the real books, with
charges quoted from the broker's published schedule, only three underlyings
carry a measured edge larger than one full round trip:

    GOLDM    cost 0.58-0.81%   edge 1.64%
    SENSEX   cost 0.82-0.89%   edge 1.20%
    NIFTY    cost 0.81-0.85%   edge 1.06%

    BANKNIFTY  0.69-0.75% vs 0.65%     CRUDEOIL   0.56-0.58% vs 0.29%
    SILVERM    0.69-0.70% vs 0.24%     NATURALGAS 0.73-0.75% vs 0.22%

That the two methods agree is the strongest thing in the file: power_lab,
from the statistics alone, had already ranked these same three nearest the
bar. The fourth it named - TrendRider/CRUDEOIL, 257 sessions away - is a cell
whose edge is BELOW its cost, so those sessions would have proven a loss more
precisely.

WHAT THIS DOES AND DOES NOT CHANGE
Everything else is still MEASURED. An unfunded cell keeps being scored every
audit; it simply cannot move capital, and it cannot be declared confirmed at
the funded bar - a number found among forty needs the correction for forty.
That is what `bar_for` enforces.

WHEN TO CHANGE THIS FILE
Adding a cell RE-OPENS the family and raises the bar for every cell in it,
including ones already confirmed. That is not a reason never to add one; it is
a reason to add one on stated reasoning and to re-read the confirmations
afterwards. A cell dropped for cost should be noted here rather than deleted,
so the next reader can see what was considered.
"""
from __future__ import annotations

#: When this family was fixed, and by whose decision.
COMMITTED_ON = "2026-11-09"
COMMITTED_BY = "commander"

#: Why each cell is in. Keyed (module_id, asset).
FUNDED: dict[tuple[str, str], str] = {
    ("strat-sessionshift-mcx-v1", "GOLDM"):
        "edge 1.64% of premium against a 0.58-0.81% round trip - the widest "
        "margin measured, and t +2.19 on the hold-out",
    ("strat-macrobreakout-commodities-v1", "SENSEX"):
        "edge 1.20% against 0.82-0.89%, and the nearest cell to the bar at "
        "t +2.31",
    ("strat-macrobreakout-commodities-v1", "NIFTY"):
        "edge 1.06% against 0.81-0.85%, t +2.14",
}

#: Considered and left out, with the measured reason. Kept rather than
#: deleted: the next reader needs to see what was weighed, and an asset that
#: becomes cheap to trade should be reconsidered from the record, not from
#: memory.
PARKED_FOR_COST: dict[str, str] = {
    "BANKNIFTY": "edge 0.65% against a 0.69-0.75% round trip",
    "CRUDEOIL": "edge 0.29% against 0.56-0.58%",
    "SILVERM": "edge 0.24% against 0.69-0.70%",
    "NATURALGAS": "edge 0.22% against 0.73-0.75% - dearest book, thinnest edge",
}

#: Modules whose hold-out edge is negative on EVERY asset they trade. This is
#: a module-level verdict rather than a per-cell one, and no amount of further
#: tape improves it: more data drives a negative t further from the bar.
NEGATIVE_EVERYWHERE: dict[str, str] = {
    "strat-eventrider-mcx-v1":
        "negative on all four MCX assets (CRUDEOIL -0.087, NATURALGAS -0.129, "
        "GOLDM -0.067, SILVERM -0.064) - answered, not underpowered",
}


def is_funded(module_id: str, asset: str) -> bool:
    return (module_id, str(asset).upper()) in FUNDED


def funded_assets() -> set[str]:
    return {asset for _, asset in FUNDED}


def funded_modules() -> set[str]:
    return {module for module, _ in FUNDED}


def family_size() -> int:
    """How many cells the funded bar is corrected for."""
    return len(FUNDED)


def reason(module_id: str, asset: str) -> str | None:
    return FUNDED.get((module_id, str(asset).upper()))


def describe() -> str:
    """One block for an audit header or a log."""
    lines = [f"funded family ({family_size()} cells, committed "
             f"{COMMITTED_ON} by the {COMMITTED_BY}):"]
    for (module, asset), why in sorted(FUNDED.items()):
        lines.append(f"  {module}/{asset}")
        lines.append(f"      {why}")
    if PARKED_FOR_COST:
        lines.append("parked on cost, still measured:")
        for asset, why in sorted(PARKED_FOR_COST.items()):
            lines.append(f"  {asset}: {why}")
    return "\n".join(lines)
