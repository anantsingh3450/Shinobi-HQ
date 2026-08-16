"""`why` must be answered from recorded facts, never from a language model.

Left to the normal route, "why did you buy that" reaches the conversation
engine's keyword cascade and then a bare LLM call with NO data attached — which
is where the phantom narratives in the logs came from. `handle_why` intercepts
first and answers from the same TradeContext that produced the alert, or admits
it has nothing. It never guesses.
"""
from __future__ import annotations

import pytest

from bots.autonomous.trade_explainer import TradeContext
from integrations.notifications.telegram_bot import TelegramBotUplink

ENTRY = TradeContext(
    tradingsymbol="SILVERM26AUG237000CE", side="entry", strategy="SessionShift",
    strategy_reason="US-overlap uptrend, price above VWAP",
    premium=4638.0, lot_size=5, target=5101.80,
    underlying_atr=564.64, stop_atr_mult=1.25, edge_score=59.7,
)
GOLD = TradeContext(
    tradingsymbol="GOLDM26AUG153500CE", side="exit", strategy="SessionShift",
    premium=2186.50, exit_price=2018.0, lot_size=10, pnl=-1685.0,
    exit_reason="Underlying Thesis Stop: GOLDM moved 1694 against position",
)


@pytest.fixture
def bot(monkeypatch):
    up = TelegramBotUplink()
    monkeypatch.setattr(up, "send_message", lambda text: True)
    return up


def test_text_that_is_not_a_why_question_is_left_alone(bot):
    """Returning None is what lets normal routing continue."""
    for text in ("status", "exit nifty", "how are you", "buy banknifty put", ""):
        assert bot.handle_why(text) is None


@pytest.mark.parametrize("text", ["why", "Why?", "  why  ", "why did you do that",
                                  "explain", "why simple"])
def test_why_phrasings_are_all_recognised(bot, text):
    bot._remember(ENTRY)
    assert bot.handle_why(text) is not None


def test_with_nothing_recorded_it_admits_it_rather_than_inventing(bot):
    """The anti-hallucination case. No data must produce an admission, never
    a plausible story."""
    reply = bot.handle_why("why")
    assert "no trade recorded" in reply.lower()
    assert "SILVERM" not in reply


def test_plain_why_gives_the_trader_register(bot):
    """The alert already carried the plain-English version, so `why` adds the
    depth that was NOT already sent."""
    bot._remember(ENTRY)
    reply = bot.handle_why("why")
    assert "ATR" in reply
    assert "R:R" in reply


def test_why_simple_gives_the_learner_register(bot):
    bot._remember(ENTRY)
    reply = bot.handle_why("why simple")
    assert "bet that the price will go UP" in reply
    assert "ATR" not in reply
    assert "VWAP" not in reply


def test_the_trader_reply_offers_the_simple_one(bot):
    bot._remember(ENTRY)
    assert "why simple" in bot.handle_why("why")
    # ...and does not offer it again when already simple.
    assert "why simple" not in bot.handle_why("why simple").replace("`why simple`", "")


def test_it_answers_about_the_most_recent_trade_by_default(bot):
    bot._remember(ENTRY)
    bot._remember(GOLD)
    reply = bot.handle_why("why")
    assert "Gold Mini" in reply
    assert "Silver Mini" not in reply


def test_a_named_asset_selects_that_trade(bot):
    bot._remember(ENTRY)
    bot._remember(GOLD)
    assert "Silver Mini" in bot.handle_why("why silver")
    assert "Gold Mini" in bot.handle_why("why gold")


def test_an_unknown_asset_says_so_instead_of_answering_about_another(bot):
    """Silently answering about a different trade would be worse than useless
    — the commander would believe he had asked about the one he named."""
    bot._remember(ENTRY)
    reply = bot.handle_why("why crude")
    assert "nothing recorded" in reply.lower()
    assert "crude" in reply.lower()


def test_the_journal_is_capped_and_keeps_the_NEWEST(bot):
    for i in range(40):
        bot._remember(TradeContext(tradingsymbol=f"NATURALGAS26AUG{200 + i}CE"))
    assert len(bot._journal) == TelegramBotUplink._WHY_JOURNAL_SIZE
    assert bot._journal[-1].tradingsymbol == "NATURALGAS26AUG239CE"


def test_alerts_populate_the_journal(bot):
    bot.notify_entry(symbol=ENTRY.tradingsymbol, cmp=4638.0, target=5101.8,
                     edge=59.7, strategy="SessionShift", context=ENTRY)
    assert bot.handle_why("why") is not None


def test_an_alert_without_a_context_records_nothing(bot):
    """Half a trade is not answerable. Better to say nothing is recorded than
    to explain a trade using fields we never received."""
    bot.notify_exit(symbol="NIFTY2672124100PE", price=0.0, reason="ghost flatten")
    assert "no trade recorded" in bot.handle_why("why").lower()


def test_why_never_reaches_the_language_model(bot, monkeypatch):
    """The whole point of intercepting early."""
    def _boom(*_args, **_kwargs):
        raise AssertionError("the LLM must not be consulted for `why`")

    monkeypatch.setattr(bot, "_conversational_reply", _boom)
    bot._remember(ENTRY)
    assert bot.handle_why("why") is not None
