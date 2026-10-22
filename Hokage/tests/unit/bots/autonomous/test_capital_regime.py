"""A 20,000 account cannot buy anything Hokage trades, and he must say so.

Measured 2026-08-15 on live chain data against the 33% premium cap production
already enforces:

    NATURALGAS  7,688   NIFTY   8,141   SENSEX   9,401   CRUDEOIL 10,950
    BANKNIFTY  16,050   GOLDM  22,755   SILVERM 23,615

The cheapest lot in the entire universe needs a 23,295 account to sit inside
the cap. At the commander's real starting capital of 20,000, every single entry
would be refused at the router — one rejected trade at a time, with nothing
anywhere saying why.

Phase 0 is REPORTING ONLY: no gate consults any of this, no order is refused
because of it. The point is that Hokage knows at 08:45 instead of discovering
it at 11:20.
"""
from __future__ import annotations

import pytest

from bots.autonomous import capital_regime as cr
from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

CAP = 0.33

#: Real prices, 2026-08-15.
LOTS = {
    "NATURALGAS": 7_688.0,
    "NIFTY": 8_141.0,
    "SENSEX": 9_401.0,
    "CRUDEOIL": 10_950.0,
    "BANKNIFTY": 16_050.0,
    "GOLDM": 22_755.0,
    "SILVERM": 23_615.0,
}


def test_the_commanders_real_seed_can_afford_nothing():
    """The finding that drove Phase 0. If this test ever starts failing because
    premiums fell, that is genuinely good news — but it must be noticed, not
    silently assumed."""
    affordable, priced_out = cr.affordable_assets(20_000.0, LOTS, CAP)
    assert affordable == []
    assert len(priced_out) == len(LOTS)


def test_the_minimum_account_for_the_cheapest_lot():
    need = cr.minimum_account_for(LOTS["NATURALGAS"], CAP)
    assert 23_200 < need < 23_400  # 7,688 / 0.33 = 23,296
    affordable, _ = cr.affordable_assets(need, LOTS, CAP)
    assert affordable == ["NATURALGAS"]


@pytest.mark.parametrize(
    "equity,expected",
    [(0.0, cr.SEED), (20_000.0, cr.SEED), (74_999.0, cr.SEED),
     (75_000.0, cr.GROWTH), (200_000.0, cr.GROWTH), (299_999.0, cr.GROWTH),
     (300_000.0, cr.SCALE), (1_000_000.0, cr.SCALE)],
)
def test_regime_boundaries(equity, expected):
    assert cr.regime_for(equity) == expected


def test_todays_live_accounts_land_where_expected():
    """Index 1,83,143 and MCX 3,95,112 as of 2026-08-15."""
    assert cr.regime_for(183_143.75) == cr.GROWTH
    assert cr.regime_for(395_112.50) == cr.SCALE


def test_a_seed_account_demands_a_higher_bar_than_a_grown_one():
    """A small account has fewer trades to average over and no cushion to
    survive a losing run, so it should take only the very best signals.
    (Phase 3 intent — recorded here, not yet enforced anywhere.)"""
    assert cr.profile_for(20_000.0).min_t_stat > cr.profile_for(500_000.0).min_t_stat
    assert cr.profile_for(20_000.0).max_open_positions == 1


def test_an_unpriceable_asset_is_never_reported_as_unaffordable():
    """THE false alarm this must not produce. A feed hiccup means we do not
    KNOW the cost; it does not mean the account is broke. Only symbols that
    actually quoted are ever judged."""
    partial = {"NIFTY": LOTS["NIFTY"]}  # everything else failed to quote
    affordable, priced_out = cr.affordable_assets(100_000.0, partial, CAP)
    assert affordable == ["NIFTY"]
    assert priced_out == []


def test_a_zero_cap_makes_everything_unaffordable_without_dividing_by_zero():
    assert cr.minimum_account_for(7_688.0, 0.0) == float("inf")
    affordable, priced_out = cr.affordable_assets(1e9, LOTS, 0.0)
    assert affordable == []
    assert len(priced_out) == len(LOTS)


# --------------------------------------------------------------- bot wiring
class _Source:
    def __init__(self, quotes: dict[str, float], lot: float = 1.0, boom: bool = False):
        self.quotes, self.lot, self.boom = quotes, lot, boom

    def get_price(self, symbol):
        if self.boom:
            raise RuntimeError("venue down")
        return 100.0

    def resolve_option_contract(self, symbol, option_type, spot):
        if symbol.upper() not in self.quotes:
            return None
        return {"tradingsymbol": f"{symbol}CE", "lot_size": self.lot}

    def get_quote(self, tradingsymbol):
        symbol = tradingsymbol[:-2].upper()
        return type("Q", (), {"price": self.quotes[symbol]})()


def _bot(source):
    bot = object.__new__(Bot)
    bot.orchestrator = type("O", (), {"price_source": source})()
    bot.telegram_bot = None
    return bot


def test_pricing_skips_what_it_cannot_quote_rather_than_guessing():
    bot = _bot(_Source({"NIFTY": 100.0}, lot=75.0))
    costs = bot.price_universe_lots(["NIFTY", "BANKNIFTY", "GOLDM"])
    assert costs == {"NIFTY": 7500.0}


def test_a_dead_venue_prices_nothing_and_raises_no_alarm():
    """The whole point of the retry: silence, not a starvation alarm."""
    bot = _bot(_Source({"NIFTY": 100.0}, boom=True))
    assert bot.price_universe_lots(["NIFTY"]) == {}

    bot._capital_regime_announced = False
    bot._announce_capital_regime()
    # Nothing priced -> must NOT latch, so a later iteration can try again.
    assert bot._capital_regime_announced is False


#: Everything _announce_capital_regime prices. A source that quotes all of it
#: produces a COMPLETE reading; anything less is partial, and partial is the
#: case that went wrong on 2026-10-22.
FULL_UNIVERSE = {s: 100.0 for s in
                 ("NIFTY", "BANKNIFTY", "SENSEX",
                  "CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM")}


def _counted(bot):
    """The bot, with price_universe_lots counting its own calls."""
    calls = {"n": 0}
    real = bot.price_universe_lots

    def _counting(symbols):
        calls["n"] += 1
        return real(symbols)

    bot.price_universe_lots = _counting
    return calls


def test_the_announcement_runs_once_per_boot(monkeypatch):
    """Once per boot — on a COMPLETE reading. The qualifier is the fix:
    before 2026-10-22 this latched on whatever the feed managed."""
    bot = _bot(_Source(FULL_UNIVERSE, lot=75.0))
    monkeypatch.setattr(Bot, "_account_equity", lambda self, acct: 183_143.75)
    calls = _counted(bot)
    for _ in range(10):
        bot._announce_capital_regime()
    assert calls["n"] == 1


# ------------------------------------------ 2026-10-22: the partial reading
# At 08:32, with the venue unauthenticated, three of four MCX symbols priced
# off something cached and NATURALGAS did not. The line read
#
#     MCX Arena: 411,282 -> SCALE regime | can trade CRUDEOIL, GOLDM, SILVERM
#
# Gas was not "priced out" and not "unknown" — it was absent, and the reader
# had to notice an omission. The announcement then latched for the whole day
# and fed an 08:45 Telegram check that said "API: OK".
def test_a_partial_reading_does_not_latch(monkeypatch):
    """The whole universe did not quote, so this is not the day's answer."""
    bot = _bot(_Source({"NIFTY": 100.0, "GOLDM": 100.0}, lot=75.0))
    monkeypatch.setattr(Bot, "_account_equity", lambda self, acct: 411_282.0)
    bot._announce_capital_regime()
    assert getattr(bot, "_capital_regime_announced", False) is False


def test_an_asset_that_did_not_quote_is_named_rather_than_dropped(
        monkeypatch, caplog):
    """MISSING IS NOT ZERO, and it is not affordability either."""
    quotes = dict(FULL_UNIVERSE)
    quotes.pop("NATURALGAS")
    bot = _bot(_Source(quotes, lot=75.0))
    monkeypatch.setattr(Bot, "_account_equity", lambda self, acct: 411_282.0)
    with caplog.at_level("INFO"):
        bot._announce_capital_regime()
    said = " ".join(r.message for r in caplog.records)
    assert "COULD NOT PRICE" in said and "NATURALGAS" in said
    assert "INCOMPLETE" in said


def test_it_latches_once_the_reading_completes(monkeypatch):
    """The retry has to END. A feed that comes up mid-morning gives one
    complete line and then silence for the rest of the day."""
    source = _Source({"NIFTY": 100.0}, lot=75.0)
    bot = _bot(source)
    monkeypatch.setattr(Bot, "_account_equity", lambda self, acct: 411_282.0)
    bot._announce_capital_regime()
    assert getattr(bot, "_capital_regime_announced", False) is False

    source.quotes = dict(FULL_UNIVERSE)          # the login lands
    calls = _counted(bot)
    for _ in range(5):
        bot._announce_capital_regime()
    assert bot._capital_regime_announced is True
    assert calls["n"] == 1, "it must stop pricing once it has a full answer"


def test_the_same_incomplete_reading_is_not_repeated_every_loop(
        monkeypatch, caplog):
    """The loop runs every minute. Announcing the same partial line each time
    would bury the corrected one under hundreds of copies."""
    bot = _bot(_Source({"NIFTY": 100.0}, lot=75.0))
    monkeypatch.setattr(Bot, "_account_equity", lambda self, acct: 411_282.0)
    with caplog.at_level("INFO"):
        for _ in range(6):
            bot._announce_capital_regime()
    spoken = [r for r in caplog.records if "Capital regime" in r.message]
    assert spoken, "the FIRST partial is still worth saying out loud"
    assert len([r for r in spoken if "INCOMPLETE" in r.message]) == 1


def test_a_partial_reading_never_fires_the_starvation_alarm(monkeypatch):
    """CAPITAL STARVED is CRITICAL plus a Telegram message. Firing it off
    three of seven quotes is the false alarm the blind-system work killed."""
    sent: list[str] = []
    # One symbol, priced far beyond the chest: "affordable" is empty, which
    # on a complete reading would be genuine starvation.
    bot = _bot(_Source({"NIFTY": 10_000.0}, lot=75.0))
    bot.telegram_bot = type("T", (), {"send_message": lambda s, m: sent.append(m)})()
    monkeypatch.setattr(Bot, "_account_equity", lambda self, acct: 1_000.0)
    bot._announce_capital_regime()
    assert sent == [], "no starvation claim until the scope is fully priced"


def test_unknown_equity_stays_silent_rather_than_guessing(monkeypatch):
    """A confident regime computed from a guessed equity is worse than none."""
    bot = _bot(_Source({"NIFTY": 100.0}, lot=75.0))
    monkeypatch.setattr(Bot, "_account_equity", lambda self, acct: None)
    bot._announce_capital_regime()  # must not raise
