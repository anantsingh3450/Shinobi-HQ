"""Make the portfolio books match the funded family. Shows first, applies only
when asked, and refuses while Hokage is running.

APPROVED 2026-11-09: fund three cells and nothing else. See
`hokage.research.funded_cells` for which three and why.

WHY THIS IS A TOOL AND NOT AN EDIT
A RUNNING HOKAGE OVERWRITES THE PORTFOLIO JSON FROM MEMORY. He holds the book
in process and writes it back, so a hand-edit made while he is up disappears
at the next save with nothing logged. That has happened before. So this refuses
to apply unless the process is gone, and says so rather than writing into a
race.

It also takes a copy of both books before touching them, because the brain
backup task is STILL not registered - which makes this the only copy that will
exist if the rewrite is wrong.

WHAT IT CHANGES
  * a funded module's scope is narrowed to its funded assets
  * a funded module is set ACTIVE (MacroBreakout sits in SHADOW_MODE today,
    so the decision to fund it would otherwise change nothing)
  * every other live module is set PARKED, not ARCHIVED - they keep being
    measured every audit, and parking is reversible by editing this file's
    output back. A module negative on every asset it trades is ARCHIVED
    instead, because more tape cannot rescue a negative edge.

WHAT IT DOES NOT TOUCH
Chests, capital, risk constants, open positions. Those are a separate decision
and a separate tool; this one only says who is allowed to compete.

USAGE
    python tools/ops/fund_cells.py              # show the plan, change nothing
    python tools/ops/fund_cells.py --apply      # Hokage must be stopped
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from hokage.memory.resolver import brain_root  # noqa: E402
from hokage.research import funded_cells  # noqa: E402

BOOKS = ("strategy_portfolio.json", "mcx_strategy_portfolio.json")

def hokage_is_running() -> bool:
    """True if any process is running start.py. Unknown counts as RUNNING.

    The dangerous direction is writing into a race, so a check that cannot
    answer must block the write rather than allow it.
    """
    try:
        import subprocess

        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -like '*start.py*' }).ProcessId"],
            capture_output=True, text=True, timeout=30)
        return bool(out.stdout.strip())
    except Exception:
        return True


def book_paths() -> list[Path]:
    found = []
    for name in BOOKS:
        found.extend(sorted(brain_root().rglob(name)))
    return found


#: Measured reasons for archiving, not generic ones. A strategy removed
#: without the number that removed it is a decision nobody can audit later.
ARCHIVE_REASONS = {
    "strat-eventrider-mcx-v1":
        "negative hold-out edge on all four MCX assets (CRUDEOIL -0.087, "
        "NATURALGAS -0.129, GOLDM -0.067, SILVERM -0.064); scoped to GOLDM, "
        "which is funded, so it would compete for it",
    "strat-meanreversion-sideways-v1":
        "SENSEX +0.161 ATR t+0.76 needs ~2,328 more sessions to reach the "
        "bar; BANKNIFTY -0.032 is negative; scoped to NIFTY and SENSEX, both "
        "funded, so it would compete for them",
}

ACTIVE = "ACTIVE"
ARCHIVED = "ARCHIVED"


def parked_assets() -> dict[str, str]:
    """The standing decisions not to trade, from the one place they live."""
    from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

    return dict(Bot.PARKED_ASSETS)


def plan_for(book: Path) -> list[dict]:
    """What would change in this book.

    THE ENFORCEMENT IS `PARKED_ASSETS`, NOT A STATUS. The scan loop skips a
    parked asset entirely, and it checks only for ARCHIVED among strategy
    statuses - so inventing a PARKED status would have changed nothing, and
    worse: any status outside (ACTIVE, PRODUCTION, ARCHIVED) is fed to
    `evaluate_pipeline_transition`, which can promote it back to ACTIVE on its
    own. A funding decision that the system can quietly undo is not a
    decision.

    So with the four cost-failing assets parked, most unfunded strategies are
    already inert - every asset they are scoped to is parked. Only a strategy
    that would still reach a FUNDED asset needs removing, and it is removed
    with the measurement that removed it.

    NEVER WRITES AN EMPTY SCOPE. `_strategy_covers` fails OPEN on an empty
    supported_assets - a missing restriction means no restriction - so
    narrowing a scope to nothing would silently let a strategy trade
    everything.
    """
    parked = parked_assets()
    data = json.loads(book.read_text(encoding="utf-8-sig"))
    rows = []
    for sid, strat in (data.get("strategies") or {}).items():
        status = strat.get("status")
        assets = [a.upper() for a in (strat.get("supported_assets") or [])]
        funded_here = sorted(a for a in assets if funded_cells.is_funded(sid, a))
        reaches_funded = [a for a in assets
                          if a not in parked and a in funded_cells.funded_assets()]

        if funded_here:
            rows.append({
                "book": book.name, "id": sid, "action": "FUND",
                "status_from": status, "status_to": ACTIVE,
                "assets_from": assets, "assets_to": funded_here,
                "why": funded_cells.reason(sid, funded_here[0]) or "",
            })
        elif status == ARCHIVED:
            rows.append({"book": book.name, "id": sid, "action": "leave",
                         "status_from": status, "status_to": status,
                         "assets_from": assets, "assets_to": assets,
                         "why": "already archived"})
        elif reaches_funded:
            rows.append({
                "book": book.name, "id": sid, "action": "ARCHIVE",
                "status_from": status, "status_to": ARCHIVED,
                "assets_from": assets, "assets_to": assets,
                "why": ARCHIVE_REASONS.get(
                    sid, f"not funded, and would compete for "
                         f"{', '.join(sorted(reaches_funded))}"),
            })
        else:
            rows.append({
                "book": book.name, "id": sid, "action": "leave",
                "status_from": status, "status_to": status,
                "assets_from": assets, "assets_to": assets,
                "why": f"already inert - every asset it trades is parked "
                       f"({', '.join(a for a in assets if a in parked)})",
            })

    for row in rows:
        assert row["assets_to"], (
            f"{row['id']}: refusing to write an empty scope - it fails OPEN")
    return rows


def apply_to(book: Path, rows: list[dict]) -> int:
    data = json.loads(book.read_text(encoding="utf-8-sig"))
    changed = 0
    for row in rows:
        if row["action"] == "leave":
            continue
        strat = (data.get("strategies") or {}).get(row["id"])
        if strat is None:
            continue
        strat["status"] = row["status_to"]
        strat["supported_assets"] = row["assets_to"]
        # Stamped, so the next reader knows who narrowed it and on what.
        strat["funding_decision"] = {
            "on": funded_cells.COMMITTED_ON,
            "by": funded_cells.COMMITTED_BY,
            "action": row["action"],
            "why": row["why"],
        }
        changed += 1
    book.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return changed


def main() -> int:
    apply = "--apply" in sys.argv[1:]

    print("=" * 84)
    print("  FUND THE COMMITTED CELLS" + ("  [APPLYING]" if apply else
                                          "  [dry run - nothing is written]"))
    print("=" * 84)
    print(funded_cells.describe())
    print()

    books = book_paths()
    if not books:
        print("  No portfolio book found under the brain root.")
        return 1

    all_rows: list[tuple[Path, list[dict]]] = []
    for book in books:
        rows = plan_for(book)
        all_rows.append((book, rows))
        print(f"  {book.name}")
        for row in rows:
            if row["action"] == "leave":
                print(f"      {row['id']:<36} leave ({row['why']})")
                continue
            print(f"      {row['id']:<36} {row['action']}")
            print(f"          status  {row['status_from']} -> {row['status_to']}")
            if row["assets_from"] != row["assets_to"]:
                print(f"          assets  {row['assets_from']} -> "
                      f"{row['assets_to']}")
            print(f"          why     {row['why'][:90]}")
        print()

    acting = [r for _, rows in all_rows for r in rows if r["action"] != "leave"]
    print(f"  {len(acting)} strategy record(s) would change.")

    if not apply:
        print()
        print("  Nothing written. Re-run with --apply, with Hokage STOPPED:")
        print("    .\\Stop-Hokage.ps1 -Reason \"funding decision\"")
        print("    python tools/ops/fund_cells.py --apply")
        print("    .\\Restart-Hokage.ps1")
        return 0

    if hokage_is_running():
        print()
        print("  REFUSING TO WRITE: Hokage is running (or could not be")
        print("  checked). He holds the portfolio book in memory and writes it")
        print("  back, so this edit would vanish at his next save with nothing")
        print("  logged. Stop him first.")
        return 1

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    for book, rows in all_rows:
        backup = book.with_suffix(f".json.before-funding-{stamp}")
        shutil.copy2(book, backup)
        print(f"  copied {book.name} -> {backup.name}")
        n = apply_to(book, rows)
        print(f"  rewrote {book.name}: {n} record(s)")

    print()
    print("  Done. Start him and check the boot audit:")
    print("    .\\Restart-Hokage.ps1")
    print("  Expect 'Strategy chest audit' and 'Asset coverage audit' to pass,")
    print("  and the parked assets to report no live strategy - which is now")
    print("  correct rather than a fault.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
