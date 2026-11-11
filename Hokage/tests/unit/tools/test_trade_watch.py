"""The watch must never answer "no trade" because it could not look.

The previous day-watch reported no trade for four consecutive days and was
wrong every time: it opened the ledger by a relative path, the error was
swallowed by a handler that logged "no change", and a real +1,505 win went
unreported. A watcher's failure mode is not a crash, it is confident silence,
so these tests are mostly about what it does when it CANNOT see.

They also pin the two facts a previous version got wrong: `positions` is the
ledger (`trades` is the exit writer's dead table and has never held a real
entry), and the ledger is opened read-only, because a watcher that can lock
the ledger can stop the thing it is watching.
"""
from __future__ import annotations

import ast
import importlib.util
import pathlib
import sqlite3
import sys

import pytest


def _repo_root() -> pathlib.Path:
    return next(p for p in pathlib.Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())


SRC = _repo_root() / "tools" / "ops" / "trade_watch.py"


def _module(monkeypatch, brain_root):
    """Import trade_watch fresh with BRAIN_ROOT pointed at a copy."""
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(brain_root))
    sys.modules.pop("trade_watch", None)
    spec = importlib.util.spec_from_file_location("trade_watch", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _ledger(tmp_path, rows=()):
    root = tmp_path / "brain"
    root.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(root / "hokage.db")
    con.execute("""CREATE TABLE positions (
        position_id TEXT, account_id TEXT, market TEXT, direction TEXT,
        quantity REAL, entry_price REAL, current_price REAL,
        unrealized_pnl REAL, realized_pnl REAL, status TEXT, opened_at TEXT,
        closed_at TEXT, playbook_id TEXT, failure_reason TEXT,
        volatility_regime TEXT, strategy_id TEXT, charges REAL)""")
    for row in rows:
        con.execute(
            "INSERT INTO positions (position_id, market, direction, quantity,"
            " entry_price, realized_pnl, status, opened_at, closed_at,"
            " strategy_id) VALUES (?,?,?,?,?,?,?,?,?,?)", row)
    con.commit()
    con.close()
    return root


OPEN_ROW = ("p1", "NIFTY26NOV25500CE", "LONG", 75, 120.5, 0.0, "OPEN",
            "2026-11-11T05:00:00+00:00", None, "strat-proof")


# =============================================== it can see what happened
def test_a_new_position_is_reported_as_an_entry(tmp_path, monkeypatch):
    root = _ledger(tmp_path)
    mod = _module(monkeypatch, root)
    before = mod._snapshot(root / "hokage.db")
    assert before == {}

    con = sqlite3.connect(root / "hokage.db")
    con.execute(
        "INSERT INTO positions (position_id, market, direction, quantity,"
        " entry_price, realized_pnl, status, opened_at, closed_at,"
        " strategy_id) VALUES (?,?,?,?,?,?,?,?,?,?)", OPEN_ROW)
    con.commit()
    con.close()

    after = mod._snapshot(root / "hokage.db")
    assert set(after) - set(before) == {"p1"}
    line = mod._entry_line(after["p1"])
    assert "NIFTY26NOV25500CE" in line and "LONG" in line
    assert "strat-proof" in line


def test_a_status_change_is_reported_as_an_exit_with_the_money(tmp_path,
                                                               monkeypatch):
    root = _ledger(tmp_path, [OPEN_ROW])
    mod = _module(monkeypatch, root)
    row = dict(mod._snapshot(root / "hokage.db")["p1"])
    row.update(status="CLOSED", realized_pnl=1505.0,
               closed_at="2026-11-11T06:00:00+00:00")
    line = mod._exit_line(row)
    assert "EXIT" in line and "CLOSED" in line
    assert "+1,505" in line, "the realised number is the point of the alert"


def test_the_money_survives_a_missing_number(tmp_path, monkeypatch):
    """A None realised P&L must not crash the alert. An alert that raises is
    an alert that is not sent."""
    mod = _module(monkeypatch, tmp_path / "brain")
    assert mod._money(None) == "None"
    assert mod._money("") == ""
    assert mod._money(-250) == "-250"


# ================================= and it says so when it CANNOT see
def test_an_unreadable_ledger_is_an_error_not_a_quiet_answer(tmp_path,
                                                             monkeypatch,
                                                             capsys):
    """THE DEFECT THIS FILE EXISTS FOR. Four days of "no trade" came from a
    path that could not be opened, reported as no change."""
    mod = _module(monkeypatch, tmp_path / "there-is-no-brain-here")
    assert mod.main() == 1
    out = capsys.readouterr().out
    assert "WATCH-ERROR" in out
    assert "could not open the ledger" in out
    assert "no trade" not in out.lower()


def test_the_brain_root_is_absolute_and_not_cwd_relative(monkeypatch,
                                                         tmp_path):
    """THE ORIGINAL BUG, asserted on the behaviour rather than on the text.

    A relative default makes the answer depend on who launched the watch and
    from where - which is how four days of "no trade" happened. Checking the
    source string for a drive letter would just be a quoting puzzle; the
    question is whether the resolved path is absolute.
    """
    monkeypatch.delenv("HOKAGE_BRAIN_ROOT", raising=False)
    sys.modules.pop("trade_watch", None)
    spec = importlib.util.spec_from_file_location("trade_watch", SRC)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.BRAIN_ROOT.is_absolute(), (
        f"the default brain root is relative: {mod.BRAIN_ROOT}")

    # and the environment must still be able to point it elsewhere, which is
    # what makes this testable at all
    moved = _module(monkeypatch, tmp_path / "elsewhere")
    assert moved.BRAIN_ROOT == tmp_path / "elsewhere"


def test_the_ledger_is_opened_read_only():
    """A watcher that can lock the ledger can stop the thing it watches."""
    src = SRC.read_text(encoding="utf-8")
    assert "mode=ro" in src
    assert "uri=True" in src


def test_it_reads_positions_and_never_the_dead_trades_table():
    """`trades` is the exit writer's table and has never held a real entry.
    Reading it has already produced three wrong answers, one of them from an
    earlier version of this watch."""
    src = SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    sql = [n.value for n in ast.walk(tree)
           if isinstance(n, ast.Constant) and isinstance(n.value, str)
           and "FROM " in n.value]
    assert sql, "no query found; this rail must be re-aimed"
    assert any("FROM positions" in q for q in sql)
    assert not any("FROM trades" in q for q in sql)


def test_a_poll_fault_keeps_the_watch_alive_but_loud(monkeypatch, tmp_path,
                                                     capsys):
    """A momentary lock is normal; going silent about it is not. The loop
    must print every fault and keep watching."""
    root = _ledger(tmp_path, [OPEN_ROW])
    mod = _module(monkeypatch, root)

    # The REAL reader, captured before patching. Calling mod._snapshot from
    # inside the replacement would call the replacement.
    real = mod._snapshot(root / "hokage.db")
    calls = {"n": 0}

    def flaky(_db):
        calls["n"] += 1
        if calls["n"] == 1:
            return dict(real)
        if calls["n"] <= 3:
            raise sqlite3.OperationalError("database is locked")
        raise KeyboardInterrupt           # end the test's loop

    monkeypatch.setattr(mod, "_snapshot", flaky)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    with pytest.raises(KeyboardInterrupt):
        mod.main()

    out = capsys.readouterr().out
    assert out.count("WATCH-ERROR") == 2, "every fault must print"
    assert "read 1 failed" in out and "read 2 failed" in out


def test_it_announces_itself_on_start(tmp_path, monkeypatch, capsys):
    """An armed watch must be distinguishable from a dead one WITHOUT
    waiting for a trade, which is the only way to notice the four-day
    silence on day one instead of day four."""
    root = _ledger(tmp_path, [OPEN_ROW])
    mod = _module(monkeypatch, root)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: (_ for _ in ()).throw(
        KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        mod.main()
    out = capsys.readouterr().out
    assert "BASELINE" in out
    assert "1 positions on record" in out
    assert "1 open" in out
    # an already-open position is named, so a restart mid-trade is not silent
    assert "ALREADY OPEN" in out
