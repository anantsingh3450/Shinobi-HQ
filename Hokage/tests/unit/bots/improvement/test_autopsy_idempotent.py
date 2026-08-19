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
    def __init__(self, trade_id, symbol="CRUDEOIL26SEP8150CE", pnl=3030.0):
        self.trade_id = trade_id
        self.symbol = symbol
        self._d = {"trade_id": trade_id, "symbol": symbol, "pnl": pnl,
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


def test_records_without_a_trade_id_are_never_deduplicated(bot):
    """371 of the 440 rows on file carry no trade_id. They are DIFFERENT trades
    that predate the field. Treating a missing id as a collision would collapse
    real history into one row."""
    for _ in range(3):
        bot.process_autopsy(_Autopsy(None))
    assert len(_rows(bot)) == 3


def test_an_empty_trade_id_is_treated_the_same_as_a_missing_one(bot):
    for _ in range(3):
        bot.process_autopsy(_Autopsy(""))
    assert len(_rows(bot)) == 3


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
