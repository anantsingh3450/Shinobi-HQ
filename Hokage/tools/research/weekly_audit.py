"""Measure every entry module against every asset, weekly, and report what MOVED.

WHY THIS EXISTS
Hokage's ImprovementBot has written 430 trade autopsies and applied exactly
zero improvements — it is wired to a strategy id that exists in neither
portfolio, and writes to fields production does not read. The real measurement
machinery is the labs in this directory, and until now every one of them had to
be fired by hand. That made Claude the evolution loop, not Hokage.

This is the tool that removes the hand. It runs the same measurement
entry_module_lab performs, over the whole universe, writes a dated snapshot to
the brain, and DIFFS against the previous one.

WHAT IT REPORTS, AND WHY IT REPORTS DELTAS
A weekly dump of forty t-statistics is noise nobody reads. What matters is what
CHANGED: a module whose edge is decaying, or an archived one that has come back
to life. Those are the two events that should change the lineup, and both are
invisible in a snapshot taken alone.

  DEMOTION CANDIDATE  a LIVE module whose t is below the ship bar for TWO
                      consecutive weeks. One bad week is noise; two is a trend
                      worth acting on. Only ever removes risk.
  REVIVAL CANDIDATE   an ARCHIVED module whose t has climbed back above the
                      bar. Archiving is not meant to be permanent — regimes
                      change and a module can become right again.

Neither is applied automatically. Phase 1 REPORTS; Phase 2 is where anything
acts on it, and even then only demotion is autonomous.

CAVEAT THAT TRAVELS WITH EVERY NUMBER: these are in-sample over the measurement
window, they score the UNDERLYING rather than option P&L, and a t-stat computed
weekly on an overlapping window is correlated with last week's. Treat a single
week's move as weak evidence and the two-week rule as the real signal.

USAGE
    python tools/research/weekly_audit.py                 # measure + diff
    python tools/research/weekly_audit.py --telegram      # ...and alert
    python tools/research/weekly_audit.py --dry-run       # no snapshot written
"""
from __future__ import annotations

import json
import math
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from signal_lab import Ctx, load_bars, _MCX_FUTURES  # noqa: E402
from entry_module_lab import build_context  # noqa: E402

from bots.strategy.components.entries import ENTRY_MODULES  # noqa: E402
from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES  # noqa: E402

#: The horizon Hokage's trades actually live at. One number, deliberately:
#: reporting three horizons triples the noise without tripling the information.
HORIZON = 4

#: Below this a measured edge is indistinguishable from luck. Same bar every
#: other lab in this directory ships against.
SHIP_BAR = 2.0

#: Minimum signals before a t-statistic is quoted at all.
MIN_N = 30

#: How much history each run measures over. Long enough for a decent n, short
#: enough that a regime change shows up rather than being averaged away.
LOOKBACK_DAYS = 105

UNIVERSE = ["NIFTY", "BANKNIFTY", "SENSEX", "CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM"]

SNAPSHOT_DIR = ROOT / "hokage_brain" / "research" / "snapshots"
PORTFOLIO_DIR = ROOT / "hokage_brain" / "portfolio"


# ------------------------------------------------------------------ measuring
def _stats(edges: list[float], hits: int) -> dict[str, float] | None:
    n = len(edges)
    if n < MIN_N:
        return None
    mean = sum(edges) / n
    var = sum((e - mean) ** 2 for e in edges) / (n - 1)
    t = mean / (math.sqrt(var / n) or 1e-9)
    return {"n": n, "accuracy": hits / n * 100.0, "edge_atr": mean, "t": t}


def measure(symbol: str, bars: list[dict], modules: dict) -> dict[str, dict]:
    """Every module's edge on this asset. Mirrors entry_module_lab exactly."""
    acc = {name: {"edges": [], "hits": 0} for name in modules}
    for i in range(42, len(bars) - HORIZON):
        window = bars[: i + 1]
        day = window[-1]["date"].date()
        session = [b for b in window if b["date"].date() == day]
        if len(session) < 6 or bars[i + HORIZON]["date"].date() != day:
            continue
        ctx = Ctx(window, session)
        if not ctx.atr:
            continue
        mkt = build_context(symbol, window, ctx, session)
        forward = bars[i + HORIZON]["close"] - ctx.price
        for name, module in modules.items():
            try:
                sig = module.evaluate(mkt)
            except Exception:
                continue
            if not getattr(sig, "should_enter", False):
                continue
            call = 1 if sig.direction == "long" else -1
            acc[name]["edges"].append((forward * call) / ctx.atr)
            if (forward * call) > 0:
                acc[name]["hits"] += 1
    out = {}
    for name, rec in acc.items():
        stat = _stats(rec["edges"], rec["hits"])
        if stat:
            out[name] = stat
    return out


# ------------------------------------------------------------------ portfolio
def live_lineup() -> dict[str, dict]:
    """module_id -> {status, scope, strategy_id, name} from the real brain."""
    from bots.strategy.components.entries import ENTRY_MODULES as _E
    from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES as _M

    module_id_of = {}
    for key, module in {**_E, **_M}.items():
        module_id_of[key] = getattr(module, "module_id", key)

    lineup: dict[str, dict] = {}
    for name in ("strategy_portfolio.json", "mcx_strategy_portfolio.json"):
        path = PORTFOLIO_DIR / name
        if not path.exists():
            continue
        book = json.loads(path.read_text(encoding="utf-8-sig"))
        for sid, strat in (book.get("strategies") or {}).items():
            mid = module_id_of.get(sid)
            if not mid:
                continue
            lineup[mid] = {
                "strategy_id": sid,
                "name": strat.get("name", sid),
                "status": strat.get("status", "UNKNOWN"),
                "scope": [a.upper() for a in (strat.get("supported_assets") or [])],
            }
    return lineup


# ------------------------------------------------------------------ snapshots
def previous_snapshots(limit: int = 2, exclude: str | None = None) -> list[dict]:
    if not SNAPSHOT_DIR.exists():
        return []
    files = sorted(SNAPSHOT_DIR.glob("*.json"), reverse=True)
    out = []
    for path in files:
        if exclude and path.stem == exclude:
            continue
        try:
            out.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
        if len(out) >= limit:
            break
    return out


def _get(snapshot: dict, module: str, symbol: str) -> dict | None:
    return (snapshot.get("measurements") or {}).get(symbol, {}).get(module)


# ------------------------------------------------------------------- reporting
def build_report(current: dict, history: list[dict]) -> dict:
    """Deltas, demotion candidates, revival candidates."""
    prev = history[0] if history else None
    older = history[1] if len(history) > 1 else None
    lineup = current["lineup"]

    moves, demotions, revivals, new_rows = [], [], [], []

    for symbol, per_module in current["measurements"].items():
        for module, stat in per_module.items():
            info = lineup.get(module, {})
            status = info.get("status", "UNKNOWN")
            scoped = symbol in info.get("scope", [])
            is_live = status not in ("ARCHIVED", "UNKNOWN") and scoped

            before = _get(prev, module, symbol) if prev else None
            if before is None:
                new_rows.append({"module": module, "symbol": symbol, **stat,
                                 "status": status, "scoped": scoped})
            else:
                delta = stat["t"] - before["t"]
                if abs(delta) >= 0.75:  # smaller moves are week-to-week noise
                    moves.append({
                        "module": module, "symbol": symbol, "status": status,
                        "scoped": scoped, "t_before": before["t"], "t_now": stat["t"],
                        "delta": delta, "n": stat["n"],
                    })

            if is_live and stat["t"] < SHIP_BAR:
                two_weeks = before is not None and before["t"] < SHIP_BAR
                if two_weeks:
                    demotions.append({
                        "module": module, "symbol": symbol,
                        "name": info.get("name", module),
                        "t_now": stat["t"], "t_prev": before["t"], "n": stat["n"],
                    })
            if status == "ARCHIVED" and stat["t"] >= SHIP_BAR:
                revivals.append({
                    "module": module, "symbol": symbol,
                    "name": info.get("name", module),
                    "t": stat["t"], "n": stat["n"],
                })

    moves.sort(key=lambda m: abs(m["delta"]), reverse=True)
    demotions.sort(key=lambda d: d["t_now"])
    revivals.sort(key=lambda r: -r["t"])
    return {
        "compared_to": prev["date"] if prev else None,
        "had_two_priors": older is not None,
        "moves": moves, "demotions": demotions, "revivals": revivals,
        "new": new_rows,
    }


def render(current: dict, report: dict) -> str:
    lines = [f"HOKAGE WEEKLY AUDIT — {current['date']}",
             f"horizon {HORIZON * 15}min · ship bar t>={SHIP_BAR} · min n={MIN_N}"]
    if report["compared_to"]:
        lines.append(f"compared to {report['compared_to']}")
    else:
        lines.append("FIRST RUN — no prior snapshot, so nothing to diff yet.")
    lines.append("")

    if report["demotions"]:
        lines.append("DEMOTION CANDIDATES (live, below the bar TWO weeks running):")
        for d in report["demotions"]:
            lines.append(f"  {d['name']} on {d['symbol']}: t={d['t_now']:+.2f} "
                         f"(was {d['t_prev']:+.2f}), n={d['n']}")
        lines.append("")
    if report["revivals"]:
        lines.append("REVIVAL CANDIDATES (archived, back above the bar):")
        for r in report["revivals"]:
            lines.append(f"  {r['name']} on {r['symbol']}: t={r['t']:+.2f}, n={r['n']}")
        lines.append("")
    if report["moves"]:
        lines.append("NOTABLE MOVES (|delta t| >= 0.75):")
        for m in report["moves"][:12]:
            tag = "LIVE" if m["scoped"] and m["status"] != "ARCHIVED" else m["status"].lower()
            lines.append(f"  {m['module']} / {m['symbol']} [{tag}]: "
                         f"{m['t_before']:+.2f} -> {m['t_now']:+.2f} "
                         f"({m['delta']:+.2f})")
        lines.append("")
    if not (report["demotions"] or report["revivals"] or report["moves"]):
        if report["compared_to"]:
            lines.append("Nothing moved enough to report. The lineup measures as it did last week.")
        else:
            lines.append(f"Baseline recorded: {len(report['new'])} (module, asset) pairs measured. "
                         f"Deltas begin next run.")
        lines.append("")

    live = [(s, m, st) for s, per in current["measurements"].items()
            for m, st in per.items()
            if s in current["lineup"].get(m, {}).get("scope", [])
            and current["lineup"].get(m, {}).get("status") not in ("ARCHIVED", "UNKNOWN")]
    if live:
        lines.append("LIVE LINEUP AS MEASURED:")
        for symbol, module, stat in sorted(live, key=lambda x: -x[2]["t"]):
            flag = "" if stat["t"] >= SHIP_BAR else "   << below bar"
            lines.append(f"  {current['lineup'][module]['name']:14s} {symbol:11s} "
                         f"n={stat['n']:>4d} t={stat['t']:+.2f}{flag}")
    return "\n".join(lines)


# ------------------------------------------------------------------------ main
def main() -> int:
    args = set(sys.argv[1:])
    dry_run = "--dry-run" in args
    telegram = "--telegram" in args

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=LOOKBACK_DAYS)
    window = (start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S"))

    lineup = live_lineup()
    measurements: dict[str, dict] = {}
    failed: list[str] = []

    for symbol in UNIVERSE:
        modules = MCX_ENTRY_MODULES if symbol in _MCX_FUTURES else ENTRY_MODULES
        named = {getattr(m, "module_id", k): m for k, m in modules.items()}
        try:
            bars = load_bars(symbol, *window)
        except Exception as exc:
            print(f"  {symbol}: could not load bars ({exc})")
            failed.append(symbol)
            continue
        measurements[symbol] = measure(symbol, bars, named)

    if not measurements:
        print("No asset could be measured — is the broker session live? "
              "Refusing to write an empty snapshot.")
        return 1

    today = date.today().isoformat()
    current = {
        "date": today,
        "generated_at": end.isoformat(),
        "horizon_bars": HORIZON,
        "ship_bar": SHIP_BAR,
        "lookback_days": LOOKBACK_DAYS,
        "failed_symbols": failed,
        "lineup": lineup,
        "measurements": measurements,
    }

    report = build_report(current, previous_snapshots(2, exclude=today))
    text = render(current, report)
    print("\n" + text + "\n")

    if not dry_run:
        SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
        (SNAPSHOT_DIR / f"{today}.json").write_text(
            json.dumps(current, indent=2), encoding="utf-8"
        )
        print(f"snapshot written: hokage_brain/research/snapshots/{today}.json")

    if telegram:
        worth_sending = bool(report["demotions"] or report["revivals"] or report["moves"])
        if not worth_sending:
            print("telegram: nothing changed, staying quiet.")
        else:
            try:
                from integrations.notifications.telegram_bot import TelegramBotUplink

                bot = TelegramBotUplink()
                if bot.enabled:
                    bot.send_message(text)
                    print("telegram: sent.")
                else:
                    print("telegram: uplink disabled.")
            except Exception as exc:
                print(f"telegram: failed ({exc})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
