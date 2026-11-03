"""The one number in a scan that cannot be recovered later.

2026-11-03. The mirror experiment — "every time it takes a call, take a put" —
had run eleven days on natural gas and could not be settled. A mirror loses
every tie to its original by design, so it never fills and has no premium
path; and on the UNDERLYING its edge is exactly minus its original's, which is
no information at all. The distinction the experiment exists to measure —
wrong about DIRECTION versus wrong about MOVEMENT — lives only in premium,
because both sides BUY options and both pay theta and the spread.

An option's history dies with its contract. So the cost of the trade a losing
side would have taken can only ever be written down at the instant it was
proposed; no later archiving can go back for it. That is what this captures.

WHAT THESE TESTS ARE REALLY GUARDING. The capture sits in the live scan loop.
It runs after the auction is already settled, and the rules it must obey are
that it cannot raise, cannot change a decision, cannot cost more than two
quotes a scan, and cannot write a number it did not get from the venue. A
missing premium is a NULL; 0.0 is a price the market might really have quoted,
and writing it for "we could not ask" would put a fabricated fill in the
corpus.
"""
from __future__ import annotations

import sqlite3

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot
from hokage.memory import signal_archive as sa


class _Sig:
    def __init__(self, fired=True, direction="long", confidence=70.0, reason="r"):
        self.should_enter = fired
        self.direction = direction
        self.confidence = confidence
        self.reason = reason


class _Quote:
    def __init__(self, price):
        self.price = price


class _Source:
    """A price source that records what it was asked."""

    def __init__(self, premium=18.4, contracts=True, raises=False):
        self.premium, self.contracts, self.raises = premium, contracts, raises
        self.resolved: list[tuple] = []
        self.quoted: list[str] = []

    def resolve_option_contract(self, symbol, option_type, price):
        self.resolved.append((symbol, option_type, price))
        if self.raises:
            raise RuntimeError("chain unavailable")
        if not self.contracts:
            return None
        return {"tradingsymbol": f"{symbol}26NOV275{option_type}", "lot_size": 1250}

    def get_quote(self, tradingsymbol):
        self.quoted.append(tradingsymbol)
        return _Quote(self.premium)


class _Bot(AutonomousTradingBot):
    """The real method, no broker and no boot."""

    def __init__(self, source):
        class _Orch:
            price_source = source
        self.orchestrator = _Orch()


@pytest.fixture
def archive(tmp_path, monkeypatch):
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "brain"))
    return sa


# ========================================================= the capture
def test_a_fired_side_is_priced():
    source = _Source(premium=18.4)
    verdicts = [("strat-a", "mod-a", _Sig(direction="long"))]
    out = _Bot(source)._scan_premiums("NATURALGAS", verdicts, 276.3)
    assert out == {"long": ("NATURALGAS26NOV275CE", 18.4)}


def test_long_buys_a_call_and_short_buys_a_put():
    source = _Source()
    verdicts = [("strat-a", "mod-a", _Sig(direction="long")),
                ("strat-b", "mod-b", _Sig(direction="short"))]
    _Bot(source)._scan_premiums("NATURALGAS", verdicts, 276.3)
    assert sorted(t for _s, t, _p in source.resolved) == ["CE", "PE"]


def test_a_mirror_and_its_original_cost_two_quotes_not_four():
    """A mirror fires on the same bar with the opposite direction, so the map
    is keyed by DIRECTION. Four modules firing two directions is still one CE
    and one PE."""
    source = _Source()
    verdicts = [
        ("strat-trendrider", "entry-trendrider", _Sig(direction="long")),
        ("strat-ridertrend", "entry-ridertrend", _Sig(direction="short")),
        ("strat-rangefade", "entry-rangefade", _Sig(direction="long")),
        ("strat-faderange", "entry-faderange", _Sig(direction="short")),
    ]
    _Bot(source)._scan_premiums("NATURALGAS", verdicts, 276.3)
    assert len(source.quoted) == 2


def test_a_stand_aside_is_never_priced():
    """It proposed no trade, so there is no contract it would have bought."""
    source = _Source()
    verdicts = [("strat-a", "mod-a", _Sig(fired=False, direction=None))]
    assert _Bot(source)._scan_premiums("NATURALGAS", verdicts, 276.3) == {}
    assert source.resolved == []


# ========================================================= it must not break a scan
def test_a_raising_resolver_costs_a_null_and_nothing_else():
    source = _Source(raises=True)
    verdicts = [("strat-a", "mod-a", _Sig(direction="long"))]
    assert _Bot(source)._scan_premiums("NATURALGAS", verdicts, 276.3) == {}


def test_no_contract_means_no_row_rather_than_a_guess():
    source = _Source(contracts=False)
    verdicts = [("strat-a", "mod-a", _Sig(direction="long"))]
    assert _Bot(source)._scan_premiums("NATURALGAS", verdicts, 276.3) == {}


def test_a_zero_premium_is_refused():
    """0.0 is a price the venue might really have quoted, so it cannot double
    as "we could not ask"."""
    source = _Source(premium=0.0)
    verdicts = [("strat-a", "mod-a", _Sig(direction="long"))]
    assert _Bot(source)._scan_premiums("NATURALGAS", verdicts, 276.3) == {}


def test_no_underlying_price_asks_nothing():
    source = _Source()
    verdicts = [("strat-a", "mod-a", _Sig(direction="long"))]
    assert _Bot(source)._scan_premiums("NATURALGAS", verdicts, None) == {}
    assert _Bot(source)._scan_premiums("NATURALGAS", verdicts, 0.0) == {}
    assert source.resolved == []


def test_a_source_with_no_option_chain_is_not_an_error():
    class _Bare:
        pass

    verdicts = [("strat-a", "mod-a", _Sig(direction="long"))]
    assert _Bot(_Bare())._scan_premiums("NATURALGAS", verdicts, 276.3) == {}


def test_an_unknown_direction_is_skipped():
    source = _Source()
    verdicts = [("strat-a", "mod-a", _Sig(direction="sideways"))]
    assert _Bot(source)._scan_premiums("NATURALGAS", verdicts, 276.3) == {}
    assert source.resolved == []


# ========================================================= what lands in the archive
def _read(archive, column):
    con = sqlite3.connect(archive.db_path())
    try:
        return [r[0] for r in con.execute(
            f"SELECT {column} FROM auction_signals ORDER BY strategy_id")]
    finally:
        con.close()


def test_the_premium_is_stored_against_the_side_that_fired(archive):
    archive.remember_scan(
        "NATURALGAS",
        [("strat-a", "mod-a", _Sig(direction="long")),
         ("strat-b", "mod-b", _Sig(direction="short"))],
        underlying=276.3,
        premiums={"long": ("NATURALGAS26NOV275CE", 18.4),
                  "short": ("NATURALGAS26NOV275PE", 21.1)},
    )
    assert _read(archive, "option_symbol") == [
        "NATURALGAS26NOV275CE", "NATURALGAS26NOV275PE"]
    assert _read(archive, "option_premium") == [18.4, 21.1]


def test_a_side_with_no_quote_is_null_not_zero(archive):
    archive.remember_scan(
        "NATURALGAS",
        [("strat-a", "mod-a", _Sig(direction="long")),
         ("strat-b", "mod-b", _Sig(direction="short"))],
        underlying=276.3,
        premiums={"long": ("NATURALGAS26NOV275CE", 18.4)},
    )
    assert _read(archive, "option_premium") == [18.4, None]


def test_a_stand_aside_stores_no_contract(archive):
    archive.remember_scan(
        "NATURALGAS",
        [("strat-a", "mod-a", _Sig(fired=False, direction=None))],
        underlying=276.3,
        premiums={"long": ("NATURALGAS26NOV275CE", 18.4)},
    )
    assert _read(archive, "option_symbol") == [None]


def test_no_premiums_at_all_still_records_the_scan(archive):
    """Every caller that predates this writes no premiums, and a scan without
    one is still the record of an auction."""
    n = archive.remember_scan(
        "NATURALGAS", [("strat-a", "mod-a", _Sig())], underlying=276.3)
    assert n == 1
    assert _read(archive, "option_premium") == [None]


# ========================================================= the migration
def test_an_existing_old_shape_table_gains_the_columns(archive, tmp_path):
    """CREATE TABLE IF NOT EXISTS does nothing to a table that already exists.
    Without an explicit ALTER, every brain already in the field would keep
    writing the old shape and the lab would read NULLs forever."""
    path = archive.db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript("""
        CREATE TABLE auction_signals (
            scanned_at TEXT NOT NULL, day TEXT NOT NULL, symbol TEXT NOT NULL,
            strategy_id TEXT NOT NULL, module_id TEXT, fired INTEGER NOT NULL,
            direction TEXT, confidence REAL, won INTEGER NOT NULL,
            filled INTEGER, underlying REAL, reason TEXT,
            PRIMARY KEY (scanned_at, symbol, strategy_id));
    """)
    con.execute(
        "INSERT INTO auction_signals VALUES"
        " ('2026-11-01T10:00:00','2026-11-01','NATURALGAS','old','m',1,"
        "  'long',70.0,1,NULL,275.0,'before the migration')")
    con.commit()
    con.close()

    fresh = archive.connect()
    try:
        cols = {r[1] for r in fresh.execute("PRAGMA table_info(auction_signals)")}
        assert {"option_symbol", "option_premium"} <= cols
        kept = fresh.execute(
            "SELECT reason FROM auction_signals WHERE strategy_id = 'old'"
        ).fetchone()
        assert kept[0] == "before the migration", "the migration lost a row"
    finally:
        fresh.close()


def test_the_migration_runs_twice_without_complaint(archive):
    archive.connect().close()
    archive.connect().close()
    archive.remember_scan("NATURALGAS", [("strat-a", "mod-a", _Sig())],
                          premiums={"long": ("X26NOV1CE", 5.0)})
    assert _read(archive, "option_premium") == [5.0]
