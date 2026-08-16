"""A live alert said `SILVERM26AUG237000CE` with `CMP: 4638.00`.

Three problems, the third dangerous:
  1. SILVERM is Silver MINI and nothing said so.
  2. The strike (2,37,000) and expiry (26 Aug) were welded into one token.
  3. 4,638 is the option PREMIUM. Silver itself was near 2,37,000, so the
     alert invited reading 4,638 as the price of silver.

Every symbol below is one Hokage has actually traded, pulled from the position
table — not an assumed format.
"""
from __future__ import annotations

import pytest

from shared.instrument import DISPLAY_NAMES, parse, rupees, underlying_of


@pytest.mark.parametrize(
    "symbol,name,strike,kind,expiry",
    [
        ("SILVERM26AUG237000CE", "Silver Mini", 237000, "CALL", "26 Aug"),
        ("GOLDM26AUG153500CE", "Gold Mini", 153500, "CALL", "26 Aug"),
        ("NATURALGAS26AUG265CE", "Natural Gas", 265, "CALL", "26 Aug"),
        ("CRUDEOIL26AUG7200PE", "Crude Oil", 7200, "PUT", "26 Aug"),
        ("BANKNIFTY26AUG57000PE", "Bank Nifty", 57000, "PUT", "26 Aug"),
    ],
)
def test_monthly_contracts(symbol, name, strike, kind, expiry):
    inst = parse(symbol)
    assert inst.parsed
    assert inst.display_name == name
    assert inst.strike == strike
    assert inst.direction_word == kind
    assert inst.expiry_text == expiry


@pytest.mark.parametrize(
    "symbol,name,strike,kind,expiry",
    [
        ("NIFTY2672124100PE", "Nifty 50", 24100, "PUT", "21 Jul"),
        ("NIFTY2680424300CE", "Nifty 50", 24300, "CALL", "4 Aug"),
        ("SENSEX2672378000CE", "Sensex", 78000, "CALL", "23 Jul"),
        ("SENSEX2681378300PE", "Sensex", 78300, "PUT", "13 Aug"),
    ],
)
def test_nse_weekly_contracts(symbol, name, strike, kind, expiry):
    """Weekly form is root+YY+M+DD+strike. Distinct from monthly and easy to
    mis-split, so every real example is pinned."""
    inst = parse(symbol)
    assert inst.parsed
    assert inst.display_name == name
    assert inst.strike == strike
    assert inst.direction_word == kind
    assert inst.expiry_text == expiry


def test_october_november_december_weeklies_are_letters_not_digits():
    """Kite writes months 1-9 as digits but Oct/Nov/Dec as O/N/D. A parser that
    assumes a digit silently fails for a quarter of every year."""
    assert parse("NIFTY26O1424500CE").expiry_text == "14 Oct"
    assert parse("NIFTY26N1124500CE").expiry_text == "11 Nov"
    assert parse("NIFTY26D0224500CE").expiry_text == "2 Dec"


def test_the_mini_contracts_are_named_as_mini():
    """The whole reason this module exists."""
    assert DISPLAY_NAMES["SILVERM"] == "Silver Mini"
    assert DISPLAY_NAMES["GOLDM"] == "Gold Mini"
    assert "Mini" in parse("SILVERM26AUG237000CE").headline()


def test_an_unknown_shape_degrades_to_the_raw_symbol_and_never_raises():
    """An alert must never fail to send because a symbol looked odd."""
    for junk in ["", "WEIRD123", "NOTASYMBOL", "NIFTY-FUT", "SILVERM26AUGCE"]:
        inst = parse(junk)
        assert inst.parsed is False
        assert inst.headline() == junk


def test_indian_digit_grouping():
    """2,37,000 not 237,000 — lakh grouping, because that is how the commander
    reads a price."""
    assert rupees(237000) == "2,37,000"
    assert rupees(153500) == "1,53,500"
    assert rupees(4638, paise=True) == "4,638.00"
    assert rupees(265) == "265"
    assert rupees(-1685) == "-1,685"
    assert rupees(10000000) == "1,00,00,000"


def test_underlying_extraction():
    assert underlying_of("SILVERM26AUG237000CE") == "SILVERM"
    assert underlying_of("NIFTY2672124100PE") == "NIFTY"
    assert underlying_of("GARBAGE") == "GARBAGE"


def test_the_headline_separates_every_field_that_used_to_be_welded_together():
    head = parse("SILVERM26AUG237000CE").headline()
    assert "Silver Mini" in head
    assert "2,37,000" in head
    assert "CALL" in head
    assert "26 Aug" in head
    assert "SILVERM26AUG237000CE" not in head
