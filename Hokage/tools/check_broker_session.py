"""Exit 0 if the stored Zerodha session is genuinely live, 1 otherwise.

A real kite.profile() round trip. A token string sitting on disk proves nothing:
Kite expires them daily, and Hokage spent nine days in July scanning against a
dead one. Never prints the token or any credential -- only a verdict.

Used by Start-Hokage.ps1 to decide whether the commander still needs to log in.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        from integrations.brokers.secrets import SecretManager
        from kiteconnect import KiteConnect

        secrets = SecretManager()
        api_key = secrets.get_secret("api_key", broker="zerodha")
        access_token = secrets.get_secret("access_token", broker="zerodha")
        if not api_key or not access_token:
            print("NO_CREDENTIALS")
            return 1

        kite = KiteConnect(api_key=api_key)
        kite.set_access_token(access_token)
        profile = kite.profile()
        print(f"LIVE {profile.get('user_name', '')}".strip())
        return 0
    except Exception as exc:
        message = str(exc).lower()
        if any(tag in message for tag in ("token", "auth", "session", "api_key", "forbidden", "403")):
            print("EXPIRED")
        else:
            print("UNREACHABLE")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
