"""One position must be exited once, not once per registered paper venue.

Observed live 2026-08-17. SIX paper venues are registered (paper_main,
paper_mcx, paper_alpaca, paper_coindcx, paper_oanda, paper_zerodha) and several
share the same underlying account, so `venue.get_positions()` reports the same
position repeatedly. The exit loop then fired per report:

    BANKNIFTY26AUG57600PE  (shared `paper` account, 5 venues)  5 attempts, 4 refused
    GOLDM26AUG153500PE     (alone on paper_mcx)                1 attempt,  0 refused

No money was ever at risk — reduce_only refused each duplicate with "no open
exposure left to close", which is the guard added after the July incident that
created 207 phantom positions. But each refusal logged "position remains open,
skipping exit bookkeeping" about a position that had just CLOSED, and that noise
would hide a genuine repeat-exit condition, which is the very failure the guard
exists to catch.
"""
from __future__ import annotations

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot


class _Instrument:
    def __init__(self, symbol: str):
        self.symbol = symbol


class _Pos:
    def __init__(self, symbol: str, tag: str = ""):
        self.instrument = _Instrument(symbol)
        self.tag = tag


class _Venue:
    def __init__(self, venue_id: str, symbols: list[str], boom: bool = False):
        self.venue_id = venue_id
        self._symbols = symbols
        self._boom = boom

    def get_positions(self):
        if self._boom:
            raise RuntimeError("venue unreachable")
        return [_Pos(s, self.venue_id) for s in self._symbols]


def _collect(bot, venues) -> list:
    """Reproduce the dedupe step exactly as _monitor_and_exit_positions does."""
    by_symbol: dict[str, tuple] = {}
    for venue in venues:
        try:
            venue_positions = venue.get_positions()
        except Exception:
            continue
        for pos in venue_positions:
            symbol = pos.instrument.symbol
            entry_venue = (bot._active_positions_tracking.get(symbol) or {}).get("venue_id")
            if symbol not in by_symbol or venue.venue_id == entry_venue:
                by_symbol[symbol] = (pos, venue)
    return list(by_symbol.values())


def _bot(tracking: dict | None = None):
    bot = object.__new__(Bot)
    bot._active_positions_tracking = tracking or {}
    return bot


def test_the_exact_2026_08_17_fan_out_collapses_to_one():
    """Five venues sharing one account reported BANKNIFTY five times."""
    shared = ["BANKNIFTY26AUG57600PE"]
    venues = [
        _Venue("paper_main", shared), _Venue("paper_alpaca", shared),
        _Venue("paper_coindcx", shared), _Venue("paper_oanda", shared),
        _Venue("paper_zerodha", shared),
        _Venue("paper_mcx", ["GOLDM26AUG153500PE"]),
    ]
    collected = _collect(_bot(), venues)
    symbols = sorted(p.instrument.symbol for p, _ in collected)
    assert symbols == ["BANKNIFTY26AUG57600PE", "GOLDM26AUG153500PE"]
    assert len(collected) == 2, "one position must appear exactly once"


def test_the_exit_goes_back_to_the_venue_the_ENTRY_was_placed_on():
    """BANKNIFTY was entered on paper_zerodha. Exiting on a different book
    would be wrong even when the accounts happen to be shared."""
    shared = ["BANKNIFTY26AUG57600PE"]
    venues = [_Venue("paper_main", shared), _Venue("paper_zerodha", shared),
              _Venue("paper_oanda", shared)]
    bot = _bot({"BANKNIFTY26AUG57600PE": {"venue_id": "paper_zerodha"}})
    (_pos, venue), = _collect(bot, venues)
    assert venue.venue_id == "paper_zerodha"


def test_entry_venue_preference_works_regardless_of_iteration_order():
    shared = ["GOLDM26AUG153500PE"]
    bot = _bot({"GOLDM26AUG153500PE": {"venue_id": "paper_mcx"}})
    for order in ([_Venue("paper_mcx", shared), _Venue("paper_main", shared)],
                  [_Venue("paper_main", shared), _Venue("paper_mcx", shared)]):
        (_pos, venue), = _collect(bot, order)
        assert venue.venue_id == "paper_mcx"


def test_untracked_position_still_gets_exactly_one_exit():
    """A ghost with no tracking entry must still be visited once — it is the
    case that most needs closing, and it must not be skipped."""
    shared = ["ORPHAN26AUG100CE"]
    venues = [_Venue("paper_main", shared), _Venue("paper_oanda", shared)]
    collected = _collect(_bot(), venues)
    assert len(collected) == 1


def test_a_failing_venue_does_not_hide_positions_from_the_others():
    """A venue that throws must not cost visibility of a position another venue
    reports — that would leave a real position unmanaged."""
    venues = [
        _Venue("paper_main", ["NIFTY2672124100PE"], boom=True),
        _Venue("paper_zerodha", ["NIFTY2672124100PE"]),
    ]
    collected = _collect(_bot(), venues)
    assert len(collected) == 1
    assert collected[0][1].venue_id == "paper_zerodha"


def test_distinct_symbols_are_all_kept():
    venues = [_Venue("paper_main", ["A26AUG1CE", "B26AUG2PE"]),
              _Venue("paper_mcx", ["C26AUG3CE"])]
    assert len(_collect(_bot(), venues)) == 3


def test_no_venues_yields_nothing_rather_than_raising():
    assert _collect(_bot(), []) == []


def test_production_actually_dedupes():
    """Guard against the dedupe being refactored away: the source must build a
    symbol-keyed map rather than appending every (pos, venue) pair."""
    from pathlib import Path
    import bots.autonomous.autonomous_bot as mod

    src = Path(mod.__file__).read_text(encoding="utf-8")
    start = src.index("def _monitor_and_exit_positions")
    body = src[start:start + 4000]
    assert "by_symbol" in body, "the exit loop no longer dedupes by symbol"
    assert "positions_with_venue.append" not in body, "raw fan-out has returned"
