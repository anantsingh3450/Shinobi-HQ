from __future__ import annotations
import os
import time
import logging
import re
import threading
from datetime import datetime, timezone
from typing import Any
import requests
from urllib.parse import urlparse, parse_qs
import pyotp
from integrations.brokers.secrets import SecretManager
from kiteconnect import KiteConnect
from integrations.brokers.session_manager import KolkataTime
from integrations.llm.processor import LLMProcessor

logger = logging.getLogger("Hokage.TelegramBot")

#: Matches a Telegram bot token wherever it appears in a URL: the numeric bot
#: id, a colon, then the secret.
_TOKEN_IN_URL = re.compile(r"/bot\d+:[A-Za-z0-9_\-]+")


def _scrub(text: object) -> str:
    """Remove the bot token from anything about to be logged.

    `requests` puts the FULL URL in its exception text, and the Telegram API
    carries the bot token in the path. So a network failure logged the live
    credential in plaintext:

        Failed to send Telegram message: HTTPSConnectionPool(
        host='api.telegram.org', ...) Max retries exceeded with url:
        /bot<ID>:<SECRET>/sendMessage ...

    Counted on 2026-10-12 after a brief DNS outage: 45 occurrences in the
    current log, 485 across rotated logs, 527 more under logs/. Anyone with
    read access to a log file had the token, and with it the ability to read
    and send every message on the commander's Telegram channel.

    `_audit` was already written never to log the token. This path bypassed
    that care entirely, because nobody writes the credential here -- requests
    does, inside an exception nobody reads until something breaks.
    """
    return _TOKEN_IN_URL.sub("/bot<REDACTED>", str(text))


#: One deferred queue per queue FILE, shared by every uplink in this process.
#:
#: Keyed by the file and not by the class, because the test suite points
#: HOKAGE_BRAIN_ROOT at a fresh tmp_path per test: a class-level dict would
#: leak one test's deferred alarm into the next test's "assert not _deferred".
#: The file is also exactly the thing being shared, so it is the honest key.
_QUEUE_REGISTRY: dict[str, tuple[dict, dict, threading.RLock]] = {}
_QUEUE_REGISTRY_GUARD = threading.Lock()


class TelegramBotUplink:
    """Manages Telegram bot communications, TOTP token requests, fills/exits and EOD updates."""

    def __init__(self, bot_token: str | None = None, chat_id: str | None = None) -> None:
        self.bot_token = bot_token or os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = chat_id or os.getenv("TELEGRAM_CHAT_ID")
        self.enabled = bool(self.bot_token and self.chat_id)
        # Offline config seam: HOKAGE_DISABLE_TELEGRAM=true forces the uplink
        # into mock-outbox mode regardless of configured credentials. The test
        # suite sets it so tests can NEVER send real Telegram messages;
        # production leaves it unset.
        if os.environ.get("HOKAGE_DISABLE_TELEGRAM") == "true":
            self.enabled = False
        self._thread = None
        self._stop_event = threading.Event()
        # Loaded from disk so a mid-morning restart doesn't re-send the same
        # day's login prompt a second time (in-memory only meant every
        # restart between 06:30-09:00 IST fired a fresh duplicate prompt).
        self._last_totp_request_date = self._load_prompt_state()
        self._last_confirmation_date = None
        # Retry throttle for the two daily alerts (login prompt / 09:00
        # confirmation). Negative seed so the first attempt is never delayed.
        self._last_daily_alert_attempt = -1e9
        self._last_update_id = 0
        self.latest_totp = None
        self.llm_processor = LLMProcessor()
        # Control-command handler (set by AutonomousTradingBot). Must expose
        # handle_remote_command(command: str) -> str.
        self.command_handler = None
        # Alerts the network swallowed, keyed by text so identical alarms
        # collapse. See _defer: on 2026-10-13 a 27-minute DNS outage dropped 26
        # of them and the commander was never told.
        #
        # SHARED WITH EVERY UPLINK IN THIS PROCESS that persists to the same
        # file, and the lock with it. Hokage builds one uplink per league, and
        # two private queues loading the same file both deliver what it holds.
        self._deferred, self._inflight, self._deferred_lock = self._shared_queue()
        # A queue that only lives in memory still loses the alarm if the
        # process restarts during the outage, which is exactly when someone
        # tends to restart it.
        self._load_deferred()

    def _prompt_state_path(self):
        from pathlib import Path
        from hokage.memory.resolver import PathResolver
        state_dir = PathResolver().resolve_brain_root() / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir / "telegram_login_prompt.json"

    def _load_prompt_state(self) -> str | None:
        import json
        try:
            path = self._prompt_state_path()
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8")).get("last_totp_request_date")
        except Exception as e:
            logger.warning(f"Failed to load Telegram login-prompt state: {_scrub(e)}")
        return None

    def _save_prompt_state(self, date_str: str) -> None:
        import json
        try:
            self._prompt_state_path().write_text(
                json.dumps({"last_totp_request_date": date_str}), encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"Failed to save Telegram login-prompt state: {_scrub(e)}")

    def _mark_prompted(self, date_str: str) -> None:
        """Record that the day's login prompt is genuinely settled — either it
        was delivered, or the session was already live so no prompt was owed."""
        self._last_totp_request_date = date_str
        self._save_prompt_state(date_str)

    def _may_retry_send(self) -> bool:
        """Throttle daily-alert retries to one attempt a minute.

        The uplink loop ticks every 5s. Without this, an unreachable network
        would retry the login prompt twelve times a minute and bury the log in
        identical send failures.
        """
        now = time.monotonic()
        if now - self._last_daily_alert_attempt < 60.0:
            return False
        self._last_daily_alert_attempt = now
        return True
    def start(self) -> None:
        """Start the background polling thread."""
        if not self.enabled:
            logger.info("Telegram uplink disabled; polling thread not started.")
            return
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="HokageTelegramBotLoop", daemon=True)
        self._thread.start()
        logger.info("Telegram background thread started.")

    def stop(self) -> None:
        """Stop the background polling thread gracefully."""
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=5.0)
        self._thread = None
        logger.info("Telegram background thread stopped.")

    @staticmethod
    def escape_markdown(value: Any) -> str:
        """Neutralise legacy-Markdown control characters in interpolated text.

        Messages are sent with parse_mode "Markdown", so any of _ * ` [ inside a
        VALUE — not the template — opens a formatting entity. Symbol and reason
        strings routinely carry them: "CRUDE_OIL moved 40.00 against position"
        left an unclosed italic run, and Telegram answered 400 "can't parse
        entities". The exit alert was dropped in full, so on 2026-07-15 every
        CRUDE_OIL thesis-stop exit went unannounced while the commander was
        told nothing at all.

        Apply to interpolated values only; the surrounding template keeps its
        intentional markup.
        """
        text = str(value)
        for ch in ("_", "*", "`", "["):
            text = text.replace(ch, "\\" + ch)
        return text

    #: Characters of the outgoing message kept in the audit line.
    _AUDIT_PREVIEW_CHARS = 90

    def _audit(self, outcome: str, text: str, extra: str = "") -> None:
        """Record that a message was sent, not merely that one failed.

        2026-08-27: two round trips opened and closed, and the log carried NO
        evidence either was announced. `send_message` returned True silently and
        logged only on failure, so the single Telegram line in the whole day was
        a DNS error at 16:11:58 — meaning the commander could not audit what
        Hokage had told him, or whether it had told him anything at all.

        One line per send, first %d characters only: enough to know which alert
        this was, never the whole payload, and never the token (which lives in
        the URL and is not touched here).
        """ % 90,
        preview = " ".join(str(text).split())[:self._AUDIT_PREVIEW_CHARS]
        logger.info("Telegram %s: %s%s%s", outcome, preview,
                    "..." if len(str(text)) > self._AUDIT_PREVIEW_CHARS else "",
                    f" [{extra}]" if extra else "")

    #: Distinct alerts held while the network is unreachable. Bounded, because
    #: an outage lasting hours must not grow without limit; identical texts
    #: collapse into one entry, so the real bound is on DISTINCT alerts.
    _DEFERRED_MAX_ENTRIES = 40

    #: An alert older than this describes a world that no longer exists -- for
    #: the alerts that genuinely expire. It does NOT apply to durable ones.
    #:
    #: THIS CONSTANT USED TO DELETE THE ONLY ALARM THAT MATTERED. From 22:38 on
    #: 2026-11-04 the host stopped resolving DNS for eleven hours. "HOKAGE IS
    #: BLIND -- MARKET DATA UNREACHABLE" was raised 104 times into a dead pipe,
    #: held here, and then dropped at 01:46 for being 183 minutes old. The
    #: commander woke to a system that had been blind all night and a queue
    #: that had thrown the evidence away. The old comment said two hours after
    #: the fact "HOKAGE IS BLIND" is archaeology -- which is true of the
    #: SENTENCE and false of the FACT: the blindness was still going on, and
    #: outlived the alert telling him about it by nine hours.
    _DEFERRED_MAX_AGE_SECONDS = 7200

    #: Alerts that really do expire, matched case-insensitively against the
    #: message text. Everything NOT on this list is DURABLE and is never
    #: dropped for age.
    #:
    #: THE DEFAULT IS DELIBERATELY "DURABLE". Listing what to keep would mean a
    #: future alarm nobody remembered to list gets silently deleted during the
    #: exact outage it was written for -- the shape of
    #: absent-is-not-false. A report of a day that has ended is genuinely
    #: worthless late; an alarm about the system's ability to trade is not.
    _PERISHABLE_MARKERS = (
        "how today went",        # the end-of-day report, per league
        "morning system",        # the pre-open system check
        "daily briefing",
        "delayed alert",         # a preamble must never be re-queued
    )

    def _is_perishable(self, text: str) -> bool:
        """True only for alerts whose value really does decay to nothing.

        Durability is decided by the TEXT because that is all the queue has:
        _defer is handed a finished string by send_message, with no severity
        and no caller identity. Matching the text is crude, and it is honest
        about being crude -- the default protects anything it does not
        recognise.
        """
        low = " ".join(str(text).split()).lower()
        return any(marker in low for marker in self._PERISHABLE_MARKERS)

    #: Sent per flush. A drain of twenty messages at a 10s timeout each would
    #: stall whichever loop happened to trigger it.
    _DEFERRED_FLUSH_BATCH = 5

    def _defer(self, text: str) -> None:
        """Hold an alert the network swallowed, to send when it comes back.

        THE ALARM ABOUT THE NETWORK CANNOT TRAVEL OVER THE NETWORK.

        2026-10-13 14:51:58 the host stopped resolving DNS - api.kite.trade and
        api.telegram.org alike. Hokage went blind for 27 minutes, said
        "Market data feed is DOWN (network)" 26 times, and tried to tell the
        commander 26 times. Every one failed with getaddrinfo and was audited
        "NOT SENT" and dropped. He was never going to learn about those 27
        minutes; the only record was a log file.

        IDENTICAL TEXTS COLLAPSE. Flushing 26 copies of the same alarm would
        be its own failure - an alarm that arrives 26 times teaches him to mute
        the channel, which is the same ending by a different road. One entry
        per distinct text, carrying how many times it was raised and over what
        span.
        """
        now = time.time()
        with self._deferred_lock:
            # An in-flight copy counts as queued. Raising the same alarm again
            # while its first copy is mid-send must bump that one, not start a
            # second entry that arrives moments after it.
            entry = self._deferred.get(text) or self._inflight.get(text)
            if entry is None:
                if len(self._deferred) >= self._DEFERRED_MAX_ENTRIES:
                    # SPEND A PERISHABLE ALERT FIRST. Evicting purely by age
                    # would let forty routine messages push the blind alarm
                    # out of a full queue, which is the same loss by a
                    # different door.
                    spendable = [t for t in self._deferred if self._is_perishable(t)]
                    pool = spendable or list(self._deferred)
                    oldest = min(pool, key=lambda k: self._deferred[k]["first"])
                    if spendable:
                        logger.warning(
                            "Deferred Telegram queue is full (%d distinct "
                            "alerts); dropping the oldest expendable one.",
                            self._DEFERRED_MAX_ENTRIES,
                        )
                    else:
                        # Every single one is load-bearing. Say so at the level
                        # that matches: something is being lost.
                        logger.critical(
                            "Deferred Telegram queue is full of %d DURABLE "
                            "alerts; dropping the oldest: %s",
                            self._DEFERRED_MAX_ENTRIES,
                            " ".join(oldest.split())[:self._AUDIT_PREVIEW_CHARS],
                        )
                    self._deferred.pop(oldest, None)
                self._deferred[text] = {"first": now, "last": now, "count": 1}
            else:
                entry["last"] = now
                entry["count"] += 1
        self._save_deferred()

    #: On restart, a durable alert older than this is let go. A day-old
    #: "HOKAGE IS BLIND" tells him nothing he cannot read in the log, and
    #: replaying it would compete with whatever is true now.
    _DEFERRED_RESTART_MAX_AGE_SECONDS = 86400

    def _deferred_path(self):
        from pathlib import Path
        from hokage.memory.resolver import PathResolver
        state_dir = PathResolver().resolve_brain_root() / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir / "telegram_deferred.json"

    def _shared_queue(self) -> tuple[dict, dict, threading.RLock]:
        """The queue this uplink works on, the in-flight set, and their lock.

        2026-11-06 14:28:55, four seconds after a restart: the 12:45 "HOKAGE IS
        NOT TRADING" alarm, correctly held across the restart, was delivered
        TWICE, 166 ms apart. Two uplinks (one per league) each hold a private
        dict and each load the same file, so whatever disk is carrying goes out
        once per uplink. Sharing the dict makes a claim by one a claim for all.

        Reentrant lock because _save_deferred is called from inside the
        critical sections that mutate the queue; a plain Lock deadlocks there.

        Falls back to a private queue if the path cannot be resolved -- an
        uplink that cannot find its brain is still worth having in memory, and
        a constructor that raises here takes the whole bot down with it.
        """
        try:
            key = str(self._deferred_path())
        except Exception as e:
            logger.warning(
                "Deferred queue is private to this uplink; its path could not "
                "be resolved: %s", _scrub(e))
            return {}, {}, threading.RLock()
        with _QUEUE_REGISTRY_GUARD:
            if key not in _QUEUE_REGISTRY:
                _QUEUE_REGISTRY[key] = ({}, {}, threading.RLock())
            return _QUEUE_REGISTRY[key]

    def _save_deferred(self) -> None:
        """Persist the durable queue. NEVER raises.

        Written temp-then-rename for the reason active_positions.json was: on
        2026-10-28 a json.dump straight into an open "w" handle truncated that
        file 168 times while positions were open, because the truncate happens
        before the first value is serialised. A failure here must cost the new
        copy, never the queue already on disk.

        Only durable alerts are stored. A perishable one has no business
        surviving the process that raised it.

        IN-FLIGHT ALERTS ARE STORED TOO. An alert claimed by a flush is out of
        the queue but not yet delivered, and a send that is still waiting on a
        10s timeout is exactly when a restart tends to land. Leaving it out of
        the file would make the claim itself a way to lose the alarm.
        """
        try:
            import json
            with self._deferred_lock:
                keep = {t: e for t, e in {**self._inflight, **self._deferred}.items()
                        if not self._is_perishable(t)}
            path = self._deferred_path()
            if not keep:
                path.unlink(missing_ok=True)
                return
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(
                json.dumps(keep, default=str, ensure_ascii=False),
                encoding="utf-8")
            tmp.replace(path)
        except Exception as e:
            logger.warning(f"Could not persist the deferred alert queue: {_scrub(e)}")

    def _load_deferred(self) -> None:
        """Restore durable alerts queued before a restart. NEVER raises."""
        try:
            import json
            path = self._deferred_path()
            if not path.exists():
                return
            # utf-8-sig: a file ever rewritten by PowerShell carries a BOM,
            # and json.loads treats that as a parse error.
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(raw, dict):
                return
            now = time.time()
            restored, expired = 0, 0
            with self._deferred_lock:
                for text, entry in raw.items():
                    try:
                        first = float(entry["first"])
                        last = float(entry.get("last", first))
                        count = int(entry.get("count", 1))
                    except (KeyError, TypeError, ValueError):
                        continue
                    if self._is_perishable(text):
                        continue
                    if text in self._deferred or text in self._inflight:
                        # Already live in this process. The file is a carrier
                        # BETWEEN processes, not a second source of truth: a
                        # reload must not restamp a live alert as "restored"
                        # and claim it outlived a restart it never saw, nor
                        # resurrect one a sibling uplink is mid-delivery on.
                        continue
                    if now - first > self._DEFERRED_RESTART_MAX_AGE_SECONDS:
                        expired += 1
                        continue
                    self._deferred[text] = {
                        "first": first, "last": last,
                        "count": count, "restored": True,
                    }
                    restored += 1
            if restored:
                logger.warning(
                    "Restored %d undelivered Telegram alert(s) queued before "
                    "this restart; they will be sent with their real age.",
                    restored)
            if expired:
                logger.warning(
                    "Let go of %d deferred alert(s) older than %d hours.",
                    expired, self._DEFERRED_RESTART_MAX_AGE_SECONDS // 3600)
        except Exception as e:
            logger.warning(f"Could not restore the deferred alert queue: {_scrub(e)}")

    def _deferred_preamble(self, entry: dict, now: float) -> str:
        """Say that this alert is OLD, and how old, before its own words.

        A replayed alarm presented as current is worse than silence: he would
        read "HOKAGE IS BLIND" while the feed was live and act on a condition
        that had already cleared.
        """
        first = datetime.fromtimestamp(entry["first"], tz=timezone.utc).astimezone(
            KolkataTime()
        )
        age_min = max(0, int((now - entry["first"]) / 60))
        head = (
            f"⏱ *DELAYED ALERT* - raised {first.strftime('%H:%M')} IST, "
            f"{age_min} min ago, undeliverable until now"
        )
        if entry["count"] > 1:
            last = datetime.fromtimestamp(entry["last"], tz=timezone.utc).astimezone(
                KolkataTime()
            )
            head += (
                f"\n_Raised {entry['count']} times, "
                f"{first.strftime('%H:%M')}-{last.strftime('%H:%M')} IST._"
            )
        if entry.get("restored"):
            # He needs to know this one outlived the process that raised it,
            # because the condition it describes may have been fixed by the
            # very restart that queued it here.
            head += "\n_Held across a restart; the condition may have cleared._"
        return head + "\n\n"

    def _flush_deferred(self) -> int:
        """Try to deliver what the network ate. Returns how many went out.

        Called at the top of every send, because a send being attempted at all
        is the cheapest signal available that something might work again.
        Never raises and never recurses into the queue.
        """
        with self._deferred_lock:
            if not self._deferred:
                return 0
            now = time.time()
            # AGE ONLY RETIRES PERISHABLE ALERTS. A durable one waits as long
            # as it has to; it is delivered with its real age on the front, so
            # a long wait costs honesty nothing.
            stale = [
                t for t, e in self._deferred.items()
                if now - e["first"] > self._DEFERRED_MAX_AGE_SECONDS
                and self._is_perishable(t)
            ]
            for t in stale:
                e = self._deferred.pop(t)
                logger.warning(
                    "Dropping a deferred Telegram alert raised %d min ago "
                    "(%dx), too old to be worth sending: %s",
                    int((now - e["first"]) / 60), e["count"],
                    " ".join(t.split())[:self._AUDIT_PREVIEW_CHARS],
                )
            if stale:
                self._save_deferred()
            # Durable first, then oldest first. Only _DEFERRED_FLUSH_BATCH go
            # per flush, so a queue holding ten end-of-day reports and one
            # blind alarm must not spend the whole batch on the reports.
            batch = sorted(
                self._deferred.items(),
                key=lambda kv: (self._is_perishable(kv[0]), kv[1]["first"]),
            )
            batch = batch[: self._DEFERRED_FLUSH_BATCH]
            # CLAIMED HERE, NOT AFTER THE SEND. This used to leave the batch in
            # the queue until each _post returned, so two threads flushing at
            # once took the same snapshot and both delivered all of it -- and
            # the flush runs at the top of EVERY send, from every thread
            # Hokage has. Removing them under the lock means a second thread
            # finds an empty queue and sends nothing; _requeue puts back
            # anything the network then refused.
            for text, entry in batch:
                self._deferred.pop(text, None)
                self._inflight[text] = entry

        sent = 0
        for i, (text, entry) in enumerate(batch):
            body = self._deferred_preamble(entry, time.time()) + text
            if not self._post(body):
                # Still down. Put back what was claimed and not delivered; do
                # not spend the loop's time on messages that will fail the
                # same way.
                self._requeue(batch[i:])
                break
            with self._deferred_lock:
                self._inflight.pop(text, None)
                # Only now is it safe to drop from the file: he has been told.
                self._save_deferred()
            sent += 1
        if sent:
            logger.info("Delivered %d deferred Telegram alert(s).", sent)
        return sent

    def _requeue(self, claimed) -> None:
        """Return claimed-but-undelivered alerts to the queue.

        The claim is what stops a second thread sending the same alarm. Losing
        it when the send fails would trade one duplicate for the exact defect
        this queue exists to prevent, so a failed flush must leave the queue
        as it found it.
        """
        with self._deferred_lock:
            for text, entry in claimed:
                self._inflight.pop(text, None)
                live = self._deferred.get(text)
                if live is None:
                    self._deferred[text] = dict(entry)
                    continue
                # An identical alarm was raised while this copy was in flight.
                # Keep the older start, the newer sighting, and both counts --
                # the preamble reports all of it as one alert.
                live["first"] = min(live["first"], entry["first"])
                live["last"] = max(live["last"], entry["last"])
                live["count"] = live["count"] + entry["count"]
                if entry.get("restored"):
                    live["restored"] = True
            self._save_deferred()

    def send_message(self, text: str) -> bool:
        """Send a message to the configured Telegram chat.

        Anything the network swallows is queued by _defer and delivered when
        the link returns, stamped with its real age.
        """
        if not self.enabled:
            logger.info(f"[MOCK TELEGRAM OUTBOX]: {text}")
            return True

        # Before this message, settle the debt from the last outage.
        self._flush_deferred()

        ok, unreachable = self._post(text, report_reachability=True)
        if not ok and unreachable:
            self._defer(text)
        return ok

    def _post(self, text: str, report_reachability: bool = False):
        """The raw send. No queueing, so _flush_deferred cannot recurse.

        Returns bool, or (bool, unreachable) when report_reachability is set.
        `unreachable` is True ONLY when the request never reached Telegram -
        a DNS failure, a timeout, a dead link. An HTTP response, even a
        rejection, proves the network works, and queueing a message Telegram
        has already refused would retry it forever.
        """
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown"
        }
        try:
            res = requests.post(url, json=payload, timeout=10)
            if res.status_code == 200:
                self._audit("sent", text)
                return (True, False) if report_reachability else True
            # Telegram rejects the WHOLE message when an interpolated value
            # opens a Markdown entity it cannot close — an underscore in
            # CRUDE_OIL, a backtick in Kite's "Incorrect `api_key`" error. The
            # alert is then lost in full, exactly when it matters most: on
            # 2026-07-30 the login reply died on "request_token" (byte offset
            # 23) and on 2026-07-15 every CRUDE_OIL exit went unannounced.
            # Escaping each call site is whack-a-mole, so make the transport
            # itself refuse to lose a message: resend verbatim as plain text.
            # Ugly beats unsent.
            if res.status_code == 400 and "parse" in res.text.lower():
                logger.warning(
                    f"Telegram rejected Markdown ({_scrub(res.text)}); resending as plain text."
                )
                payload.pop("parse_mode", None)
                retry = requests.post(url, json=payload, timeout=10)
                if retry.status_code == 200:
                    self._audit("sent", text, "plain-text fallback")
                    return (True, False) if report_reachability else True
                logger.error(f"Telegram plain-text retry also failed {_scrub(retry.status_code)}: {_scrub(retry.text)}")
                self._audit("NOT SENT", text)
                # Telegram answered. The network is fine and it refused this
                # payload; queueing it would retry a rejection forever.
                return (False, False) if report_reachability else False
            logger.error(f"Telegram API error {_scrub(res.status_code)}: {_scrub(res.text)}")
            self._audit("NOT SENT", text)
            return (False, False) if report_reachability else False
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {_scrub(e)}")
        # Nothing came back at all - DNS, timeout, dead link. Worth holding.
        self._audit("NOT SENT", text, "queued for retry")
        return (False, True) if report_reachability else False

    def notify_fill(self, trade_details: dict) -> None:
        """Push a real-time order fill notification."""
        symbol = trade_details.get("symbol", "N/A")
        side = trade_details.get("side", "N/A")
        qty = trade_details.get("qty", 0.0)
        price = trade_details.get("price", 0.0)
        msg = (
            f"⚡ *TRADE FILL ALERT* ⚡\n"
            f"• *Asset*: {symbol}\n"
            f"• *Side*: {side}\n"
            f"• *Qty*: {qty}\n"
            f"• *Execution Price*: ₹{price:.2f}"
        )
        self.send_message(msg)

    def notify_stop_loss(self, trade_details: dict) -> None:
        """Push a stop-loss execution alert."""
        symbol = trade_details.get("symbol", "N/A")
        side = trade_details.get("side", "N/A")
        price = trade_details.get("price", 0.0)
        pnl = trade_details.get("pnl", 0.0)
        msg = (
            f"🛑 *STOP-LOSS HIT ALERT* 🛑\n"
            f"• *Asset*: {symbol}\n"
            f"• *Position Closed*: {side}\n"
            f"• *Price*: ₹{price:.2f}\n"
            f"• *PnL*: ₹{pnl:+.2f}"
        )
        self.send_message(msg)

    def send_eod_summary(self, pnl_details: dict) -> None:
        """Send End-of-Day P&L summary."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        realized_pnl = pnl_details.get("realized_pnl", 0.0)
        unrealized_pnl = pnl_details.get("unrealized_pnl", 0.0)
        total_equity = pnl_details.get("total_equity", 0.0)
        trades_count = pnl_details.get("trades_count", 0)
        msg = (
            f"📊 *EOD P&L SUMMARY ({date_str})* 📊\n"
            f"• *Realized P&L*: ₹{realized_pnl:+.2f}\n"
            f"• *Unrealized P&L*: ₹{unrealized_pnl:+.2f}\n"
            f"• *Total Portfolio Equity*: ₹{total_equity:.2f}\n"
            f"• *Trades Completed Today*: {trades_count}"
        )
        self.send_message(msg)

    def notify_entry(
        self,
        symbol: str,
        cmp: float,
        target: float,
        edge: float,
        strategy: str | None = None,
        context: Any | None = None,
        target_adaptive: bool | None = None,
    ) -> None:
        """Send a real-time entry notification.

        `target_adaptive` says what KIND of number `target` is, and the alert
        is worded accordingly:

          True  - the adaptive premium target the exit ladder will actually
                  use. It decays through the session as the day runs out of
                  time to deliver the move, so the alert says so rather than
                  printing a figure that looks fixed.
          False - there is NO live target rung for this position. The figure
                  is the percentage take-profit, which the option ladder does
                  not consult; the alert says exits come from the trail or the
                  stop instead of naming a level nothing acts on.
          None  - the caller did not say. Printed bare, as before.

        WHY THIS ARGUMENT EXISTS. Until 2026-11-06 every entry path seeded
        target_price as entry * (1 + tp_percent) and this alert quoted it,
        while the exit ladder overwrote that value with its own adaptive
        target about a minute later and never announced the new one. The gas
        280 CE was bought at 14.55: the alert said ₹16.01, the engine wanted
        ₹16.61. The premium crossed 16.01 at 11:28 and sat above it for nine
        marks, so the commander watched a position pass its stated target and
        not sell, and had to ask whether that was a feature. It was a number
        nothing in the system acted on - the same defect as the `floor` that
        could not stop anything.

        `context` is an optional TradeContext. When supplied, a plain-English
        paragraph is appended explaining the trade to someone who does not
        trade. When absent the alert is still correctly NAMED — the instrument
        header does not depend on it — so every call site benefits without
        having to pass one.

        `strategy` names which arena competitor won this asset. Four strategies
        share one account, so without it an alert says a trade happened but not
        who made it — and the whole point of the tournament is knowing which
        one to promote. Optional so older//manual call sites keep working.
        """
        who = f"• *Strategy*: {self.escape_markdown(strategy)}\n" if strategy else ""
        if target_adaptive is False:
            target_line = "• *Target*: none — exits on the trail or the stop\n"
        elif target_adaptive:
            target_line = (
                f"• *Target*: ₹{target:,.2f} _(adaptive — drifts down as the "
                f"session runs out of time)_\n"
            )
        else:
            target_line = f"• *Target*: ₹{target:,.2f}\n"
        msg = (
            f"🚀 *ENTRY · {self.escape_markdown(self._instrument_line(symbol))}*\n"
            f"{who}"
            f"• *Premium paid*: ₹{cmp:,.2f}\n"
            f"{target_line}"
            f"• *Edge*: {edge:.1f}%\n"
            f"{self._plain_terms(context)}"
            f"\n`{self.escape_markdown(symbol)}`"
        )
        self._remember(context)
        self.send_message(msg)

    def notify_exit(
        self,
        symbol: str,
        price: float,
        reason: str,
        strategy: str | None = None,
        pnl: float | None = None,
        context: Any | None = None,
    ) -> None:
        """Send a real-time exit notification.

        Carries the same strategy attribution as the entry, so a closed trade
        can be read back to its author without opening the dashboard.
        `context` behaves exactly as in notify_entry.
        """
        who = f"• *Strategy*: {self.escape_markdown(strategy)}\n" if strategy else ""
        # Sign OUTSIDE the currency symbol: "+₹2,720.00", never "₹+2,720.00".
        money = ""
        if pnl is not None:
            money = f"• *P&L*: {'+' if pnl >= 0 else '-'}₹{abs(pnl):,.2f}\n"
        mark = "🟢" if (pnl or 0) > 0 else ("🔴" if pnl is not None else "🛑")
        msg = (
            f"{mark} *EXIT · {self.escape_markdown(self._instrument_line(symbol))}*\n"
            f"{who}"
            f"• *Exit price*: ₹{price:,.2f}\n"
            f"{money}"
            f"• *Reason*: {self.escape_markdown(reason)}\n"
            f"{self._plain_terms(context)}"
            f"\n`{self.escape_markdown(symbol)}`"
        )
        self._remember(context)
        self.send_message(msg)

    #: How many recent trades stay answerable by "why". Small on purpose — the
    #: question is almost always about the last one or two.
    _WHY_JOURNAL_SIZE = 20

    @property
    def _journal(self) -> list:
        """Recent TradeContexts, newest last. Created on first use so the
        constructor signature stays untouched."""
        if not hasattr(self, "_trade_journal"):
            self._trade_journal: list = []
        return self._trade_journal

    def _remember(self, context: Any | None) -> None:
        """Keep a trade so `why` can answer about it later. Never raises."""
        if context is None:
            return
        try:
            journal = self._journal
            journal.append(context)
            del journal[: max(0, len(journal) - self._WHY_JOURNAL_SIZE)]
        except Exception:
            pass

    def handle_why(self, text: str) -> str | None:
        """Answer "why" about a recent trade, from RECORDED FACTS only.

        Returns None when the text is not a why-question, so normal routing
        continues.

            why                  the last trade, trader register
            why simple           the last trade, explained to a non-trader
            why silver / gold    the last trade on that underlying

        THE POINT OF DOING THIS BEFORE THE LLM: "why" currently falls through
        to the conversation engine's keyword cascade and then to a bare LLM
        call with no data attached — which is where confidently invented
        numbers come from. This answers from the same TradeContext that
        produced the alert, or admits it does not know. It never guesses.
        """
        low = (text or "").strip().lower().rstrip("?").strip()
        if not low.startswith("why") and low not in ("explain", "explain simply"):
            return None

        from bots.autonomous.trade_explainer import LEARNER, TRADER, explain

        wants_simple = any(w in low for w in ("simple", "simply", "plain", "eli5", "basic"))
        audience = LEARNER if wants_simple else TRADER

        # "Why NO trades?" is a question about the ABSENCE of trades, and it is
        # answerable in detail — every refusal is recorded with its reason.
        # Checked BEFORE the trade journal, because the old code read it as
        # "explain a trade", found none, and replied "I have no trade recorded
        # to explain yet." On 2026-09-02 the commander asked exactly this and
        # got exactly that, while 75 recorded refusals sat in the journal.
        if self._asks_about_absence(low):
            return self._explain_no_trades()

        journal = list(self._journal)
        if not journal:
            return ("I have no trade recorded to explain yet. Ask me again after "
                    "the next entry or exit and I'll walk you through it.")

        # "why silver" / "why goldm" / "why the nifty one"
        remainder = low.replace("why", "", 1)
        for word in ("simple", "simply", "plain", "eli5", "basic", "the", "did", "you",
                     "that", "one", "trade", "about"):
            remainder = remainder.replace(word, " ")
        remainder = remainder.strip()

        chosen = journal[-1]
        if remainder:
            from shared.instrument import parse

            for ctx in reversed(journal):
                inst = parse(getattr(ctx, "tradingsymbol", ""))
                haystack = f"{inst.root} {inst.display_name}".lower()
                if any(tok and tok in haystack for tok in remainder.split()):
                    chosen = ctx
                    break
            else:
                return (f"I have nothing recorded matching '{remainder.strip()}'. "
                        f"The most recent trade I can explain is "
                        f"{self._instrument_line(getattr(chosen, 'tradingsymbol', ''))}.")

        try:
            body = explain(chosen, audience)
        except Exception as exc:
            logger.error(f"Explaining a trade failed: {_scrub(exc)}")
            return "I could not put that trade into words just now."

        head = self._instrument_line(getattr(chosen, "tradingsymbol", ""))
        tail = ("" if wants_simple else
                "\n\n_Reply `why simple` for the same thing without the jargon._")
        return f"*{self.escape_markdown(head)}*\n\n{body}{tail}"

    #: A negation plus a trading noun. Matched as two parts rather than as
    #: whole phrases, because a phrase list is always one wording short: it had
    #: "didn't trade" and missed "didn't YOU trade", which is how a person
    #: actually types it.
    _ABSENCE_NEGATIONS = ("no ", "not ", "n't", "nt ", "never", "zero", "without")
    _ABSENCE_SUBJECTS = ("trade", "trading", "entry", "entries", "position",
                         "signal", "buy", "bought", "bet")
    #: Complete on their own — no trading noun required.
    _ABSENCE_PHRASES = ("nothing", "so quiet", "idle", "sitting out",
                        "stayed out", "doing nothing")

    @classmethod
    def _asks_about_absence(cls, low: str) -> bool:
        if any(p in low for p in cls._ABSENCE_PHRASES):
            return True
        return (any(n in low for n in cls._ABSENCE_NEGATIONS)
                and any(s in low for s in cls._ABSENCE_SUBJECTS))

    #: Gates worth naming individually before the tally is summarised.
    _EXPLAIN_TOP_GATES = 5

    def _explain_no_trades(self) -> str:
        """Why nothing traded, from the recorded refusals. Never the LLM.

        2026-09-02, 12:50. The commander asked "Why no trades so far?" and was
        told "I have no trade recorded to explain yet." Seventy-five refusals
        were on record at that moment, each with its reason, and a gate
        classifier already existed to rank them. The question was answerable in
        detail and the answer was a shrug.

        Same doctrine as handle_why: this reads what was RECORDED. Every number
        below is counted, never estimated, and when there is no record it says
        so instead of inventing a story.
        """
        from datetime import datetime, timedelta, timezone

        try:
            from bots.autonomous.decision_journal import DecisionJournalSystem
            from bots.autonomous.gate_analytics import tally_gate_rejections

            decisions = list(DecisionJournalSystem().load_no_trade_decisions())
        except Exception as exc:
            logger.error(f"Could not read the no-trade journal: {_scrub(exc)}")
            return ("I keep a record of every refusal, but I could not read it "
                    "just now, so I will not guess at the reason.")

        # Journal timestamps are UTC; "today" must be measured in IST or a
        # question asked in the evening reads the wrong day entirely.
        now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        since = (now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
                 - timedelta(hours=5, minutes=30)).replace(tzinfo=timezone.utc)

        tally = tally_gate_rejections(decisions, since=since)
        looked = int(tally.get("decisions_analysed") or 0)
        gates = list(tally.get("gates") or [])

        if not looked:
            return ("I have not refused anything today — which means I have not "
                    "been scanning. That is usually a dead market-data feed or a "
                    "session that never started, not a quiet market. Worth "
                    "checking that I am actually running.")

        total = int(tally.get("total_rejections") or 0)
        lines = [
            f"*No trades today, and here is exactly why.*",
            "",
            f"I looked at *{looked}* opportunities and turned down every one. "
            f"Those refusals carried *{total}* separate reasons, which sort like this:",
            "",
        ]

        for g in gates[: self._EXPLAIN_TOP_GATES]:
            assets = ", ".join(g.get("assets") or []) or "—"
            kind = str(g.get("kind", "")).upper()
            note = " (safety — blocking is its job)" if kind == "SAFETY" else ""
            lines.append(
                f"• *{self.escape_markdown(str(g.get('label') or g.get('gate')))}* "
                f"— {g.get('count')} times, {g.get('share_pct'):.0f}% of all refusals"
                f"{note}\n   on {self.escape_markdown(assets)}"
            )
            sample = (g.get("samples") or [None])[0]
            if sample:
                lines.append(f"   _{self.escape_markdown(str(sample)[:160])}_")

        rest = gates[self._EXPLAIN_TOP_GATES:]
        if rest:
            lines.append(
                f"\n…and {len(rest)} smaller blockers accounting for "
                f"{sum(int(g.get('count') or 0) for g in rest)} more refusals."
            )

        top = tally.get("top_gate")
        if top:
            lines.append(
                f"\n*The bottleneck is {self.escape_markdown(str(top))}.* "
                f"If you want more trades, that is the gate to argue with — but "
                f"only against measurement, never because a day felt quiet."
            )

        unclassified = int(tally.get("unclassified_count") or 0)
        if unclassified:
            lines.append(
                f"\n{unclassified} refusals did not match any gate I know. "
                f"I am reporting that rather than filing them somewhere tidy."
            )
        return "\n".join(lines)

    @staticmethod
    def _instrument_line(symbol: str) -> str:
        """`SILVERM26AUG237000CE` -> `Silver Mini · 2,37,000 CALL · 26 Aug expiry`.

        A live alert once read "SILVERM26AUG237000CE / CMP: 4638.00". SILVERM is
        Silver MINI and nothing said so; the strike and expiry were welded into
        one token; and 4,638 is the PREMIUM while silver itself was near
        2,37,000 — inviting the reader to mistake one for the other. Anything
        that does not parse falls back to the raw symbol.
        """
        try:
            from shared.instrument import parse

            return parse(symbol).headline()
        except Exception:
            return symbol

    @staticmethod
    def _plain_terms(context: Any | None) -> str:
        """The learner-register paragraph, or nothing at all.

        Never allowed to break an alert: any failure here returns empty rather
        than losing the notification that a real trade happened.
        """
        if context is None:
            return ""
        try:
            from bots.autonomous.trade_explainer import LEARNER, explain

            text = explain(context, LEARNER).strip()
            return f"\n📖 *In plain terms*\n{text}\n" if text else ""
        except Exception:
            return ""

    def _validate_broker_session(self) -> bool:
        """Return True only if the stored Zerodha access token passes a REAL
        API round-trip (kite.profile()). A token string merely existing on
        disk proves nothing — Kite expires tokens daily, and a stale token
        must never be announced as a live broker connection."""
        try:
            mgr = SecretManager()
            api_key = mgr.get_secret("api_key", broker="zerodha")
            acc_token = mgr.get_secret("access_token", broker="zerodha")
            if not api_key or not acc_token:
                return False
            kite = KiteConnect(api_key=api_key)
            kite.set_access_token(acc_token)
            kite.profile()
            return True
        except Exception as e:
            logger.warning(f"Broker session validation failed: {_scrub(e)}")
            return False

    def _run_loop(self) -> None:
        tz = KolkataTime()
        while not self._stop_event.is_set():
            try:
                # 1. Handle daily 06:30 AM IST TOTP request
                ist_now = datetime.now(timezone.utc).astimezone(tz)
                current_date_str = ist_now.strftime("%Y-%m-%d")

                # NOTHING TO LOG IN FOR ON A DAY NOTHING TRADES. Both prompts
                # below demand a Zerodha session: the 06:30 login brief and the
                # 09:00 confirmation that answers "Login Missing - Autonomous
                # execution halted". The token expires every single night, so
                # on every weekend and every holiday both fired about a market
                # that was shut - two of the three alerts the commander got on
                # Saturday 2026-11-07.
                #
                # SILENCE NEEDS A POSITIVE CLOSURE. trading_calendar.nothing_
                # trades is False for an unknown date and for an evening-only
                # holiday, so an unmaintained calendar goes back to prompting
                # rather than going quiet. A calendar that cannot be imported
                # changes nothing.
                # Guards the two prompts only. The rest of this loop still runs:
                # his own /commands must keep working on a Saturday, and a
                # `continue` here would have duplicated the loop's sleep.
                shut_today = False
                try:
                    from hokage.memory import trading_calendar
                    shut_today = trading_calendar.nothing_trades(ist_now.date())
                except Exception:
                    shut_today = False

                if not shut_today and (
                        ist_now.hour > 6 or (ist_now.hour == 6 and ist_now.minute >= 30)):
                    if self._last_totp_request_date != current_date_str and self._may_retry_send():
                        try:
                            # Skip the prompt entirely when today's session is
                            # already live (e.g. a restart re-ran this loop,
                            # or the commander logged in before 06:30) — a
                            # real kite.profile() round-trip, not just a
                            # token-string-exists check.
                            if self._validate_broker_session():
                                logger.info(
                                    "Morning login prompt skipped: existing Zerodha session is already valid."
                                )
                                self._mark_prompted(current_date_str)
                            else:
                                mgr = SecretManager()
                                api_key = mgr.get_secret("api_key", broker="zerodha")
                                totp_secret = os.getenv("ZERODHA_TOTP_SECRET")

                                login_url = f"https://kite.trade/connect/login?v=3&api_key={api_key}"
                                totp_msg = ""
                                if totp_secret:
                                    totp_pin = pyotp.TOTP(totp_secret).now()
                                    totp_msg = f"\n• *Live TOTP*: `{totp_pin}` (Tap to copy)"

                                sent = self.send_message(
                                    "⚠️ *ZERODHA LIVE AUTONOMOUS LOGIN REQUIRED* ⚠️\n"
                                    f"1. Click here to login: [Kite Login]({login_url}){totp_msg}\n"
                                    "2. The browser will show \"Authentication successful\" when done — that's it, you're logged in.\n"
                                    "3. Only reply with `/token URL` if the browser shows an error page instead."
                                )
                                # Only burn the day's prompt once it actually
                                # LANDED. Marking it before the send meant a
                                # transient network failure (laptop asleep, DNS
                                # down) silently consumed the day's only login
                                # prompt: on 2026-07-27 the send failed at
                                # 11:46 with getaddrinfo failed, was never
                                # retried, and Hokage sat blind on an expired
                                # token with the commander never told.
                                if sent:
                                    self._mark_prompted(current_date_str)
                                else:
                                    logger.warning(
                                        "Morning login prompt failed to send; will retry (day NOT marked as prompted)."
                                    )
                        except Exception as e:
                            logger.error(f"Failed to generate morning login brief: {_scrub(e)}")

                # 1.5 Handle daily 09:00 AM IST Connection Confirmation
                if not shut_today and ist_now.hour >= 9:
                    if self._last_confirmation_date != current_date_str and self._may_retry_send():
                        if self._validate_broker_session():
                            sent = self.send_message("✅ *Login Successful* - Broker Connected. Execution engines standing by.")
                        else:
                            sent = self.send_message("🚨 *Login Missing* - No valid Zerodha session. Autonomous execution halted. Please login via Dashboard or /token command.")
                        # Same rule as the login prompt: a dropped send must not
                        # count as "the commander has been told".
                        if sent:
                            self._last_confirmation_date = current_date_str
                
                # 2. Check for updates from Telegram
                if self.enabled:
                    self._check_telegram_updates()
                    
            except Exception as e:
                logger.error(f"Error in Telegram Uplink run loop: {_scrub(e)}")
                
            time.sleep(5.0)

    def _conversational_reply(self, text: str) -> str:
        """Answer a free-text query the way the dashboard chat does.

        Routes through the natural CommanderConversationEngine (humor controls,
        plain-language explainers) when a trading bot is attached; otherwise
        falls back to the raw LLM processor.
        """
        # GROUNDED FIRST. The model is handed read-only tools and a live-state
        # digest, so it answers from Hokage's actual ledger instead of from
        # imagination. The old route reached a bare
        # generate_response(query, system_instruction="") with no data attached
        # whenever the keyword cascade missed — the source of the phantom
        # narratives in the logs.
        try:
            from bots.autonomous.grounded_chat import GroundedChat

            answer = GroundedChat().ask(text)
            if answer.text.strip():
                return answer.text
        except Exception as exc:
            logger.error(f"Grounded chat failed on Telegram: {_scrub(exc)}")

        handler = self.command_handler
        orch = getattr(handler, "orchestrator", None) if handler is not None else None
        if orch is not None:
            try:
                from bots.autonomous.conversation import CommanderConversationEngine
                from bots.autonomous.cache import IntelligenceCache
                engine = CommanderConversationEngine(orch, IntelligenceCache(orch.resolver.resolve_brain_root()))
                return engine.respond(text)
            except Exception as e:
                logger.error(f"Conversation engine failed on Telegram, using LLM fallback: {_scrub(e)}")
        return self.llm_processor.generate_response(text)

    def _try_natural_trade(self, text: str) -> str | None:
        """Detect plain-English trade intent and execute it immediately.

        "exit nifty", "close my banknifty", "sell sensex", "buy nifty call",
        "go short on banknifty" → an immediate paper action. Returns the ack,
        or None when the text isn't an imperative trade (so it flows on to
        normal conversation). Questions ("how do I buy nifty?") are ignored.
        """
        handler = self.command_handler
        if handler is None:
            return None
        low = text.strip().lower()
        # Never fire a trade from a question or an explainer request.
        if "?" in low or low.split()[0] in ("how", "what", "why", "can", "should", "is", "are", "do", "does", "when", "where", "which", "explain", "tell"):
            return None

        import re
        if re.search(r"\bbank\s*nifty\b|\bbanknifty\b", low):
            underlying = "BANKNIFTY"
        elif re.search(r"\bnifty\b", low):
            underlying = "NIFTY"
        elif re.search(r"\bsensex\b", low):
            underlying = "SENSEX"
        else:
            underlying = None

        exit_words = ("exit", "close", "sell", "square off", "squareoff", "get out", "dump", "offload")
        buy_words = ("buy", "enter", "go long", "take a call", "go short", "purchase")
        is_exit = any(w in low for w in exit_words)
        is_buy = any(w in low for w in buy_words) or bool(re.search(r"\blong\b|\bshort\b", low))

        # "close/exit everything"
        if is_exit and any(w in low for w in ("all", "everything", "every position")) and underlying is None:
            return handler.handle_remote_command("/close_all")

        if underlying is None:
            return None

        if is_exit and not is_buy:
            return handler.handle_remote_command(f"/exit {underlying}")
        if is_buy and not is_exit:
            direction = "put" if re.search(r"\bput\b|\bpe\b|\bshort\b|\bbear", low) else "call"
            return handler.handle_remote_command(f"/buy {underlying} {direction}")
        return None

    def _check_telegram_updates(self) -> None:
        url = f"https://api.telegram.org/bot{self.bot_token}/getUpdates"
        params = {"offset": self._last_update_id + 1, "timeout": 2}
        try:
            res = requests.get(url, params=params, timeout=5)
            if res.status_code != 200:
                return
            data = res.json()
            for update in data.get("result", []):
                self._last_update_id = update.get("update_id", self._last_update_id)
                msg = update.get("message", {})
                chat = msg.get("chat", {})
                
                # Make sure message is from the configured chat ID
                if str(chat.get("id")) == str(self.chat_id):
                    text = msg.get("text", "").strip()
                    # A pasted Kite callback URL IS a login attempt, with or
                    # without the /token prefix. Routing a bare URL to the LLM
                    # once produced a hallucinated "connection is solid" reply
                    # while the token was silently discarded.
                    if text.startswith("/token ") or "request_token=" in text:
                        # Extract token
                        if text.startswith("/token "):
                            request_token = text.split("/token ", 1)[1].strip()
                        else:
                            request_token = text
                        if "request_token=" in request_token:
                            try:
                                parsed = urlparse(request_token)
                                qs = parse_qs(parsed.query)
                                if 'request_token' in qs:
                                    request_token = qs['request_token'][0]
                                else:
                                    # Fallback simple split
                                    request_token = request_token.split("request_token=")[1].split("&")[0]
                            except Exception:
                                request_token = request_token.split("request_token=")[1].split("&")[0]
                        
                        logger.info("Intercepted request_token via Telegram")
                        self.send_message("🔄 Processing request\\_token...")
                        try:
                            from integrations.brokers.secrets import update_env_file
                            mgr = SecretManager()
                            api_key = mgr.get_secret("api_key", broker="zerodha")
                            api_secret = mgr.get_secret("api_secret", broker="zerodha")
                            kite = KiteConnect(api_key=api_key)
                            session_data = kite.generate_session(request_token, api_secret=api_secret)
                            final_access_token = session_data["access_token"]
                            
                            # Sync state completely
                            mgr.set_secret("access_token", final_access_token, broker="zerodha")
                            os.environ["ZERODHA_ACCESS_TOKEN"] = final_access_token
                            update_env_file(".env", "ZERODHA_ACCESS_TOKEN", final_access_token)
                            
                            # Push the new token into the RUNNING session. The
                            # connection manager reads it once at boot, so
                            # without this the vault is updated and Hokage
                            # carries on blind on the dead token.
                            refreshed = False
                            handler = self.command_handler
                            orch = getattr(handler, "orchestrator", None) if handler else None
                            manager = getattr(orch, "kite_connection", None) if orch else None
                            if manager is not None and hasattr(manager, "try_reconnect"):
                                try:
                                    refreshed = manager.try_reconnect()
                                except Exception as exc:
                                    logger.error(f"Broker session refresh failed after /token: {_scrub(exc)}")
                            self.send_message(
                                "✅ *Access Granted*. Vault updated. "
                                + ("Live session refreshed — scanning has resumed."
                                   if refreshed else
                                   "Restart Hokage to pick up the new session.")
                            )
                        except Exception as e:
                            # A request_token is single-use: if the browser
                            # already hit the dashboard callback, the token is
                            # spent but the session it created is live. Check
                            # before alarming the commander.
                            if self._validate_broker_session():
                                self.send_message(
                                    "⚠️ That request\\_token was already used or expired — "
                                    "but your existing Zerodha session is *VALID*. "
                                    "Broker is connected; no further login needed."
                                )
                            else:
                                self.send_message(f"❌ *Login Failed*: {self.escape_markdown(e)}")
                            
                    elif text.lower().split()[0] in (
                        "/kill", "/pause", "/resume", "/close_all", "/status",
                        "/exit", "/sell", "/close", "/squareoff", "/square_off",
                        "/buy", "/enter", "/long", "/short",
                        "/report", "/summary", "/eod", "/daily",
                    ):
                        first = text.lower().split()[0]
                        logger.warning(f"Received control command via Telegram: {first}")
                        if self.command_handler is None:
                            self.send_message("❌ Control command received but no trading bot is attached to the uplink.")
                        else:
                            try:
                                # Pass the FULL text so commands with arguments
                                # (/exit NIFTY, /buy BANKNIFTY put) keep their arg.
                                ack = self.command_handler.handle_remote_command(text)
                                self.send_message(ack)
                            except Exception as e:
                                logger.error(f"Control command {first} failed: {_scrub(e)}")
                                self.send_message(
                                    f"❌ Command {self.escape_markdown(first)} failed: {self.escape_markdown(e)}"
                                )
                    elif text.isdigit() and len(text) == 6:
                        self.latest_totp = text
                        logger.info(f"Received valid 6-digit TOTP token: {text}")
                        # Echo confirmation back to the user
                        self.send_message(f"✅ Received TOTP token: {text}. Authenticating Zerodha Connect...")
                    elif text:
                        # Conversational query. Route through the SAME natural
                        # conversation engine the dashboard chat uses, so humor
                        # controls ("be funnier") and the plain-language
                        # explainers work over Telegram too. It also catches
                        # plain-English trade intent like "exit nifty" / "buy
                        # banknifty put" and executes it immediately.
                        logger.info(f"Received conversational query via Telegram: {text}")
                        try:
                            # "why" is answered from the RECORDED TradeContext
                            # before anything else sees it. Left to the normal
                            # route it reaches the keyword cascade and then a
                            # bare LLM call with no data attached — which is
                            # exactly where invented numbers come from.
                            why_reply = self.handle_why(text)
                            trade_reply = (
                                None if why_reply is not None
                                else self._try_natural_trade(text)
                            )
                            if why_reply is not None:
                                self.send_message(why_reply)
                            elif trade_reply is not None:
                                self.send_message(trade_reply)
                            else:
                                self.send_message(self._conversational_reply(text))
                        except Exception as e:
                            logger.error(f"Failed to generate response for Telegram: {_scrub(e)}")
                            self.send_message("❌ Commander, I hit an error processing that. Try again?")
        except Exception as e:
            logger.debug(f"Failed to check Telegram updates: {e}")
