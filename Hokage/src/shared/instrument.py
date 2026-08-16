"""Turn a broker tradingsymbol into something a human can read at a glance.

WHY THIS EXISTS
A live alert read:

    ENTERING POSITION: SILVERM26AUG237000CE
    CMP: 4638.00

Three problems, and the third is dangerous:
  1. "SILVERM" is Silver MINI. Nothing says so.
  2. The strike (2,37,000) and expiry (26 Aug) are welded into one token.
  3. "CMP 4638" is the OPTION PREMIUM. Silver itself was near 2,37,000. The
     alert invites you to read 4,638 as the price of silver.

Parsing is deliberately defensive: anything that does not match a known shape
comes back as the raw symbol with `parsed=False`. An alert must never fail to
send because a tradingsymbol had an unexpected format.

THE TWO REAL FORMATS, taken from every symbol Hokage has actually traded:

  MONTHLY  root + YY + MMM + strike + CE/PE
           SILVERM26AUG237000CE   BANKNIFTY26AUG57000PE   CRUDEOIL26AUG7200PE

  WEEKLY   root + YY + M + DD + strike + CE/PE      (NSE/BSE index)
           NIFTY2672124100PE  -> 21 Jul 2026
           SENSEX2681378300PE -> 13 Aug 2026

In the weekly form Kite writes months 1-9 as a digit and October, November,
December as the LETTERS O, N and D — so a naive \\d matcher silently fails for
a quarter of the year.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: Broker root -> the name a human uses. GOLDM/SILVERM are the MINI contracts;
#: saying so is the entire point of this table.
DISPLAY_NAMES: dict[str, str] = {
    "SILVERM": "Silver Mini",
    "GOLDM": "Gold Mini",
    "SILVER": "Silver",
    "GOLD": "Gold",
    "CRUDEOIL": "Crude Oil",
    "NATURALGAS": "Natural Gas",
    "NIFTY": "Nifty 50",
    "BANKNIFTY": "Bank Nifty",
    "SENSEX": "Sensex",
    "FINNIFTY": "Fin Nifty",
    "MIDCPNIFTY": "Midcap Nifty",
}

_MONTHS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

#: Kite's weekly month code: 1-9 as digits, then O/N/D for Oct/Nov/Dec.
_WEEKLY_MONTH = {**{str(i): i for i in range(1, 10)}, "O": 10, "N": 11, "D": 12}

_MONTHLY_RE = re.compile(
    r"^(?P<root>[A-Z]+?)(?P<yy>\d{2})(?P<mon>" + "|".join(_MONTHS) + r")"
    r"(?P<strike>\d+)(?P<opt>CE|PE)$"
)
_WEEKLY_RE = re.compile(
    r"^(?P<root>[A-Z]+?)(?P<yy>\d{2})(?P<m>[1-9OND])(?P<dd>\d{2})"
    r"(?P<strike>\d+)(?P<opt>CE|PE)$"
)


def rupees(value: float, paise: bool = False) -> str:
    """Indian digit grouping: 237000 -> 2,37,000. Last three, then pairs."""
    negative = value < 0
    whole = abs(int(value))
    frac = f"{abs(value) - whole:.2f}"[1:] if paise else ""
    text = str(whole)
    if len(text) > 3:
        head, tail = text[:-3], text[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        text = ",".join(parts) + "," + tail
    return ("-" if negative else "") + text + frac


@dataclass(frozen=True)
class Instrument:
    """A tradingsymbol, taken apart. `parsed` False means keep using `raw`."""

    raw: str
    parsed: bool = False
    root: str = ""
    display_name: str = ""
    strike: float = 0.0
    option_type: str = ""      # CE / PE
    expiry_text: str = ""      # "26 Aug" / "21 Jul"

    @property
    def direction_word(self) -> str:
        return {"CE": "CALL", "PE": "PUT"}.get(self.option_type, "")

    def headline(self) -> str:
        """One line naming the instrument in plain terms."""
        if not self.parsed:
            return self.raw
        return (f"{self.display_name} · {rupees(self.strike)} {self.direction_word} "
                f"· {self.expiry_text} expiry")


def parse(tradingsymbol: str) -> Instrument:
    """Take a tradingsymbol apart. Never raises; unknown shapes return raw."""
    if not tradingsymbol:
        return Instrument(raw="")
    symbol = tradingsymbol.strip().upper()

    # Monthly first: its 3-letter month cannot match the weekly pattern, but a
    # weekly could in principle be mis-split, so the more constrained form wins.
    monthly = _MONTHLY_RE.match(symbol)
    if monthly:
        root = monthly.group("root")
        return Instrument(
            raw=tradingsymbol, parsed=True, root=root,
            display_name=DISPLAY_NAMES.get(root, root.title()),
            strike=float(monthly.group("strike")),
            option_type=monthly.group("opt"),
            expiry_text=f"{monthly.group('yy')} {monthly.group('mon').title()}",
        )

    weekly = _WEEKLY_RE.match(symbol)
    if weekly:
        root = weekly.group("root")
        month = _WEEKLY_MONTH.get(weekly.group("m"))
        if month:
            day = int(weekly.group("dd"))
            return Instrument(
                raw=tradingsymbol, parsed=True, root=root,
                display_name=DISPLAY_NAMES.get(root, root.title()),
                strike=float(weekly.group("strike")),
                option_type=weekly.group("opt"),
                expiry_text=f"{day} {_MONTHS[month - 1].title()}",
            )

    return Instrument(raw=tradingsymbol)


def underlying_of(tradingsymbol: str) -> str:
    """The underlying root, or the symbol itself when it does not parse."""
    inst = parse(tradingsymbol)
    return inst.root if inst.parsed else tradingsymbol
