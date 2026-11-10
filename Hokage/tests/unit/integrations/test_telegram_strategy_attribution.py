"""Every trade alert must name the strategy that made it.

Four strategies share one paper account. An alert saying a trade happened
without saying WHO made it hides the only thing the tournament exists to
measure, and the commander cannot tell a TrendPullback loss from a Malfoy loss
without opening the dashboard.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from bots.autonomous.autonomous_bot import AutonomousTradingBot
from integrations.notifications.telegram_bot import TelegramBotUplink

_NAME = AutonomousTradingBot._strategy_display_name


def _uplink() -> TelegramBotUplink:
    up = TelegramBotUplink(bot_token="123456:fake", chat_id="777")
    up.send_message = MagicMock(return_value=True)
    return up


def test_entry_alert_names_the_strategy():
    up = _uplink()
    up.notify_entry(symbol="NIFTY2681124500PE", cmp=130.30, target=138.72,
                    edge=71.0, strategy="TrendPullback")
    body = up.send_message.call_args[0][0]
    assert "Strategy" in body and "TrendPullback" in body


def test_exit_alert_names_the_strategy_and_the_money():
    up = _uplink()
    up.notify_exit(symbol="SENSEX2681378300PE", price=449.75,
                   reason="TIERED_PREMIUM_BACKSTOP", strategy="MeanReversion", pnl=-1301.0)
    body = up.send_message.call_args[0][0]
    assert "MeanReversion" in body
    # 2026-08-16: money now carries a currency symbol, with the SIGN OUTSIDE it
    # ("-₹1,301.00", not "₹-1,301.00"). The loss must still be unmistakable.
    assert "-₹1,301.00" in body
    assert "Sensex · 78,300 PUT · 13 Aug expiry" in body


def test_alerts_still_work_without_attribution():
    """Optional, so manual and legacy call sites keep sending."""
    up = _uplink()
    up.notify_entry(symbol="NIFTY", cmp=1.0, target=2.0, edge=0.0)
    body = up.send_message.call_args[0][0]
    assert "Strategy" not in body
    up.notify_exit(symbol="NIFTY", price=1.0, reason="x")
    assert "P&L" not in up.send_message.call_args[0][0]


def test_underscores_in_a_strategy_name_cannot_eat_the_alert():
    """Markdown entity bugs have silently dropped whole alerts before."""
    up = _uplink()
    up.notify_entry(symbol="X", cmp=1.0, target=2.0, edge=0.0, strategy="mean_reversion_v2")
    assert "mean\\_reversion\\_v2" in up.send_message.call_args[0][0]


def _bot_with(strategies: dict) -> SimpleNamespace:
    return SimpleNamespace(
        strategy_portfolio=SimpleNamespace(portfolio={"strategies": strategies}),
        mcx_strategy_portfolio=SimpleNamespace(portfolio={"strategies": {}}),
    )


def test_display_name_resolves_from_the_index_league():
    bot = _bot_with({"strat-trendpullback-v2": {"name": "TrendPullback"}})
    assert _NAME(bot, "strat-trendpullback-v2") == "TrendPullback"


def test_display_name_resolves_from_the_mcx_league():
    bot = _bot_with({})
    bot.mcx_strategy_portfolio = SimpleNamespace(
        portfolio={"strategies": {"strat-trendrider-mcx-v1": {"name": "TrendRider"}}}
    )
    assert _NAME(bot, "strat-trendrider-mcx-v1") == "TrendRider"


def test_manual_commander_trades_are_labelled_as_such():
    assert _NAME(_bot_with({}), "COMMANDER_MANUAL_MCX") == "Commander (manual)"


def test_unknown_id_falls_back_to_the_id_rather_than_inventing_a_name():
    assert _NAME(_bot_with({}), "strat-who-v9") == "strat-who-v9"


def test_no_strategy_id_yields_no_attribution():
    assert _NAME(_bot_with({}), None) is None


# ======================= the alert reports what reached the account
def test_the_exit_alert_headline_is_net_of_charges():
    """The number in the alert was the price move. On the lifetime record
    the broker's cut is 3.2x the whole gross profit, so a per-trade alert
    quoting gross is quoting the wrong number to the only person reading."""
    up = _uplink()
    up.notify_exit(symbol="NATURALGAS26NOV285PE", price=13.90,
                   reason="STOP_LOSS", strategy="TrendRider",
                   pnl=-1000.0, charges=74.11)
    body = up.send_message.call_args[0][0]
    assert "-₹1,074.11" in body
    assert "net of ₹74.11 charges" in body
    assert "gross -₹1,000.00" in body


def test_a_gross_winner_eaten_by_charges_is_not_a_green_exit():
    """The mark is the thing he reads first. A trade that moved 50 in our
    favour and cost 74 is red, and the emoji has to agree with the money."""
    up = _uplink()
    up.notify_exit(symbol="NATURALGAS26NOV285PE", price=14.74,
                   reason="TARGET_HIT", strategy="TrendRider",
                   pnl=50.0, charges=74.11)
    body = up.send_message.call_args[0][0]
    assert body.startswith("🔴")
    assert "-₹24.11" in body


def test_an_alert_with_no_charge_accounting_claims_nothing_about_costs():
    """None is unknown, not free. The old call sites and the live venue pass
    nothing, and the alert must read exactly as it did before."""
    up = _uplink()
    up.notify_exit(symbol="SENSEX2681378300PE", price=449.75,
                   reason="TIERED_PREMIUM_BACKSTOP", pnl=-1301.0)
    body = up.send_message.call_args[0][0]
    assert "-₹1,301.00" in body
    assert "charges" not in body


def test_the_net_line_carries_no_stray_backslash():
    """Legacy Markdown — the parse_mode this bot sends — does not treat
    parentheses as control characters, so escaping them prints the backslash
    to him instead of hiding it."""
    up = _uplink()
    up.notify_exit(symbol="NATURALGAS26NOV285PE", price=13.90,
                   reason="STOP_LOSS", pnl=-1000.0, charges=74.11)
    body = up.send_message.call_args[0][0]
    assert r"\(" not in body and r"\)" not in body
    assert "(gross -₹1,000.00)" in body
