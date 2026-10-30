"""The repair script must never become the thing it was written to repair.

`tools/ops/repair_eia_record.py` gave EIAReaction the eleven fields it never
got, because it was deployed on 2026-10-21 by editing the MCX portfolio JSON
by hand instead of calling `StrategyPortfolio.register_strategy`. One of the
eleven was `strategy_id`, which held a shipped bias-gate exemption shut for a
week.

It is kept in the tree rather than deleted, so it can be run again - and
that is exactly what makes it dangerous. A second run seeds priors. On an
untraded record those priors are the truth it was denied; on a record that
has since traded they would overwrite measured win_rate and expectancy and
empty pnl_history, destroying the only history that exists. Run while Hokage
is up, it would be reverted silently, because a running process holds the
portfolio in memory and writes it back over anything changed on disk - which
is how the CRUDEOIL park was undone on 2026-08-26.

WHAT THIS FILE PINS: the two refusals, in both orders; that the dashboard
check cannot be frozen at import; that the seeded values are the real
`register_strategy` defaults rather than a copy that can drift; that
`created_at` comes from the record's own birth and not from today; and that
a failed write leaves the original file byte-for-byte intact.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

# Same idiom as test_reconcile_phantom_trades / test_liveness_probe: tools/ops
# is not an importable package.
_spec = importlib.util.spec_from_file_location(
    "repair_eia_record", ROOT / "tools" / "ops" / "repair_eia_record.py"
)
tool = importlib.util.module_from_spec(_spec)
sys.modules["repair_eia_record"] = tool
_spec.loader.exec_module(tool)


STUB = {
    "name": "EIAReaction",
    "status": "ACTIVE",
    "version": "1.0.0",
    "supported_assets": ["NATURALGAS"],
    "supported_regimes": ["BULL", "BEAR", "SIDEWAYS"],
    "capital": {"starting": 100_000.0, "realized_pnl": 0.0},
    "history": [{"timestamp": "2026-10-21T03:07:22.229701+00:00",
                 "event": "Deployed by commander directive."}],
}

PEER = {
    "strategy_id": "strat-rangefade-mcx-v1",
    "name": "RangeFade",
    "status": "ACTIVE",
    "version": "1.0.0",
    "supported_assets": ["NATURALGAS"],
    "supported_regimes": ["SIDEWAYS"],
    "capital": {"starting": 100_000.0, "realized_pnl": 1234.0},
    "created_at": "2026-07-17T20:07:27.742999+00:00",
    "history": [],
    "context_memory": {"notes": "", "regime_performance": {},
                       "volatility_performance": {}},
    "domain_confidence": {"DEFAULT": 41.34},
    "drawdown": {"DEFAULT": 0.475},
    "expectancy": {"DEFAULT": 207.03},
    "pnl_history": {"NATURALGAS": [-437.5]},
    "regime_stats": {"BEAR_RISK-ON": {"trade_count": 25, "win_rate": 56.0}},
    "sharpe_ratio": {"DEFAULT": 0.189},
    "trade_count": {"DEFAULT": 16},
    "win_rate": {"DEFAULT": 43.74},
}


def _portfolio(tmp_path, eia=None) -> pathlib.Path:
    path = tmp_path / "mcx_strategy_portfolio.json"
    path.write_text(json.dumps({
        "updated_at": "2026-10-29T00:00:00+00:00",
        "strategies": {
            "strat-eiareaction-mcx-v1": json.loads(json.dumps(eia or STUB)),
            "strat-rangefade-mcx-v1": json.loads(json.dumps(PEER)),
        },
    }, indent=2), encoding="utf-8")
    return path


@pytest.fixture
def offline(monkeypatch):
    """Hokage is stopped, which is the only state the repair may run in."""
    monkeypatch.setattr(tool, "hokage_is_serving", lambda *a, **k: False)


# --------------------------------------------- 1. it refuses to run twice
def test_an_untraded_stub_is_the_one_record_it_will_touch():
    assert tool.already_repaired(dict(STUB, trade_count={"DEFAULT": 0})) is None


def test_a_record_that_has_traded_is_refused():
    """THE DESTRUCTIVE CASE. Priors would replace measured performance."""
    reason = tool.already_repaired({"trade_count": {"NATURALGAS": 4}})
    assert reason and "erase measured performance" in reason


def test_an_already_repaired_record_is_refused():
    reason = tool.already_repaired({"strategy_id": tool.SID,
                                    "trade_count": {"DEFAULT": 0}})
    assert reason and "already carries strategy_id" in reason


def test_the_traded_refusal_outranks_the_repaired_one():
    """Order matters. Both refuse, but only one of them names the real
    hazard, and that is the sentence someone will act on."""
    reason = tool.already_repaired({"strategy_id": tool.SID,
                                    "trade_count": {"NATURALGAS": 9}})
    assert "erase measured performance" in reason


def test_a_missing_or_malformed_trade_count_does_not_wave_it_through():
    """An absent count is unknown, not zero - the lesson of this whole
    episode. It must not crash, and it must not invent a reason to proceed
    on a record that already carries its id."""
    assert tool.already_repaired({"name": "X"}) is None
    assert tool.already_repaired({"trade_count": "nonsense"}) is None
    assert tool.already_repaired({"trade_count": {"A": 2.0}}) is not None
    assert tool.already_repaired(
        {"strategy_id": tool.SID, "trade_count": None}) is not None


# ------------------------------- 2. the dashboard check resolves at call time
def test_the_dashboard_url_is_not_frozen_at_import(monkeypatch):
    """THE BUG THIS TEST EXISTS FOR, caught while proving the guard worked.

    As `def hokage_is_serving(url: str = DASHBOARD)` the module global was
    captured once at import, so overriding it changed nothing and the guard
    silently probed the real dashboard instead. Same fault liveness_probe.py
    carries a comment about, where a default-argument path meant the reader
    and the deleter could target different files.
    """
    asked: list[str] = []

    def _fake_urlopen(url, timeout=None):
        asked.append(url)
        raise OSError("refused")

    monkeypatch.setattr(tool.urllib.request, "urlopen", _fake_urlopen)
    monkeypatch.setattr(tool, "DASHBOARD", "http://127.0.0.1:65000")
    assert tool.hokage_is_serving() is False
    assert asked == ["http://127.0.0.1:65000"]


def test_a_dashboard_that_answers_means_serving(monkeypatch):
    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(tool.urllib.request, "urlopen",
                        lambda url, timeout=None: _Resp())
    assert tool.hokage_is_serving() is True


def test_a_running_hokage_stops_the_repair_before_it_reads_anything(
        tmp_path, monkeypatch):
    path = _portfolio(tmp_path)
    before = path.read_bytes()
    monkeypatch.setattr(tool, "PORTFOLIO", path)
    monkeypatch.setattr(tool, "hokage_is_serving", lambda *a, **k: True)
    assert tool.main() == 1
    assert path.read_bytes() == before


def test_a_second_run_changes_nothing(tmp_path, monkeypatch, offline):
    path = _portfolio(tmp_path)
    monkeypatch.setattr(tool, "PORTFOLIO", path)
    assert tool.main() == 0
    after_first = path.read_bytes()
    assert tool.main() == 0
    assert path.read_bytes() == after_first


# ------------------------------------------------ 3. nothing is invented
def test_the_record_gains_every_field_its_peers_have(tmp_path, monkeypatch,
                                                     offline):
    path = _portfolio(tmp_path)
    monkeypatch.setattr(tool, "PORTFOLIO", path)
    assert tool.main() == 0
    strategies = json.loads(path.read_text(encoding="utf-8"))["strategies"]
    eia, peer = strategies[tool.SID], strategies["strat-rangefade-mcx-v1"]
    assert set(peer) - set(eia) == set()
    assert eia["strategy_id"] == tool.SID


def test_created_at_is_its_own_birthday_not_today(tmp_path, monkeypatch,
                                                  offline):
    """Today's date would restart the retirement clock on a strategy that has
    been deployed since 2026-10-21."""
    path = _portfolio(tmp_path)
    monkeypatch.setattr(tool, "PORTFOLIO", path)
    tool.main()
    eia = json.loads(path.read_text(encoding="utf-8"))["strategies"][tool.SID]
    assert eia["created_at"] == STUB["history"][0]["timestamp"]


def test_the_seeded_values_are_register_strategy_s_own_defaults(tmp_path):
    """DRIFT PIN. The priors are defensible only because they are exactly
    what the system writes for a new strategy. A hand-copied constant stops
    being that the moment register_strategy changes, so compare against the
    real function rather than against a literal.
    """
    from hokage.memory.resolver import PathResolver
    from bots.strategy.portfolio import StrategyPortfolioManager

    mgr = StrategyPortfolioManager(PathResolver(tmp_path))
    sid = mgr.register_strategy("Probe", "1.0.0", ["NATURALGAS"], ["BULL"])
    fresh = mgr.portfolio["strategies"][sid]

    shared = {k: v for k, v in tool.PRIORS.items() if k in fresh}
    # The six metrics register_strategy actually writes. pnl_history and
    # regime_stats are added later by the outcome recorder, so they are not
    # in a freshly registered record and are empty here by measurement.
    assert set(shared) == {"domain_confidence", "expectancy", "win_rate",
                           "drawdown", "sharpe_ratio", "trade_count"}
    for key, value in shared.items():
        assert fresh[key] == value, f"{key} drifted from register_strategy"
    assert tool.PRIORS["pnl_history"] == {}
    assert tool.PRIORS["regime_stats"] == {}


def test_nothing_but_the_one_record_is_touched(tmp_path, monkeypatch, offline):
    path = _portfolio(tmp_path)
    monkeypatch.setattr(tool, "PORTFOLIO", path)
    tool.main()
    strategies = json.loads(path.read_text(encoding="utf-8"))["strategies"]
    assert strategies["strat-rangefade-mcx-v1"] == PEER
    assert strategies[tool.SID]["capital"] == STUB["capital"]
    assert strategies[tool.SID]["status"] == "ACTIVE"


def test_the_repair_is_written_into_the_record_s_own_history(
        tmp_path, monkeypatch, offline):
    """The portfolio lives outside the repo, so the record's history is the
    only place the change is visible to anyone reading the file."""
    path = _portfolio(tmp_path)
    monkeypatch.setattr(tool, "PORTFOLIO", path)
    tool.main()
    eia = json.loads(path.read_text(encoding="utf-8"))["strategies"][tool.SID]
    assert len(eia["history"]) == 2
    assert "register_strategy" in eia["history"][-1]["event"]


# -------------------------------------------------- 4. the write is atomic
def test_a_failed_write_leaves_the_original_intact(tmp_path, monkeypatch,
                                                   offline):
    """54540db: json.dump truncates the handle BEFORE it raises, which is how
    every open position lost its stop. This writes a temp file, re-parses it,
    and only then replaces - so a failure costs nothing."""
    path = _portfolio(tmp_path)
    before = path.read_bytes()
    monkeypatch.setattr(tool, "PORTFOLIO", path)

    # Swap the module's OWN reference, not an attribute of the real json
    # module. Mutating json.dumps globally is how an unrelated test started
    # counting someone else's Path.replace calls and failed only under
    # certain orderings.
    class _ExplodingJson:
        loads = staticmethod(json.loads)

        @staticmethod
        def dumps(*a, **k):
            raise ValueError("boom")

    monkeypatch.setattr(tool, "json", _ExplodingJson)
    with pytest.raises(ValueError):
        tool.main()
    assert path.read_bytes() == before


def test_it_leaves_a_backup_and_no_temp_file(tmp_path, monkeypatch, offline):
    path = _portfolio(tmp_path)
    monkeypatch.setattr(tool, "PORTFOLIO", path)
    tool.main()
    assert not list(tmp_path.glob("*.tmp"))
    backups = list(tmp_path.glob("*pre_eia_repair*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8")) == \
        json.loads(json.dumps({
            "updated_at": "2026-10-29T00:00:00+00:00",
            "strategies": {"strat-eiareaction-mcx-v1": STUB,
                           "strat-rangefade-mcx-v1": PEER},
        }))


def test_a_missing_portfolio_refuses_rather_than_creating_one(
        tmp_path, monkeypatch, offline):
    monkeypatch.setattr(tool, "PORTFOLIO", tmp_path / "nope.json")
    assert tool.main() == 1
    assert not (tmp_path / "nope.json").exists()


def test_a_portfolio_without_the_strategy_refuses(tmp_path, monkeypatch,
                                                  offline):
    path = tmp_path / "mcx_strategy_portfolio.json"
    path.write_text(json.dumps({"strategies": {"strat-rangefade-mcx-v1": PEER}}),
                    encoding="utf-8")
    monkeypatch.setattr(tool, "PORTFOLIO", path)
    assert tool.main() == 1
