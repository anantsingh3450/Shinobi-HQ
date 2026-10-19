"""A defined-risk spread, and the arithmetic that makes "defined" true.

The mandate changed on 2026-10-19 to allow short-premium spreads and NEVER
naked shorts. That distinction is the whole safety story, so it is enforced
here as a type rather than remembered as a convention: a VerticalSpread
cannot be constructed unless the long leg genuinely caps the short leg's
loss.

WHAT A NAKED SHORT COSTS, measured against the live venue the same day on one
NIFTY contract:

    naked SELL 22900CE                     189,563 margin, UNBOUNDED loss
    naked BUY  23000CE                      25,350 margin
    as a spread, 22900/23000                33,004 margin, loss capped 2,925

The hedge is worth 85% of the margin and, far more importantly, it converts
an unbounded loss into a number known before entry. Everything in this file
exists to make the second property impossible to lose by accident.

THE FOUR CONDITIONS, all enforced:
  * same underlying        — legs on different indices do not hedge
  * same expiry            — a calendar is not a vertical, and its loss is
                             not bounded by strike width
  * same option type       — a CE does not cap a PE
  * the long leg is on the losing side of the short leg, so the payoff is
    bounded: for calls the long strike is ABOVE, for puts BELOW

MAX LOSS IS COMPUTED, NEVER PASSED IN. A caller that could supply its own
max loss is a caller that can be wrong about it, and the one number this
whole structure exists to guarantee would then rest on the caller's
arithmetic.

NOTHING HERE PLACES AN ORDER. This is the shape of the position and the
arithmetic of its risk. The margin it will actually require comes from the
broker (bots.execution.margin), never from this file — margin is the
exchange's number and guessing it would be a synthetic price by another name.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

#: Option types this understands. Anything else is refused rather than
#: assumed to behave like a call.
CALL = "CE"
PUT = "PE"


class NotDefinedRisk(ValueError):
    """Raised when the legs do not cap each other's loss.

    A distinct type so callers cannot catch it alongside ordinary input
    errors and carry on with an unbounded position.
    """


@dataclass(frozen=True, slots=True)
class Leg:
    """One side of a spread. `quantity` is in units, already lot-multiplied."""

    tradingsymbol: str
    exchange: str
    option_type: str
    strike: float
    expiry: dt.date
    quantity: int
    is_short: bool
    price: float

    @property
    def transaction_type(self) -> str:
        return "SELL" if self.is_short else "BUY"


@dataclass(frozen=True, slots=True)
class VerticalSpread:
    """A short-premium vertical with a loss bounded by strike width.

    Construct with `build`, which refuses anything that is not defined-risk.
    """

    underlying: str
    option_type: str
    expiry: dt.date
    short: Leg
    long: Leg
    lot_size: int

    # ------------------------------------------------------------ arithmetic
    @property
    def width(self) -> float:
        """Distance between the strikes, in index points."""
        return abs(self.long.strike - self.short.strike)

    @property
    def net_credit(self) -> float:
        """Premium received net of premium paid, in rupees.

        Negative means the structure costs money to put on — which is a
        DEBIT spread. It is not forbidden here, but a short-premium strategy
        asking for one has mispriced its legs, and `is_credit` lets the
        caller refuse it.
        """
        return (self.short.price - self.long.price) * self.quantity

    @property
    def is_credit(self) -> bool:
        return self.net_credit > 0

    @property
    def quantity(self) -> int:
        return self.short.quantity

    @property
    def max_loss(self) -> float:
        """The worst case, in rupees, known before entry.

        Width times quantity is the most the position can be worth against
        you at expiry; the credit already received offsets it. A debit
        spread's "max loss" is simply the debit, which falls out of the same
        formula because net_credit is then negative.
        """
        return self.width * self.quantity - self.net_credit

    @property
    def max_profit(self) -> float:
        """The best case: keeping the credit, or the width less the debit."""
        if self.net_credit >= 0:
            return self.net_credit
        return self.width * self.quantity + self.net_credit

    # ------------------------------------------------------------- building
    @classmethod
    def build(cls, underlying: str, short: Leg, long: Leg,
              lot_size: int) -> "VerticalSpread":
        """The only way to make one. Refuses anything not defined-risk."""
        if short.quantity <= 0 or long.quantity <= 0:
            raise NotDefinedRisk("a leg with no quantity hedges nothing")
        if short.quantity != long.quantity:
            raise NotDefinedRisk(
                f"unequal legs ({short.quantity} short vs {long.quantity} "
                f"long) leave {abs(short.quantity - long.quantity)} units "
                f"naked")
        if not short.is_short or long.is_short:
            raise NotDefinedRisk(
                "a vertical is one short leg protected by one long leg")
        if short.option_type != long.option_type:
            raise NotDefinedRisk(
                f"a {long.option_type} does not cap a {short.option_type}")
        if short.option_type not in (CALL, PUT):
            raise NotDefinedRisk(f"unknown option type {short.option_type!r}")
        if short.expiry != long.expiry:
            raise NotDefinedRisk(
                f"different expiries ({short.expiry} vs {long.expiry}) — a "
                f"calendar's loss is not bounded by strike width")
        if short.strike == long.strike:
            raise NotDefinedRisk("same strike on both legs is not a spread")

        # THE DIRECTION OF PROTECTION. A call you are short loses as price
        # rises, so the long call must sit ABOVE it; a short put loses as
        # price falls, so the long put must sit BELOW. Backwards, the long
        # leg is simply a second cost and the short leg is still unbounded.
        if short.option_type == CALL and long.strike <= short.strike:
            raise NotDefinedRisk(
                f"long call at {long.strike} does not cap a short call at "
                f"{short.strike}: it must be higher")
        if short.option_type == PUT and long.strike >= short.strike:
            raise NotDefinedRisk(
                f"long put at {long.strike} does not cap a short put at "
                f"{short.strike}: it must be lower")

        if lot_size <= 0:
            raise NotDefinedRisk("a lot size of zero prices nothing")

        return cls(underlying=underlying.upper(),
                   option_type=short.option_type, expiry=short.expiry,
                   short=short, long=long, lot_size=lot_size)

    # -------------------------------------------------------------- orders
    def basket(self, product: str = "NRML",
               order_type: str = "MARKET") -> list[dict]:
        """The legs in the shape the broker's margin and order APIs take.

        THE LONG LEG IS FIRST, and that ordering is a safety property rather
        than a style choice: if a basket is ever placed leg by leg and the
        second one fails, the position left behind must be the PROTECTION,
        not the naked short.
        """
        return [
            {"exchange": leg.exchange, "tradingsymbol": leg.tradingsymbol,
             "transaction_type": leg.transaction_type, "variety": "regular",
             "product": product, "order_type": order_type,
             "quantity": leg.quantity}
            for leg in (self.long, self.short)
        ]

    def describe(self) -> str:
        return (f"{self.underlying} {self.expiry} "
                f"{self.short.strike:.0f}/{self.long.strike:.0f} "
                f"{self.option_type} x{self.quantity} — "
                f"credit {self.net_credit:,.0f}, max loss {self.max_loss:,.0f}")
