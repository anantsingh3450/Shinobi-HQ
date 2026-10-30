"""Give EIAReaction the registration it never got.

Run once, on 2026-10-30 08:12. Kept because it is the record of what was
changed and why, and because the next hand-deployed strategy will need the
same reasoning applied to it.

WHAT WAS WRONG. EIAReaction was added to the MCX portfolio on 2026-10-21 by
editing the portfolio JSON by hand instead of calling
`StrategyPortfolio.register_strategy`, so it arrived carrying 7 of the 18
fields every other competitor has. One of the eleven it lacked was
`strategy_id` - and `_is_counter_trend_strategy` reads exactly that to decide
whether a module may skip the trend-join bias gate. `.get()` returned None,
the check evaluated False, and the exemption shipped in a68de90 on 2026-10-23
could never fire. On 2026-10-29 the module won the 20:30 NATURALGAS auction
and was refused for being "1.77 ATR from VWAP, too extended to join the
trend" - a fade module told it was too extended to join a trend it was
betting against. See 5fe17f2 (the boot audit that names thin records),
8937972 (ten subscript sites that would have crashed instead of trading) and
6494f67 (the gate reading the resolved id).

NOTHING HERE IS INVENTED.

  strategy_id        the key it is already filed under
  created_at         the timestamp of its OWN history[0] registration event,
                     2026-10-21 - not today. Today's date would restart the
                     retirement clock on a strategy deployed nine days ago.
  the six metrics    exactly what register_strategy() writes for a strategy
                     that has not traded - the defaults it was denied
  pnl_history        empty, and MEASURED empty: `positions` holds 406 rows,
  regime_stats       zero attributed to this strategy, and every unattributed
                     row falls between 2026-07-15 and 2026-08-17, months
                     before it was deployed (attribution has been complete
                     since 2026-08-18)
  context_memory     the peer shape, with a note from the module's docstring

IT REFUSES TO RUN TWICE. A second run would overwrite measured performance
with those same priors and empty pnl_history - the script would become the
thing it was written to repair. It also refuses while Hokage is serving,
because a running process holds the portfolio in memory and writes it back
over anything changed on disk.

Writes atomically (temp, re-parse, os.replace), because the lesson of
54540db is that json.dump truncates the handle BEFORE it raises.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BRAIN = Path(os.environ.get("HOKAGE_BRAIN_ROOT", r"C:/Hokage/hokage_brain"))
PORTFOLIO = BRAIN / "portfolio" / "mcx_strategy_portfolio.json"
DASHBOARD = "http://127.0.0.1:5000"
SID = "strat-eiareaction-mcx-v1"

NOTE = ("Fades the weekly EIA natural gas storage print in the hour after "
        "the release (Thursday 20:00 IST), never into it. Roughly 30 minutes "
        "of eligible window a week, so it accumulates evidence slowly.")

#: register_strategy()'s values for a strategy that has not traded yet.
PRIORS: dict[str, object] = {
    "domain_confidence": {"DEFAULT": 50.0},
    "expectancy": {"DEFAULT": 0.0},
    "win_rate": {"DEFAULT": 50.0},
    "drawdown": {"DEFAULT": 0.0},
    "sharpe_ratio": {"DEFAULT": 1.0},
    "trade_count": {"DEFAULT": 0},
    "pnl_history": {},
    "regime_stats": {},
}

REPAIR_NOTE = (
    "Registration fields restored. Deployed by hand on 2026-10-21 without "
    "going through register_strategy, so it carried 7 of 18 fields; the "
    "missing strategy_id made _is_counter_trend_strategy return False and "
    "held the a68de90 bias-gate exemption shut from 2026-10-23 to "
    "2026-10-30. Metrics seeded with register_strategy's defaults for an "
    "untraded strategy - zero rows in `positions` confirm it has never "
    "traded."
)


def hokage_is_serving(url: str | None = None, timeout: float = 3.0) -> bool:
    """True if something answers the dashboard. Any doubt counts as SERVING:
    refusing a repair is recoverable, writing under a running process is the
    silent revert that undid the CRUDEOIL park on 2026-08-26.

    `url` resolves at CALL time. As `url: str = DASHBOARD` it froze the
    module global at import, so overriding DASHBOARD changed nothing and the
    guard could not be exercised - the same fault liveness_probe.py carries a
    comment about, where a default-argument path meant the reader and the
    deleter could target different files.
    """
    url = url or DASHBOARD
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 500
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def already_repaired(rec: dict) -> str | None:
    """The reason to refuse, or None.

    Two separate refusals, because they fail differently. A record that
    already carries its id needs nothing. A record that has TRADED must never
    be overwritten with priors, even if some field is somehow still absent -
    that would destroy measured history, which no repair is worth.
    """
    counts = rec.get("trade_count")
    if isinstance(counts, dict):
        traded = sum(int(v) for v in counts.values() if isinstance(v, (int, float)))
        if traded > 0:
            return (f"it has traded {traded} time(s) - seeding priors now "
                    f"would erase measured performance")
    if rec.get("strategy_id"):
        return "it already carries strategy_id; the repair is done"
    return None


def main() -> int:
    if not PORTFOLIO.exists():
        print(f"REFUSING: no portfolio at {PORTFOLIO}")
        return 1
    if hokage_is_serving():
        print("REFUSING: Hokage is serving on " + DASHBOARD + ".")
        print("  He holds the portfolio in memory and writes it back over any")
        print("  change on disk. Run Stop-Hokage.ps1 first, then this, then")
        print("  Start-Hokage.ps1.")
        return 1

    raw = json.loads(PORTFOLIO.read_text(encoding="utf-8-sig"))
    strategies = raw["strategies"]
    rec = strategies.get(SID)
    if not isinstance(rec, dict):
        print(f"REFUSING: {SID} is not in the portfolio")
        return 1

    refusal = already_repaired(rec)
    if refusal:
        print(f"NOTHING TO DO: {refusal}.")
        return 0

    peer_fields = {
        f for sid, other in strategies.items()
        if sid != SID and isinstance(other, dict) and other.get("status") != "ARCHIVED"
        for f in other
    }
    before = len(rec)

    # From the record's own registration event, never datetime.now().
    born = rec["history"][0]["timestamp"]

    rec.update(PRIORS)
    rec["strategy_id"] = SID
    rec["created_at"] = born
    rec["context_memory"] = {
        "notes": NOTE,
        "regime_performance": {},
        "volatility_performance": {},
    }
    rec.setdefault("history", []).append({
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": REPAIR_NOTE,
    })

    still_missing = sorted(peer_fields - set(rec))
    print(f"fields before : {before}")
    print(f"fields after  : {len(rec)}")
    print(f"created_at    : {born}  (from its own history[0])")
    print(f"peers carry   : {len(peer_fields)} distinct fields")
    print(f"still missing : {still_missing or 'nothing'}")

    backup = PORTFOLIO.with_name(
        f"{PORTFOLIO.stem}.pre_eia_repair_"
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}.bak.json")
    shutil.copy2(PORTFOLIO, backup)
    print(f"backup        : {backup}")

    raw["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = PORTFOLIO.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(raw, indent=2, ensure_ascii=False, default=str),
                   encoding="utf-8")
    json.loads(tmp.read_text(encoding="utf-8"))   # prove it parses BEFORE the swap
    os.replace(tmp, PORTFOLIO)
    print("written       : atomically, and re-parsed before the swap")
    return 0


if __name__ == "__main__":
    sys.exit(main())
