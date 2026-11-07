"""The one component here whose effect has never been measurable.

WHY IT WAS NOT MEASURABLE
veto_lab scores the bias gate over all history and answers in edge_atr - the
UNDERLYING's forward move. Hokage buys options. transfer_lab measured the
conversion at +3.31% of premium per 1.0 ATR (n=15), which puts the gate's
largest confirmed effect at ~1.05% of premium and its 60-minute effect at 0.03
on a 13.90 option, under the 0.05 that is the smallest premium change ever
archived on gas. Those are conversions, not measurements.

The gate itself could not be scored in premium at all, and no amount of history
fixes it: a blocked trade is never bought, so NOTHING HAS EVER PRICED ONE. The
inventory on 2026-11-07 was total - `option_chain` holds one snapshot per day,
`auction_signals` holds the blocked contract's premium at the instant it was
proposed and nothing after it, and all 22 paths in `position_marks` belong to
trades that were TAKEN.

WHAT THESE TESTS ARE ABOUT. Not the answer - the archive will be empty for
days. What has to hold from the start is that only the BIAS gate opens a path
(the conduct gate refuses for several other reasons), that the archive is its
own registry so a restart resumes rather than abandons, that the bound of one
shadow per underlying holds, that two refusals of the same strike stay two
paths, and that nothing in here can disturb the entry loop it sits inside.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from zoneinfo import ZoneInfo

import pytest

from hokage.memory import shadow_path as sp
from hokage.memory import signal_archive as sa

IST = ZoneInfo("Asia/Kolkata")

#: The real refusal of 2026-11-06 19:15: TrendRider won SHORT on gas with the
#: 280 PE at 13.35, and the bias engine blocked it 0.58 ATR from VWAP.
GAS = "NATURALGAS"
REFUSED = "NATURALGAS26NOV280PE"
REFUSED_ENTRY = 13.35
MIRROR = "NATURALGAS26NOV285CE"
T0 = dt.datetime(2026, 11, 6, 19, 15, 10, tzinfo=IST)
BLOCK = "Bias engine: underlying tape is MIXED — standing aside."


class _Sig:
    def __init__(self, enter, direction=None, confidence=0.0, reason=""):
        self.should_enter = enter
        self.direction = direction
        self.confidence = confidence
        self.reason = reason


WINNER = ("strat-trendrider-mcx-v1", "entry-trendrider-mcx-v1",
          _Sig(True, "short", 59.0, "TrendRider: confirmed downtrend."))
LOSER = ("strat-ridertrend-mcx-v1", "entry-ridertrend-mcx-v1",
         _Sig(True, "long", 59.0, "MIRROR of SHORT - by commander hypothesis."))
PRICED = {"short": (REFUSED, REFUSED_ENTRY), "long": (MIRROR, 13.50)}


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "brain"))
    return sp


@pytest.fixture
def scanned(archive):
    """One recorded scan where TrendRider won and both sides were priced."""
    sa.remember_scan(GAS, [WINNER, LOSER], winner_strategy_id=WINNER[0],
                     underlying=282.60, when=T0, premiums=PRICED)
    return T0.isoformat()


def _mark(archive, minutes, premium, scanned_at=None, symbol=REFUSED,
          underlying=GAS, entry=REFUSED_ENTRY):
    return archive.remember(
        symbol, premium, entry, underlying=underlying,
        scanned_at=scanned_at or T0.isoformat(), direction="short",
        blocked_by=BLOCK, module_id="entry-trendrider-mcx-v1",
        when=T0 + dt.timedelta(minutes=minutes))


# ============================================== only the bias gate opens a path
def test_a_bias_block_is_recognised():
    for reason in (
        "Bias engine: underlying tape is MIXED — standing aside.",
        "Bias engine: bearish entry against a BULLISH tape.",
        "Bias engine: bullish entry against a BEARISH tape.",
    ):
        assert sp.is_gate_block(reason) is True


def test_every_other_refusal_is_not_this_gate():
    """`_entry_conduct_gate` returns ONE reason string for several different
    refusals. A shadow path for the IV guard or the session cutoff would be
    measuring something nobody asked about."""
    for reason in (
        "India VIX in the top quintile — premium too rich.",
        "Late-session cutoff (15:00 IST): no new entries into the close.",
        "PRECIOUS(corr 0.87) family already holds 1 position.",
        "",
        None,
    ):
        assert sp.is_gate_block(reason) is False


# ======================================================= a mark is an observation
def test_a_mark_carries_the_refusal_that_caused_it(archive):
    assert _mark(archive, 0, REFUSED_ENTRY) is True
    row = archive.path_for(REFUSED)[0]
    assert row["symbol"] == REFUSED
    assert row["entry"] == REFUSED_ENTRY
    assert row["underlying"] == GAS
    assert row["blocked_by"] == BLOCK
    assert row["direction"] == "short"


def test_the_path_runs_oldest_first(archive):
    for minutes, premium in ((0, 13.35), (15, 13.80), (60, 12.90)):
        _mark(archive, minutes, premium)
    assert [r["premium"] for r in archive.path_for(REFUSED)] == [13.35, 13.80, 12.90]


@pytest.mark.parametrize("premium,entry", [(0.0, 13.35), (-1.0, 13.35),
                                           (13.35, 0.0), (13.35, -1.0)])
def test_a_bad_print_is_refused(archive, premium, entry):
    """A premium at or below zero is a dead quote, never a free option."""
    assert archive.remember(REFUSED, premium, entry, underlying=GAS,
                            scanned_at=T0.isoformat()) is False
    assert archive.path_for(REFUSED) == []


def test_a_mark_with_no_scan_to_attach_it_to_is_refused(archive):
    """Without the scan, two refusals of the same strike cannot be told apart
    and would merge into one path."""
    assert archive.remember(REFUSED, 13.35, REFUSED_ENTRY, underlying=GAS,
                            scanned_at="") is False


def test_a_mark_with_no_underlying_is_refused(archive):
    assert archive.remember(REFUSED, 13.35, REFUSED_ENTRY, underlying="",
                            scanned_at=T0.isoformat()) is False


def test_an_instant_is_never_overwritten(archive):
    _mark(archive, 0, 13.35)
    _mark(archive, 0, 99.99)
    assert [r["premium"] for r in archive.path_for(REFUSED)] == [13.35]


# ======================================= two refusals of one strike stay two
def test_the_same_strike_refused_twice_is_two_paths(archive):
    """Gas was refused eight times on 2026-11-06, twice on the same contract.
    A key of (symbol, observed_at) would merge two separate refusals."""
    later = (T0 + dt.timedelta(minutes=15)).isoformat()
    _mark(archive, 0, 13.35)
    _mark(archive, 0, 13.35, scanned_at=later)
    assert len(archive.path_for(REFUSED)) == 2
    assert len(archive.path_for(REFUSED, scanned_at=T0.isoformat())) == 1
    assert len(archive.path_for(REFUSED, scanned_at=later)) == 1


def test_a_path_is_read_by_its_own_scan(archive):
    later = (T0 + dt.timedelta(minutes=15)).isoformat()
    _mark(archive, 0, 13.35)
    _mark(archive, 16, 14.00, scanned_at=later)
    assert [r["premium"] for r in
            archive.path_for(REFUSED, scanned_at=later)] == [14.00]


# ========================================== the archive IS the live registry
def test_a_fresh_refusal_is_live(archive):
    _mark(archive, 0, 13.35)
    live = archive.live(when=T0 + dt.timedelta(minutes=5))
    assert len(live) == 1
    assert live[0]["symbol"] == REFUSED
    assert live[0]["entry"] == REFUSED_ENTRY
    assert live[0]["scanned_at"] == T0.isoformat()


def test_a_refusal_past_its_window_is_no_longer_live(archive):
    _mark(archive, 0, 13.35)
    assert archive.live(when=T0 + dt.timedelta(
        minutes=sp.WINDOW_MINUTES + 1)) == []


def test_the_window_is_the_longest_horizon_the_labs_score():
    """veto_lab scores 2, 4 and 8 fifteen-minute bars, so a 120-minute path can
    be sliced at 30 and 60 without being collected twice."""
    assert sp.WINDOW_MINUTES == 120


def test_only_one_shadow_per_underlying_is_live(archive):
    """THE BOUND. A 15-minute scan and a 120-minute window would otherwise
    stack eight shadows on one asset and quote all of them every tick."""
    for i in range(4):
        _mark(archive, i * 15, 13.35,
              scanned_at=(T0 + dt.timedelta(minutes=i * 15)).isoformat())
    live = archive.live(when=T0 + dt.timedelta(minutes=50))
    assert len(live) == 1


def test_the_newest_refusal_is_the_one_tracked(archive):
    """That is the trade Hokage would have had open NOW."""
    later = T0 + dt.timedelta(minutes=30)
    _mark(archive, 0, 13.35)
    _mark(archive, 30, 14.00, scanned_at=later.isoformat())
    live = archive.live(when=T0 + dt.timedelta(minutes=35))
    assert live[0]["scanned_at"] == later.isoformat()


def test_two_assets_are_both_live_at_once(archive):
    _mark(archive, 0, 13.35)
    _mark(archive, 0, 3035.50, symbol="GOLDM26NOV138500PE",
          underlying="GOLDM", entry=3035.50)
    live = archive.live(when=T0 + dt.timedelta(minutes=5))
    assert {s["underlying"] for s in live} == {GAS, "GOLDM"}


def test_a_restart_resumes_the_path_rather_than_abandoning_it(archive):
    """There is no state file and no in-memory set: what is live is whatever
    was written recently enough, so a fresh process picks the path back up."""
    _mark(archive, 0, 13.35)
    _mark(archive, 15, 13.80)
    live = archive.live(when=T0 + dt.timedelta(minutes=20))
    assert live[0]["marks"] == 2
    assert live[0]["entry"] == REFUSED_ENTRY        # still the refusal price


def test_yesterdays_refusal_is_not_live_today(archive):
    _mark(archive, 0, 13.35)
    assert archive.live(when=T0 + dt.timedelta(days=1)) == []


# ================================================== empty reads stay quiet
def test_reading_an_archive_that_does_not_exist_is_empty_not_an_error(archive):
    assert archive.path_for(REFUSED) == []
    assert archive.live() == []
    assert archive.coverage() == {"rows": 0, "shadows": 0, "first_day": None,
                                  "last_day": None, "armed": False}


def test_coverage_says_whether_the_table_exists_at_all(archive):
    """ROWS=0 IS TWO DIFFERENT FACTS - never wired, or nothing to show - and
    reading them as one is how mirror_marks got reported live on 2026-11-06
    when it had never been reached."""
    assert archive.coverage()["armed"] is False
    _mark(archive, 0, 13.35)
    cov = archive.coverage()
    assert cov["armed"] is True and cov["rows"] == 1 and cov["shadows"] == 1


def test_coverage_counts_refusals_not_rows(archive):
    _mark(archive, 0, 13.35)
    _mark(archive, 15, 13.80)
    _mark(archive, 0, 13.35, scanned_at=(T0 + dt.timedelta(minutes=30)).isoformat())
    cov = archive.coverage()
    assert cov["rows"] == 3 and cov["shadows"] == 2


# ===================================== it must not contaminate the trail study
def test_a_shadow_mark_never_enters_position_marks(archive):
    """THE RAIL. trail_arm_lab does SELECT DISTINCT symbol, day FROM
    position_marks and treats each one as a position that was HELD. A path for
    a contract nobody bought would enter that study as a trade."""
    _mark(archive, 0, 13.35)
    con = sqlite3.connect(sp.db_path())
    try:
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "shadow_marks" in tables
        if "position_marks" in tables:
            assert con.execute("SELECT COUNT(*) FROM position_marks"
                               " WHERE symbol = ?", (REFUSED,)).fetchone()[0] == 0
    finally:
        con.close()


def test_it_shares_the_history_store_with_the_other_paths(archive):
    """candles.db, not hokage.db, which gets pruned. This is meant to be read
    in three months."""
    assert sp.db_path().name == "candles.db"


# ========================================== the winning leg comes from the scan
def test_the_refused_contract_is_read_off_the_scan(archive, scanned):
    leg = sa.winning_leg(GAS, scanned)
    assert leg["option_symbol"] == REFUSED
    assert leg["option_premium"] == REFUSED_ENTRY
    assert leg["direction"] == "short"


def test_the_loser_is_never_mistaken_for_the_winner(archive, scanned):
    """winning_leg and opposing_leg must not return the same row, or the
    shadow would price the side that lost the auction - which mirror_path
    already does, for a different question."""
    win = sa.winning_leg(GAS, scanned)
    lose = sa.opposing_leg(GAS, scanned, win["option_symbol"])
    assert win["option_symbol"] == REFUSED
    assert lose["option_symbol"] == MIRROR


def test_a_scan_with_no_winner_yields_no_leg(archive):
    sa.remember_scan(GAS, [LOSER], winner_strategy_id=None,
                     underlying=282.60, when=T0, premiums=PRICED)
    assert sa.winning_leg(GAS, T0.isoformat()) is None


def test_an_unpriceable_winner_yields_no_leg(archive):
    """A leg with no entry premium cannot start a path. Absent is not zero."""
    sa.remember_scan(GAS, [WINNER], winner_strategy_id=WINNER[0],
                     underlying=282.60, when=T0, premiums={})
    assert sa.winning_leg(GAS, T0.isoformat()) is None


def test_no_scan_yields_no_leg(archive):
    assert sa.winning_leg(GAS, "") is None
    assert sa.winning_leg(GAS, T0.isoformat()) is None


# ============================================ what the bot stores and reads
@pytest.fixture
def bot():
    """A bare bot: the shadow hooks read nothing off the engine except
    orchestrator.price_source and _active_positions_tracking."""
    from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot
    b = Bot.__new__(Bot)
    b._active_positions_tracking = {}
    return b


class _Quote:
    def __init__(self, price):
        self.price = price


class _Source:
    def __init__(self, prices):
        self.prices = prices
        self.asked: list[str] = []

    def get_quote(self, symbol):
        self.asked.append(symbol)
        if symbol not in self.prices:
            raise KeyError(symbol)
        return _Quote(self.prices[symbol])


class _Orchestrator:
    def __init__(self, source):
        self.price_source = source


def _wire(bot, prices):
    source = _Source(prices)
    bot.orchestrator = _Orchestrator(source)
    return source


def test_a_bias_block_opens_a_path_at_the_refusal_price(archive, scanned, bot):
    bot._start_shadow_path(GAS, scanned, BLOCK)
    path = archive.path_for(REFUSED, scanned_at=scanned)
    assert len(path) == 1
    assert path[0]["premium"] == REFUSED_ENTRY
    assert path[0]["entry"] == REFUSED_ENTRY
    assert path[0]["blocked_by"] == BLOCK


def test_another_gate_opens_nothing(archive, scanned, bot):
    bot._start_shadow_path(GAS, scanned, "India VIX in the top quintile.")
    assert archive.path_for(REFUSED) == []


def test_no_path_opens_while_that_symbol_holds_a_position(archive, scanned, bot):
    """A symbol already holding a position had no trade to lose."""
    bot._active_positions_tracking = {GAS: {"venue_id": "paper_mcx"}}
    bot._start_shadow_path(GAS, scanned, BLOCK)
    assert archive.path_for(REFUSED) == []


def test_a_second_refusal_does_not_open_a_second_live_path(archive, scanned, bot):
    """The bound, enforced where the path is opened and not only where it is
    read."""
    bot._start_shadow_path(GAS, scanned, BLOCK)
    later = (T0 + dt.timedelta(minutes=15)).isoformat()
    sa.remember_scan(GAS, [WINNER, LOSER], winner_strategy_id=WINNER[0],
                     underlying=281.00, when=T0 + dt.timedelta(minutes=15),
                     premiums=PRICED)
    bot._start_shadow_path(GAS, later, BLOCK)
    assert len(archive.path_for(REFUSED, scanned_at=later)) == 0


def test_a_block_with_no_recorded_scan_writes_nothing_and_does_not_raise(
        archive, bot):
    bot._start_shadow_path(GAS, None, BLOCK)
    bot._start_shadow_path(GAS, "2026-11-06T00:00:00+05:30", BLOCK)
    assert archive.path_for(REFUSED) == []


def test_the_tick_prices_every_live_shadow(archive, scanned, bot):
    bot._start_shadow_path(GAS, scanned, BLOCK)
    source = _wire(bot, {REFUSED: 12.90})
    bot._poll_shadow_paths()
    path = archive.path_for(REFUSED, scanned_at=scanned)
    assert [r["premium"] for r in path] == [REFUSED_ENTRY, 12.90]
    assert source.asked == [REFUSED]


def test_the_tick_asks_for_exactly_one_quote_per_shadow(archive, scanned, bot):
    """The cost bound, measured rather than asserted in a comment."""
    bot._start_shadow_path(GAS, scanned, BLOCK)
    source = _wire(bot, {REFUSED: 12.90})
    bot._poll_shadow_paths()
    assert len(source.asked) == 1


def test_the_entry_price_is_carried_forward_not_re_read(archive, scanned, bot):
    """Every mark must measure against the premium at the REFUSAL. Re-reading
    the current price as the entry would make every percentage zero."""
    bot._start_shadow_path(GAS, scanned, BLOCK)
    _wire(bot, {REFUSED: 12.90})
    bot._poll_shadow_paths()
    assert {r["entry"] for r in archive.path_for(REFUSED)} == {REFUSED_ENTRY}


def test_a_dead_quote_is_skipped_silently(archive, scanned, bot):
    bot._start_shadow_path(GAS, scanned, BLOCK)
    _wire(bot, {REFUSED: 0.0})
    bot._poll_shadow_paths()
    assert len(archive.path_for(REFUSED, scanned_at=scanned)) == 1


def test_an_unquotable_contract_is_skipped_silently(archive, scanned, bot):
    bot._start_shadow_path(GAS, scanned, BLOCK)
    _wire(bot, {})
    bot._poll_shadow_paths()
    assert len(archive.path_for(REFUSED, scanned_at=scanned)) == 1


def test_the_tick_does_nothing_when_nothing_is_live(archive, bot):
    source = _wire(bot, {REFUSED: 12.90})
    bot._poll_shadow_paths()
    assert source.asked == []


def test_the_tick_survives_a_missing_price_source(archive, scanned, bot):
    """It sits on the monitoring tick, which must not be taken down by an
    experiment."""
    bot._start_shadow_path(GAS, scanned, BLOCK)
    bot.orchestrator = _Orchestrator(None)
    bot._poll_shadow_paths()
    assert len(archive.path_for(REFUSED, scanned_at=scanned)) == 1


def test_the_entry_path_calls_the_opener_after_the_journal():
    """The journal row is the decision's audit trail; the shadow is an
    experiment. If an experiment can throw before the journal is written, a
    refusal could go unrecorded."""
    from pathlib import Path
    src = Path("src/bots/autonomous/autonomous_bot.py").read_text(encoding="utf-8")
    block = src.split("MCX Arena entry blocked for {symbol}: {conduct_reason}")[1]
    journal = block.index("_journal_no_trade")
    shadow = block.index("_start_shadow_path")
    assert journal < shadow


def test_the_monitor_tick_polls_the_shadows():
    from pathlib import Path
    src = Path("src/bots/autonomous/autonomous_bot.py").read_text(encoding="utf-8")
    monitor = src.split("def _monitor_and_exit_positions")[1][:2000]
    assert "_poll_shadow_paths()" in monitor
