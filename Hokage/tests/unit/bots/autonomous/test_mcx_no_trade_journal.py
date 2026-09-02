"""The commodity arena refused things all day and recorded none of it.

2026-09-02. The commander asked on Telegram "Why no trades so far?" and got a
shrug. Chasing that turned up the deeper fault: `no_trade_decisions` held 75
rows for the day and EVERY ONE was an index asset.

    BANKNIFTY  25    NIFTY  25    SENSEX  25
    CRUDEOIL    0    NATURALGAS 0    GOLDM  0    SILVERM  0

The index league journals its refusals. The MCX league logged them to a file,
published them on the event bus, and journaled nothing — so `/journal/gate-tally`,
the daily briefing, and any answer about a quiet day were structurally blind to
the arena holding most of the capital and both assets the commander wants
mastered. A refusal that is only ever printed is a refusal nobody can count.

Three places refuse an MCX entry and all three must record it:
  * no module wanted it            (the auction found no winner)
  * the entry conduct gate         (bias alignment, IV premium)
  * the portfolio cluster gate     (correlation cap, opposing bet, watermark)

The last two are the interesting ones — they are refusals of a signal that WAS
generated, which is the difference between "nothing set up" and "something set
up and I stopped it".
"""
from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

from bots.autonomous.autonomous_bot import AutonomousTradingBot as Bot


class _Journal:
    def __init__(self):
        self.records = []

    def record_no_trade_decision(self, decision):
        self.records.append(decision)


def _bot(journal=None):
    bot = object.__new__(Bot)
    bot.journal = journal
    return bot


def test_a_refusal_is_recorded_with_its_asset_and_reasons():
    journal = _Journal()
    Bot._journal_no_trade(_bot(journal), "NATURALGAS",
                          ["EntrySignal: RangeFade: tape is trending (EMA gap 0.352%)"])
    assert len(journal.records) == 1
    rec = journal.records[0]
    assert rec.asset == "NATURALGAS"
    assert rec.decision == "NO_TRADE"
    assert "tape is trending" in rec.reasons[0]


def test_the_asset_is_normalised_so_the_tally_can_group_it():
    journal = _Journal()
    Bot._journal_no_trade(_bot(journal), "naturalgas", ["EntrySignal: x"])
    assert journal.records[0].asset == "NATURALGAS"


def test_the_league_is_recorded_so_MCX_can_be_told_from_the_index():
    journal = _Journal()
    Bot._journal_no_trade(_bot(journal), "GOLDM", ["EntrySignal: x"])
    assert journal.records[0].supporting_evidence.get("league") == "MCX"


def test_the_recorded_reason_is_one_the_gate_classifier_understands():
    """Recording a refusal the tally cannot classify would move the blindness
    rather than fix it — the rows would exist and land in UNCLASSIFIED."""
    from bots.autonomous.gate_analytics import GateId, classify_reason

    journal = _Journal()
    Bot._journal_no_trade(
        _bot(journal), "NATURALGAS",
        ["EntrySignal: RangeFade: RangeFade: outside the 09:30-17:00 IST quiet window."])
    assert classify_reason(journal.records[0].reasons[0]) is GateId.ENTRY_SIGNAL


# ------------------------------------------------------------ never fatal
def test_a_missing_journal_does_not_stop_the_scan():
    Bot._journal_no_trade(_bot(None), "GOLDM", ["EntrySignal: x"])   # must not raise


def test_a_journal_that_throws_does_not_stop_the_scan():
    class _Broken:
        def record_no_trade_decision(self, decision):
            raise OSError("disk full")

    Bot._journal_no_trade(_bot(_Broken()), "GOLDM", ["EntrySignal: x"])


# --------------------------------------------- every refusal path is wired
def _calls_in(method_name):
    src = textwrap.dedent(inspect.getsource(getattr(Bot, method_name)))
    return [n for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Call)
            and getattr(n.func, "attr", None) == "_journal_no_trade"]


def test_all_three_mcx_refusal_paths_record_their_decision():
    """The stand-aside, the conduct gate and the cluster gate. Wiring only the
    first would leave the two most interesting refusals — a signal that existed
    and was stopped — invisible again."""
    assert len(_calls_in("_scan_and_enter_mcx_opportunities")) >= 3


def test_the_journalling_never_swallows_the_log_line():
    """The log line stays: it is what a human reads live, and the journal is
    what the tally counts. Losing either would trade one blindness for another."""
    src = inspect.getsource(Bot._scan_and_enter_mcx_opportunities)
    assert "MCX league stand-aside on" in src
    assert "MCX Arena entry blocked for" in src
