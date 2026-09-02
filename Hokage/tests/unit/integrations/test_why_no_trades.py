"""«Why no trades?» is a question with a detailed answer. He shrugged at it.

2026-09-02, 12:50, on Telegram:

    commander: Why no trades so far?
    Hokage:    I have no trade recorded to explain yet. Ask me again after the
               next entry or exit and I'll walk you through it.

Seventy-five refusals were on record at that moment, each carrying its reasons,
and `gate_analytics` already existed to rank them. The question was answerable
in detail and the answer was a shrug.

THE BUG IS A CATEGORY ERROR. `handle_why` explains a TRADE. Asked about the
ABSENCE of trades it looked in the trade journal, found it empty, and reported
that emptiness as if it were the answer. "Why did you do that" and "why did you
do nothing" are different questions with different evidence behind them.

SAME DOCTRINE AS handle_why: this answers from what was RECORDED. Every number
is counted, never estimated. When there is no record it says so rather than
inventing a story — an invented explanation for silence is worse than silence,
because it cannot be checked.

AND THE RECORD ITSELF WAS HALF-BLIND. Of those 75 rows, every single one was an
index asset. The MCX league logged its stand-asides and journaled NOTHING, so
the gate tally, the daily briefing and any answer about a quiet day were
structurally blind to the arena holding most of the capital — and to the assets
the commander wants mastered. Covered by
tests/unit/bots/autonomous/test_mcx_no_trade_journal.py.
"""
from __future__ import annotations

import pytest

from integrations.notifications.telegram_bot import TelegramBotUplink as T


def _bot():
    return object.__new__(T)


# ------------------------------------------------- recognising the question
@pytest.mark.parametrize("question", [
    "why no trades so far?",
    "Why no trade today",
    "why nothing today?",
    "why havent traded",
    "why haven't traded anything",
    "why didn't you trade",
    "why no entries",
    "why so quiet",
    "why are you not trading",
    "why no positions",
])
def test_every_way_of_asking_about_silence_is_recognised(question):
    low = question.strip().lower().rstrip("?").strip()
    assert T._asks_about_absence(low), question


@pytest.mark.parametrize("question", [
    "why",
    "why simple",
    "why silver",
    "why did you buy that",
    "why the goldm one",
])
def test_a_question_about_an_ACTUAL_trade_is_not_diverted(question):
    """The absence path must not swallow the original feature."""
    low = question.strip().lower().rstrip("?").strip()
    assert not T._asks_about_absence(low), question


def test_the_absence_check_runs_before_the_empty_journal_shrug():
    """Order is the whole fix. Reading the trade journal first is what produced
    "I have no trade recorded to explain yet" for a question that was never
    about a trade."""
    import ast
    import inspect
    import textwrap

    src = textwrap.dedent(inspect.getsource(T.handle_why))
    tree = ast.parse(src)
    absence = shrug = None
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "attr", None) == "_asks_about_absence"
                and absence is None):
            absence = node.lineno
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and "no trade recorded to explain" in node.value):
            shrug = node.lineno
    assert absence and shrug
    assert absence < shrug, "the absence question must be answered first"


# ------------------------------------------------------------- the answer
class _Journal:
    def __init__(self, rows):
        self._rows = rows

    def load_no_trade_decisions(self):
        return self._rows


def _row(asset, reason, ts="2026-09-02T09:16:04+00:00"):
    return {"asset": asset, "timestamp": ts, "decision": "NO_TRADE",
            "reasons": [reason]}


@pytest.fixture
def journal(monkeypatch):
    def _install(rows):
        import bots.autonomous.decision_journal as dj
        monkeypatch.setattr(dj, "DecisionJournalSystem", lambda *a, **k: _Journal(rows))
    return _install


def test_the_answer_counts_what_was_refused_and_why(journal, monkeypatch):
    rows = [_row("NATURALGAS", "EntrySignal: RangeFade: tape is trending (EMA gap 0.35%)")
            for _ in range(12)]
    rows += [_row("GOLDM", "Opening Bell Observation Protocol: prohibited until 09:30")
             for _ in range(3)]
    journal(rows)
    monkeypatch.setattr(T, "escape_markdown", staticmethod(lambda s: s))

    answer = T._explain_no_trades(_bot())
    assert "15" in answer, "it must say how many opportunities it looked at"
    assert "NATURALGAS" in answer
    assert "tape is trending" in answer, "the verbatim reason carries the detail"
    assert "bottleneck" in answer


def test_a_safety_gate_is_labelled_rather_than_blamed(journal, monkeypatch):
    """A gate that exists to protect capital blocking a lot is it working. The
    answer must not invite the commander to tune it.

    The reason text here is the one the classifier ACTUALLY matches
    ("liquidityengine"). My first version of this test invented
    "Liquidity: ATM strike has no open interest", which matches no rule and
    landed in UNCLASSIFIED — a test asserting behaviour on a string the system
    never produces proves nothing about the system."""
    journal([_row("SILVERM", "LiquidityEngine: ATM strike has no market (OI 1)")
             for _ in range(9)])
    monkeypatch.setattr(T, "escape_markdown", staticmethod(lambda s: s))
    assert "blocking is its job" in T._explain_no_trades(_bot())


def test_the_reason_texts_hokage_really_writes_are_classified(journal, monkeypatch):
    """Guards the join between what the bot RECORDS and what the tally can READ.
    An unclassified pile would make the answer say "I don't recognise these",
    which is honest but useless — and it is exactly what happens if a refusal
    is reworded without updating gate_analytics."""
    from bots.autonomous.gate_analytics import GateId, classify_reason

    real = {
        "EntrySignal: RangeFade: tape is trending (EMA gap 0.352%) — refusing to fade it.":
            GateId.ENTRY_SIGNAL,
        "Opening Bell Observation Protocol: Prohibited from executing entry orders until 09:30 AM IST.":
            GateId.OBSERVATION_WINDOW,
        "OptionsRouter: no tradable contract resolved":
            GateId.OPTIONS_ROUTING,
    }
    for reason, gate in real.items():
        assert classify_reason(reason) is gate, reason


def test_no_refusals_at_all_means_he_was_not_SCANNING(journal, monkeypatch):
    """The dangerous case, and the one worth saying out loud. Zero refusals is
    not a quiet market — it is a bot that never looked. On 2026-09-02 a stuck
    connection pool kept him blind for 47 minutes and he made no trades; a
    reply of "nothing met my criteria" would have been a lie."""
    journal([])
    monkeypatch.setattr(T, "escape_markdown", staticmethod(lambda s: s))
    answer = T._explain_no_trades(_bot())
    assert "not been scanning" in answer
    assert "feed" in answer


def test_an_unreadable_journal_refuses_to_guess(monkeypatch):
    """Same rule as handle_why: it answers from facts or admits it cannot."""
    import bots.autonomous.decision_journal as dj

    def _boom(*a, **k):
        raise OSError("journal unreadable")

    monkeypatch.setattr(dj, "DecisionJournalSystem", _boom)
    answer = T._explain_no_trades(_bot())
    assert "could not read" in answer
    assert "will not guess" in answer


def test_yesterdays_refusals_are_not_counted_as_todays(journal, monkeypatch):
    """The window is measured in IST while the journal stores UTC. Getting that
    wrong reports the wrong day to anyone asking in the evening."""
    from datetime import datetime, timedelta, timezone

    now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
    old = (now_ist - timedelta(days=3)).replace(tzinfo=timezone.utc).isoformat()
    fresh = datetime.now(timezone.utc).isoformat()

    journal([_row("NIFTY", "EntrySignal: MacroBreakout: inside range", ts=old)
             for _ in range(50)]
            + [_row("NIFTY", "EntrySignal: MacroBreakout: inside range", ts=fresh)])
    monkeypatch.setattr(T, "escape_markdown", staticmethod(lambda s: s))

    answer = T._explain_no_trades(_bot())
    assert "*1*" in answer, "only today's single refusal should be counted"
    assert "51" not in answer


def test_the_answer_never_calls_an_llm():
    """An invented explanation for silence is worse than silence, because it
    cannot be checked. This is the same reason handle_why exists."""
    import ast
    import inspect
    import textwrap

    tree = ast.parse(textwrap.dedent(inspect.getsource(T._explain_no_trades)))
    names = {getattr(n.func, "attr", None) for n in ast.walk(tree)
             if isinstance(n, ast.Call)}
    names |= {getattr(n.func, "id", None) for n in ast.walk(tree)
              if isinstance(n, ast.Call)}
    for forbidden in ("LLMProcessor", "generate", "complete", "chat"):
        assert forbidden not in names, forbidden
