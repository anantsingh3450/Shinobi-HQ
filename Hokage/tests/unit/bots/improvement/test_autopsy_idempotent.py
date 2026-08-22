"""An autopsy is written once per trade, not once per exit attempt.

The exit loop once fired once per REGISTERED PAPER VENUE rather than once per
position (fixed 2026-08-17), and every firing submitted its own post-exit
analysis. A 2026-07-15 trade left FIVE identical autopsies behind.

That is the ONLY duplication in the corpus — 440 rows, one id repeated, four
extra records. It was originally reported (by me) as "436 records for 61 unique
trades, roughly seven duplicates each", which was wrong: 371 of those rows carry
no trade_id at all and were being counted as collisions. The write path is
append-only though, and nothing prevented a recurrence, so the guard is worth
having even though the damage was four rows.

WHY IT MATTERS AT ALL: this file is what detect_patterns counts. A trade
autopsied five times votes five times on whatever pattern the Pattern Reader
concludes.
"""
from __future__ import annotations

import json

import pytest

from bots.improvement.improvement_bot import ImprovementBot


class _Autopsy:
    def __init__(self, trade_id, symbol="CRUDEOIL26SEP8150CE", pnl=3030.0,
                 entry=429.70, timestamp="2026-08-19T14:39:01"):
        self.trade_id = trade_id
        self.symbol = symbol
        self._d = {"trade_id": trade_id, "symbol": symbol, "pnl": pnl,
                   "entry_price": entry, "timestamp": timestamp,
                   "exit_reason": "TARGET_HIT: premium 460.00"}

    def to_dict(self):
        return dict(self._d)


@pytest.fixture()
def bot(tmp_path, monkeypatch):
    b = object.__new__(ImprovementBot)
    b._autopsies_file = tmp_path / "trade_autopsies.jsonl"
    b._autopsies_file.write_text("", encoding="utf-8")
    return b


def _rows(bot):
    """Parseable records only — one test deliberately seeds a corrupt line,
    and the helper must tolerate exactly what production tolerates."""
    out = []
    for line in bot._autopsies_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def test_the_same_trade_is_written_once(bot):
    a = _Autopsy("mcx-20260819074542")
    bot.process_autopsy(a)
    bot.process_autopsy(a)
    bot.process_autopsy(a)
    assert len(_rows(bot)) == 1


def test_the_2026_07_15_case_would_have_been_one_row(bot):
    """Five firings of the same exit, which is what actually happened."""
    a = _Autopsy("c7d579b1-ded4-4b82-9520-75878c3dae05", "CRUDEOIL26JUL7750CE")
    for _ in range(5):
        bot.process_autopsy(a)
    assert len(_rows(bot)) == 1


def test_distinct_trades_are_all_kept(bot):
    for tid in ("mcx-1", "mcx-2", "mcx-3"):
        bot.process_autopsy(_Autopsy(tid))
    assert sorted(r["trade_id"] for r in _rows(bot)) == ["mcx-1", "mcx-2", "mcx-3"]


def test_id_less_rows_for_ONE_position_collapse_to_one(bot):
    """The 2026-08-22 finding. 378 EOD square-off rows carried no trade_id and
    represented just 42 positions — one CRUDEOIL position wrote 32 identical
    rows a second apart. Keyed on trade_id alone they were invisible."""
    a = _Autopsy(None, symbol="CRUDEOIL26JUL7750CE", entry=63.7,
                 timestamp="2026-07-15T17:45:45")
    for _ in range(32):
        bot.process_autopsy(a)
    assert len(_rows(bot)) == 1


def test_id_less_rows_for_DIFFERENT_positions_are_all_kept(bot):
    """Identity is (symbol, entry, day) — genuinely distinct positions differ in
    at least one, and must survive."""
    bot.process_autopsy(_Autopsy(None, symbol="CRUDEOIL26JUL7750CE", entry=63.7,
                                 timestamp="2026-07-15T17:45:45"))
    bot.process_autopsy(_Autopsy(None, symbol="CRUDEOIL26JUL7750CE", entry=66.8,
                                 timestamp="2026-07-15T18:02:11"))
    bot.process_autopsy(_Autopsy(None, symbol="NATURALGAS26AUG265CE", entry=3.25,
                                 timestamp="2026-07-15T17:45:45"))
    bot.process_autopsy(_Autopsy(None, symbol="CRUDEOIL26JUL7750CE", entry=63.7,
                                 timestamp="2026-07-16T17:45:45"))
    assert len(_rows(bot)) == 4


def test_an_empty_trade_id_falls_back_to_position_identity(bot):
    """An empty string is not an id. It must take the same (symbol, entry, day)
    path as a missing one rather than being treated as a distinct key."""
    for _ in range(3):
        bot.process_autopsy(_Autopsy(""))
    assert len(_rows(bot)) == 1


def test_an_id_beats_position_identity_when_present(bot):
    """Two entries on the same contract at the same premium on the same day
    ARE distinguishable once they carry ids, and must both survive."""
    bot.process_autopsy(_Autopsy("mcx-1", entry=429.70, timestamp="2026-08-19T10:00:00"))
    bot.process_autopsy(_Autopsy("mcx-2", entry=429.70, timestamp="2026-08-19T14:00:00"))
    assert len(_rows(bot)) == 2


def test_a_corrupt_line_does_not_block_the_write(bot):
    """A half-written line from an earlier crash must not make every later
    autopsy look like a duplicate, nor raise."""
    bot._autopsies_file.write_text('{"trade_id": "mcx-1"}\n{not json\n',
                                   encoding="utf-8")
    bot.process_autopsy(_Autopsy("mcx-2"))
    ids = [r["trade_id"] for r in _rows(bot)]
    assert "mcx-2" in ids


def test_a_missing_file_is_not_an_error(bot):
    bot._autopsies_file.unlink()
    assert bot._autopsy_exists("mcx-1") is False
