"""End-of-day trade report in language a non-trader can understand.

Deterministic on purpose: it translates the day's real trades into plain
English without an LLM, so a number is never hallucinated. Every rupee figure
comes straight from the trade record.
"""
from __future__ import annotations

import re
from typing import Any

_INDEX_NICE = {
    "BANKNIFTY": "Bank Nifty",
    "NIFTY": "Nifty",
    "SENSEX": "Sensex",
    "BANKEX": "Bankex",
    "FINNIFTY": "Fin Nifty",
    "MIDCPNIFTY": "Midcap Nifty",
}


def humanize_instrument(symbol: str) -> str:
    """Turn an option contract symbol into a plain-English description.

    NIFTY2672124150CE -> "a Nifty CALL option (a bet the index would go UP)".
    """
    s = (symbol or "").upper()
    index = None
    for known in ("BANKNIFTY", "MIDCPNIFTY", "FINNIFTY", "BANKEX", "SENSEX", "NIFTY"):
        if s.startswith(known):
            index = known
            break
    if index is None:
        m = re.match(r"^([A-Z]+)", s)
        index = m.group(1) if m else s
    nice = _INDEX_NICE.get(index, index.title())
    if s.endswith("CE"):
        return f"a {nice} CALL option (a bet that {nice} would go UP)"
    if s.endswith("PE"):
        return f"a {nice} PUT option (a bet that {nice} would go DOWN)"
    return nice


def explain_exit_reason(reason: str | None) -> str:
    """Map an internal exit reason to a plain-English clause."""
    r = (reason or "").lower()
    if not r:
        return "it was closed"
    if "square-off" in r or "square_off" in r or "eod" in r:
        return "it was held until the market closed and squared off automatically"
    if "target_hit" in r or "target" in r:
        return "it reached its profit target, so the gain was booked"
    if "profit_lock" in r or "trail_lock" in r:
        return "the profit was locked in before it could slip away"
    if "thesis stop" in r or "thesis_stop" in r:
        return "the index moved the wrong way, so the loss was cut early to protect the money"
    if "backstop" in r or "stop-loss" in r or "stop_loss" in r:
        return "the option lost too much value, so it was cut to stop the bleeding"
    if "instant-exit" in r or "hard sell" in r or "manual" in r:
        return "you chose to close it yourself"
    if "kill" in r:
        return "the safety kill-switch closed it"
    return f"it was closed ({reason})"


def _fmt_rupees(v: float) -> str:
    return f"₹{v:,.0f}" if abs(v) >= 100 else f"₹{v:,.2f}"


def build_plain_report(
    closed_trades: list[dict[str, Any]],
    open_trades: list[dict[str, Any]],
    date_label: str,
) -> str:
    """Compose the full plain-language report.

    Each dict in ``closed_trades`` should carry: symbol, entry_price,
    exit_price, quantity, pnl, exit_reason, closed_at_label (optional).
    ``open_trades``: symbol, entry_price, current_price, quantity,
    unrealized_pnl (optional).
    """
    lines: list[str] = []
    lines.append(f"📊 Hokage — how today went ({date_label})")
    lines.append("")

    if not closed_trades and not open_trades:
        lines.append("No trades today — Hokage watched the market but didn't find a setup worth the risk. A quiet day is a fine day; it only trades when the odds look right.")
        return "\n".join(lines)

    # ---- closed trades -------------------------------------------------
    total_pnl = 0.0
    winners = 0
    if closed_trades:
        lines.append(f"Trades finished today: {len(closed_trades)}")
        lines.append("")
        for i, t in enumerate(closed_trades, 1):
            entry = float(t.get("entry_price") or 0.0)
            exit_ = float(t.get("exit_price") or 0.0)
            qty = float(t.get("quantity") or 0.0)
            pnl = float(t.get("pnl") or 0.0)
            total_pnl += pnl
            if pnl > 0:
                winners += 1
            what = humanize_instrument(str(t.get("symbol", "")))
            why = explain_exit_reason(t.get("exit_reason"))
            outcome = (
                f"made {_fmt_rupees(pnl)}" if pnl > 0
                else (f"lost {_fmt_rupees(abs(pnl))}" if pnl < 0 else "ended flat (no gain, no loss)")
            )
            when = t.get("closed_at_label")
            when_str = f" around {when}" if when else ""
            lines.append(
                f"{i}. Hokage bought {what}. It paid ₹{entry:,.2f} per unit and sold at "
                f"₹{exit_:,.2f}{when_str}. Because {why}, this trade {outcome}."
            )
        lines.append("")
        net_word = "made" if total_pnl > 0 else ("lost" if total_pnl < 0 else "broke even")
        if total_pnl == 0:
            lines.append(f"Bottom line on finished trades: {winners} of {len(closed_trades)} made money, and it all {net_word} — no net change.")
        else:
            lines.append(
                f"Bottom line on finished trades: {winners} of {len(closed_trades)} made money, "
                f"and together they {net_word} {_fmt_rupees(abs(total_pnl))} today."
            )

    # ---- still-open trades --------------------------------------------
    if open_trades:
        lines.append("")
        lines.append(f"Still open (not finished yet): {len(open_trades)}")
        for t in open_trades:
            what = humanize_instrument(str(t.get("symbol", "")))
            entry = float(t.get("entry_price") or 0.0)
            cur = t.get("current_price")
            unreal = t.get("unrealized_pnl")
            tail = ""
            if isinstance(cur, (int, float)) and cur:
                tail = f" It's now worth ₹{float(cur):,.2f} per unit"
                if isinstance(unreal, (int, float)):
                    if unreal > 0:
                        tail += f" — up {_fmt_rupees(unreal)} so far."
                    elif unreal < 0:
                        tail += f" — down {_fmt_rupees(abs(unreal))} so far."
                    else:
                        tail += " — flat so far."
                else:
                    tail += "."
            lines.append(f"• Hokage is holding {what}, bought at ₹{entry:,.2f}.{tail}")

    lines.append("")
    lines.append("Remember: this is paper money on real prices — practice, not real cash. 🧪")
    return "\n".join(lines)
