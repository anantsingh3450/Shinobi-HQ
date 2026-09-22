"""Set the dashboard password WITHOUT anyone but you ever seeing it.

The dashboard can place trades, close positions and write the broker token. On
a public server it needs a lock. This prints the HASH to put in .env; the
password itself is typed at a hidden prompt, never stored, never logged, and
never passed to anyone helping with the system.

    python tools/ops/set_dashboard_password.py

Copy the printed line into .env and restart Hokage. The password cannot be
recovered from the hash — losing it means running this again.
"""
from __future__ import annotations

import getpass
import sys

#: Short enough to remember, long enough that the rate limiter is not the only
#: thing standing between a stranger and a trading terminal.
MIN_LENGTH = 12


def main() -> int:
    print("Hokage dashboard password")
    print("-" * 60)
    print("Typed hidden. Never stored, never logged, never shown to anyone.")
    print(f"Minimum {MIN_LENGTH} characters — length beats punctuation.")
    print()

    try:
        first = getpass.getpass("Password: ")
        second = getpass.getpass("Again:    ")
    except (KeyboardInterrupt, EOFError):
        print("\nCancelled. Nothing written.")
        return 1

    if first != second:
        print("They do not match. Nothing written.")
        return 1
    if len(first) < MIN_LENGTH:
        print(f"Too short — {len(first)} characters, minimum {MIN_LENGTH}.")
        return 1

    try:
        from werkzeug.security import generate_password_hash
    except ImportError:
        print("werkzeug is missing. Install dependencies first: pip install -e .")
        return 1

    # PBKDF2-SHA256. Deliberately slow, so a stolen .env does not hand over the
    # password itself at any useful rate.
    digest = generate_password_hash(first, method="pbkdf2:sha256:600000")
    del first, second

    print()
    print("Add this line to .env, then restart Hokage:")
    print()
    print(f"HOKAGE_DASHBOARD_PASSWORD_HASH={digest}")
    print()
    print("Optional — keeps you logged in across restarts instead of having to")
    print("sign in again after each deploy:")
    print()
    import os
    print(f"HOKAGE_DASHBOARD_SECRET_KEY={os.urandom(32).hex()}")
    print()
    print("Set HOKAGE_DASHBOARD_HTTPS=1 as well, but ONLY once TLS is actually")
    print("in front. A Secure cookie over plain HTTP is never sent back, and")
    print("you would be locked out of your own dashboard with no error shown.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
