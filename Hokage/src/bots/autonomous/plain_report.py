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
    exit_price, quantity, pnl, exit_reason, closed_at_label (optional),
    charges and net_pnl (optional).
    ``open_trades``: symbol, entry_price, current_price, quantity,
    unrealized_pnl (optional).

    WHAT REACHED THE ACCOUNT, NOT THE PRICE DIFFERENCE. `pnl` is gross. If
    `charges` is present the sentence says what the broker took and what was
    left, because on the lifetime record those charges are 3.2x the whole
    gross profit - a report that says "made ₹500" about a trade that put
    ₹448 in the account is telling him the wrong thing in plain English.
    A missing `charges` means the trade was booked before charge accounting;
    the report then says nothing about costs rather than implying there were
    none.
    """
    lines: list[str] = []
    lines.append(f"📊 Hokage — how today went ({date_label})")
    lines.append("")

    if not closed_trades and not open_trades:
        lines.append("No trades today — Hokage watched the market but didn't find a setup worth the risk. A quiet day is a fine day; it only trades when the odds look right.")
        return "\n".join(lines)

    # ---- closed trades -------------------------------------------------
    total_pnl = 0.0
    total_charges = 0.0
    uncharged = 0
    winners = 0
    if closed_trades:
        lines.append(f"Trades finished today: {len(closed_trades)}")
        lines.append("")
        for i, t in enumerate(closed_trades, 1):
            entry = float(t.get("entry_price") or 0.0)
            exit_ = float(t.get("exit_price") or 0.0)
            qty = float(t.get("quantity") or 0.0)
            gross = float(t.get("pnl") or 0.0)
            charges = t.get("charges")
            charges = None if charges is None else float(charges)
            pnl = gross if charges is None else round(gross - charges, 2)
            total_pnl += pnl
            total_charges += charges or 0.0
            if charges is None:
                uncharged += 1
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
            cost_str = ""
            if charges:
                # Spelled out, because this is the line that turns a winner
                # into a loser often enough to matter.
                if gross > 0:
                    cost_str = (f" The price move was {_fmt_rupees(gross)} in our "
                                f"favour and the broker took {_fmt_rupees(charges)} "
                                f"of it.")
                else:
                    # The broker does not take a share of a loss, it adds to
                    # one. "took X of it" reads as if the loss were smaller.
                    cost_str = (f" The price move cost {_fmt_rupees(abs(gross))} "
                                f"and the broker added {_fmt_rupees(charges)} "
                                f"on top.")
            lines.append(
                f"{i}. Hokage bought {what}. It paid ₹{entry:,.2f} per unit and sold at "
                f"₹{exit_:,.2f}{when_str}. Because {why}, this trade {outcome}.{cost_str}"
            )
        lines.append("")
        net_word = "made" if total_pnl > 0 else ("lost" if total_pnl < 0 else "broke even")
        if total_pnl == 0:
            lines.append(f"Bottom line on finished trades: {winners} of {len(closed_trades)} made money, and it all {net_word} — no net change.")
        else:
            lines.append(
                f"Bottom line on finished trades: {winners} of {len(closed_trades)} made money, "
                f"and together they {net_word} {_fmt_rupees(abs(total_pnl))} today "
                f"after costs."
            )
        if total_charges:
            lines.append(
                f"The broker was paid {_fmt_rupees(total_charges)} today. Every figure "
                f"above already has that taken out."
            )
        if uncharged:
            lines.append(
                f"({uncharged} of these trades were booked before Hokage started "
                f"counting broker costs, so for those the figure is the price move "
                f"only — the costs were real, they were just never recorded.)"
            )

    # ---- what the options did after he sold ---------------------------
    # PHASE 5, the daily half. Written in plain words because this report is
    # the one the commander actually reads, and the whole point of the
    # post-exit corpus is that somebody reads it - the mirror experiment ran
    # 11 days and nothing ever opened its archive.
    #
    # ALL THREE OUTCOMES OR NONE. Printing only "sold too early" would turn
    # the report into a regret machine: you notice the ones that recovered
    # and forget the ones that collapsed.
    try:
        from hokage.memory import exit_followup

        _cover = exit_followup.coverage()
        if _cover["exits"]:
            import sys as _sys
            from pathlib import Path as _P

            _tools = str(_P(__file__).resolve().parents[3]
                         / "tools" / "research")
            if _tools not in _sys.path:
                _sys.path.insert(0, _tools)
            import post_exit_lab as _pel

            _judged = [_pel.judge(r) for r in exit_followup.followups(limit=40)]
            _watched = [j for j in _judged
                        if j["verdict"] != _pel.Verdict.UNWATCHED]
            if _watched:
                _cost = sum(1 for j in _watched
                            if j["verdict"] == _pel.Verdict.COST)
                _saved = sum(1 for j in _watched
                             if j["verdict"] == _pel.Verdict.SAVED)
                _same = len(_watched) - _cost - _saved
                lines.append("")
                lines.append("After he sold — what the option did next:")
                lines.append(
                    f"Of the last {len(_watched)} trades he closed, the price "
                    f"later went higher on {_cost} (he sold too early), fell "
                    f"further on {_saved} (selling saved money), and barely "
                    f"moved on {_same}."
                )
                _reached = sum(1 for j in _watched if j["reached_target"])
                if _reached:
                    lines.append(
                        f"{_reached} of them went on to reach the price target "
                        f"he had been aiming for."
                    )
                lines.append(
                    "This judges the SELL decision, not the buy. It also "
                    "ignores that an option loses value just by time passing, "
                    "so holding on is not as free as it looks."
                )
    except Exception:
        # A measurement must never cost the commander his daily report.
        pass

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
