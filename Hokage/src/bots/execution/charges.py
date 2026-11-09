"""What a round trip actually costs, from the broker's published schedule.

WHY THIS EXISTS
2026-11-09. `PortfolioBot.apply_trade` moves cash by `(exit - entry) x quantity`
and nothing else, so every P&L figure Hokage has ever reported is GROSS -
including the profit factor 1.04 the go-live gate is judged on. The only
charges model in this repo was `integrations/tax/mock_provider`, which
recorded 0.0144% of traded value, denominated in USD, on Indian options, and
stopped writing on 2026-08-17.

THESE RATES ARE QUOTED, NOT REMEMBERED. Third-party brokerage calculators
disagreed by a factor of 2.4 on the single largest line - options STT read as
0.0625% on some and 0.15% on others - and a go-live decision cannot rest on
whichever page ranked first. Every number below comes from zerodha.com/charges,
read 2026-11-09, and is recorded with that date so the next reader knows how
old it is. A rate that has moved is a wrong answer, not a stale one.

WHAT MAKES THIS DIFFERENT FROM THE SPREAD
Brokerage is FLAT: 20 rupees an order, 40 a round trip, whatever the position.
As a percentage it therefore depends entirely on position size, and at this
account's size it is the single biggest line - 0.22% of a 17,810 NIFTY lot.
Trading smaller does not make it cheaper; it makes it dearer.

WHAT THIS DOES NOT DO
It does not touch the ledger. Subtracting these from historical P&L would
rewrite every number the commander has ever been shown, which is his call to
make knowingly rather than mine to slip in. This MEASURES; wiring it into
fills is a separate, announced change.
"""
from __future__ import annotations

from dataclasses import dataclass

#: When these rates were read from the broker's own page. Quoted in output so
#: a stale schedule is visible rather than assumed current.
RATES_READ_ON = "2026-11-09"
RATES_SOURCE = "zerodha.com/charges"

#: Flat, per executed order, both legs. The dominant cost at small size.
BROKERAGE_PER_ORDER = 20.0

#: 18% on brokerage + transaction + SEBI charges. Not on STT or stamp duty.
GST_RATE = 0.18

#: 10 rupees per crore of turnover.
SEBI_RATE = 10.0 / 1e7

#: Buy side only.
STAMP_RATE = 0.00003          # 0.003%


@dataclass(frozen=True)
class SegmentRates:
    """One exchange segment's published rates."""

    name: str
    #: Of premium turnover, SELL side only.
    stt: float
    #: Of premium turnover, both sides.
    transaction: float


#: NSE equity options (index options are the whole tradable universe) and MCX
#: commodity options. BSE's transaction charge is 0.0325%, slightly cheaper
#: than NSE's, which matters only for SENSEX and is not modelled separately
#: until something acts on the difference.
RATES = {
    "NSE": SegmentRates("NSE equity options", stt=0.0015, transaction=0.0003553),
    "MCX": SegmentRates("MCX commodity options", stt=0.0005, transaction=0.000418),
}

MCX_UNDERLYINGS = ("CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM")


def segment_for(underlying: str) -> str:
    return "MCX" if str(underlying).upper() in MCX_UNDERLYINGS else "NSE"


@dataclass(frozen=True)
class RoundTrip:
    """Every line of one buy-then-sell, in rupees."""

    brokerage: float
    stt: float
    transaction: float
    sebi: float
    stamp: float
    gst: float
    turnover: float

    @property
    def total(self) -> float:
        return (self.brokerage + self.stt + self.transaction
                + self.sebi + self.stamp + self.gst)

    @property
    def pct_of_premium(self) -> float:
        """Cost as a percentage of the premium paid, which is the number that
        compares directly against a measured edge."""
        return (self.total / self.turnover * 100.0) if self.turnover else 0.0

    def breakdown(self) -> list[tuple[str, float, float]]:
        """(line, rupees, percent of premium), largest first."""
        rows = [
            ("brokerage", self.brokerage), ("STT/CTT", self.stt),
            ("transaction", self.transaction), ("GST", self.gst),
            ("stamp duty", self.stamp), ("SEBI", self.sebi),
        ]
        scale = (100.0 / self.turnover) if self.turnover else 0.0
        return sorted(((n, v, v * scale) for n, v in rows),
                      key=lambda r: -r[1])


def option_round_trip(premium_value: float, underlying: str,
                      exit_value: float | None = None) -> RoundTrip:
    """Charges for buying one lot and selling it again.

    `premium_value` is premium x lot size in rupees - the turnover, not the
    quoted premium. `exit_value` defaults to the entry: the exit turnover is
    unknowable in advance, and assuming a flat exit keeps this an estimate of
    COST rather than a forecast of the trade.

    STT falls on the SELL side only, stamp duty on the BUY side only, and
    both are charged on their own side's turnover - which is why they take
    different bases when the two differ.
    """
    rates = RATES[segment_for(underlying)]
    entry = max(0.0, float(premium_value))
    exit_ = entry if exit_value is None else max(0.0, float(exit_value))
    both = entry + exit_

    brokerage = BROKERAGE_PER_ORDER * 2
    stt = rates.stt * exit_                 # sell side
    transaction = rates.transaction * both
    sebi = SEBI_RATE * both
    stamp = STAMP_RATE * entry              # buy side
    # GST does NOT apply to STT or stamp duty.
    gst = GST_RATE * (brokerage + transaction + sebi)

    return RoundTrip(brokerage=brokerage, stt=stt, transaction=transaction,
                     sebi=sebi, stamp=stamp, gst=gst, turnover=entry)


def breakeven_move_pct(premium_value: float, underlying: str) -> float:
    """How far the premium must rise, in percent, just to cover costs."""
    return option_round_trip(premium_value, underlying).pct_of_premium
