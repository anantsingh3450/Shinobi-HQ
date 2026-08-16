"""Explain a trade twice: once to a trader, once to someone learning.

Commander's requirement, 2026-08-16: every piece of reasoning should be
available in two registers —

    TRADER   dense, assumes ATR / VWAP / R:R / theta are known vocabulary
    LEARNER  assumes nothing, explains the concept as it uses it, so reading
             the alert teaches trading rather than merely reporting it

WHY THESE ARE TEMPLATES AND NOT LLM PROSE
Every sentence below is assembled from fields the system actually holds — the
strategy that won, the gates it passed, the real stop distance for THAT
(strategy, asset) pair, the real premium and lot size. An LLM narration would
read better and be *usually* correct. For the trader register that is a
preference; for the LEARNER register it is a safety question. The entire point
of the learner text is that the commander learns how this works, and a
confident, slightly-wrong explanation teaches something false. A template
cannot invent a number it was not given.

The LLM still has a place — freeform conversation, where the human can push
back. Not here, where the text is a teaching aid delivered unprompted.

Everything degrades: any field that is missing is simply not mentioned, and no
sentence claims a number it did not receive.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shared.instrument import Instrument, parse, rupees

TRADER = "trader"
LEARNER = "learner"


@dataclass
class TradeContext:
    """Everything known about one trade. Every field optional by design."""

    tradingsymbol: str
    side: str = "entry"                 # entry | exit
    strategy: str | None = None
    strategy_reason: str | None = None  # the module's own words
    premium: float | None = None
    lot_size: float | None = None
    lots: int = 1
    target: float | None = None
    underlying_price: float | None = None
    underlying_atr: float | None = None
    stop_atr_mult: float | None = None
    edge_score: float | None = None
    exit_reason: str | None = None
    pnl: float | None = None
    exit_price: float | None = None
    blocked_rivals: list[str] = field(default_factory=list)

    @property
    def instrument(self) -> Instrument:
        return parse(self.tradingsymbol)

    @property
    def units(self) -> float | None:
        if self.lot_size is None:
            return None
        return self.lot_size * max(1, self.lots)

    @property
    def cost(self) -> float | None:
        if self.premium is None or self.units is None:
            return None
        return self.premium * self.units

    @property
    def stop_points(self) -> float | None:
        if self.underlying_atr is None or self.stop_atr_mult is None:
            return None
        return self.underlying_atr * self.stop_atr_mult

    @property
    def risk_rupees(self) -> float | None:
        """Premium at risk if the underlying stop is hit, via a ~0.45 ATM delta."""
        pts = self.stop_points
        if pts is None or self.units is None:
            return None
        return pts * 0.45 * self.units

    @property
    def reward_rupees(self) -> float | None:
        if self.target is None or self.premium is None or self.units is None:
            return None
        return (self.target - self.premium) * self.units


def _pct(part: float, whole: float) -> str:
    return f"{part / whole * 100:+.1f}%" if whole else ""


# --------------------------------------------------------------------- trader
def _trader_entry(c: TradeContext) -> list[str]:
    inst = c.instrument
    lines = []
    who = f"{c.strategy} " if c.strategy else ""
    what = inst.headline() if inst.parsed else c.tradingsymbol
    lines.append(f"{who}long {what}.")
    if c.strategy_reason:
        lines.append(c.strategy_reason.rstrip(".") + ".")
    bits = []
    if c.premium is not None:
        bits.append(f"premium ₹{rupees(c.premium, paise=True)}")
    if c.units:
        bits.append(f"{c.units:g} units")
    if c.cost is not None:
        bits.append(f"outlay ₹{rupees(c.cost)}")
    if bits:
        lines.append(" · ".join(bits) + ".")
    if c.stop_points is not None and c.underlying_atr:
        # Points on the underlying are NOT rupees of P&L — they carry no ₹ on
        # purpose, and the delta conversion that follows is what turns one into
        # the other. Mixing the two units silently is how a stop distance gets
        # read as a loss figure.
        stop_line = (f"Thesis stop {c.stop_atr_mult:g} ATR = "
                     f"{rupees(c.stop_points)} pts on the underlying")
        if c.risk_rupees is not None:
            stop_line += f" ≈ ₹{rupees(c.risk_rupees)} at a 0.45 delta"
        lines.append(stop_line + ".")
    if c.target is not None and c.premium:
        rr = ""
        if c.risk_rupees and c.reward_rupees:
            rr = f", R:R {c.reward_rupees / c.risk_rupees:.2f}:1"
        lines.append(f"Target ₹{rupees(c.target, paise=True)} "
                     f"({_pct(c.target - c.premium, c.premium)}){rr}.")
    if c.edge_score is not None:
        lines.append(f"Edge {c.edge_score:.1f}%.")
    if c.blocked_rivals:
        lines.append("Beat: " + "; ".join(c.blocked_rivals) + ".")
    return lines


def _trader_exit(c: TradeContext) -> list[str]:
    inst = c.instrument
    lines = [f"Closed {inst.headline() if inst.parsed else c.tradingsymbol}"
             + (f" ({c.strategy})" if c.strategy else "") + "."]
    if c.exit_reason:
        lines.append(c.exit_reason.rstrip(".") + ".")
    if c.exit_price is not None and c.premium:
        lines.append(f"₹{rupees(c.premium, paise=True)} -> "
                     f"₹{rupees(c.exit_price, paise=True)} "
                     f"({_pct(c.exit_price - c.premium, c.premium)}).")
    if c.pnl is not None:
        # Sign OUTSIDE the currency symbol, matching the alert: "-₹1,685".
        lines.append(f"P&L {'+' if c.pnl >= 0 else '-'}₹{rupees(abs(c.pnl))}.")
    return lines


# -------------------------------------------------------------------- learner
#: What each strategy BETS ON, in words a non-trader can follow.
#:
#: The learner register must NOT echo a module's own reason string. Those read
#: "US-overlap uptrend (EMA9 236773 > EMA21 236654), price above VWAP" — every
#: term in that sentence is the jargon this register exists to avoid, and
#: quoting it defeats the whole purpose. A strategy Hokage does not have a
#: plain description for is simply not described, never paraphrased on the fly.
_STRATEGY_IN_PLAIN_WORDS: dict[str, str] = {
    "SessionShift": (
        "it looks for a metal that has been climbing steadily during the "
        "evening hours when American markets are open alongside ours, and "
        "joins that move while it lasts"
    ),
    "RangeFade": (
        "it looks for a price that has drifted unusually far from its average "
        "for the day during the quiet hours, and bets on it snapping back "
        "toward normal"
    ),
    "MacroBreakout": (
        "it waits for a price to break clearly out of the range it has been "
        "stuck in, and bets that the break keeps going"
    ),
    "MeanReversion": (
        "it looks for a price that has stretched too far from its average and "
        "bets on it returning toward the middle"
    ),
    "TrendRider": (
        "it joins an evening trend that has already proven itself, rather than "
        "trying to catch a turn"
    ),
    "EventRider": (
        "it trades around scheduled news events, when prices tend to move fast"
    ),
}

_WHAT_IS_AN_OPTION = {
    "CE": ("A CALL option is a bet that the price will go UP. You pay a small "
           "fee up front (the 'premium') and it gains value if the price rises."),
    "PE": ("A PUT option is a bet that the price will go DOWN. You pay a small "
           "fee up front (the 'premium') and it gains value if the price falls."),
}


def _learner_entry(c: TradeContext) -> list[str]:
    inst = c.instrument
    lines: list[str] = []

    name = inst.display_name if inst.parsed else c.tradingsymbol
    if inst.parsed:
        lines.append(
            f"Hokage bought a {inst.direction_word} option on {name}."
        )
        lines.append(_WHAT_IS_AN_OPTION.get(inst.option_type, ""))
        lines.append(
            f"This particular one is priced around the {rupees(inst.strike)} "
            f"level (the 'strike') and expires on {inst.expiry_text} — after "
            f"that date it is worthless, so this is a bet on the next few "
            f"hours or days, not a long-term investment."
        )
    else:
        lines.append(f"Hokage bought an option on {name}.")

    if c.strategy:
        lines.append(
            f"The strategy that made this call is named {c.strategy}. Hokage "
            f"runs several strategies that compete, and only the most "
            f"confident one gets to trade each asset."
        )
        plain = _STRATEGY_IN_PLAIN_WORDS.get(c.strategy)
        if plain:
            lines.append(f"In plain terms, {plain}.")
    # c.strategy_reason is deliberately NOT quoted here. It is the module's own
    # technical sentence and every term in it is the jargon this register
    # exists to avoid. The trader register carries it verbatim instead.

    if c.cost is not None and c.units:
        lines.append(
            f"One lot is {c.units:g} units, so at a premium of "
            f"₹{rupees(c.premium or 0, paise=True)} the total spent is "
            f"₹{rupees(c.cost)}. That is the most that could ever be lost on "
            f"this trade even in the worst case — buying options cannot lose "
            f"more than what you paid."
        )

    if c.risk_rupees is not None and c.stop_points is not None:
        lines.append(
            f"Hokage will not wait for the worst case though. If {name} itself "
            f"moves about {rupees(c.stop_points)} points against this position, "
            f"he sells automatically and takes a smaller loss of roughly "
            f"₹{rupees(c.risk_rupees)}. That automatic exit is called a 'stop'."
        )
    if c.reward_rupees is not None:
        lines.append(
            f"If it goes the right way, he aims to sell for about "
            f"₹{rupees(c.reward_rupees)} profit."
        )
    if c.risk_rupees and c.reward_rupees:
        ratio = c.reward_rupees / c.risk_rupees
        judgement = (
            "which means he wins more when right than he loses when wrong"
            if ratio >= 1.0 else
            "which means he needs to be right more often than not to come out ahead"
        )
        lines.append(
            f"So he is risking ₹{rupees(c.risk_rupees)} to make "
            f"₹{rupees(c.reward_rupees)} — about {ratio:.1f} to 1, {judgement}."
        )
    return [ln for ln in lines if ln]


_EXIT_IN_PLAIN_WORDS = {
    "TARGET_HIT": ("it reached the profit level Hokage was aiming for, so he "
                   "took the money rather than getting greedy"),
    "Underlying Thesis Stop": ("the underlying moved against the position far "
                               "enough that the reason for the trade no longer "
                               "held, so he cut it rather than hoping"),
    "Option Hard Backstop": ("the option itself lost more value than Hokage "
                             "allows any single trade to lose, so a hard safety "
                             "limit closed it"),
    "TRAIL_LOCK": ("it had been profitable and then started giving those gains "
                   "back, so he locked in what was left"),
    "Time-Based Square-Off": ("the market was about to close and Hokage never "
                              "holds these overnight"),
    "TIME_SQUARE_OFF": ("the market was about to close and Hokage never holds "
                        "these overnight"),
    "KILL_SWITCH": ("an emergency stop was triggered and everything was closed"),
}


def _plain_exit_reason(reason: str | None) -> str | None:
    if not reason:
        return None
    for key, text in _EXIT_IN_PLAIN_WORDS.items():
        if key.lower() in reason.lower():
            return text
    return None


def _learner_exit(c: TradeContext) -> list[str]:
    inst = c.instrument
    name = inst.display_name if inst.parsed else c.tradingsymbol
    lines = [f"Hokage closed the {name} position."]

    plain = _plain_exit_reason(c.exit_reason)
    if plain:
        lines.append(f"He sold because {plain}.")
    elif c.exit_reason:
        lines.append(f"Reason given: {c.exit_reason.rstrip('.')}.")

    if c.premium and c.exit_price is not None:
        move = _pct(c.exit_price - c.premium, c.premium)
        lines.append(
            f"The option was bought at ₹{rupees(c.premium, paise=True)} and sold "
            f"at ₹{rupees(c.exit_price, paise=True)} — a move of {move} in the "
            f"option's own price."
        )
    if c.pnl is not None:
        if c.pnl >= 0:
            lines.append(f"That is a profit of ₹{rupees(c.pnl)}.")
        else:
            lines.append(
                f"That is a loss of ₹{rupees(abs(c.pnl))}. Losses like this are "
                f"expected and planned for — the goal is that the wins are "
                f"bigger, not that there are never losses."
            )
    return [ln for ln in lines if ln]


# ----------------------------------------------------------------------- api
def explain(context: TradeContext, audience: str = TRADER) -> str:
    """One explanation of one trade, in the requested register."""
    is_exit = (context.side or "entry").lower() == "exit"
    if audience == LEARNER:
        lines = _learner_exit(context) if is_exit else _learner_entry(context)
        return " ".join(lines)
    lines = _trader_exit(context) if is_exit else _trader_entry(context)
    return " ".join(lines)


def explain_both(context: TradeContext) -> dict[str, str]:
    return {TRADER: explain(context, TRADER), LEARNER: explain(context, LEARNER)}
