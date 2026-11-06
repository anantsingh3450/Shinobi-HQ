"""The alarm about the network cannot travel over the network.

2026-10-13 14:51:58 the host stopped resolving DNS. api.kite.trade and
api.telegram.org failed alike, so Hokage went blind for 27 minutes AND could
not say so:

    14:52:12  CRITICAL: Market data feed is DOWN (network)
    14:52:12  Telegram NOT SENT: getaddrinfo failed: 'api.telegram.org'
       ...    26 of each, one per minute
    15:17:40  last one
    15:18:44  Market data feed recovered by re-authenticating

26 alerts were audited "NOT SENT" and dropped. The commander was never going
to learn about those 27 minutes - the only record was a log file, read 45
minutes after the fact and only because someone went looking.

So undeliverable alerts are now held and sent when the link returns. Three
things make that safe rather than merely noisy, and all three are pinned here:

  1. A REPLAY MUST NOT READ AS CURRENT. "HOKAGE IS BLIND" arriving while the
     feed is live is worse than silence - he would act on a condition that had
     already cleared. Every flushed alert leads with its real age.

  2. IDENTICAL ALARMS COLLAPSE. Delivering 26 copies teaches him to mute the
     channel, which is the same ending by a different road.

  3. ONLY UNREACHABLE FAILURES QUEUE. A payload Telegram has already refused
     would be retried forever; an HTTP response, even a rejection, proves the
     network works.
"""
from __future__ import annotations

import time

import pytest
import requests

from integrations.notifications.telegram_bot import TelegramBotUplink

ALARM = "⚠️ *HOKAGE IS BLIND — MARKET DATA UNREACHABLE* ⚠️"


class _Response:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


@pytest.fixture
def bot(monkeypatch, tmp_path) -> TelegramBotUplink:
    """A bot that believes it is configured but can never reach the network.

    HOKAGE_DISABLE_TELEGRAM is set for the whole suite, so `enabled` is forced
    off and nothing here can post for real; it is re-enabled on this instance
    only, with requests.post replaced in every test.

    PER-TEST BRAIN ROOT. The durable queue is persisted now, and the suite's
    sandbox root is one directory for the whole session - so without this, an
    alarm deferred by one test is restored by the next test's constructor and
    every "assert not bot._deferred" becomes a coin toss.
    """
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path))
    b = TelegramBotUplink(bot_token="111:fake-not-a-real-token", chat_id="999")
    b.enabled = True
    monkeypatch.setattr(
        requests, "post",
        lambda *a, **k: pytest.fail("a test reached requests.post unstubbed"),
    )
    return b


def _sends(monkeypatch, outcomes):
    """Replace requests.post with a scripted sequence; records payloads."""
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


DNS = requests.exceptions.ConnectionError(
    "HTTPSConnectionPool(host='api.telegram.org', port=443): "
    "Failed to resolve 'api.telegram.org' ([Errno 11001] getaddrinfo failed)"
)


# ------------------------------------------- an unreachable alert is held
def test_an_unreachable_alert_is_queued_not_dropped(bot, monkeypatch):
    _sends(monkeypatch, [DNS])
    assert bot.send_message(ALARM) is False
    assert ALARM in bot._deferred


def test_it_is_delivered_when_the_link_returns(bot, monkeypatch):
    _sends(monkeypatch, [DNS])
    bot.send_message(ALARM)

    sent = _sends(monkeypatch, [_Response(200)])
    bot.send_message("next unrelated alert")

    assert any("BLIND" in s for s in sent), "the held alarm was never delivered"
    assert not bot._deferred, "it stayed queued after a successful send"


def test_the_queue_drains_before_the_message_that_triggered_it(bot, monkeypatch):
    """Order matters: the outage alert describes an earlier world and must not
    arrive after the recovery notice that supersedes it."""
    _sends(monkeypatch, [DNS])
    bot.send_message(ALARM)

    sent = _sends(monkeypatch, [_Response(200), _Response(200)])
    bot.send_message("✅ HOKAGE CAN SEE AGAIN")

    assert "BLIND" in sent[0]
    assert "CAN SEE AGAIN" in sent[1]


# ----------------------------------- a replay never reads as happening now
def test_a_flushed_alert_says_it_is_delayed(bot, monkeypatch):
    """THE RAIL. Without this he reads "HOKAGE IS BLIND" while the feed is
    live and acts on a condition that already cleared."""
    _sends(monkeypatch, [DNS])
    bot.send_message(ALARM)

    sent = _sends(monkeypatch, [_Response(200), _Response(200)])
    bot.send_message("anything")

    replay = next(s for s in sent if "BLIND" in s)
    assert "DELAYED ALERT" in replay
    assert "undeliverable until now" in replay
    assert "IST" in replay


def test_the_delay_preamble_states_the_real_age(bot):
    now = time.time()
    entry = {"first": now - 27 * 60, "last": now - 60, "count": 1}
    head = bot._deferred_preamble(entry, now)
    assert "27 min ago" in head


def test_the_original_text_survives_intact(bot, monkeypatch):
    """A stamp must not mangle the alert it is stamping."""
    _sends(monkeypatch, [DNS])
    bot.send_message(ALARM)
    sent = _sends(monkeypatch, [_Response(200), _Response(200)])
    bot.send_message("x")
    replay = next(s for s in sent if "BLIND" in s)
    assert ALARM in replay


# ------------------------------------------------ identical alarms collapse
def test_twenty_six_identical_alarms_become_one(bot, monkeypatch):
    """The measured case. 26 deliveries of the same alarm is alarm fatigue
    manufactured by the fix for alarm loss."""
    _sends(monkeypatch, [DNS])
    for _ in range(26):
        bot.send_message(ALARM)

    assert len(bot._deferred) == 1
    assert bot._deferred[ALARM]["count"] == 26

    sent = _sends(monkeypatch, [_Response(200), _Response(200)])
    bot.send_message("x")
    assert sum("BLIND" in s for s in sent) == 1


def test_the_collapsed_alert_reports_how_many_and_over_what_span(bot):
    now = time.time()
    entry = {"first": now - 26 * 60, "last": now - 60, "count": 26}
    head = bot._deferred_preamble(entry, now)
    assert "26 times" in head


def test_different_alarms_do_not_collapse_into_each_other(bot, monkeypatch):
    _sends(monkeypatch, [DNS])
    bot.send_message(ALARM)
    bot.send_message("🚨 something else entirely")
    assert len(bot._deferred) == 2


# ------------------------------- only unreachable failures are worth holding
def test_a_payload_telegram_refused_is_not_queued(bot, monkeypatch):
    """An HTTP response proves the network works. Queueing a rejection would
    retry it forever and block the alerts behind it."""
    _sends(monkeypatch, [_Response(400, "Bad Request: chat not found")])
    assert bot.send_message(ALARM) is False
    assert not bot._deferred


def test_a_bad_token_is_not_queued(bot, monkeypatch):
    _sends(monkeypatch, [_Response(401, "Unauthorized")])
    bot.send_message(ALARM)
    assert not bot._deferred


def test_a_markdown_rejection_still_falls_back_to_plain_text(bot, monkeypatch):
    """The existing rail must survive this change: ugly beats unsent."""
    sent = _sends(monkeypatch, [
        _Response(400, "Bad Request: can't parse entities"),
        _Response(200),
    ])
    assert bot.send_message("CRUDE_OIL exit at `price`") is True
    assert len(sent) == 2
    assert not bot._deferred


def test_a_successful_send_queues_nothing(bot, monkeypatch):
    _sends(monkeypatch, [_Response(200)])
    assert bot.send_message(ALARM) is True
    assert not bot._deferred


# ------------------------------------------------------- bounded and sane
def test_the_queue_is_bounded(bot, monkeypatch):
    """An outage lasting hours must not grow memory without limit."""
    _sends(monkeypatch, [DNS])
    for i in range(bot._DEFERRED_MAX_ENTRIES + 15):
        bot.send_message(f"distinct alert {i}")
    assert len(bot._deferred) <= bot._DEFERRED_MAX_ENTRIES


def test_a_perishable_alert_too_old_to_matter_is_dropped_loudly(
        bot, monkeypatch, caplog):
    """A report of a day that has ended really is worthless late. Dropping it
    is right; dropping it silently is how the original defect happened."""
    stale = "📊 Hokage — how today went (MCX Arena — Wednesday, 04 Nov 2026)"
    _sends(monkeypatch, [DNS])
    bot.send_message(stale)
    bot._deferred[stale]["first"] = time.time() - bot._DEFERRED_MAX_AGE_SECONDS - 60

    _sends(monkeypatch, [_Response(200)])
    with caplog.at_level("WARNING", logger="Hokage.TelegramBot"):
        bot.send_message("x")

    assert stale not in bot._deferred
    assert "too old" in caplog.text


def test_a_flush_that_fails_leaves_the_queue_intact(bot, monkeypatch):
    """Still down. Nothing may be lost by trying."""
    _sends(monkeypatch, [DNS])
    bot.send_message(ALARM)
    _sends(monkeypatch, [DNS])
    bot.send_message("another")
    assert ALARM in bot._deferred


def test_a_flush_stops_at_the_first_failure(bot, monkeypatch):
    """Spending a trading loop's time on messages that will fail identically
    is how a 10s timeout becomes a minute of stall."""
    _sends(monkeypatch, [DNS])
    for i in range(5):
        bot.send_message(f"alert {i}")

    sent = _sends(monkeypatch, [DNS])
    bot._flush_deferred()
    assert len(sent) == 1, "it kept trying after the link was proven still down"


def test_the_flush_is_batched(bot, monkeypatch):
    """A drain of twenty at a 10s timeout each would stall the caller."""
    _sends(monkeypatch, [DNS])
    for i in range(20):
        bot.send_message(f"alert {i}")

    sent = _sends(monkeypatch, [_Response(200)] * 30)
    bot._flush_deferred()
    assert len(sent) == bot._DEFERRED_FLUSH_BATCH


def test_mock_mode_never_queues(bot, monkeypatch):
    """The suite forces HOKAGE_DISABLE_TELEGRAM; a disabled uplink must not
    accumulate a queue nobody will ever drain."""
    bot.enabled = False
    bot.send_message(ALARM)
    assert not bot._deferred


def test_flushing_an_empty_queue_costs_nothing(bot, monkeypatch):
    sent = _sends(monkeypatch, [_Response(200)])
    assert bot._flush_deferred() == 0
    assert sent == []
