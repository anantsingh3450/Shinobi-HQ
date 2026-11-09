"""A watch that does not live on this machine.

2026-09-23, 06:27. Hokage's process wrote its last line. The next one started
2026-10-09 18:26 — sixteen days, eleven market sessions, no process, no
decisions, no log file. The commander was travelling and the laptop was off.

NOTHING REPORTED IT. The external liveness probe exists precisely because
"his own watchdog dies with him", and it did not fire either: it is a Windows
scheduled task on the same laptop, running as LogonType=Interactive, like
every other Hokage task. It is independent of the PROCESS and not of the
MACHINE, and the machine is what went away.

A probe inside the failure domain it watches cannot report that domain
failing. There is only one shape that works from in here: INVERT THE SIGNAL.
Hokage pushes a heartbeat OUT on a schedule, and SILENCE raises the alarm.
The alarm then lives somewhere that does not share his fate — it does not
need to reach him, it needs him to stop reaching it.

    every INTERVAL      POST to the ping URL with a one-line status
    clean shutdown      POST to {url}/fail with the reason, so the alert can
                        say "stopped cleanly" rather than "vanished"
    anything else       silence, and the service alarms after its grace

NO SUPPRESSION, DELIBERATELY. A deliberate stop will raise the alarm after
the grace period, and that is correct: Hokage is not running. Any mechanism
to mute a planned absence from in here is a mechanism that can mute a real
one, and the stop marker has already failed to survive a scheduled task once
(2026-10-09). Simplicity is the safety property. Mute it at the service for a
planned absence.

A FAILED PING IS NOT A DEATH, and the difference is invisible from outside.
This laptop lost DNS for 44 distinct minutes on 10-14 and 10-15 — both
api.kite.trade and api.telegram.org at once — so some pings will be lost to
the network rather than to Hokage. That is what the service's grace period is
for; the recommended 15-minute period against a 30-minute grace absorbs an
outage twice as long as the worst one measured.

THE URL IS A CREDENTIAL. Anyone holding it can forge a heartbeat, which would
turn this watch off silently. It is read from the environment, never written
to a log, never put in an alert, and never echoed back. Only the host is ever
logged.
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Callable
from urllib.parse import urlsplit

logger = logging.getLogger("Hokage.DeadMansSwitch")

#: Where the ping URL is read from. The commander creates the check and pastes
#: the URL into .env; nothing in this repo ever holds it.
URL_ENV = "HOKAGE_DEADMAN_URL"

#: Offline config seam, the same shape as HOKAGE_DISABLE_TELEGRAM. The test
#: suite sets it, so no test can ever reach the real service.
DISABLE_ENV = "HOKAGE_DISABLE_DEADMAN"

#: How often a living Hokage reports in. Deliberately shorter than the
#: service-side period so a single lost ping is not a missed deadline.
DEFAULT_INTERVAL_SECONDS = 600

#: A ping must never hold up the trading loop. It runs on its own thread, and
#: this bounds the worst case anyway.
PING_TIMEOUT_SECONDS = 10


#: Characters that cannot occur in any valid ping URL, and what each one
#: means. ANGLE BRACKETS ARE THE COMMON ONE: every piece of documentation
#: writes the URL as https://hc-ping.com/<your-uuid>, and on 2026-11-09 the
#: placeholder went into .env still wearing its brackets. The scheme was
#: right, the host was right, the switch armed and announced itself - and the
#: service answered 400 "invalid url format" to every heartbeat.
_IMPOSSIBLE_CHARS = (
    ("<", "an unreplaced <placeholder> from the setup instructions"),
    (">", "an unreplaced <placeholder> from the setup instructions"),
    ('"', "quotes around the value (.env needs none)"),
    ("'", "quotes around the value (.env needs none)"),
    (" ", "whitespace inside the URL"),
)


def url_problem(url: str) -> str | None:
    """Why this URL can never work, or None if it might.

    DELIBERATELY NARROW. It rejects only what is impossible, never what is
    merely unfamiliar: healthchecks.io serves both UUID ping URLs and
    ping-key-plus-slug URLs, so "does not look like a UUID" is not a fault
    and a shape check that insisted on one would break a correct setup.

    Never quotes the value back. The reason is named; the secret is not.
    """
    for char, reason in _IMPOSSIBLE_CHARS:
        if char in url:
            return reason
    if url.rstrip("/").count("/") <= 2:      # scheme's two, then nothing
        return "no path at all - this is a host, not a ping URL"
    return None


def configured_url() -> str | None:
    """The ping URL, or None when the switch is not set up."""
    if os.environ.get(DISABLE_ENV) == "true":
        return None
    url = (os.environ.get(URL_ENV) or "").strip().strip('"').strip("'")
    if not url:
        return None
    if not url.lower().startswith(("http://", "https://")):
        logger.warning(
            "Dead man's switch: %s is set but is not an http(s) URL. Ignored.",
            URL_ENV,
        )
        return None
    problem = url_problem(url)
    if problem is not None:
        # REFUSED, not armed. Arming on a URL that cannot work is worse than
        # not arming: the boot line says "armed", and the only sign of trouble
        # is a generic failure warning every ten minutes that reads exactly
        # like the DNS outages this laptop really does have.
        logger.error(
            "Dead man's switch: %s cannot work - %s. NOT armed. "
            "Re-copy the ping URL from the check's page.",
            URL_ENV, problem,
        )
        return None
    return url


def safe_host(url: str | None) -> str:
    """The host alone. The PATH is the secret, so it never appears anywhere."""
    if not url:
        return "(not configured)"
    try:
        return urlsplit(url).hostname or "(unparseable)"
    except Exception:
        return "(unparseable)"


def _default_transport(url: str, body: str, timeout: float) -> bool:
    import requests

    resp = requests.post(url, data=body.encode("utf-8"), timeout=timeout)
    return 200 <= resp.status_code < 300


class DeadMansSwitch:
    """Pushes a heartbeat out so that silence becomes the alarm."""

    def __init__(
        self,
        url: str | None = None,
        interval_seconds: int = DEFAULT_INTERVAL_SECONDS,
        transport: Callable[[str, str, float], bool] | None = None,
        status_fn: Callable[[], str] | None = None,
    ) -> None:
        self._url = url if url is not None else configured_url()
        self._interval = max(30, int(interval_seconds))
        self._transport = transport or _default_transport
        self._status_fn = status_fn
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        #: Consecutive failures. The first is a WARNING and the rest are DEBUG:
        #: a DNS outage produced 144 identical WARNING lines on 10-14, and a
        #: log nobody can read is a log nobody reads.
        self._consecutive_failures = 0
        self._pings = 0

    # ------------------------------------------------------------ properties
    @property
    def enabled(self) -> bool:
        return bool(self._url)

    @property
    def pings(self) -> int:
        return self._pings

    # ---------------------------------------------------------------- pinging
    def _status(self) -> str:
        if self._status_fn is None:
            return "alive"
        try:
            return str(self._status_fn())[:400]
        except Exception as exc:
            # A broken status line must not cost the heartbeat. The heartbeat
            # is the signal; the status is a convenience printed beside it.
            return f"alive (status unavailable: {str(exc)[:80]})"

    def ping(self, suffix: str = "", body: str | None = None) -> bool:
        """One heartbeat. Returns whether it was accepted. Never raises."""
        if not self._url:
            return False
        url = self._url.rstrip("/") + suffix
        try:
            ok = bool(self._transport(
                url, body if body is not None else self._status(),
                PING_TIMEOUT_SECONDS))
        except Exception as exc:
            ok = False
            self._note_failure(exc)
        if ok:
            if self._consecutive_failures:
                logger.info(
                    "Dead man's switch: heartbeat restored to %s after %d "
                    "failed attempt(s).",
                    safe_host(self._url), self._consecutive_failures,
                )
            self._consecutive_failures = 0
            self._pings += 1
        elif not self._consecutive_failures:
            self._note_failure(None)
        return ok

    def _note_failure(self, exc: Exception | None) -> None:
        self._consecutive_failures += 1
        detail = f": {str(exc)[:120]}" if exc else ""
        if self._consecutive_failures == 1:
            logger.warning(
                "Dead man's switch: heartbeat to %s failed%s. The service "
                "will alarm if this continues past its grace period.",
                safe_host(self._url), detail,
            )
        else:
            logger.debug(
                "Dead man's switch: heartbeat failed (%d consecutive)%s",
                self._consecutive_failures, detail,
            )

    # ------------------------------------------------------------- lifecycle
    def start(self) -> None:
        if not self._url:
            # Said ONCE, at boot, not every cycle. An unconfigured switch is a
            # real gap and must be visible, but a line per cycle is how a real
            # warning gets scrolled past.
            logger.warning(
                "Dead man's switch is NOT configured (%s unset). Nothing off "
                "this machine will notice if Hokage stops: that is the gap "
                "that cost 11 market sessions between 2026-09-23 and "
                "2026-10-08.", URL_ENV,
            )
            return
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="HokageDeadMansSwitch", daemon=True)
        self._thread.start()
        logger.info(
            "Dead man's switch armed: heartbeat to %s every %ds.",
            safe_host(self._url), self._interval,
        )

    def _run(self) -> None:
        # Ping IMMEDIATELY, then on the interval. Waiting a full interval
        # first would leave a boot that crashes in its first minutes looking
        # exactly like a healthy start to the service.
        self.ping()
        while not self._stop.wait(self._interval):
            self.ping()

    def stop(self, reason: str = "stopped") -> None:
        """Stand down, telling the service why.

        The final /fail does not suppress anything — the check goes DOWN
        either way. It replaces "vanished" with a reason, which is the
        difference between an alert the commander has to investigate and one
        he can read.
        """
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=5.0)
        if self._url:
            self.ping(suffix="/fail", body=f"stopped: {reason}"[:400])
