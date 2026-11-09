"""Is the dead man's switch set up? Answered without revealing the secret.

THE PING URL IS A CREDENTIAL. Anyone holding it can forge a heartbeat, which
turns the watch off without anything appearing wrong. So the commander needs a
way to confirm it is configured that does not involve printing it, pasting it
into a chat, or putting it on screen while sharing - and `type .env` or a grep
for the key does exactly that.

This prints three things and nothing else:

    configured   whether HOKAGE_DEADMAN_URL is set and is an http(s) URL
    host         the HOSTNAME only, which is not secret - the path is
    armed        whether a running Hokage would start the switch

The path never reaches stdout, a log, or an exception message.

USAGE
    python tools/ops/check_deadman.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    from dotenv import load_dotenv

    load_dotenv(str(ROOT / ".env"))
    from shared.watchdog.deadman import (
        DEFAULT_INTERVAL_SECONDS, DISABLE_ENV, URL_ENV, configured_url, safe_host,
    )

    raw = (os.environ.get(URL_ENV) or "").strip()
    url = configured_url()
    disabled = os.environ.get(DISABLE_ENV) == "true"

    print("  dead man's switch")
    print(f"    {URL_ENV:<24} {'set' if raw else 'NOT SET'}")
    if raw and not url and not disabled:
        # Set but rejected: almost always a pasted value with the scheme
        # missing, or quotes around it. Say which without quoting it back.
        print("    value                    REJECTED - not an http(s) URL")
        print("                             (check for missing https:// or "
              "stray quotes)")
    print(f"    host                     {safe_host(url)}")
    if disabled:
        print(f"    {DISABLE_ENV:<24} true - the switch is deliberately OFF")
    print(f"    would arm at boot        {'yes' if url else 'NO'}")
    if url:
        print(f"    heartbeat interval       {DEFAULT_INTERVAL_SECONDS}s")
        print()
        print("  Restart Hokage and this line should appear once, at boot:")
        print(f"    Dead man's switch armed: heartbeat to {safe_host(url)} "
              f"every {DEFAULT_INTERVAL_SECONDS}s.")
        print("  The first ping is sent immediately, so the check should go")
        print("  green within a few seconds rather than after a full period.")
        return 0

    print()
    print("  NOT CONFIGURED. Between 2026-09-23 and 2026-10-09 Hokage did not")
    print("  exist for eleven market sessions and nothing reported it. See")
    print("  docs/runbooks/DEAD_MANS_SWITCH.md - three steps, about five")
    print("  minutes, and none of them involve showing anyone the URL.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
