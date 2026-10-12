"""The bot token was sitting in the logs in plaintext, 1,057 times.

2026-10-12, 15:05 IST: a brief local DNS failure took out name resolution.
Hokage could not reach Kite, correctly reported "Market data feed is DOWN",
and tried to Telegram the commander about it. That failed too -- same
outage -- and the failure was logged:

    Failed to send Telegram message: HTTPSConnectionPool(
    host='api.telegram.org', port=443): Max retries exceeded with url:
    /bot<ID>:<SECRET>/sendMessage (Caused by NameResolutionError(...))

`requests` puts the FULL URL in its exception text, and the Telegram API
carries the bot token in the path. Nobody wrote the credential to the log --
requests did, inside an exception that nobody reads until something breaks.

Counted immediately afterwards:

    45 lines in the current hokage.log
   485 lines across the rotated logs
   527 lines under logs/

Anyone with read access to a log file had the token, and with it the ability
to read and send every message on the commander's channel. Zero in the
database, but only by luck of timing: the event-bus fix earlier that same day
stopped SHINOBI_LOG persisting every log line to audit_trail. Before it, these
would have been durable rows too.

`_audit` in the same module was already written to never log the token. This
path bypassed that care entirely.
"""
from __future__ import annotations

import re

import pytest

from integrations.notifications.telegram_bot import _scrub

#: A token-shaped value that is NOT the real one.
FAKE_ID = "1234567890"
FAKE_SECRET = "AAHxxYYzz_-QqRrSsTt0123456789abcd"
FAKE = f"/bot{FAKE_ID}:{FAKE_SECRET}"


@pytest.mark.parametrize("endpoint", ["sendMessage", "getUpdates", "getMe"])
def test_the_secret_never_survives_a_scrub(endpoint):
    """Both endpoints the module calls put the token in the path."""
    raw = (
        "HTTPSConnectionPool(host='api.telegram.org', port=443): Max retries "
        f"exceeded with url: {FAKE}/{endpoint} (Caused by NameResolutionError"
        "(\"Failed to resolve 'api.telegram.org'\"))"
    )
    out = _scrub(raw)
    assert FAKE_SECRET not in out
    assert FAKE_ID not in out
    assert "<REDACTED>" in out


def test_the_rest_of_the_message_is_kept():
    """Redaction must not destroy the diagnostic. The reason the feed was
    down is the whole point of the log line."""
    raw = f"Max retries exceeded with url: {FAKE}/sendMessage (Caused by NameResolutionError)"
    out = _scrub(raw)
    assert "Max retries exceeded" in out
    assert "NameResolutionError" in out
    assert "sendMessage" in out


def test_several_occurrences_in_one_message_all_go():
    raw = f"first {FAKE}/sendMessage then again {FAKE}/getUpdates"
    out = _scrub(raw)
    assert FAKE_SECRET not in out
    assert out.count("<REDACTED>") == 2


def test_a_message_with_no_token_is_untouched():
    raw = "Telegram API error 400: Bad Request: can't parse entities"
    assert _scrub(raw) == raw


def test_it_accepts_an_exception_object_not_just_a_string():
    """The call sites pass `e` directly."""
    err = RuntimeError(f"boom {FAKE}/sendMessage")
    out = _scrub(err)
    assert FAKE_SECRET not in out
    assert "boom" in out


def test_none_and_empty_do_not_raise():
    assert _scrub(None) == "None"
    assert _scrub("") == ""


# ------------------------------------------- every risky log site is covered
def test_no_log_call_passes_a_url_bearing_value_unscrubbed():
    """The four sites that can carry a URL or an API response body must all
    route through _scrub. A new one added later is the regression this
    guards."""
    import ast
    import pathlib

    src = pathlib.Path(
        "src/integrations/notifications/telegram_bot.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(src)

    risky = {"e", "exc", "res", "retry"}
    offenders = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and getattr(node.func.value, "id", None) == "logger"
                and node.func.attr in ("error", "warning")):
            continue
        for arg in node.args:
            if not isinstance(arg, ast.JoinedStr):
                continue
            for part in arg.values:
                if not isinstance(part, ast.FormattedValue):
                    continue
                inner = part.value
                # f"...{e}" or f"...{res.text}"
                name = getattr(inner, "id", None) or getattr(
                    getattr(inner, "value", None), "id", None)
                if name in risky and not (
                        isinstance(inner, ast.Call)
                        and getattr(inner.func, "id", "") == "_scrub"):
                    offenders.append(f"line {node.lineno}: {name}")
    assert not offenders, (
        f"these log an unscrubbed value that can contain the token: {offenders}"
    )


def test_the_pattern_matches_a_real_telegram_token_shape():
    """Bot tokens are <digits>:<base64-ish>. A pattern that misses the real
    shape redacts nothing while looking like it works."""
    pattern = re.compile(r"/bot\d+:[A-Za-z0-9_\-]+")
    assert pattern.search(f"{FAKE}/sendMessage")
    assert pattern.search("/bot8000000000:AA-_azAZ09/getUpdates")
