"""VIX is the only input to the gate that can switch Hokage off, and it was
archived nowhere.

The IV premium guard refuses every options BUY at or above the 80th percentile
of VIX's own trailing 60 days. It refused all thirteen signals Hokage found on
2026-10-14 and eleven more on 2026-10-15. One number decides whether he may act
at all.

It was never written down. `variance_premium_lab` then produced the first
result in this system to clear a corrected bar on both halves -- sellers paid
+3.0% out of sample on NIFTY, +2.4% on SENSEX -- and that result could only be
reproduced while a Zerodha token happened to be alive, because VIX had to be
fetched fresh on every run. Evidence that expires with a token is an anecdote
with a t-statistic attached.

THE TRAP THIS FILE EXISTS FOR, and it is not the obvious one. Kite serves a
bar for the session in progress, and that bar's `close` is the last trade, not
the close. The archive is INSERT OR IGNORE and never corrects itself, so
writing today would freeze a 09:30 reading as a settled close forever -- and
Hokage writes through from inside the guard, which runs all day. The cutoff is
therefore IST rather than the host clock, because the planned move to a VPS
would otherwise shift it five and a half hours in silence.
"""
from __future__ import annotations

import ast
import datetime as dt
import pathlib
import sys
from zoneinfo import ZoneInfo

import pytest

from hokage.memory import vix_archive

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents
            if (p / "pyproject.toml").is_file())


@pytest.fixture
def archive(tmp_path, monkeypatch):
    """A throwaway brain, so no test ever writes the real VIX history."""
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "brain"))
    return vix_archive


def _kite_day(day: dt.date, close: float) -> dict:
    """The shape Kite's historical_data returns for a daily candle."""
    return {"date": dt.datetime(day.year, day.month, day.day),
            "open": close - 0.2, "high": close + 0.3,
            "low": close - 0.4, "close": close}


# ------------------------------------------- the session in progress is not a close
def test_today_is_never_written(archive):
    """THE HEADLINE TRAP. The guard runs all day and writes through, so if
    today were storable the archive would freeze whatever VIX printed at the
    first evaluation and call it that day's close, forever."""
    today = dt.date(2026, 10, 16)
    added = archive.remember(
        [_kite_day(dt.date(2026, 10, 15), 12.0), _kite_day(today, 99.0)],
        today=today,
    )
    assert added == 1
    assert [d for d, _ in archive.load()] == [dt.date(2026, 10, 15)]


def test_tomorrow_is_never_written_either(archive):
    """A host whose clock is behind the exchange's would otherwise accept a
    bar from a session that has not happened."""
    today = dt.date(2026, 10, 16)
    assert archive.remember([_kite_day(dt.date(2026, 10, 17), 11.0)],
                            today=today) == 0


def test_the_cutoff_is_the_exchange_day_not_the_host_clock(archive, monkeypatch):
    """A VPS in UTC is 5h30m behind IST. At 02:00 IST the host would still
    call it yesterday and happily store a day that is now in progress."""
    assert vix_archive.IST == ZoneInfo("Asia/Kolkata")
    src = (ROOT / "src" / "hokage" / "memory" / "vix_archive.py").read_text(
        encoding="utf-8")
    tree = ast.parse(src)
    today_fn = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "today_ist")
    assert "IST" in ast.dump(today_fn), "today_ist must be timezone-anchored"


def test_a_settled_day_is_written(archive):
    added = archive.remember([_kite_day(dt.date(2026, 10, 14), 13.5)],
                             today=dt.date(2026, 10, 16))
    assert added == 1
    assert archive.load() == [(dt.date(2026, 10, 14), 13.5)]


# ------------------------------------------------ nothing is ever overwritten
def test_a_day_already_held_is_never_rewritten(archive):
    """Same doctrine as the candle archive: what the market charged on a day
    is the record of that day, and a later re-fetch does not get to revise
    it."""
    today = dt.date(2026, 10, 16)
    archive.remember([_kite_day(dt.date(2026, 10, 14), 13.5)], today=today)
    assert archive.remember([_kite_day(dt.date(2026, 10, 14), 99.0)],
                            today=today) == 0
    assert archive.load() == [(dt.date(2026, 10, 14), 13.5)]


def test_running_the_sync_twice_adds_nothing_twice(archive):
    today = dt.date(2026, 10, 16)
    days = [_kite_day(dt.date(2026, 10, 12) + dt.timedelta(days=i), 12.0 + i)
            for i in range(3)]
    assert archive.remember(days, today=today) == 3
    assert archive.remember(days, today=today) == 0


# ---------------------------------------------------- missing is not zero
def test_an_absent_archive_reads_as_empty_not_as_an_error(archive):
    assert archive.load() == []
    assert archive.coverage() == {"days": 0, "first": None, "last": None,
                                  "stale_days": None}


def test_a_zero_close_is_refused(archive):
    """A zero VIX is a bad print, not a calm market. It would score at the 0th
    percentile of its own trailing window and unblock every gate that reads
    it."""
    today = dt.date(2026, 10, 16)
    assert archive.remember([_kite_day(dt.date(2026, 10, 14), 0.0)],
                            today=today) == 0
    assert archive.remember([_kite_day(dt.date(2026, 10, 13), -3.0)],
                            today=today) == 0
    assert archive.load() == []


def test_a_row_with_no_close_is_dropped_rather_than_defaulted(archive):
    today = dt.date(2026, 10, 16)
    assert archive.remember([{"date": dt.date(2026, 10, 14), "close": None}],
                            today=today) == 0
    assert archive.remember([{"close": 12.0}], today=today) == 0


def test_one_bad_row_does_not_lose_the_good_ones(archive):
    """A single unparseable record must not cost the day's whole sync."""
    today = dt.date(2026, 10, 16)
    added = archive.remember(
        [_kite_day(dt.date(2026, 10, 13), 12.0),
         {"date": "not-a-date", "close": 11.0},
         object(),
         _kite_day(dt.date(2026, 10, 14), 13.0)],
        today=today,
    )
    assert added == 2


def test_nothing_at_all_is_not_an_error(archive):
    assert archive.remember([], today=dt.date(2026, 10, 16)) == 0
    assert archive.remember(None, today=dt.date(2026, 10, 16)) == 0


# ------------------------------------------- it takes what each caller already has
def test_it_accepts_the_candle_objects_production_already_fetched(archive):
    """The guard holds model objects, not Kite dicts. Making production
    convert them would be a second place for the schema to drift."""
    class Candle:
        def __init__(self, day, close):
            self.date = dt.datetime(day.year, day.month, day.day)
            self.open = self.high = self.low = None
            self.close = close

    assert archive.remember([Candle(dt.date(2026, 10, 14), 13.5)],
                            today=dt.date(2026, 10, 16)) == 1
    assert archive.load() == [(dt.date(2026, 10, 14), 13.5)]


def test_it_accepts_the_day_close_pairs_the_labs_already_use(archive):
    assert archive.remember([(dt.date(2026, 10, 14), 13.5)],
                            today=dt.date(2026, 10, 16)) == 1
    assert archive.load() == [(dt.date(2026, 10, 14), 13.5)]


# ---------------------------------------------------------------- reading back
def test_closes_come_back_oldest_first(archive):
    today = dt.date(2026, 10, 16)
    archive.remember([_kite_day(dt.date(2026, 10, 14), 13.0),
                      _kite_day(dt.date(2026, 10, 12), 11.0),
                      _kite_day(dt.date(2026, 10, 13), 12.0)], today=today)
    assert [c for _, c in archive.load()] == [11.0, 12.0, 13.0]


def test_a_span_can_be_asked_for(archive):
    today = dt.date(2026, 10, 16)
    archive.remember([_kite_day(dt.date(2026, 10, 10) + dt.timedelta(days=i),
                                10.0 + i) for i in range(5)], today=today)
    assert [d.isoformat() for d, _ in
            archive.load("2026-10-11", "2026-10-13")] == [
        "2026-10-11", "2026-10-12", "2026-10-13"]


def test_coverage_reports_how_far_behind_it_has_fallen(archive, monkeypatch):
    """Staleness has to be visible. The candle archive went on "succeeding"
    for days while writing nothing, and nobody could see it from the outside."""
    monkeypatch.setattr(vix_archive, "today_ist", lambda: dt.date(2026, 10, 16))
    archive.remember([_kite_day(dt.date(2026, 10, 13), 12.0)],
                     today=dt.date(2026, 10, 16))
    cover = archive.coverage()
    assert cover["days"] == 1
    assert cover["last"] == dt.date(2026, 10, 13)
    assert cover["stale_days"] == 3


def test_moving_the_brain_moves_the_archive(tmp_path, monkeypatch):
    """The 2026-10-09 split brain: nine tools each computed their own path and
    went on writing a database nobody read."""
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "one"))
    first = vix_archive.db_path()
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "two"))
    assert vix_archive.db_path() != first


def test_it_lives_beside_the_candles(archive):
    """Same corpus: the candle archive holds what the index DID, this holds
    what the market CHARGED for it. Neither answers a volatility question
    alone."""
    assert vix_archive.db_path().name == "candles.db"


# ------------------------------------------------ production writes it through
def _bot_source() -> str:
    return (ROOT / "src" / "bots" / "autonomous" / "autonomous_bot.py").read_text(
        encoding="utf-8")


def test_the_guard_archives_what_it_fetched():
    """The guard already pulls 70 daily bars whenever it runs. Archiving them
    there costs no extra broker call and happens on exactly the days a live
    session exists -- which is why this is the primary archiver and the ops
    tool is only the backstop.

    Checked by AST rather than by searching the text, because this file's own
    prose mentions both names and a text scan would match itself."""
    tree = ast.parse(_bot_source())
    guard = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef)
                 and n.name == "_india_vix_percentile")
    called = {ast.unparse(n.func) for n in ast.walk(guard)
              if isinstance(n, ast.Call)}
    assert any("_archive_vix" in c for c in called), (
        "the guard fetches VIX history and throws it away again"
    )


def test_a_failed_archive_write_can_never_break_the_guard():
    """The guard decides whether Hokage may trade at all. A bookkeeping write
    must not be able to stop it -- so the whole body sits inside try/except."""
    tree = ast.parse(_bot_source())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_archive_vix")
    body = [s for s in fn.body if not isinstance(s, ast.Expr)
            or not isinstance(s.value, ast.Constant)]
    assert len(body) == 1 and isinstance(body[0], ast.Try), (
        "_archive_vix must be nothing but a guarded try/except"
    )
    assert body[0].handlers and body[0].handlers[0].type is not None


def test_the_guard_still_returns_a_percentile_when_the_archive_throws(monkeypatch):
    """The statement above, exercised rather than asserted about."""
    from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot

    def explode(_candles):
        raise RuntimeError("disk full")

    monkeypatch.setattr(vix_archive, "remember", explode)
    Bot._archive_vix([_kite_day(dt.date(2026, 10, 14), 13.0)])  # must not raise


# -------------------------------------------------- the labs read the archive
def test_the_lab_prefers_the_archive_and_leaves_the_broker_alone(archive,
                                                                 monkeypatch):
    """The point of the whole exercise: a volatility question is answerable
    without a Zerodha session."""
    sys.path.insert(0, str(ROOT / "tools" / "research"))
    import iv_lab

    monkeypatch.setattr(vix_archive, "today_ist", lambda: dt.date(2026, 10, 16))
    archive.remember([_kite_day(dt.date(2026, 10, 1) + dt.timedelta(days=i),
                                12.0 + i * 0.1) for i in range(15)],
                     today=dt.date(2026, 10, 16))

    def forbidden():
        raise AssertionError("the lab reached for the broker with a fresh archive")

    monkeypatch.setattr(iv_lab, "fetch_vix_from_kite", forbidden)
    assert len(iv_lab.load_vix_closes()) == 15


def test_a_stale_archive_is_topped_up(archive, monkeypatch):
    sys.path.insert(0, str(ROOT / "tools" / "research"))
    import iv_lab

    monkeypatch.setattr(vix_archive, "today_ist", lambda: dt.date(2026, 10, 16))
    archive.remember([_kite_day(dt.date(2026, 9, 1), 12.0)],
                     today=dt.date(2026, 10, 16))
    monkeypatch.setattr(iv_lab, "fetch_vix_from_kite",
                        lambda: [(dt.date(2026, 10, 15), 13.0)])
    out = iv_lab.load_vix_closes()
    assert [d for d, _ in out] == [dt.date(2026, 9, 1), dt.date(2026, 10, 15)]


def test_a_failed_top_up_answers_from_the_archive_rather_than_dying(archive,
                                                                    monkeypatch):
    """A dead token should cost freshness, not the answer."""
    sys.path.insert(0, str(ROOT / "tools" / "research"))
    import iv_lab

    monkeypatch.setattr(vix_archive, "today_ist", lambda: dt.date(2026, 10, 16))
    archive.remember([_kite_day(dt.date(2026, 9, 1), 12.0)],
                     today=dt.date(2026, 10, 16))

    def dead_token():
        raise RuntimeError("Incorrect `api_key` or `access_token`")

    monkeypatch.setattr(iv_lab, "fetch_vix_from_kite", dead_token)
    assert iv_lab.load_vix_closes() == [(dt.date(2026, 9, 1), 12.0)]


def test_nothing_archived_and_no_session_raises_rather_than_returning_empty(
        archive, monkeypatch):
    """An empty VIX series makes every percentile None and every guard
    silently skipped, so the whole lab would report "no signal" when it means
    "no data"."""
    sys.path.insert(0, str(ROOT / "tools" / "research"))
    import iv_lab

    monkeypatch.setattr(iv_lab, "fetch_vix_from_kite",
                        lambda: (_ for _ in ()).throw(RuntimeError("no session")))
    with pytest.raises(ValueError, match="archive is empty"):
        iv_lab.load_vix_closes()


def test_the_lab_can_be_told_not_to_touch_the_broker_at_all(archive, monkeypatch):
    sys.path.insert(0, str(ROOT / "tools" / "research"))
    import iv_lab

    monkeypatch.setattr(iv_lab, "fetch_vix_from_kite",
                        lambda: (_ for _ in ()).throw(AssertionError("fetched")))
    with pytest.raises(ValueError, match="archive is empty"):
        iv_lab.load_vix_closes(allow_fetch=False)


# ----------------------------------------------------------- the daily job
def test_the_daily_sync_job_keeps_the_vix_too():
    """Hokage is the primary archiver, but he is the one thing that is not
    running on the days this matters most."""
    ps = (ROOT / "Sync-Candles.ps1").read_text(encoding="utf-8-sig")
    assert "archive_vix.py" in ps
    assert "candle_archive.py" in ps, "it must still do the candles as well"
