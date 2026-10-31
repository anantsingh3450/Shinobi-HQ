"""The bar to REMOVE a strategy was the bar to SHIP one, and it had outgrown
every cell in the arena.

`ship_bar` is Sidak-corrected for the size of the measured family, so it rises
as the arena grows: 2.0, then 3.16 at 32 cells, then 3.22 when FadeRange and
RiderTrend took it to 40. Retirement reused that number. By 2026-10-31 no cell
in either league cleared it — 0 of 29, and 0 even at the old t>=2 — so "below
the bar for two consecutive audits" had stopped being a decline signal and
become a statement of membership.

Run on the first two snapshots that shared geometry (2026-10-23 and
2026-10-30, seven days apart), `plan()` queued 13 OF 14 LIVE PAIRS, among them
the two best cells in the system and all three MacroBreakout cells, every one
of them IMPROVING:

    SessionShift  SILVERM   +3.15 -> +2.65     the only cell above t=2
    SessionShift  GOLDM     +2.71 -> +2.81     improving
    MacroBreakout SENSEX    +1.79 -> +1.97     improving

Only MAX_ARCHIVES_PER_RUN and RAIL 2 stood between that list and an empty
arena — and the single cell RAIL 1 cleared was RangeFade/NATURALGAS at
-0.92 -> -0.63, which is also improving. The worst cell was blocked, so the
fourth-worst took the slot.

AND RAIL 2 COULD NOT SEE A PARKED ASSET. `grep -c PARKED evolution.py` was 0,
so EventRider — negative or indistinguishable from zero on all four of its
assets, pooled t=-1.49 on n=494 at 39.7% accuracy — was blocked on EVERY one
of them because retiring it would "leave CRUDEOIL with no live strategy".
CRUDEOIL has been parked since the seven sweeps that all failed out of sample.
The guard was defending coverage of an asset the bot refuses to trade.
"""
from __future__ import annotations

import pytest

from bots.autonomous import evolution as ev
from tests.unit.bots.autonomous.test_evolution_tiers import _snap, TWO_LIVE

def _sole(asset):
    return {"mod-a": {"strategy_id": "s-a", "name": "Alpha",
                      "status": "SHADOW_MODE", "scope": [asset]}}


SOLE = _sole("CRUDEOIL")

#: The bar the real incident ran at: Sidak-corrected for a 40-cell family, and
#: above every cell in it.
BAR = 3.22


def _archives(now_t, prev_t, lineup=TWO_LIVE, asset="GOLDM", bar=BAR, **extra):
    prev = _snap("2026-10-23", {("mod-a", asset): prev_t}, lineup, bar=bar)
    now = _snap("2026-10-30", {("mod-a", asset): now_t}, lineup, bar=bar)
    now.update(extra)
    return [d for d in ev.plan([now, prev]) if d.action == "archive"]


# ------------------------------------- unconfirmed is not the same as harmful
def test_the_best_cell_in_the_system_is_never_retired_autonomously():
    """SessionShift/SILVERM, the real numbers. It is the ONLY cell above t=2
    and the old rule queued it for retirement."""
    d, = _archives(2.65, 3.15)
    assert not d.is_autonomous
    assert d.tier == ev.TIER_PROPOSE
    assert "not measurably harmful" in d.blocked_reason


def test_an_improving_cell_is_never_retired_autonomously():
    """MacroBreakout/SENSEX: +1.79 -> +1.97, queued by the old rule."""
    d, = _archives(1.97, 1.79)
    assert not d.is_autonomous


def test_a_positive_cell_is_still_REPORTED_not_silently_dropped():
    """Narrowing retirement must not hide the fact that a cell is unconfirmed.
    It stays in the report; it just cannot be acted on."""
    d, = _archives(1.97, 1.79)
    assert d.action == "archive"
    assert f"{ev.RETIRE_T:+.2f}" in d.blocked_reason
    assert "SHIP bar" in d.blocked_reason


@pytest.mark.parametrize("now_t,prev_t", [(0.0, -1.0), (-1.0, 0.0), (0.0, 0.0)])
def test_exactly_zero_is_not_harmful(now_t, prev_t):
    """A zero edge is money going nowhere, not money going the wrong way, and
    BOTH readings must be below the bar."""
    d, = _archives(now_t, prev_t)
    assert not d.is_autonomous


def test_negative_in_both_readings_IS_retired():
    d, = _archives(-0.66, -1.12)      # TrendRider/NATURALGAS, real numbers
    assert d.is_autonomous
    assert d.blocked_reason is None


def test_one_negative_reading_is_not_enough():
    d, = _archives(-1.2, 0.5)
    assert not d.is_autonomous


# ------------------------------------ a parked asset is a decision, not a gap
def test_a_parked_asset_is_not_coverage_worth_defending():
    """EventRider's real block: sole coverer of CRUDEOIL, which is parked."""
    d, = _archives(-1.51, -1.95, lineup=SOLE, asset="CRUDEOIL",
                   parked_assets=["CRUDEOIL"])
    assert d.is_autonomous, "a parked asset must not shield a losing module"
    assert d.blocked_reason is None


def test_an_UNPARKED_asset_still_blocks_the_same_way():
    """RAIL 2's real job is untouched."""
    d, = _archives(-1.51, -1.95, lineup=SOLE, asset="CRUDEOIL",
                   parked_assets=[])
    assert not d.is_autonomous
    assert "no live strategy" in d.blocked_reason


def test_the_snapshots_own_stamp_wins_over_the_live_constant():
    """A retirement must be reproducible from the snapshot alone, which is why
    geometry is stamped too. An empty stamp is an answer, not a missing one."""
    d, = _archives(-1.51, -1.95, lineup=SOLE, asset="CRUDEOIL",
                   parked_assets=[])
    assert not d.is_autonomous


def test_the_parked_list_is_case_insensitive():
    d, = _archives(-1.51, -1.95, lineup=SOLE, asset="CRUDEOIL",
                   parked_assets=["crudeoil"])
    assert d.is_autonomous


def test_an_unreadable_parked_list_blocks_rather_than_allows():
    """The conservative direction: not knowing must never ALLOW a retirement."""
    assert ev._parked_assets({"parked_assets": None}) == \
        ev._parked_assets({})          # both fall back, neither invents
    d, = _archives(-1.51, -1.95, lineup=_sole("SILVERM"), asset="SILVERM")
    assert not d.is_autonomous, "SILVERM is not parked, so RAIL 2 must hold"


# --------------------------------------------- the audit stamps what it knew
def test_the_audit_stamps_the_parked_list_into_the_snapshot():
    import sys
    from pathlib import Path
    root = next(p for p in Path(__file__).resolve().parents
                if (p / "pyproject.toml").is_file())
    sys.path.insert(0, str(root / "tools" / "research"))
    import weekly_audit
    assert callable(weekly_audit._parked_now)
    src = Path(weekly_audit.__file__).read_text(encoding="utf-8")
    assert '"parked_assets": sorted(_parked_now())' in src
