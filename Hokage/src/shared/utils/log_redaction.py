"""Strip credentials out of every log line, at the handler.

WHY THIS IS NOT DONE AT THE CALL SITE
`_scrub` in telegram_bot.py already wraps its own logging calls, and it works:
the bot token is at 0 occurrences across every log on disk. But it only
protects lines Hokage writes about itself. On 2026-11-02 the commander's
Zerodha login landed and werkzeug - Flask's access logger, which nobody in
this codebase calls - wrote the whole callback URL to stderr:

    "GET /api/v1/broker/zerodha/callback?status=success&request_token=<SECRET>
     &action=login&type=login HTTP/1.1" 200 -

29 occurrences across 18 log files: every login since the callback route was
added. A request_token is single-use and short-lived, so a spent one grants
nothing - but it is exchanged for the access_token that can read the account,
and anything that can be exchanged for a session does not belong on disk in
plaintext.

A CALL-SITE SCRUB CANNOT COVER A LOGGER YOU DO NOT CALL. werkzeug, requests,
urllib3 and kiteconnect all log, and each new one is a hole that opens
silently. So the redaction sits on the HANDLER'S FORMATTER, which every record
passes through on its way to disk no matter who logged it - including
tracebacks, which are rendered by the formatter from exc_info and never touch
`record.msg` at all. That was the shape of the 2026-10-12 leak: nobody wrote
the credential, `requests` did, inside an exception nobody reads until
something breaks.
"""
from __future__ import annotations

import logging
import re

#: Query parameters and header forms that carry a credential. Each pattern
#: keeps its label and replaces only the value, so a redacted line still says
#: WHICH secret was there - a log that hides the shape of its own leak is
#: harder to audit than one that names it.
_REDACTIONS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Telegram puts the bot token in the URL path.
    (re.compile(r"/bot\d+:[A-Za-z0-9_\-]+"), "/bot<REDACTED>"),
    # Kite's own auth header: "Authorization: token <api_key>:<access_token>".
    # Runs before the parameter pattern below, which would otherwise redact
    # the word "token" and leave the credential beside it.
    (
        re.compile(r"\btoken\s+[\w\-]{6,}:[\w\-]{6,}"),
        "token <REDACTED>:<REDACTED>",
    ),
    # Kite's login callback (request_token), its session exchange
    # (access_token, public_token, refresh_token, enctoken) and the TOTP.
    #
    # No \b before the label: a nested redirect arrives percent-encoded as
    # "...%3Frequest_token%3D...", and "F" to "r" is not a word boundary, so a
    # \b here silently missed the encoded form. Without it the pattern also
    # catches "my_api_key=", which is the direction to err in.
    #
    # The value must not be the bare word "token", or the header shape above
    # loses its "token" and keeps its secret.
    (
        re.compile(
            r"(request_token|access_token|public_token|refresh_token|enctoken"
            r"|api_key|api_secret|apikey|totp|password|checksum|sess_id|session_token"
            r"|authorization)"
            r"(=|%3D|\"\s*:\s*\"|'\s*:\s*'|:\s*)"
            r"(?!token\b)"
            r"([^&\s\"'},;]{4,})",
            re.IGNORECASE,
        ),
        r"\1\2<REDACTED>",
    ),
)


def redact(text: object) -> str:
    """Return `text` with every known credential shape replaced."""
    out = str(text)
    for pattern, replacement in _REDACTIONS:
        out = pattern.sub(replacement, out)
    return out


class RedactingFormatter(logging.Formatter):
    """Wraps another formatter and redacts whatever it produced.

    It formats through the handler's original formatter first, so the output
    keeps its configured shape, and redacts the finished string. Formatting
    first is what makes tracebacks safe: `exc_info` is rendered here, not in
    `record.msg`, so a filter that only rewrites the message misses it.
    """

    def __init__(self, inner: logging.Formatter) -> None:
        super().__init__()
        self.inner = inner

    def format(self, record: logging.LogRecord) -> str:
        return redact(self.inner.format(record))


def install_log_redaction(*logger_names: str) -> int:
    """Wrap the formatter of every handler on the named loggers.

    Returns the number of handlers newly wrapped. Idempotent: a handler that
    already redacts is left alone, so this is safe to call again after more
    handlers are attached - which boot does, because the rotating file handler
    cannot be created until the brain root has been resolved.

    Pass "" for the root logger. Root is the one that matters: werkzeug and
    every other third-party logger propagates there rather than holding
    handlers of its own.
    """
    wrapped = 0
    for name in logger_names or ("",):
        for handler in logging.getLogger(name).handlers:
            if isinstance(handler.formatter, RedactingFormatter):
                continue
            handler.setFormatter(RedactingFormatter(handler.formatter or logging.Formatter()))
            wrapped += 1
    return wrapped
