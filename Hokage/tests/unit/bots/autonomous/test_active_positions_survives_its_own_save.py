"""The file holding every stop and target was destroyed by writing it.

2026-10-28 15:16:50 was the first of 168 identical lines across two days:

    [ERROR] Hokage.AutonomousTrading: Failed to save active positions:
            Object of type datetime is not JSON serializable

One minute apart, every minute a position was open. The cause was three
characters wide - the premium-path archive stamped `tracking["_archived_at"]`
with a `datetime`, and that same dict is `json.dump`ed to
active_positions.json on every tick.

THE DAMAGE WAS NOT THE ERROR LINE. json.dump streams into a handle already
opened "w", so the truncate happens BEFORE the first byte is written. Every
one of those 168 failures cut the real file off mid-key. Checked live on
2026-10-29 with two positions open, it ended:

      "trough_price": 19.25,
      "_archived_at":

- 660 bytes, invalid JSON, and `_load_positions_tracking` turns invalid JSON
into `{}`. An empty dict is how this bot says "flat". So a restart, a crash
or another critical-battery sleep would have brought Hokage back with two
live positions and NO stop and NO target on either, reporting nothing worse
than one ERROR among thousands at boot.

The same shape as every other wound in this repo: the dead token that
reported Health Score 100/100, the watcher whose read error was swallowed as
"no change", the ledger that answered 0 because it was written at EOD.
MISSING IS NOT ZERO, AND UNREADABLE IS NOT EMPTY.

WHAT THIS FILE PINS: that a save which cannot serialize something leaves the
previous file intact, that the stamp which started it stays JSON-native, and
that an unreadable file arrives as an alarm with its bytes kept rather than
as a quiet fresh start.
"""
from __future__ import annotations

import json

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot


def _bot(tmp_path):
    bot = object.__new__(Bot)
    bot._positions_file = tmp_path / "active_positions.json"
    bot._active_positions_tracking = {}
    return bot


#: A FUNCTION, not a module-level dict. This started life as a constant
#: copied with `dict(...)` - a shallow copy - so the test that stamps a
#: datetime onto the position reached through it into the shared inner dict,
#: and two later tests compared against a baseline that had already been
#: changed. The fixture equivalent of a global.
def _good() -> dict:
    return {
        "NATURALGAS26NOV290CE": {
            "entry_price": 19.7,
            "stop_price": 18.715,
            "target_price": 20.8,
        }
    }


# ------------------------------------------------ 1. the save cannot destroy
def test_a_normal_save_round_trips(tmp_path):
    bot = _bot(tmp_path)
    bot._active_positions_tracking = _good()
    bot._save_positions_tracking()
    assert json.loads(bot._positions_file.read_text(encoding="utf-8")) == _good()


def test_an_unserializable_value_does_not_cost_the_whole_file(tmp_path):
    """THE WHOLE POINT. The previous version left 660 bytes of truncated
    JSON here and two positions with no recoverable stop."""
    import datetime as dt

    bot = _bot(tmp_path)
    bot._active_positions_tracking = _good()
    bot._save_positions_tracking()

    bot._active_positions_tracking["NATURALGAS26NOV290CE"]["_archived_at"] = dt.datetime.now()
    bot._save_positions_tracking()

    on_disk = json.loads(bot._positions_file.read_text(encoding="utf-8"))
    assert on_disk["NATURALGAS26NOV290CE"]["stop_price"] == 18.715, (
        "the stop must survive a value the encoder cannot handle"
    )


def test_a_write_that_fails_outright_leaves_the_old_file_standing(tmp_path, monkeypatch):
    """default=str covers the encoder. This covers the disk."""
    bot = _bot(tmp_path)
    bot._active_positions_tracking = _good()
    bot._save_positions_tracking()

    def boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(json, "dump", boom)
    bot._active_positions_tracking = {"LATER": {"stop_price": 1.0}}
    bot._save_positions_tracking()                      # must not raise

    assert json.loads(bot._positions_file.read_text(encoding="utf-8")) == _good()


def test_a_failed_save_does_not_leave_its_scratch_file_behind(tmp_path, monkeypatch):
    bot = _bot(tmp_path)
    monkeypatch.setattr(json, "dump", lambda *a, **k: (_ for _ in ()).throw(OSError("x")))
    bot._save_positions_tracking()
    assert list(tmp_path.glob("*.tmp")) == []


def test_the_file_is_never_left_half_written(tmp_path):
    """Whatever is at that path must always parse. The temp-and-rename is
    what makes that true; a reader can open it at any instant."""
    bot = _bot(tmp_path)
    for i in range(5):
        bot._active_positions_tracking[f"SYM{i}"] = {"stop_price": float(i)}
        bot._save_positions_tracking()
        json.loads(bot._positions_file.read_text(encoding="utf-8"))


# ----------------------------------------------- 2. the load is not silent
def test_an_unreadable_file_is_critical_not_an_error_among_thousands(tmp_path, caplog):
    bot = _bot(tmp_path)
    bot._positions_file.write_text('{"X": {"stop_price": 1.0, "_archived_at": ',
                                   encoding="utf-8")
    with caplog.at_level("CRITICAL"):
        assert bot._load_positions_tracking() == {}
    assert "ACTIVE POSITIONS UNREADABLE" in caplog.text
    assert "NO stop and NO target" in caplog.text, (
        "the consequence, not just the exception"
    )


def test_the_unreadable_bytes_are_kept_not_overwritten(tmp_path):
    """They are usually MOST of a valid file - the live one on 2026-10-29
    held a complete position record and died inside the next key. Those
    levels are recoverable by hand, but only if the first save of the new
    session does not land on top of them."""
    bot = _bot(tmp_path)
    bad = '{"NATURALGAS26NOV290CE": {"stop_price": 18.715, "_archived_at": '
    bot._positions_file.write_text(bad, encoding="utf-8")
    bot._load_positions_tracking()

    kept = list(tmp_path.glob("active_positions.unreadable-*.json"))
    assert len(kept) == 1
    assert kept[0].read_text(encoding="utf-8") == bad
    assert not bot._positions_file.exists(), "moved aside, not copied"


def test_a_missing_file_is_a_normal_first_boot_and_says_nothing(tmp_path, caplog):
    """Absent is not corrupt. A fresh brain must not raise an alarm."""
    bot = _bot(tmp_path)
    with caplog.at_level("INFO"):
        assert bot._load_positions_tracking() == {}
    assert caplog.text == ""


def test_a_good_file_loads(tmp_path):
    bot = _bot(tmp_path)
    bot._positions_file.write_text(json.dumps(_good()), encoding="utf-8")
    assert bot._load_positions_tracking() == _good()


def test_save_then_load_is_the_identity(tmp_path):
    bot = _bot(tmp_path)
    bot._active_positions_tracking = _good()
    bot._save_positions_tracking()
    assert _bot(tmp_path)._load_positions_tracking() == _good()
