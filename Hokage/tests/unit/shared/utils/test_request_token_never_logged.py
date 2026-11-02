"""The commander's Zerodha request_token went to disk on every login.

2026-11-02 07:39 IST. He logged in, the feed came back, and werkzeug - Flask's
access logger - wrote the callback URL to stderr with the token in it:

    "GET /api/v1/broker/zerodha/callback?status=success&request_token=<SECRET>
     &action=login&type=login HTTP/1.1" 200 -

29 occurrences across 18 log files: every login since the callback route was
added. A spent request_token grants nothing, but it is exchanged for the
access_token that can read the account, and the window is the few seconds
before Hokage exchanges it.

THE LESSON IS WHY THE EXISTING FIX DID NOT COVER THIS. `_scrub` in
telegram_bot.py wraps its own logging calls and works - the bot token is at 0
occurrences on disk. But it protects only lines Hokage writes. werkzeug is a
logger nobody in this codebase calls, so no call-site discipline could reach
it, and the same is true of requests, urllib3 and kiteconnect. The redaction
belongs on the HANDLER, which every record crosses on its way to disk.
"""
from __future__ import annotations

import logging

import pytest

from shared.utils.log_redaction import (
    RedactingFormatter,
    install_log_redaction,
    redact,
)


# The real line, copied from logs/hokage_1793604971_err.log. The token is
# INVENTED - same length and alphabet, derived from nothing. The first
# version of this file used the real token's first 20 characters, which is
# a fragment of a real credential in a file headed for a git remote. A
# truncated spent token is useless to an attacker and that is not the
# point: a test fixture must not be built out of the secret it tests for.
_REAL_ACCESS_LINE = (
    '127.0.0.1 - - [02/Nov/2026 07:39:08] "GET /api/v1/broker/zerodha/callback'
    "?status=success&request_token=Zq4nTbW9kRy2HcVxLm7P&action=login&type=login"
    ' HTTP/1.1" 200 -'
)


# =========================================================================
# The string that leaked
# =========================================================================

def test_the_real_access_log_line_is_redacted():
    out = redact(_REAL_ACCESS_LINE)
    assert "Zq4nTbW9kRy2HcVxLm7P" not in out
    assert "request_token=<REDACTED>" in out


def test_the_rest_of_the_line_survives():
    """A redacted log line still has to be usable as a log line."""
    out = redact(_REAL_ACCESS_LINE)
    for kept in ("127.0.0.1", "02/Nov/2026 07:39:08", "GET",
                 "/api/v1/broker/zerodha/callback", "200"):
        assert kept in out


def test_the_label_is_kept_so_the_leak_can_be_audited():
    """Which secret was there is not itself a secret, and hiding it makes a
    future leak harder to find than naming it does."""
    assert "request_token" in redact(_REAL_ACCESS_LINE)


@pytest.mark.parametrize("param", [
    "request_token", "access_token", "public_token", "refresh_token",
    "enctoken", "api_key", "api_secret", "totp", "password", "checksum",
])
def test_every_credential_parameter_kite_can_carry(param):
    secret = "s3cr3tValue1234567890"
    out = redact(f"GET /callback?{param}={secret}&action=login")
    assert secret not in out
    assert f"{param}=<REDACTED>" in out


def test_url_encoded_equals_too():
    """A nested redirect arrives percent-encoded."""
    assert "abcd1234efgh" not in redact("redirect=%2Fcb%3Frequest_token%3Dabcd1234efgh")


def test_json_bodies_too():
    out = redact('{"access_token": "zzzz9999yyyy8888", "user_id": "AB1234"}')
    assert "zzzz9999yyyy8888" not in out
    assert "AB1234" in out, "a user id is not a credential"


def test_kites_authorization_header():
    out = redact("Authorization: token abcdef123456:ghijkl789012")
    assert "abcdef123456" not in out
    assert "ghijkl789012" not in out


def test_the_telegram_shape_is_still_covered():
    """6c3d8b7 fixed this at the call site. The handler must not be a step
    backwards for the credential that was already leaking."""
    out = redact("Max retries exceeded with url: /bot123456789:AAHxyzTOKEN_part/sendMessage")
    assert "AAHxyzTOKEN_part" not in out
    assert "/bot<REDACTED>" in out


def test_ordinary_lines_are_untouched():
    for line in (
        "Market data feed is DOWN (auth): Venue is not connected.",
        "TARGET_HIT: premium 137.80 reached adaptive target 136.53 (entry 120.55)",
        "Strategy chest audit: every competing strategy can afford to trade.",
        '127.0.0.1 - - [02/Nov/2026 07:36:17] "GET / HTTP/1.1" 200 -',
    ):
        assert redact(line) == line


# =========================================================================
# It has to work through the logging stack, not just as a function
# =========================================================================

def _capture(logger_name: str, emit) -> str:
    import io

    stream = logging.StreamHandler(io.StringIO())
    stream.setFormatter(logging.Formatter("%(name)s: %(message)s"))
    root = logging.getLogger()
    was = root.level
    root.addHandler(stream)
    # werkzeug logs its access lines at INFO and root defaults to WARNING, so
    # without this the record never reaches a handler and every assertion of
    # the form "the secret is not in the output" passes on empty output.
    root.setLevel(logging.INFO)
    try:
        install_log_redaction("")
        emit(logging.getLogger(logger_name))
        captured = stream.stream.getvalue()
    finally:
        root.removeHandler(stream)
        root.setLevel(was)
    assert captured, "nothing was logged: an absence test would pass vacuously"
    return captured


def test_a_werkzeug_record_reaching_a_root_handler_is_redacted():
    """werkzeug holds no handlers of its own: it propagates to root. That is
    the only reason wrapping root is enough."""
    out = _capture("werkzeug", lambda log: log.info(_REAL_ACCESS_LINE))
    assert "Zq4nTbW9kRy2HcVxLm7P" not in out
    assert "request_token=<REDACTED>" in out


def test_lazy_percent_args_are_redacted():
    """A record whose secret is in `args`, not in `msg`."""
    out = _capture(
        "werkzeug",
        lambda log: log.info('"GET %s HTTP/1.1" %s -', "/cb?request_token=qqqq8888wwww", 200),
    )
    assert "qqqq8888wwww" not in out


def test_a_traceback_is_redacted():
    """The 2026-10-12 shape: nobody logged the credential, `requests` put it in
    the exception text. Tracebacks are rendered by the FORMATTER from
    exc_info, so a filter that rewrites record.msg never sees them."""
    def emit(log):
        try:
            raise ConnectionError(
                "HTTPSConnectionPool(host='api.kite.trade', port=443): Max retries "
                "exceeded with url: /session/token?api_key=live9999key8888"
            )
        except ConnectionError:
            log.exception("Session exchange failed")

    out = _capture("Hokage.Test", emit)
    assert "live9999key8888" not in out
    assert "Traceback" in out, "the traceback itself must survive"


# =========================================================================
# Installation
# =========================================================================

def test_install_is_idempotent():
    log = logging.getLogger("Hokage.Test.Idempotent")
    log.handlers = [logging.StreamHandler()]
    assert install_log_redaction("Hokage.Test.Idempotent") == 1
    assert install_log_redaction("Hokage.Test.Idempotent") == 0
    assert isinstance(log.handlers[0].formatter, RedactingFormatter)
    log.handlers = []


def test_a_handler_with_no_formatter_still_gets_one():
    log = logging.getLogger("Hokage.Test.NoFormatter")
    handler = logging.StreamHandler()
    handler.setFormatter(None)
    log.handlers = [handler]
    install_log_redaction("Hokage.Test.NoFormatter")
    assert isinstance(handler.formatter, RedactingFormatter)
    log.handlers = []


def test_the_configured_format_is_preserved():
    """Redacting must not quietly replace the log format."""
    log = logging.getLogger("Hokage.Test.Format")
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("PREFIX %(levelname)s %(message)s"))
    log.handlers = [handler]
    install_log_redaction("Hokage.Test.Format")
    record = log.makeRecord("Hokage.Test.Format", logging.INFO, "f", 1, "hello", None, None)
    assert handler.formatter.format(record) == "PREFIX INFO hello"
    log.handlers = []


def test_boot_installs_it_on_root():
    """A redaction nobody calls is not a fix. Both call sites must exist: the
    module-level one, and the one after the rotating file handler is added -
    that handler is the one that writes to disk and it is created later."""
    from pathlib import Path

    src = Path(__import__("hokage.boot", fromlist=["x"]).__file__).read_text(encoding="utf-8")
    assert "from shared.utils.log_redaction import install_log_redaction" in src
    # Two calls: once at module level, once after the rotating file handler is
    # attached, because that handler is created later in the boot and it is
    # the one that writes to disk.
    assert src.count('install_log_redaction("", "Hokage")') == 2
    # And werkzeug by name after the dashboard is built: it attaches a handler
    # of its own if it finds none upstream, and it is the logger that leaked.
    assert 'install_log_redaction("werkzeug")' in src
