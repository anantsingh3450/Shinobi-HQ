"""The facts Hokage is allowed to answer from. Read-only, by construction.

WHY THIS EXISTS
Hokage's chat was a 16-branch keyword cascade with a bare LLM as the final
fallthrough — `generate_response(query, system_instruction="")`, no data
attached. So it was canned when a keyword matched and an ungrounded language
model guessing when it did not, which is where the phantom narratives in the
logs came from. Worse, the system prompt hardcoded system facts that have since
gone stale ("four competing strategies... 50,000-rupee budget... NIFTY, BANK
NIFTY and SENSEX"), so the model was being TOLD wrong things before it started.

This module is the correction. Every function here returns real state read from
the brain or the ledger, each stamped with when it was read. The chat layer is
then told, as a hard rule, that it may not state a number that did not come
from one of these.

TWO INVARIANTS, both enforced by tests:
  1. NOTHING HERE WRITES. No INSERT, no UPDATE, no file write, no order. The
     chat surface must not be able to move money — the existing chat-trade path
     already skips every risk check, which is why it is pinned to paper.
  2. NOTHING HERE RAISES. A tool that throws would either crash the reply or,
     worse, tempt the model to fill the gap itself. Every failure returns
     {"error": ...} so the model can say "I could not read that" honestly.

Tools read the brain and the ledger directly rather than going through the
running bot, so they work when the bot is stopped, are testable without one,
and can serve the dashboard as well as Telegram.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from hokage.memory.resolver import brain_root

ROOT = Path(__file__).resolve().parents[3]

#: NOT `ROOT / "hokage_brain"`. That ignored HOKAGE_BRAIN_ROOT, so moving
#: the brain left this module reading a different one from the rest of Hokage.
BRAIN = brain_root()
DB_PATH = BRAIN / "hokage.db"
PORTFOLIO_DIR = BRAIN / "portfolio"
SNAPSHOT_DIR = BRAIN / "research" / "snapshots"

_ACCOUNT_LABELS = {"paper": "Index Dojo", "paper_mcx": "MCX Arena"}


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _connect() -> sqlite3.Connection:
    """Read-only sqlite handle. `mode=ro` makes invariant 1 structural rather
    than a promise — a stray write raises instead of succeeding."""
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _safe(fn: Callable[[], Any]) -> Any:
    try:
        return fn()
    except Exception as exc:
        return {"error": f"could not read this: {exc}", "as_of": _now()}


def _load_portfolios() -> dict[str, dict]:
    books: dict[str, dict] = {}
    for name, league in (("strategy_portfolio.json", "Index Dojo"),
                         ("mcx_strategy_portfolio.json", "MCX Arena")):
        path = PORTFOLIO_DIR / name
        if path.exists():
            books[league] = json.loads(path.read_text(encoding="utf-8-sig"))
    return books


# --------------------------------------------------------------------- tools
def get_open_positions() -> dict:
    """List every position Hokage currently holds open, with entry price and
    when it was opened. Use for "what are we in right now", "anything open"."""
    def _run():
        with _connect() as conn:
            rows = conn.execute(
                "select market, account_id, direction, quantity, entry_price,"
                " current_price, unrealized_pnl, opened_at"
                " from positions where status <> 'CLOSED' order by opened_at"
            ).fetchall()
        from shared.instrument import parse
        return {
            "as_of": _now(),
            "count": len(rows),
            "positions": [{
                "instrument": parse(r["market"]).headline(),
                "tradingsymbol": r["market"],
                "league": _ACCOUNT_LABELS.get(r["account_id"], r["account_id"]),
                "entry_price": r["entry_price"],
                "current_price": r["current_price"],
                "unrealized_pnl": r["unrealized_pnl"],
                "opened_at": r["opened_at"],
            } for r in rows],
        }
    return _safe(_run)


def get_account_summary() -> dict:
    """Cash and realised P&L for both paper leagues, plus which capital regime
    each sits in. Use for "how much money do we have", "what's the balance"."""
    def _run():
        from bots.autonomous import capital_regime as cr
        with _connect() as conn:
            # `portfolio.realized_pnl` IS GROSS and the charges live one
            # table over, on the positions. `cash` has been net since
            # 2026-11-09, so quoting the gross figure beside it described an
            # account that does not exist. Both are reported, and the
            # uncharged count says how many closed rows have no charge to
            # subtract - for those net equals gross because nothing was
            # measured, not because nothing was paid.
            # A brain older than schema 10 has no `charges` column at all.
            # Then charges_paid is 0.00 and EVERY closed position counts as
            # uncharged, which is the true description of such a brain - not
            # a fallback that hides the difference.
            charged_brain = any(
                r[1] == "charges" for r in
                conn.execute("pragma table_info(positions)").fetchall()
            )
            charges_sql = (
                " coalesce((select sum(charges) from positions x"
                "           where x.account_id = p.account_id"
                "             and x.charges is not null), 0.0) as charges_paid,"
                " (select count(*) from positions x"
                "  where x.account_id = p.account_id and x.status = 'CLOSED'"
                "    and x.charges is null) as uncharged_closed"
                if charged_brain else
                " 0.0 as charges_paid,"
                " (select count(*) from positions x"
                "  where x.account_id = p.account_id and x.status = 'CLOSED')"
                " as uncharged_closed"
            )
            rows = conn.execute(
                "select p.account_id, p.initial_balance, p.cash, p.realized_pnl,"
                + charges_sql + " from portfolio p"
            ).fetchall()
        out = []
        for r in rows:
            regime = cr.profile_for(r["cash"])
            gross = float(r["realized_pnl"] or 0.0)
            charges = float(r["charges_paid"] or 0.0)
            out.append({
                "league": _ACCOUNT_LABELS.get(r["account_id"], r["account_id"]),
                "cash": r["cash"],
                "started_with": r["initial_balance"],
                "realized_pnl": round(gross - charges, 2),
                "gross_realized_pnl": round(gross, 2),
                "charges_paid": round(charges, 2),
                "uncharged_closed_positions": int(r["uncharged_closed"] or 0),
                "capital_regime": regime.name,
                "regime_means": regime.summary,
            })
        return {"as_of": _now(), "accounts": out,
                "note": "Paper money on real market prices. No real cash is at risk."}
    return _safe(_run)


def get_trades(days: int = 1) -> dict:
    """Closed trades over the last N days with P&L and why each was exited.
    days=1 is today. Use for "how did we do today", "what did you trade"."""
    def _run():
        cutoff = (datetime.now() - timedelta(days=max(1, int(days)) - 1)).strftime("%Y-%m-%d")
        with _connect() as conn:
            # `charges` arrived with schema 10. On an older brain the column
            # is absent and NULL is the honest value: unknown, not zero.
            charges_col = (
                " charges,"
                if any(r[1] == "charges" for r in
                       conn.execute("pragma table_info(positions)").fetchall())
                else " NULL as charges,"
            )
            rows = conn.execute(
                "select market, account_id, direction, entry_price, current_price,"
                " realized_pnl," + charges_col + " opened_at, closed_at from positions"
                " where status = 'CLOSED' and substr(opened_at,1,10) >= ?"
                " order by opened_at", (cutoff,)
            ).fetchall()
        from shared.instrument import parse
        trades = [{
            "instrument": parse(r["market"]).headline(),
            "league": _ACCOUNT_LABELS.get(r["account_id"], r["account_id"]),
            "entry_price": r["entry_price"],
            "exit_price": r["current_price"],
            "pnl": r["realized_pnl"],
            "charges": r["charges"],
            "net_pnl": (None if r["charges"] is None
                        else round((r["realized_pnl"] or 0.0) - r["charges"], 2)),
            "opened_at": r["opened_at"],
            "closed_at": r["closed_at"],
        } for r in rows]
        wins = [t for t in trades if (t["pnl"] or 0) > 0]
        # `net_pnl` USED TO BE THE GROSS SUM UNDER A NET NAME, and this is
        # what answers "how did we do today" in chat and in the EOD report.
        # Charges are 3.2x the lifetime gross profit, so the name was not a
        # detail. Gross, charges and net are now three separate keys, and
        # `uncharged_trades` counts the rows that have no charge to subtract
        # rather than letting them pass as free.
        gross_total = round(sum(t["pnl"] or 0 for t in trades), 2)
        charged = [t for t in trades if t["charges"] is not None]
        charges_total = round(sum(t["charges"] for t in charged), 2)
        return {
            "as_of": _now(), "since": cutoff, "count": len(trades),
            "wins": len(wins), "losses": len(trades) - len(wins),
            "gross_pnl": gross_total,
            "charges": charges_total,
            "net_pnl": round(gross_total - charges_total, 2),
            "uncharged_trades": len(trades) - len(charged),
            "trades": trades,
            "caveat": ("A handful of trades says nothing about edge. Do not draw "
                       "conclusions about strategy quality from fewer than ~100."),
        }
    return _safe(_run)


def get_strategy_lineup() -> dict:
    """Every strategy: live or archived, which assets it may trade, and how
    much capital it has. Use for "who is trading", "what strategies do we run"."""
    def _run():
        out = []
        for league, book in _load_portfolios().items():
            for sid, s in (book.get("strategies") or {}).items():
                cap = s.get("capital") or {}
                # NET of the broker, like get_capital_report: the chest can
                # only deploy what the account actually holds.
                chest = (float(cap.get("starting", 0) or 0)
                         + float(cap.get("realized_pnl", 0) or 0)
                         - float(cap.get("charges_paid", 0) or 0))
                out.append({
                    "league": league,
                    "name": s.get("name", sid),
                    "strategy_id": sid,
                    "status": s.get("status"),
                    "trades_only": s.get("supported_assets") or [],
                    "chest": round(chest, 2),
                })
        return {"as_of": _now(), "strategies": out}
    return _safe(_run)


def get_measured_edge() -> dict:
    """The latest weekly self-audit: each strategy's measured edge (t-statistic)
    per asset, and which are below the t>=2 bar. Use for "is X still working",
    "what does the audit say", "which strategy is best"."""
    def _run():
        if not SNAPSHOT_DIR.exists():
            return {"as_of": _now(), "error": "no audit has been run yet"}
        files = sorted(SNAPSHOT_DIR.glob("*.json"), reverse=True)
        if not files:
            return {"as_of": _now(), "error": "no audit has been run yet"}
        snap = json.loads(files[0].read_text(encoding="utf-8"))
        lineup = snap.get("lineup", {})
        rows = []
        for symbol, per_module in (snap.get("measurements") or {}).items():
            for module, stat in per_module.items():
                info = lineup.get(module, {})
                scoped = symbol in info.get("scope", [])
                if info.get("status") in (None, "ARCHIVED") or not scoped:
                    continue
                rows.append({
                    "strategy": info.get("name", module), "asset": symbol,
                    "signals_measured": stat["n"],
                    "t_stat": round(stat["t"], 2),
                    "edge_atr": round(stat["edge_atr"], 3),
                    "clears_bar": stat["t"] >= snap.get("ship_bar", 2.0),
                })
        rows.sort(key=lambda r: -r["t_stat"])
        return {
            "as_of": _now(), "measured_on": snap.get("date"),
            "ship_bar": snap.get("ship_bar", 2.0), "live_pairs": rows,
            "caveat": ("In-sample over ~3 months, and it measures the UNDERLYING's "
                       "move, not option profit after fees and decay."),
        }
    return _safe(_run)


def get_capital_reality(account_size: float = 0.0) -> dict:
    """What a given account size can actually afford to trade. Pass 0 to use
    the live paper balances. Use for "can I start with 20000", "what can we
    afford", "why can't you trade gold"."""
    def _run():
        from bots.autonomous import capital_regime as cr
        from bots.execution.options_router import MAX_PREMIUM_CHEST_FRACTION
        costs: dict[str, float] = {}
        if SNAPSHOT_DIR.exists():
            pass  # lot costs are live-only; see note below
        sizes = []
        if account_size and account_size > 0:
            sizes = [float(account_size)]
        else:
            with _connect() as conn:
                sizes = [r["cash"] for r in conn.execute("select cash from portfolio")]
        return {
            "as_of": _now(),
            "premium_cap_pct": MAX_PREMIUM_CHEST_FRACTION * 100,
            "account_sizes_checked": sizes,
            "regimes": [{"size": s, "regime": cr.regime_for(s)} for s in sizes],
            "measured_lot_costs_2026_08_15": {
                "NATURALGAS": 7688, "NIFTY": 8141, "SENSEX": 9401,
                "CRUDEOIL": 10950, "BANKNIFTY": 16050,
                "GOLDM": 22755, "SILVERM": 23615,
            },
            "minimum_account_for_cheapest_lot": 23295,
            "key_fact": ("At 20,000 NOTHING in the universe is affordable — the "
                         "cheapest lot (NATURALGAS, 7,688) needs a 23,295 account "
                         "to sit inside the 33% cap. Prices are from 2026-08-15; "
                         "run tools/research/seed_capital_check.py for live ones."),
        }
    return _safe(_run)


def get_system_health() -> dict:
    """Whether Hokage is running, can see market data, and when each subsystem
    last reported in. Use for "are you alive", "is the feed working"."""
    def _run():
        with _connect() as conn:
            rows = conn.execute(
                "select subsystem, timestamp, status from watchdog_heartbeats"
            ).fetchall()
        now = datetime.now(timezone.utc)
        beats = []
        for r in rows:
            age = None
            try:
                ts = datetime.fromisoformat(str(r["timestamp"]))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age = round((now - ts).total_seconds())
            except Exception:
                pass
            beats.append({"subsystem": r["subsystem"], "age_seconds": age,
                          "status": r["status"]})
        feed = next((b for b in beats if b["subsystem"] == "market_data"), None)
        return {
            "as_of": _now(), "subsystems": beats,
            "market_data_age_seconds": feed["age_seconds"] if feed else None,
            "how_to_read": ("market_data only publishes after a real quote comes "
                            "back, so a fresh age proves Hokage can actually SEE "
                            "the market, not merely that a token exists."),
        }
    return _safe(_run)


def get_todays_decisions(symbol: str = "") -> dict:
    """Why Hokage did NOT trade — the recorded no-trade decisions and their
    reasons. Use for "why no trades today", "why did you skip crude"."""
    def _run():
        with _connect() as conn:
            if symbol:
                rows = conn.execute(
                    "select asset, timestamp, decision, reasons from no_trade_decisions"
                    " where upper(asset) = upper(?) order by timestamp desc limit 20",
                    (symbol,)).fetchall()
            else:
                rows = conn.execute(
                    "select asset, timestamp, decision, reasons from no_trade_decisions"
                    " order by timestamp desc limit 30").fetchall()
        return {"as_of": _now(), "count": len(rows),
                "decisions": [dict(r) for r in rows]}
    return _safe(_run)


#: Every tool the chat layer may call. Read-only, all of them.
READ_ONLY_TOOLS: list[Callable[..., dict]] = [
    get_open_positions,
    get_account_summary,
    get_trades,
    get_strategy_lineup,
    get_measured_edge,
    get_capital_reality,
    get_system_health,
    get_todays_decisions,
]


def current_state_digest() -> str:
    """A compact snapshot injected into EVERY chat prompt.

    Pre-loading the common facts means the model is grounded before it decides
    whether to call anything, so the most frequent questions ("what's open",
    "how much have we got") cannot be answered from imagination even if it
    skips the tools entirely.
    """
    parts: list[str] = [f"Live state read at {_now()}:"]
    acct = get_account_summary()
    if "accounts" in acct:
        for a in acct["accounts"]:
            parts.append(
                f"- {a['league']}: cash {a['cash']:,.2f}, realised "
                f"{a['realized_pnl']:+,.2f} net of charges "
                f"(gross {a['gross_realized_pnl']:+,.2f}, charges "
                f"{a['charges_paid']:,.2f}), regime {a['capital_regime']}"
            )
    pos = get_open_positions()
    if "count" in pos:
        if pos["count"] == 0:
            parts.append("- No positions are open.")
        else:
            for p in pos["positions"]:
                parts.append(f"- OPEN: {p['instrument']} entered at {p['entry_price']}")
    today = get_trades(1)
    if "count" in today:
        parts.append(
            f"- Today: {today['count']} closed trades, {today['wins']} wins, "
            f"net {today['net_pnl']:+,.2f} (gross {today['gross_pnl']:+,.2f}, "
            f"charges {today['charges']:,.2f})"
        )
    return "\n".join(parts)
