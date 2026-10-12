"""One blended win rate across seven assets is not a pattern.

`detect_patterns` took a `strategy_id`, ignored it, pooled every autopsy ever
written across every strategy and every symbol, and returned a single win rate
with the ignored id attached as a label. `process_autopsy` passed
"strat-autotrend-equities-v1" -- an id in neither portfolio -- and the result
went to an LLM that wrote the commander a confident journal entry about it.

Measured on the live file, 2026-10-12, 122 autopsies:

    pooled        28.7%
    CRUDEOIL      10.6%   (47 autopsies)
    GOLDM         43.5%   (23)
    SILVERM       52.9%   (17)

A fivefold spread flattened into one number -- and the pooled figure was
dominated by CRUDEOIL, an asset PARKED weeks earlier for having no measurable
edge. The "insight" was mostly the failure of something already retired,
burying the fact that the metals are the one confirmed edge in the system.
The arena learned this once already: when strategies trade different markets,
a pooled figure measures the market, not the strategy.

Two further traps this pins:

  * `symbol` is the full option contract (CRUDEOIL26JUL7750CE). Grouping on it
    raw gives sixty cells of n=1.
  * `vix_at_entry` was read with a default of 15, so an absent measurement
    became a number indistinguishable from a real one.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from bots.improvement.improvement_bot import ImprovementBot
from hokage.memory.resolver import PathResolver


def _bot(tmp_path, records):
    brain = tmp_path / "brain"
    (brain / "improvement").mkdir(parents=True, exist_ok=True)
    path = brain / "improvement" / "trade_autopsies.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")
    return ImprovementBot(
        portfolio_manager=None,
        resolver=PathResolver(brain_root=brain),
        prediction_ledger=None,
        trade_store=None,
    )


def _rec(symbol, pnl, *, days_ago=1, vix=14.0, mfe=0.2, **extra):
    r = {
        "symbol": symbol,
        "pnl": pnl,
        "timestamp": (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(),
        "max_favorable_excursion_pct": mfe,
    }
    if vix is not None:
        r["vix_at_entry"] = vix
    r.update(extra)
    return r


# ------------------------------------------------------ grouped by underlying
def test_contracts_collapse_to_their_underlying(tmp_path):
    """Ten different CRUDEOIL contracts are ten CRUDEOIL trades, not ten
    assets of one trade each."""
    records = [_rec(f"CRUDEOIL26JUL{7000 + i * 50}CE", -1.0) for i in range(10)]
    assets = _bot(tmp_path, records).detect_patterns()["assets"]
    assert list(assets) == ["CRUDEOIL"]
    assert assets["CRUDEOIL"]["n"] == 10


def test_assets_are_never_pooled_together(tmp_path):
    """THE bug. A losing asset and a winning one must not average out."""
    records = ([_rec("CRUDEOIL26JUL7750CE", -1.0) for _ in range(10)]
               + [_rec("SILVERM26AUG221000CE", +1.0) for _ in range(10)])
    result = _bot(tmp_path, records).detect_patterns()

    assert result["assets"]["CRUDEOIL"]["win_rate"] == 0.0
    assert result["assets"]["SILVERM"]["win_rate"] == 1.0
    assert "win_rate" not in result, "there must be no top-level pooled rate"


def test_the_signature_no_longer_takes_a_strategy_it_cannot_honour(tmp_path):
    """Autopsies carry no strategy_id -- absent in all 122 live records -- so
    a strategy_id parameter could only ever be a label on pooled data."""
    import inspect

    params = inspect.signature(ImprovementBot.detect_patterns).parameters
    assert "strategy_id" not in params


# ----------------------------------------------- thin cells report a count
def test_an_asset_under_the_floor_reports_a_count_and_no_rate(tmp_path):
    """A win rate over three trades is a coin. Printing one invites acting
    on it."""
    records = [_rec("NIFTY2672124250CE", +1.0) for _ in range(3)]
    cell = _bot(tmp_path, records).detect_patterns()["assets"]["NIFTY"]
    assert cell["n"] == 3
    assert cell["insufficient"] is True
    assert cell["win_rate"] is None
    assert cell["needs"] == ImprovementBot.MIN_AUTOPSIES_PER_ASSET


def test_a_thin_cell_and_a_full_one_coexist(tmp_path):
    records = ([_rec("NIFTY2672124250CE", +1.0) for _ in range(3)]
               + [_rec("GOLDM26AUG161000PE", +1.0) for _ in range(9)])
    assets = _bot(tmp_path, records).detect_patterns()["assets"]
    assert assets["NIFTY"]["win_rate"] is None
    assert assets["GOLDM"]["win_rate"] == 1.0


# ------------------------------------------- missing is excluded, not defaulted
def test_a_missing_vix_is_counted_not_replaced_with_fifteen(tmp_path):
    """The old code read vix_at_entry with a default of 15, so an absent
    measurement became a plausible number."""
    records = ([_rec("GOLDM26AUG161000PE", +1.0, vix=20.0) for _ in range(4)]
               + [_rec("GOLDM26AUG161000PE", +1.0, vix=None) for _ in range(4)])
    cell = _bot(tmp_path, records).detect_patterns()["assets"]["GOLDM"]
    assert cell["avg_win_vix"] == 20.0, "absent readings must not drag the mean"
    assert cell["avg_win_vix_missing"] == 4


def test_all_vix_missing_gives_None_not_a_number(tmp_path):
    records = [_rec("GOLDM26AUG161000PE", +1.0, vix=None) for _ in range(9)]
    cell = _bot(tmp_path, records).detect_patterns()["assets"]["GOLDM"]
    assert cell["avg_win_vix"] is None
    assert cell["avg_win_vix_missing"] == 9


def test_missing_excursions_are_reported_rather_than_assumed_zero(tmp_path):
    """max_adverse_excursion_pct is absent in 35 of the 122 live records.
    Treating absence as 0.0 would silently say 'the stop was never tested'."""
    records = ([_rec("GOLDM26AUG161000PE", -1.0, mfe=2.0) for _ in range(5)]
               + [_rec("GOLDM26AUG161000PE", -1.0, mfe=None) for _ in range(4)])
    for r in records:
        if r.get("max_favorable_excursion_pct") is None:
            r.pop("max_favorable_excursion_pct")
    cell = _bot(tmp_path, records).detect_patterns()["assets"]["GOLDM"]
    assert cell["losses_with_excursion"] == 5
    assert cell["losses_missing_excursion"] == 4
    assert cell["premature_stops"] == 5


def test_no_measurable_losses_gives_None_not_False(tmp_path):
    """False would read as 'checked, stops are fine'. Nothing was checked."""
    records = [_rec("GOLDM26AUG161000PE", +1.0) for _ in range(9)]
    cell = _bot(tmp_path, records).detect_patterns()["assets"]["GOLDM"]
    assert cell["losses_with_excursion"] == 0
    assert cell["stop_tightness_issue"] is None


# --------------------------------------------------------------- the window
def test_old_autopsies_fall_out_of_the_window(tmp_path):
    """Autopsies reach back to July; a regime from three months ago should
    not dilute what is happening now."""
    records = ([_rec("GOLDM26AUG161000PE", +1.0, days_ago=5) for _ in range(9)]
               + [_rec("CRUDEOIL26JUL7750CE", -1.0, days_ago=400) for _ in range(20)])
    result = _bot(tmp_path, records).detect_patterns()
    assert "CRUDEOIL" not in result["assets"]
    assert result["autopsies_in_window"] == 9


def test_the_window_is_adjustable(tmp_path):
    records = [_rec("CRUDEOIL26JUL7750CE", -1.0, days_ago=400) for _ in range(9)]
    assert _bot(tmp_path, records).detect_patterns()["assets"] == {}
    wide = _bot(tmp_path, records).detect_patterns(window_days=3650)
    assert wide["assets"]["CRUDEOIL"]["n"] == 9


def test_an_undated_record_is_skipped_and_counted(tmp_path):
    """Silently dropping records would make the sample smaller than it looks."""
    records = [_rec("GOLDM26AUG161000PE", +1.0) for _ in range(9)]
    records.append({"symbol": "GOLDM26AUG161000PE", "pnl": 1.0})
    result = _bot(tmp_path, records).detect_patterns()
    assert result["skipped_undated"] == 1
    assert result["assets"]["GOLDM"]["n"] == 9


def test_no_autopsy_file_is_not_a_crash(tmp_path):
    bot = ImprovementBot(
        portfolio_manager=None,
        resolver=PathResolver(brain_root=tmp_path / "empty"),
        prediction_ledger=None, trade_store=None,
    )
    assert bot.detect_patterns() == {}


def test_a_corrupt_line_does_not_take_the_analysis_down(tmp_path):
    brain = tmp_path / "brain"
    (brain / "improvement").mkdir(parents=True)
    (brain / "improvement" / "trade_autopsies.jsonl").write_text(
        "{not json\n", encoding="utf-8")
    bot = ImprovementBot(portfolio_manager=None,
                         resolver=PathResolver(brain_root=brain),
                         prediction_ledger=None, trade_store=None)
    assert bot.detect_patterns() == {}
