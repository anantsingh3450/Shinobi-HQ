"""RangeFade's stretch bar is per-asset, because its two assets disagree.

Commander-approved 2026-08-20: loosen NATURALGAS from 0.30% to 0.15%. Swept six
thresholds, train 2026-05..06 against hold-out 2026-07..08, trend guard ON:

    NATURALGAS  >=0.15%  TRAIN n=129 +0.368 t=+1.70   HOLD n=207 +0.486 t=+4.08
                >=0.30%  TRAIN n= 65 +0.196 t=+0.58   HOLD n= 87 +0.585 t=+3.10

    CRUDEOIL    >=0.15%  HOLD n=143  edge=-0.052 t=-0.33
                >=0.30%  HOLD n= 91  edge=-0.174 t=-0.84

Halving the bar doubles NATURALGAS signals and improves BOTH halves. On crude
the hold-out is negative at every band and WORST at 0.15%.

STRETCH_PCT was a single class attribute shared by both assets, so the obvious
edit — change 0.30 to 0.15 — would have bought 57% more crude trades with
negative expectancy at the same time. THAT is what these tests exist to prevent.
"""
from __future__ import annotations

from bots.strategy.components.mcx_entries import MCX_ENTRY_MODULES


def _rangefade():
    return {getattr(m, "module_id", k): m
            for k, m in MCX_ENTRY_MODULES.items()}["entry-rangefade-mcx-v1"]


def test_natural_gas_uses_the_loosened_bar():
    rf = _rangefade()
    assert rf.STRETCH_PCT_BY_ASSET["NATURALGAS"] == 0.15


def test_crude_oil_is_not_in_the_override_table():
    """Its absence is the decision, not an oversight."""
    rf = _rangefade()
    assert "CRUDEOIL" not in rf.STRETCH_PCT_BY_ASSET


def test_crude_oil_still_gets_the_default_bar():
    rf = _rangefade()
    resolved = rf.STRETCH_PCT_BY_ASSET.get("CRUDEOIL", rf.STRETCH_PCT)
    assert resolved == 0.30


def test_the_default_is_unchanged_for_every_other_asset():
    rf = _rangefade()
    for asset in ("CRUDEOIL", "GOLDM", "SILVERM", "COPPER", ""):
        resolved = rf.STRETCH_PCT_BY_ASSET.get(asset.upper(), rf.STRETCH_PCT)
        assert resolved == 0.30, asset


def test_the_lookup_is_case_insensitive_via_upper():
    """The module upper-cases ctx.symbol before the lookup; a lower-case symbol
    must not silently fall back to the stricter default and mute the change."""
    rf = _rangefade()
    assert rf.STRETCH_PCT_BY_ASSET.get("naturalgas".upper(), rf.STRETCH_PCT) == 0.15


def test_the_module_reads_the_table_and_not_the_bare_constant():
    """Guards production. The bug this prevents is a one-character edit to
    STRETCH_PCT that loosens both assets at once, which a value-only test would
    happily pass."""
    import ast
    import inspect
    import textwrap

    from bots.strategy.components.mcx_entries import RangeFadeEntry

    tree = ast.parse(textwrap.dedent(inspect.getsource(RangeFadeEntry.evaluate)))
    reads_table = any(
        isinstance(n, ast.Attribute) and n.attr == "STRETCH_PCT_BY_ASSET"
        for n in ast.walk(tree)
    )
    assert reads_table, "evaluate() must resolve the threshold per asset"

    # And the comparisons must use the resolved value, not the class constant.
    compares_bare = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Attribute) and n.attr == "STRETCH_PCT"
    ]
    # One reference is legitimate: the .get() fallback default.
    assert len(compares_bare) <= 1, (
        "STRETCH_PCT should only appear as the per-asset lookup's fallback"
    )
