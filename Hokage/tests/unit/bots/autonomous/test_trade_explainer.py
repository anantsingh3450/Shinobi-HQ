"""Every trade explained twice — to a trader, and to someone learning.

Commander's requirement, 2026-08-16. The LEARNER register exists so that
reading an alert TEACHES trading rather than merely reporting it.

WHY THESE ARE TEMPLATES AND NOT LLM PROSE, encoded as tests: a language model
narration is usually correct, and "usually correct" is fine for the trader
register but actively harmful for the learner one — the whole point is that the
commander learns how this works, and a confident slightly-wrong explanation
teaches something false. A template cannot invent a number it was not given,
and the tests below prove it never does.
"""
from __future__ import annotations

import pytest

from bots.autonomous.trade_explainer import (
    LEARNER, TRADER, TradeContext, explain, explain_both,
)

ENTRY = TradeContext(
    tradingsymbol="SILVERM26AUG237000CE", side="entry", strategy="SessionShift",
    strategy_reason="US-overlap uptrend, price above VWAP",
    premium=4638.0, lot_size=5, target=5101.80,
    underlying_price=237155.0, underlying_atr=564.64, stop_atr_mult=1.25,
    edge_score=59.7,
)

WIN = TradeContext(
    tradingsymbol="SILVERM26AUG237000CE", side="exit", strategy="SessionShift",
    premium=4638.0, exit_price=5182.0, lot_size=5, pnl=2720.0,
    exit_reason="TARGET_HIT: premium 5182.00 reached adaptive target 5115.75",
)

LOSS = TradeContext(
    tradingsymbol="GOLDM26AUG153500CE", side="exit", strategy="SessionShift",
    premium=2186.50, exit_price=2018.0, lot_size=10, pnl=-1685.0,
    exit_reason="Underlying Thesis Stop: GOLDM moved 1694 against position",
)


def test_the_learner_register_uses_no_unexplained_jargon():
    """If a term appears it must be defined in the same breath. These are the
    words that make an alert opaque to a non-trader."""
    text = explain(ENTRY, LEARNER)
    for term in ("ATR", "VWAP", "EMA9", "R:R", "delta", "theta"):
        assert term not in text, f"unexplained jargon leaked: {term}"


def test_the_learner_register_defines_what_an_option_is():
    text = explain(ENTRY, LEARNER)
    assert "bet that the price will go UP" in text
    assert "premium" in text
    assert "strike" in text
    assert "expires" in text


def test_the_learner_register_explains_the_stop_as_a_concept():
    text = explain(ENTRY, LEARNER)
    assert "sells automatically" in text
    assert "'stop'" in text


def test_a_put_is_explained_as_a_downward_bet():
    put = TradeContext(tradingsymbol="NIFTY2672124100PE", side="entry")
    text = explain(put, LEARNER)
    assert "PUT" in text and "go DOWN" in text


def test_the_trader_register_keeps_the_jargon_and_the_numbers():
    text = explain(ENTRY, TRADER)
    assert "ATR" in text
    assert "R:R" in text
    assert "SessionShift" in text
    assert "59.7%" in text


def test_both_registers_name_the_instrument_readably():
    for audience in (TRADER, LEARNER):
        text = explain(ENTRY, audience)
        assert "Silver Mini" in text
        assert "SILVERM26AUG237000CE" not in text


def test_a_loss_is_explained_without_blame_or_alarm():
    """A learner reading their first loss should understand it was planned
    for, not that something broke."""
    text = explain(LOSS, LEARNER)
    assert "loss of ₹1,685" in text
    assert "expected and planned for" in text


def test_each_exit_reason_gets_plain_english():
    assert "getting greedy" in explain(WIN, LEARNER)
    assert "no longer held" in explain(LOSS, LEARNER)
    backstop = TradeContext(tradingsymbol="GOLDM26AUG153500CE", side="exit",
                            exit_reason="Option Hard Backstop breached")
    assert "hard safety limit" in explain(backstop, LEARNER)


def test_an_unknown_exit_reason_is_quoted_rather_than_invented():
    """The anti-hallucination rule. If there is no plain-English mapping, say
    the raw reason — never guess at what it meant."""
    odd = TradeContext(tradingsymbol="GOLDM26AUG153500CE", side="exit",
                       exit_reason="SOME_NEW_RUNG_v2")
    text = explain(odd, LEARNER)
    assert "SOME_NEW_RUNG_v2" in text
    assert "He sold because" not in text


def test_missing_fields_are_omitted_not_guessed():
    """A context with almost nothing must still produce a sane sentence and
    must NOT invent a premium, a stop, or a target."""
    bare = TradeContext(tradingsymbol="SILVERM26AUG237000CE", side="entry")
    for audience in (TRADER, LEARNER):
        text = explain(bare, audience)
        assert "Silver Mini" in text
        assert "₹" not in text, "invented a money figure from nothing"
        assert "stop" not in text.lower()
        assert "None" not in text


def test_no_money_figure_appears_without_the_data_to_compute_it():
    """Premium alone is not enough for an outlay — that needs the lot size."""
    partial = TradeContext(tradingsymbol="SILVERM26AUG237000CE", side="entry",
                           premium=4638.0)
    text = explain(partial, LEARNER)
    assert "total spent" not in text


def test_reward_to_risk_is_computed_not_asserted():
    text = explain(ENTRY, LEARNER)
    # risk = 1.25 * 564.64 * 0.45 * 5 = 1588.05; reward = (5101.80-4638)*5 = 2319
    assert "₹1,588" in text and "₹2,319" in text
    assert "1.5 to 1" in text


def test_a_poor_ratio_is_described_honestly():
    """It must not spin a bad trade as a good one."""
    poor = TradeContext(
        tradingsymbol="SILVERM26AUG237000CE", side="entry", premium=4638.0,
        lot_size=5, target=4700.0, underlying_atr=564.64, stop_atr_mult=1.25,
    )
    text = explain(poor, LEARNER)
    assert "needs to be right more often than not" in text


def test_explain_both_returns_two_distinct_registers():
    both = explain_both(ENTRY)
    assert set(both) == {TRADER, LEARNER}
    assert both[TRADER] != both[LEARNER]
    assert len(both[LEARNER]) > len(both[TRADER])


def test_an_unparseable_symbol_still_explains():
    odd = TradeContext(tradingsymbol="MYSTERY9999", side="entry", strategy="X")
    for audience in (TRADER, LEARNER):
        assert "MYSTERY9999" in explain(odd, audience)


def test_explaining_never_performs_io():
    """These run in the alert path. A network call or file read here would put
    latency, and a failure mode, in front of every Telegram message."""
    import bots.autonomous.trade_explainer as mod

    source = mod.__file__
    with open(source, encoding="utf-8") as fh:
        text = fh.read()
    for forbidden in ("requests.", "urlopen", "open(", "sqlite3", "LLMProcessor"):
        assert forbidden not in text, f"{forbidden} has no place in the alert path"
