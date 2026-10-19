"""What a spread actually costs to hold. Asked, never modelled.

SPAN plus exposure is computed by the exchange from a proprietary risk array
that changes intraday. There is no honest way to reproduce it here, and a
reproduction that drifted would be worse than no number at all: it would let
Hokage believe he could afford a position he could not, which is how an
account gets a margin call rather than a trade.

So this ASKS THE BROKER. `basket_order_margins` is a pure calculation
endpoint — it places nothing — and it returns the exchange's own number with
the hedge benefit already applied. Measured 2026-10-19 on one NIFTY contract:

    legs priced separately (initial)   214,913
    as a recognised spread (final)      33,004

The 85% difference IS the hedge benefit, and it is the difference between a
structure this account could never hold and one it might. Reading `initial`
where `final` is meant would overstate the requirement sixfold; computing
either locally would be a guess dressed as a fact.

IT FAILS CLOSED. No session, a broker error, a malformed reply — every path
returns None, and a caller that cannot learn the margin must refuse the
trade. There is deliberately NO fallback estimate. A fallback is only ever
consulted when the real number is unavailable, which is exactly when being
wrong is least recoverable.

AND THE NUMBER DOES NOT KEEP. SPAN moves intraday with volatility, so a
quote is cached for MAX_AGE_SECONDS and then asked again. A margin from this
morning is not evidence about this afternoon.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Callable

logger = logging.getLogger("Hokage.Margin")

#: How long a margin figure may be reused. SPAN is recomputed by the exchange
#: through the day; a few minutes is fresh, an hour is fiction.
MAX_AGE_SECONDS = 180

#: Keys the broker's reply must carry before it is believed. A reply missing
#: `final` is a reply whose shape changed, and guessing which other number
#: meant the same thing is how an unhedged figure gets used as a hedged one.
_REQUIRED = ("initial", "final")


class MarginOracle:
    """The exchange's margin for a basket, with a short memory.

    `client` is anything exposing Kite's `basket_order_margins(params,
    consider_positions=, mode=)`. Injected so no test ever reaches the real
    venue.
    """

    def __init__(self, client: Any = None,
                 clock: Callable[[], float] = time.monotonic,
                 max_age_seconds: int = MAX_AGE_SECONDS) -> None:
        self._client = client
        self._clock = clock
        self._max_age = max_age_seconds
        self._cache: dict[tuple, tuple[float, dict]] = {}

    # ------------------------------------------------------------- asking
    def required(self, basket: list[dict],
                 consider_positions: bool = True) -> float | None:
        """Rupees of margin this basket needs, or None if it cannot be known.

        `consider_positions` defaults to True because the real question is
        always "can this account add this position to what it already
        holds", and an existing offsetting position legitimately reduces the
        requirement.
        """
        detail = self.detail(basket, consider_positions)
        return None if detail is None else detail["final"]

    def detail(self, basket: list[dict],
               consider_positions: bool = True) -> dict | None:
        """{'initial', 'final', 'hedge_benefit'} or None. Never raises."""
        if not basket:
            return None
        if self._client is None:
            logger.debug("Margin oracle has no broker client; failing closed.")
            return None

        key = self._key(basket, consider_positions)
        hit = self._cache.get(key)
        now = self._clock()
        if hit is not None and (now - hit[0]) <= self._max_age:
            return hit[1]

        try:
            reply = self._client.basket_order_margins(
                basket, consider_positions=consider_positions, mode="compact")
        except Exception as exc:
            logger.warning(
                "Margin unavailable for a %d-leg basket (%s). Failing closed: "
                "no trade.", len(basket), str(exc)[:120])
            return None

        parsed = self._parse(reply)
        if parsed is None:
            return None
        self._cache[key] = (now, parsed)
        return parsed

    # ------------------------------------------------------------ parsing
    @staticmethod
    def _parse(reply: Any) -> dict | None:
        if not isinstance(reply, dict):
            logger.warning("Margin reply was %s, not a mapping. Failing "
                           "closed.", type(reply).__name__)
            return None
        for field in _REQUIRED:
            block = reply.get(field)
            if not isinstance(block, dict) or "total" not in block:
                logger.warning(
                    "Margin reply has no usable %r block, so the hedged and "
                    "unhedged figures cannot be told apart. Failing closed.",
                    field)
                return None
        try:
            initial = float(reply["initial"]["total"])
            final = float(reply["final"]["total"])
        except (TypeError, ValueError):
            logger.warning("Margin totals were not numbers. Failing closed.")
            return None
        if final <= 0 or initial <= 0:
            # A zero margin on a short option is not a gift, it is a broken
            # reply. Treating it as real would make every spread look free.
            logger.warning("Margin came back as %.2f, which is not a real "
                           "requirement for a short leg. Failing closed.",
                           final)
            return None
        return {"initial": initial, "final": final,
                "hedge_benefit": initial - final}

    @staticmethod
    def _key(basket: list[dict], consider_positions: bool) -> tuple:
        return (consider_positions, tuple(sorted(
            (leg.get("exchange"), leg.get("tradingsymbol"),
             leg.get("transaction_type"), leg.get("product"),
             leg.get("quantity"))
            for leg in basket)))


def affordable(spread, available_cash: float, oracle: MarginOracle,
               max_fraction: float) -> tuple[bool, str]:
    """Can this account hold this spread, and should it?

    Two separate questions and both must pass:

      1. Is the margin KNOWN? An unknown margin is not a small one.
      2. Is it within `max_fraction` of the account? A position that needs
         every rupee of margin available is one position away from being
         unable to respond to anything else — and on 2026-10-19 a single
         NIFTY vertical required 33,004 against a real seed of 30,000, so
         this is the binding constraint rather than a formality.
    """
    required = oracle.required(spread.basket())
    if required is None:
        return False, ("margin could not be read from the broker — refusing "
                       "rather than guessing")
    if available_cash <= 0:
        return False, "no cash in the account"
    ceiling = available_cash * max_fraction
    if required > ceiling:
        return False, (
            f"margin {required:,.0f} exceeds {max_fraction:.0%} of "
            f"{available_cash:,.0f} ({ceiling:,.0f})")
    return True, f"margin {required:,.0f} within {ceiling:,.0f}"
