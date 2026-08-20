"""Two exchanges closing in the same second must not collide on report_id.

2026-08-20 15:30:31: NSE and BSE both closed, both auto-stopped their shadow
sessions, and both generated an EOD validation report inside the SAME SECOND.
NSE wrote first. BSE died on:

    UNIQUE constraint failed: immutable_validation_reports.report_id

because the id was VAL_REP_{type}_{yyyymmdd_HHMMSS} — resolved to the second,
with nothing in it identifying the session. The day before, the two landed one
second apart (..._153041 and ..._153042) and both survived. So this is a RACE:
it only bites when two exchanges share a second, and when it does it always
kills the second one. The audit trail was quietly missing BSE days at random.

session_id already encodes both the exchange and the session start, so putting
it in the id makes uniqueness structural instead of a matter of timing.
"""
from __future__ import annotations

import re


def _report_id(report_type: str, session_id: str, stamp: str) -> str:
    """Mirror of the shipped construction, so the format can be asserted
    without standing up a database. Kept honest by
    test_the_shipped_code_includes_the_session_id below."""
    return f"VAL_REP_{report_type.upper()}_{session_id}_{stamp}"


def test_two_exchanges_in_the_same_second_get_different_ids():
    """The exact 2026-08-20 collision."""
    stamp = "20260820_153031"
    nse = _report_id("DAILY", "SHADOW_SES_NSE_20260820_091505", stamp)
    bse = _report_id("DAILY", "SHADOW_SES_BSE_20260820_091505", stamp)
    assert nse != bse


def test_all_six_exchanges_in_one_second_stay_distinct():
    stamp = "20260820_153031"
    ids = {
        _report_id("DAILY", f"SHADOW_SES_{ex}_20260820_091505", stamp)
        for ex in ("NSE", "BSE", "MCX", "NASDAQ", "BINANCE", "OANDA")
    }
    assert len(ids) == 6


def test_the_same_session_twice_in_one_second_still_collides():
    """Deliberate. Two reports for ONE session in the same second is a genuine
    duplicate, and the UNIQUE constraint should still catch it — the fix is
    about distinguishing sessions, not about defeating the constraint."""
    stamp = "20260820_153031"
    sid = "SHADOW_SES_NSE_20260820_091505"
    assert _report_id("DAILY", sid, stamp) == _report_id("DAILY", sid, stamp)


def test_report_type_still_separates_daily_from_weekly():
    stamp = "20260820_153031"
    sid = "SHADOW_SES_NSE_20260820_091505"
    assert _report_id("DAILY", sid, stamp) != _report_id("WEEKLY", sid, stamp)


def test_the_id_remains_readable_and_prefixed():
    rid = _report_id("DAILY", "SHADOW_SES_BSE_20260820_091505", "20260820_153031")
    assert rid.startswith("VAL_REP_DAILY_")
    assert "BSE" in rid
    assert re.search(r"\d{8}_\d{6}$", rid), "timestamp suffix should survive"


def test_the_shipped_code_includes_the_session_id():
    """Guards production, so the helper above cannot drift from it.

    A test that only exercised the local mirror would have passed happily on
    every day this was broken.
    """
    import ast
    import inspect
    import textwrap

    from bots.autonomous.shadow_engine import ShadowEngine

    tree = ast.parse(textwrap.dedent(
        inspect.getsource(ShadowEngine.generate_and_archive_report)
    ))
    # Find the f-string pieces assigned to report_id and confirm session_id is
    # one of the interpolated names.
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "report_id" not in targets:
                continue
            for sub in ast.walk(node.value):
                if isinstance(sub, ast.Name):
                    names.add(sub.id)
    assert "session_id" in names, (
        "report_id must include session_id, or two exchanges closing in the "
        "same second will collide on the UNIQUE constraint again"
    )
