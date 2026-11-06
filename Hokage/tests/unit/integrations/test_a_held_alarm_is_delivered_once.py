"""The alarm survived the restart and then arrived twice.

2026-11-06 12:45 the liveness probe tried to tell the commander HOKAGE IS NOT
TRADING and DNS was down, so it went into the durable queue and onto disk. At
14:28:51 Hokage was restarted onto that day's fix, and four seconds later:

    14:28:55,508 Telegram sent: DELAYED ALERT - raised 12:45 IST, 103 min ago
    14:28:55,574 Delivered 1 deferred Telegram alert(s).
    14:28:55,674 Telegram sent: DELAYED ALERT - raised 12:45 IST, 103 min ago
    14:28:55,727 Delivered 1 deferred Telegram alert(s).

Two deliveries, 166 ms apart, one "Restored 1 undelivered alert(s)" above
them. One load, two sends.

THE QUEUE WAS SNAPSHOTTED, NOT CLAIMED. `_flush_deferred` selected its batch
under the lock and then released the lock to do the network calls, deleting
each entry only once its send had returned. The flush runs at the top of EVERY
send_message, from every thread Hokage has - two leagues, a watchdog, an
orchestrator - so two threads flushing at the same moment both saw the same
batch and both delivered all of it. Nothing about restored alerts was special;
any deferred alert could double, and the measured one did.

The fix claims the batch out of the queue while still holding the lock, so a
second flush finds nothing to send, and puts back whatever the network then
refused. Two further things have to hold for that to be safe rather than
merely quiet, and both are pinned here:

  1. A CLAIM MUST NOT BE A WAY TO LOSE THE ALARM. An alert out of the queue
     and not yet acknowledged by Telegram is still undelivered, so it stays in
     the file - a kill during a 10s send timeout is exactly when a restart
     lands. The file loses it only after Telegram has taken it.

  2. ONE QUEUE PER FILE, NOT PER UPLINK. Hokage builds one uplink per league
     and both read the same file, so two private queues would each deliver
     what disk was carrying. They share the dict, the in-flight set and the
     lock, keyed by the file itself.
"""
from __future__ import annotations

import json
import threading
import time

import pytest
import requests

from integrations.notifications.telegram_bot import TelegramBotUplink

TOKEN = "111:fake-not-a-real-token"

#: The alarm that doubled, as the probe wrote it.
NOT_TRADING = (
    "HOKAGE IS NOT TRADING.\n\nthe broker session check could not run "
    "(UNREACHABLE).\n\nChecked 3 times running from 12:45 back."
)
#: Measured: raised 12:45, delivered 14:28. Relative, so the fixture does not
#: age past _DEFERRED_RESTART_MAX_AGE_SECONDS the day after it was written.
HELD_FOR_SECONDS = 103 * 60

BLIND = "⚠️ *HOKAGE IS BLIND — MARKET DATA UNREACHABLE* ⚠️"


class _Response:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


DNS = requests.exceptions.ConnectionError(
    "HTTPSConnectionPool(host='api.telegram.org', port=443): "
    "Failed to resolve 'api.telegram.org' ([Errno 11001] getaddrinfo failed)"
)


@pytest.fixture
def brain(monkeypatch, tmp_path):
    """A per-test brain root. The queue registry is keyed by the queue FILE,
    so a fresh root is also what keeps one test's queue out of the next."""
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path))
    monkeypatch.setattr(
        requests, "post",
        lambda *a, **k: pytest.fail("a test reached requests.post unstubbed"),
    )
    return tmp_path


def _uplink() -> TelegramBotUplink:
    b = TelegramBotUplink(bot_token=TOKEN, chat_id="999")
    b.enabled = True
    return b


def _queued_on_disk(brain, text=NOT_TRADING, age=HELD_FOR_SECONDS) -> None:
    """What the probe left behind before the restart."""
    state = brain / "state"
    state.mkdir(parents=True, exist_ok=True)
    first = time.time() - age
    (state / "telegram_deferred.json").write_text(
        json.dumps({text: {"first": first, "last": first, "count": 1}}),
        encoding="utf-8")


def _sends(monkeypatch, outcomes, hook=None):
    """Scripted requests.post. `hook(text)` runs while the send is in flight."""
    sent: list[str] = []
    seq = list(outcomes)
    guard = threading.Lock()

    def post(url, json=None, timeout=None, **kw):
        text = (json or {}).get("text", "")
        with guard:
            sent.append(text)
            outcome = seq.pop(0) if seq else outcomes[-1]
        if hook is not None:
            hook(text)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(requests, "post", post)
    return sent


# ================================================== the incident, replayed
def test_a_held_alarm_is_delivered_exactly_once(brain, monkeypatch):
    """THE RAIL. Two uplinks, one league each, booting on the same queue file.
    Before the fix this is the 166 ms pair in the log."""
    _queued_on_disk(brain)
    mcx, index = _uplink(), _uplink()

    sent = _sends(monkeypatch, [_Response(200)] * 10)
    mcx.send_message("MCX league is up")
    index.send_message("Index league is up")

    assert sum("NOT TRADING" in s for s in sent) == 1
    assert sum("DELAYED ALERT" in s for s in sent) == 1


def test_it_is_still_delivered_with_its_real_age(brain, monkeypatch):
    """The fix must not buy uniqueness by dropping it. 103 minutes, as
    measured, and the note that it outlived the process that raised it."""
    _queued_on_disk(brain)
    sent = _sends(monkeypatch, [_Response(200)] * 4)
    _uplink().send_message("x")

    replay = next(s for s in sent if "NOT TRADING" in s)
    assert "103 min ago" in replay
    assert "Held across a restart" in replay


def test_two_uplinks_work_on_one_queue(brain):
    """Per-uplink queues are what made disk a second source of deliveries."""
    a, b = _uplink(), _uplink()
    assert a._deferred is b._deferred
    assert a._inflight is b._inflight
    assert a._deferred_lock is b._deferred_lock


def test_an_alarm_deferred_by_one_uplink_is_seen_by_the_other(brain, monkeypatch):
    a, b = _uplink(), _uplink()
    _sends(monkeypatch, [DNS])
    a.send_message(BLIND)
    assert BLIND in b._deferred


def test_a_delivery_by_one_uplink_empties_the_other(brain, monkeypatch):
    a, b = _uplink(), _uplink()
    _sends(monkeypatch, [DNS])
    a.send_message(BLIND)

    _sends(monkeypatch, [_Response(200)] * 4)
    a.send_message("x")
    assert not b._deferred, "the sibling would have sent it again"


def test_a_second_uplink_does_not_restamp_a_live_alert_as_restored(
        brain, monkeypatch):
    """A reload must not claim an alert outlived a restart it never saw. The
    file is a carrier between processes, not a second source of truth."""
    a = _uplink()
    _sends(monkeypatch, [DNS])
    a.send_message(BLIND)

    _uplink()                                    # loads the file a + wrote
    assert not a._deferred[BLIND].get("restored")

    sent = _sends(monkeypatch, [_Response(200)] * 4)
    a.send_message("x")
    replay = next(s for s in sent if "BLIND" in s)
    assert "Held across a restart" not in replay


def test_separate_brain_roots_do_not_share(brain, monkeypatch, tmp_path):
    """The isolation rail: the registry is keyed by the queue file, so a test
    (or a second brain) gets its own queue. A class-level dict would leak."""
    a = _uplink()
    monkeypatch.setenv("HOKAGE_BRAIN_ROOT", str(tmp_path / "other"))
    b = _uplink()
    assert a._deferred is not b._deferred


# ============================================ the batch is claimed, not copied
def test_a_flush_during_a_flush_sends_nothing(brain, monkeypatch):
    """The race, deterministically. The flush runs at the top of every send,
    so a send that happens while a flush is in flight re-enters it. Before the
    fix the second pass saw the same un-deleted batch and sent it again."""
    _queued_on_disk(brain)
    bot = _uplink()
    nested: list[int] = []

    sent = _sends(monkeypatch, [_Response(200)] * 10,
                  hook=lambda t: nested.append(bot._flush_deferred())
                  if "NOT TRADING" in t else None)
    bot.send_message("x")

    assert nested == [0], "the nested flush found the batch still queued"
    assert sum("NOT TRADING" in s for s in sent) == 1


def test_two_threads_flushing_at_once_deliver_it_once(brain, monkeypatch):
    """Hokage has a thread per league plus a watchdog and an orchestrator, all
    calling send_message."""
    _queued_on_disk(brain)
    bot = _uplink()
    sent = _sends(monkeypatch, [_Response(200)] * 10,
                  hook=lambda t: time.sleep(0.05))

    threads = [threading.Thread(target=bot._flush_deferred) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
        assert not t.is_alive(), "a flush deadlocked"

    assert sum("NOT TRADING" in s for s in sent) == 1


def test_a_refused_send_puts_the_claim_back(brain, monkeypatch):
    """Claiming must not be a way to lose it. Still down, so it waits."""
    _queued_on_disk(brain)
    bot = _uplink()
    _sends(monkeypatch, [DNS])
    assert bot._flush_deferred() == 0

    assert NOT_TRADING in bot._deferred
    assert not bot._inflight
    assert bot._deferred_path().exists()


def test_a_re_raise_during_the_send_bumps_the_same_entry(brain, monkeypatch):
    """Identical alarms collapse - including against the copy mid-flight, or
    the collapse just moves the duplicate one message later."""
    _queued_on_disk(brain)
    bot = _uplink()

    def raise_it_again(text):
        if "NOT TRADING" in text:
            bot._defer(NOT_TRADING)

    _sends(monkeypatch, [DNS], hook=raise_it_again)
    bot._flush_deferred()

    assert list(bot._deferred) == [NOT_TRADING]
    assert bot._deferred[NOT_TRADING]["count"] == 2


# ===================================== a claim is not a delivery, on disk
def test_an_in_flight_alarm_is_still_in_the_file(brain, monkeypatch):
    """A send sits on a 10s timeout, which is exactly when a restart lands.
    Out of the queue is not delivered, so the file must still hold it."""
    _queued_on_disk(brain)
    bot = _uplink()
    seen: list[bool] = []

    def inspect(text):
        if "NOT TRADING" in text:
            on_disk = json.loads(
                bot._deferred_path().read_text(encoding="utf-8-sig"))
            seen.append(NOT_TRADING in on_disk)

    _sends(monkeypatch, [_Response(200)] * 4, hook=inspect)
    bot.send_message("x")

    assert seen == [True], "a kill mid-send would have lost the alarm"


def test_the_file_loses_it_only_after_telegram_took_it(brain, monkeypatch):
    _queued_on_disk(brain)
    bot = _uplink()
    _sends(monkeypatch, [_Response(200)] * 4)
    bot.send_message("x")
    assert not bot._deferred_path().exists()


def test_a_save_while_in_flight_keeps_the_in_flight_alert(brain):
    """The unit behind the rail above: anything undelivered is persisted,
    whichever half of the queue is holding it."""
    bot = _uplink()
    now = time.time()
    bot._inflight[NOT_TRADING] = {"first": now, "last": now, "count": 1}
    bot._deferred[BLIND] = {"first": now, "last": now, "count": 1}
    bot._save_deferred()

    on_disk = json.loads(bot._deferred_path().read_text(encoding="utf-8-sig"))
    assert set(on_disk) == {NOT_TRADING, BLIND}
