"""The age limit deleted the only alarm that mattered.

2026-11-04 22:38 the host stopped resolving DNS and stayed that way for about
eleven hours. api.kite.trade and api.telegram.org failed alike, so Hokage
could not see AND could not say so. "HOKAGE IS BLIND - MARKET DATA
UNREACHABLE" was raised 104 times into a dead pipe, held in the deferral
queue, and then thrown away:

    01:46:35 WARNING Dropping a deferred Telegram alert raised 183 min ago
             (104x), too old to be worth sending: HOKAGE IS BLIND ...

Five alerts went that way overnight. The Kite token then expired at 04:30 and
nobody knew to renew it, so Thursday 2026-11-05 was a blind day: twenty-seven
hours without a feed, zero trades, and the EIAReaction scan - which can only
fire on a Thursday - never happened.

THE RULE WAS RIGHT ABOUT THE WRONG THING. Two hours is correct for a message
whose SUBJECT has expired: an end-of-day report arriving tomorrow is noise,
and noise is what teaches someone to stop reading the channel. It is wrong for
a message whose subject was STILL HAPPENING nine hours after the queue
deleted it. The old code could not tell those apart because it only looked at
the clock.

So age now retires perishable alerts only, and perishable is an explicit short
list. Everything else is durable: never dropped for age, persisted across a
restart, delivered ahead of routine traffic, and stamped with its real age so
a replay can never read as current.

THE DEFAULT IS THE DESIGN. Listing what to KEEP would mean an alarm written
six months from now, which nobody remembered to add to the list, is silently
deleted during the exact outage it was written for. That is the shape of
`absent-is-not-false`, and this module inverts it.
"""
from __future__ import annotations

import time

import pytest
import requests

from integrations.notifications.telegram_bot import TelegramBotUplink

TOKEN = "111:fake-not-a-real-token"

#: Verbatim from the overnight log, which is the point.
BLIND = "⚠️ *HOKAGE IS BLIND — MARKET DATA UNREACHABLE* ⚠️"
LOGIN = "🚨 *HOKAGE IS BLIND — ZERODHA LOGIN NEEDED* 🚨"
BLACKOUT = "ARENA BLACKOUT\n\nNATURALGAS has had no market context for 4 scans"
EXIT = "🔴 *EXIT · Natural Gas · 280 CALL*\n• *P&L*: -₹1,312.50"

#: Genuinely worthless late. Also from the log: one of these was dropped at
#: 01:46 beside the blind alarm, and that drop was correct.
EOD = "📊 Hokage — how today went (MCX Arena — Wednesday, 04 Nov 2026)"
BRIEF = "🚨 Morning System Check - all engines nominal"


class _Response:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


DNS = requests.exceptions.ConnectionError(
    "HTTPSConnectionPool(host='api.telegram.org', port=443): "
    "Failed to resolve 'api.telegram.org' ([Errno 11001] getaddrinfo failed)"
)


@pytest.fixture
def bot(monkeypatch, tmp_path) -> TelegramBotUplink:
    """PER-TEST BRAIN ROOT. The durable queue is persisted now, and the
    suite's sandbox root is one directory for the whole session - so without
    this, an alarm deferred by one test is restored by the next test's
    constructor."""
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path))
    b = TelegramBotUplink(bot_token=TOKEN, chat_id="999")
    b.enabled = True
    monkeypatch.setattr(
        requests, "post",
        lambda *a, **k: pytest.fail("a test reached requests.post unstubbed"),
    )
    return b


def _sends(monkeypatch, outcomes):
    sent: list[str] = []
    seq = list(outcomes)

    def post(url, json=None, timeout=None, **kw):
        sent.append((json or {}).get("text", ""))
        outcome = seq.pop(0) if seq else outcomes[-1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(requests, "post", post)
    return sent


def _age(bot, text, seconds):
    bot._deferred[text]["first"] = time.time() - seconds


# ===================================================== the incident itself
@pytest.mark.parametrize("durable", [BLIND, LOGIN, BLACKOUT, EXIT])
def test_a_durable_alarm_is_never_dropped_for_age(bot, monkeypatch, durable):
    """THE RAIL. Eleven hours is not too long to hold an alarm about a
    condition that lasted twenty-seven."""
    _sends(monkeypatch, [DNS])
    bot.send_message(durable)
    _age(bot, durable, 11 * 3600)

    _sends(monkeypatch, [DNS])
    bot._flush_deferred()

    assert durable in bot._deferred, (
        "a load-bearing alarm was deleted for being old - the 2026-11-04 defect")


def test_the_eleven_hour_alarm_is_eventually_delivered(bot, monkeypatch):
    """Holding it is only half the job. It has to arrive, and it has to say
    how old it is, or he acts on a condition that already cleared."""
    _sends(monkeypatch, [DNS])
    bot.send_message(BLIND)
    _age(bot, BLIND, 11 * 3600)

    sent = _sends(monkeypatch, [_Response(200), _Response(200)])
    bot.send_message("✅ login complete")

    replay = next((s for s in sent if "BLIND" in s), None)
    assert replay is not None, "it was held forever instead of delivered"
    assert "660 min ago" in replay, "it arrived without its real age"
    assert "DELAYED ALERT" in replay


def test_the_hundred_and_four_raises_still_collapse(bot, monkeypatch):
    """The alarm was raised 104 times. Delivering 104 copies would be its own
    failure - the fix for alarm loss must not manufacture alarm fatigue."""
    _sends(monkeypatch, [DNS])
    for _ in range(104):
        bot.send_message(BLIND)
    _age(bot, BLIND, 11 * 3600)

    assert len(bot._deferred) == 1
    assert bot._deferred[BLIND]["count"] == 104

    sent = _sends(monkeypatch, [_Response(200), _Response(200)])
    bot.send_message("x")
    assert sum("BLIND" in s for s in sent) == 1
    assert "104 times" in next(s for s in sent if "BLIND" in s)


# ===================================================== the limit still bites
@pytest.mark.parametrize("perishable", [EOD, BRIEF])
def test_a_perishable_alert_still_expires(bot, monkeypatch, perishable):
    """The age rule is not abolished. A report of a day that has ended really
    is worthless late."""
    _sends(monkeypatch, [DNS])
    bot.send_message(perishable)
    _age(bot, perishable, bot._DEFERRED_MAX_AGE_SECONDS + 60)

    _sends(monkeypatch, [_Response(200)])
    bot.send_message("x")
    assert perishable not in bot._deferred


def test_an_unrecognised_alert_is_treated_as_durable(bot, monkeypatch):
    """THE DEFAULT IS THE WHOLE DESIGN. An alarm written later, that nobody
    remembered to classify, must be KEPT."""
    novel = "🆕 an alarm nobody has written yet"
    assert bot._is_perishable(novel) is False

    _sends(monkeypatch, [DNS])
    bot.send_message(novel)
    _age(bot, novel, 11 * 3600)
    _sends(monkeypatch, [DNS])
    bot._flush_deferred()
    assert novel in bot._deferred


def test_a_preamble_is_never_requeued(bot):
    """A flushed alert already carries DELAYED ALERT. If that text were
    deferred again it would accrete preambles forever."""
    assert bot._is_perishable("⏱ *DELAYED ALERT* - raised 22:38 IST") is True


# ===================================================== a full queue
def test_a_full_queue_evicts_noise_before_an_alarm(bot, monkeypatch):
    """Forty routine messages must not push the blind alarm out of a bounded
    queue - that is the same loss through a different door."""
    _sends(monkeypatch, [DNS])
    bot.send_message(BLIND)                       # the OLDEST entry
    for i in range(bot._DEFERRED_MAX_ENTRIES + 5):
        bot.send_message(f"{EOD} #{i}")

    assert len(bot._deferred) <= bot._DEFERRED_MAX_ENTRIES
    assert BLIND in bot._deferred, "the alarm was evicted in favour of reports"


def test_a_queue_full_of_alarms_says_so_at_critical(bot, monkeypatch, caplog):
    """When everything held is load-bearing, something IS being lost. A silent
    drop there would be the original bug wearing a different hat."""
    _sends(monkeypatch, [DNS])
    with caplog.at_level("CRITICAL", logger="Hokage.TelegramBot"):
        for i in range(bot._DEFERRED_MAX_ENTRIES + 2):
            bot.send_message(f"🚨 distinct alarm {i}")
    assert "DURABLE" in caplog.text


def test_the_flush_sends_alarms_before_reports(bot, monkeypatch):
    """Only _DEFERRED_FLUSH_BATCH go per flush. A queue of ten reports and one
    alarm must not spend the whole batch on the reports."""
    _sends(monkeypatch, [DNS])
    for i in range(10):
        bot.send_message(f"{EOD} #{i}")
    bot.send_message(BLIND)                       # newest, but load-bearing

    sent = _sends(monkeypatch, [_Response(200)] * 12)
    bot._flush_deferred()
    assert any("BLIND" in s for s in sent), "the alarm queued behind the reports"


# ===================================================== across a restart
def test_a_durable_alarm_survives_a_restart(bot, monkeypatch):
    """A queue that lives only in memory still loses the alarm when the
    process restarts mid-outage - which is exactly when someone restarts it."""
    _sends(monkeypatch, [DNS])
    bot.send_message(BLIND)

    reborn = TelegramBotUplink(bot_token=TOKEN, chat_id="999")
    assert BLIND in reborn._deferred, "the alarm died with the process"
    assert reborn._deferred[BLIND]["restored"] is True


def test_a_restored_alarm_admits_it_may_be_stale(bot):
    """The restart that preserved it may be the restart that fixed it."""
    now = time.time()
    head = bot._deferred_preamble(
        {"first": now - 600, "last": now - 60, "count": 3, "restored": True}, now)
    assert "may have cleared" in head


def test_a_perishable_alert_does_not_survive_a_restart(bot, monkeypatch):
    _sends(monkeypatch, [DNS])
    bot.send_message(EOD)
    reborn = TelegramBotUplink(bot_token=TOKEN, chat_id="999")
    assert EOD not in reborn._deferred


def test_a_day_old_alarm_is_let_go_on_restart(bot, monkeypatch, caplog):
    """"Never dropped" cannot mean forever: a day-old blind alarm tells him
    nothing the log does not, and would compete with whatever is true now."""
    _sends(monkeypatch, [DNS])
    bot.send_message(BLIND)
    _age(bot, BLIND, bot._DEFERRED_RESTART_MAX_AGE_SECONDS + 60)
    bot._save_deferred()

    with caplog.at_level("WARNING", logger="Hokage.TelegramBot"):
        reborn = TelegramBotUplink(bot_token=TOKEN, chat_id="999")
    assert BLIND not in reborn._deferred
    assert "Let go of 1" in caplog.text


def test_delivery_is_not_undone_by_a_restart(bot, monkeypatch):
    """A restart right after a drain must not resurrect what he was told."""
    _sends(monkeypatch, [DNS])
    bot.send_message(BLIND)
    _sends(monkeypatch, [_Response(200), _Response(200)])
    bot.send_message("x")
    assert not bot._deferred

    reborn = TelegramBotUplink(bot_token=TOKEN, chat_id="999")
    assert not reborn._deferred, "a delivered alarm came back from disk"


# ===================================================== the write is safe
def test_a_corrupt_queue_file_does_not_stop_the_uplink(bot, monkeypatch):
    """Never raise on the read path. An unparseable queue costs the queue,
    never the ability to send the next alert."""
    bot._deferred_path().write_text("{not json at all", encoding="utf-8")

    reborn = TelegramBotUplink(bot_token=TOKEN, chat_id="999")
    assert reborn._deferred == {}
    reborn.enabled = True
    sent = _sends(monkeypatch, [_Response(200)])
    assert reborn.send_message("still working") is True
    assert sent


def test_a_bom_in_the_queue_file_is_tolerated(bot, monkeypatch):
    """Any file on this machine may have been rewritten by PowerShell, and
    json.loads treats a BOM as a parse error."""
    import json
    now = time.time()
    bot._deferred_path().write_text(
        "﻿" + json.dumps({BLIND: {"first": now, "last": now, "count": 2}}),
        encoding="utf-8")

    reborn = TelegramBotUplink(bot_token=TOKEN, chat_id="999")
    assert BLIND in reborn._deferred


def test_the_queue_file_is_written_temp_then_renamed(bot, monkeypatch):
    """active_positions.json was truncated 168 times by a json.dump straight
    into an open "w" handle. A failed write here must cost the new copy, never
    the queue already on disk."""
    _sends(monkeypatch, [DNS])
    bot.send_message(BLIND)
    path = bot._deferred_path()
    assert path.exists()
    good = path.read_text(encoding="utf-8")

    import json as _json
    monkeypatch.setattr(
        _json, "dumps",
        lambda *a, **k: (_ for _ in ()).throw(ValueError("unserialisable")))
    bot.send_message("another alarm")            # save must fail, not destroy

    assert path.read_text(encoding="utf-8") == good, "a failed save truncated it"


def test_the_queue_file_is_removed_when_the_queue_empties(bot, monkeypatch):
    """A stale file left behind would be restored by the next restart."""
    _sends(monkeypatch, [DNS])
    bot.send_message(BLIND)
    assert bot._deferred_path().exists()

    _sends(monkeypatch, [_Response(200), _Response(200)])
    bot.send_message("x")
    assert not bot._deferred_path().exists()
