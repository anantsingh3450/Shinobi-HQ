"""A shipped fix sat inert for a week because one field was missing.

2026-10-29 was EIA Thursday. EIAReaction reached its window for only the
second time in its life, fired twice, and WON the 20:30 auction at conf 61:

    EIAReaction: the storage print moved the tape +1.80 (0.63 ATR) and the
    release bar has closed - fading it into the post-vacuum hour.

One second later:

    Bias engine: NATURALGAS MIXED - 1.77 ATR from VWAP, too extended to join
    the trend (needs <= 0.5)
    MCX Arena entry blocked for NATURALGAS

A fade module refused for being too extended to JOIN a trend it was betting
against. It carries COUNTER_TREND = True, and commit a68de90 - "A fade
module was sitting behind a trend-join gate", 2026-10-23 - added that flag
for precisely this reason, the day after the same gate blocked the same
module at 2.13 ATR.

THE FLAG WAS RIGHT. THE LOOKUP WAS BLIND. The exemption resolves through
_is_counter_trend_strategy(selected_strat.get("strategy_id")), and the
EIAReaction record in the MCX portfolio was a stub:

    strat-eiareaction-mcx-v1    7 fields
    every other competitor      18 fields

"strategy_id" was among the eleven it lacked. The record is the VALUE in a
dict keyed by its own id, so carrying that id inside itself looks redundant -
until something asks the record what it is called. The lookup returned None,
the exemption evaluated False, and an approved fix was dead on arrival for a
week while the module it was written for kept being blocked.

Nothing failed. No exception, no rejected order, no missing feed. The record
was simply thinner than its neighbours, and an absent field reads as "not
counter-trend" rather than as "unknown".

Third audit in this family, and the same lesson each time: a broke strategy
wins auctions and fills nothing; an orphaned asset never trades at all; an
incomplete record changes how the gates judge a strategy and says nothing.
ABSENT IS NOT FALSE.

WHAT THIS FILE PINS: that the audit finds a thin record, that it names what
the missing field costs, that it cannot manufacture findings from one odd
peer, and that it stays silent when every competitor matches.
"""
from __future__ import annotations

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot


FULL = {
    "strategy_id": "strat-x-mcx-v1",
    "name": "Full",
    "status": "ACTIVE",
    "created_at": "2026-01-01T00:00:00+00:00",
    "win_rate": {"DEFAULT": 50.0},
    "expectancy": {"DEFAULT": 0.0},
    "trade_count": {"DEFAULT": 0},
    "sharpe_ratio": {"DEFAULT": 1.0},
    "capital": {"starting": 100_000.0, "realized_pnl": 0.0},
}


def _record(sid: str, **changes) -> dict:
    rec = dict(FULL, strategy_id=sid, name=sid.split("-")[1].title())
    for key, value in changes.items():
        if value is None:
            rec.pop(key, None)
        else:
            rec[key] = value
    return rec


def _bot(mcx: dict | None = None, index: dict | None = None):
    bot = object.__new__(Bot)
    bot.mcx_strategy_portfolio = (
        type("M", (), {"portfolio": {"strategies": mcx}})() if mcx is not None else None
    )
    bot.strategy_portfolio = (
        type("I", (), {"portfolio": {"strategies": index}})() if index is not None else None
    )
    return bot


# ------------------------------------------------------- 1. it finds the hole
def test_the_stub_record_is_named():
    """THE WHOLE POINT, in the shape it actually occurred."""
    bot = _bot({
        "strat-eiareaction-mcx-v1": {"name": "EIAReaction", "status": "ACTIVE",
                                     "capital": {"starting": 100_000.0}},
        "strat-trendrider-mcx-v1": _record("strat-trendrider-mcx-v1"),
        "strat-rangefade-mcx-v1": _record("strat-rangefade-mcx-v1"),
    })
    findings = bot.audit_strategy_records()
    assert len(findings) == 1
    assert "EIAReaction" in findings[0]
    assert "strategy_id" in findings[0]


def test_the_finding_says_what_the_missing_field_costs():
    """A list of absent keys is a puzzle. The reason EIAReaction could not
    trade is the consequence, not the key name."""
    bot = _bot({
        "strat-eia-mcx-v1": _record("strat-eia-mcx-v1", strategy_id=None),
        "strat-trendrider-mcx-v1": _record("strat-trendrider-mcx-v1"),
    })
    line = bot.audit_strategy_records()[0]
    assert "counter-trend exemption" in line
    assert "chest lookup" in line


def test_a_field_with_no_recorded_consequence_is_still_reported():
    """The catalogue of costs will never be complete. An unlisted field is
    still a difference from every peer, and that is the finding."""
    bot = _bot({
        "strat-eia-mcx-v1": _record("strat-eia-mcx-v1", regime_stats=None),
        "strat-trendrider-mcx-v1": _record("strat-trendrider-mcx-v1", regime_stats={}),
        "strat-rangefade-mcx-v1": _record("strat-rangefade-mcx-v1", regime_stats={}),
    })
    line = bot.audit_strategy_records()[0]
    assert "regime_stats" in line


def test_both_leagues_are_audited():
    bot = _bot(
        mcx={
            "strat-eia-mcx-v1": _record("strat-eia-mcx-v1", strategy_id=None),
            "strat-trendrider-mcx-v1": _record("strat-trendrider-mcx-v1"),
        },
        index={
            "strat-malfoy-v1": _record("strat-malfoy-v1", created_at=None),
            "strat-trendpullback-v1": _record("strat-trendpullback-v1"),
        },
    )
    findings = bot.audit_strategy_records()
    assert len(findings) == 2
    assert any("MCX Arena" in f for f in findings)
    assert any("Index Dojo" in f for f in findings)


# -------------------------------------------- 2. it cannot cry wolf
def test_a_matching_field_set_says_nothing():
    """Every healthy boot calls this. It must not narrate."""
    bot = _bot({
        "strat-a-mcx-v1": _record("strat-a-mcx-v1"),
        "strat-b-mcx-v1": _record("strat-b-mcx-v1"),
    })
    assert bot.audit_strategy_records() == []


def test_one_peer_with_an_extra_field_does_not_indict_the_rest():
    """CONSERVATIVE ON PURPOSE. Only fields that EVERY other competitor
    carries count, or a single unusual record manufactures a finding against
    all of its neighbours - the reasoning that put CRUDEOIL in PARKED_ASSETS
    rather than letting the orphan audit scream on every boot."""
    bot = _bot({
        "strat-a-mcx-v1": _record("strat-a-mcx-v1", experiment={"n": 1}),
        "strat-b-mcx-v1": _record("strat-b-mcx-v1"),
        "strat-c-mcx-v1": _record("strat-c-mcx-v1"),
    })
    assert bot.audit_strategy_records() == []


def test_an_archived_strategy_is_not_compared():
    """It cannot trade by design, and old records are allowed to be old."""
    bot = _bot({
        "strat-dead-mcx-v1": {"name": "Dead", "status": "ARCHIVED"},
        "strat-a-mcx-v1": _record("strat-a-mcx-v1"),
        "strat-b-mcx-v1": _record("strat-b-mcx-v1"),
    })
    assert bot.audit_strategy_records() == []


def test_a_single_competitor_has_nothing_to_be_compared_against():
    """One record is not a sample. Reporting it against a hardcoded field
    list would make this audit an opinion about schema rather than a
    measurement of divergence."""
    bot = _bot({"strat-only-mcx-v1": {"name": "Only", "status": "ACTIVE"}})
    assert bot.audit_strategy_records() == []


def test_a_missing_portfolio_is_not_an_error():
    assert _bot().audit_strategy_records() == []


def test_a_non_dict_record_is_skipped_rather_than_crashing():
    bot = _bot({
        "strat-junk-mcx-v1": "this is not a record",
        "strat-a-mcx-v1": _record("strat-a-mcx-v1"),
        "strat-b-mcx-v1": _record("strat-b-mcx-v1"),
    })
    assert bot.audit_strategy_records() == []


# ------------------------------------------------- 3. the announcement
class _Telegram:
    def __init__(self):
        self.sent: list[str] = []

    def send_message(self, text):
        self.sent.append(text)


def _thin_bot(telegram=None):
    bot = _bot({
        "strat-eia-mcx-v1": _record("strat-eia-mcx-v1", strategy_id=None),
        "strat-trendrider-mcx-v1": _record("strat-trendrider-mcx-v1"),
    })
    bot.telegram_bot = telegram
    return bot


def test_a_finding_is_critical_and_reaches_telegram(caplog):
    tg = _Telegram()
    bot = _thin_bot(tg)
    with caplog.at_level("CRITICAL"):
        bot._announce_incomplete_strategy_records()
    assert "INCOMPLETE STRATEGY RECORD" in caplog.text
    assert len(tg.sent) == 1
    assert "strategy_id" in tg.sent[0]


def test_it_runs_once_per_boot_not_once_per_loop():
    """A critical that repeats every sixty seconds teaches the commander to
    ignore criticals."""
    tg = _Telegram()
    bot = _thin_bot(tg)
    for _ in range(10):
        bot._announce_incomplete_strategy_records()
    assert len(tg.sent) == 1


def test_a_clean_audit_logs_the_all_clear_and_sends_nothing(caplog):
    """Silence and success must be distinguishable in the log - that is the
    fault this whole project exists to hunt."""
    tg = _Telegram()
    bot = _bot({"strat-a-mcx-v1": _record("strat-a-mcx-v1"),
                "strat-b-mcx-v1": _record("strat-b-mcx-v1")})
    bot.telegram_bot = tg
    with caplog.at_level("INFO"):
        bot._announce_incomplete_strategy_records()
    assert "every competitor carries the same fields" in caplog.text
    assert tg.sent == []


def test_a_telegram_that_throws_never_breaks_the_boot():
    class _Broken:
        def send_message(self, text):
            raise RuntimeError("telegram down")

    _thin_bot(_Broken())._announce_incomplete_strategy_records()      # must not raise


def test_a_missing_telegram_never_breaks_the_boot():
    _thin_bot(None)._announce_incomplete_strategy_records()           # must not raise


def test_an_audit_that_raises_never_breaks_the_boot(caplog, monkeypatch):
    bot = _thin_bot()
    monkeypatch.setattr(
        Bot, "audit_strategy_records",
        lambda self: (_ for _ in ()).throw(RuntimeError("audit exploded")),
    )
    with caplog.at_level("ERROR"):
        bot._announce_incomplete_strategy_records()                   # must not raise
    assert "Strategy record audit failed" in caplog.text
